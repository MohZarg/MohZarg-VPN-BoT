"""
GhYiAb V2 — Hiddify Provider Adapter (REST API)
================================================

مرز معماری: V2 Core → VPNProvider → این Adapter → Hiddify REST API → Xray/Sing-box

قواعد سخت
---------
- فقط از طریق REST API پنل (``/api/v2/...``) با توکن Bearer (API Key).
- تغییر مکان Hiddify به سرور دیگر = فقط تغییر ``HIDDIFY_BASE_URL`` (و توکن).
- NOT_CONFIGURED/BLOCKED هرگز شبیه‌سازی نمی‌شود: ``NotConfiguredError``.
- توکن هرگز لاگ/نمایش داده نمی‌شود.
- Retry محدود و Exponential backoff فقط برای درخواست‌های GET.
- Circuit breaker سبک.

مرجع API: Hiddify Panel API v2 — ``/api/v2/docs``
واحدها: ``data_limit`` در پنل **بایت** است؛ ``expire_time`` epoch میلی‌ثانیه.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Any, Optional, Sequence
from urllib.parse import quote

import requests

from providers.vpn.base import (
    ClientSpec, ClientState, NotConfiguredError, ProviderAuthError,
    ProviderRejectedError, ProviderUnavailableError, VPNProviderError,
)

logger = logging.getLogger("ghyiab.providers.hiddify")


def _truthy(v: str, default: bool = True) -> bool:
    v = (v or "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


def _env_int(*names: str, default: int) -> int:
    for n in names:
        raw = os.getenv(n, "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                break
    return default


@dataclass(frozen=True)
class HiddifyConfig:
    base_url: str = ""
    api_key: str = ""
    timeout: int = 10
    verify_tls: bool = True
    sub_url_base: str = ""
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "HiddifyConfig":
        base = (os.getenv("HIDDIFY_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            api_key=os.getenv("HIDDIFY_API_KEY", "").strip(),
            timeout=_env_int("HIDDIFY_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("HIDDIFY_VERIFY_TLS", "1")),
            sub_url_base=os.getenv("HIDDIFY_SUB_URL_BASE", "").strip(),
            max_retries=min(5, _env_int("HIDDIFY_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def __repr__(self) -> str:
        return (f"HiddifyConfig(base_url={self.base_url!r}, api_key={'***' if self.api_key else ''!r}, "
                f"timeout={self.timeout}, verify_tls={self.verify_tls})")


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class HiddifyProvider:
    name = "hiddify"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30

    def __init__(self, config: Optional[HiddifyConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or HiddifyConfig.from_env()
        self._session = session or requests.Session()
        self._sleep = sleep
        self._lock = threading.Lock()
        self._fails = 0
        self._open_until = 0.0

    # ---- پیکربندی ---------------------------------------------------------
    def is_configured(self) -> bool:
        return self.config.is_configured

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise NotConfiguredError(
                "NOT_CONFIGURED: HIDDIFY_BASE_URL و HIDDIFY_API_KEY تنظیم نشده‌اند؛ عملیات BLOCKED است.")

    # ---- HTTP -------------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل Hiddify موقتاً در دسترس نیست (circuit open)")

    def _breaker_record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._fails = 0
                self._open_until = 0.0
            else:
                self._fails += 1
                if self._fails >= self.BREAKER_THRESHOLD:
                    self._open_until = time.monotonic() + self.BREAKER_COOLDOWN_S

    def _request(self, method: str, path: str, *, json_body: Any = None, params: Any = None) -> Any:
        self._require_configured()
        self._breaker_check()
        url = f"{self.config.base_url}/api/v2{path}"
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Accept": "application/json"}
        attempts = (self.config.max_retries + 1) if method == "GET" else 1
        last_exc: Optional[Exception] = None

        for i in range(attempts):
            try:
                resp = self._session.request(
                    method, url, json=json_body, params=params, headers=headers,
                    timeout=self.config.timeout, verify=self.config.verify_tls)
            except requests.RequestException as exc:
                last_exc = ProviderUnavailableError(f"اتصال به پنل ناموفق ({type(exc).__name__})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(2.0, 0.25 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc from None

            if resp.status_code >= 500:
                last_exc = ProviderUnavailableError(f"خطای سرور پنل (HTTP {resp.status_code})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(2.0, 0.25 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc

            break

        self._breaker_record(True)

        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"API Key نامعتبر یا بدون دسترسی (HTTP {resp.status_code})")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر/منبع یافت نشد", status=404)

        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(
                f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code) from None

        # Hiddify returns {success: true, data: ...} or direct data
        if isinstance(payload, dict) and "success" in payload:
            if not payload.get("success", False):
                raise ProviderRejectedError(
                    f"پنل درخواست را رد کرد: {_clean(payload.get('message', ''))}",
                    status=resp.status_code)
            return payload.get("data")

        return payload

    # ---- سلامت ------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/admin/status")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound ----------------------------------------------------------
    def list_inbounds(self) -> list[dict]:
        try:
            data = self._request("GET", "/admin/user/list")
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    # ---- کلاینت -----------------------------------------------------------
    def _to_client_state(self, user_data: dict) -> ClientState:
        """Convert Hiddify user object to ClientState."""
        enable = user_data.get("is_active", True)
        expiry_ms = int(user_data.get("expire_time", 0) or 0)
        total_bytes = int(user_data.get("data_limit", 0) or 0)
        used_bytes = int(user_data.get("used_traffic", 0) or 0)

        sub_id = user_data.get("sub_id", "") or ""
        uuid = user_data.get("uuid", "") or ""

        return ClientState(
            email=user_data.get("name", "") or user_data.get("username", ""),
            enable=enable,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
            up_bytes=0,
            down_bytes=used_bytes,
            sub_id=sub_id,
            uuid=uuid,
            inbound_ids=tuple(user_data.get("inbounds", [])) if user_data.get("inbounds") else (),
        )

    def get_traffic(self, email: str) -> Optional[ClientState]:
        try:
            # Hiddify uses name/username as identifier
            users = self._request("GET", "/admin/user/list", params={"search": email})
            if isinstance(users, list):
                for u in users:
                    if u.get("name") == email or u.get("username") == email:
                        return self._to_client_state(u)
            return None
        except ProviderRejectedError as e:
            if e.status == 404:
                return None
            raise

    def get_client(self, email: str) -> Optional[ClientState]:
        return self.get_traffic(email)

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        if not inbound_ids:
            raise ProviderRejectedError("حداقل یک inbound لازم است")

        user_data = {
            "name": spec.email,
            "uuid": spec.client_uuid or str(_uuid.uuid4()),
            "inbounds": [str(i) for i in inbound_ids],
            "expire_time": int(spec.expiry_ms) if spec.expiry_ms > 0 else 0,
            "data_limit": int(spec.total_bytes) if spec.total_bytes > 0 else 0,
            "data_limit_reset_strategy": "no_reset",
            "comment": spec.comment or "",
            "is_active": spec.enable,
            "sub_id": spec.sub_id,
        }

        self._request("POST", "/admin/user", json_body=user_data)

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("کلاینت پس از ساخت قابل تأیید نبود")
        return created

    def _raw_record(self, email: str) -> dict:
        users = self._request("GET", "/admin/user/list", params={"search": email})
        if isinstance(users, list):
            for u in users:
                if u.get("name") == email or u.get("username") == email:
                    return u
        raise ProviderRejectedError("کلاینت یافت نشد", status=404)

    def update_client(self, email: str, **changes) -> ClientState:
        current = self._raw_record(email)
        uuid = current.get("uuid", "")

        update_data = {}
        mapping = {
            "enable": "is_active",
            "expiry_ms": "expire_time",
            "total_bytes": "data_limit",
            "limit_ip": "limit_ip",
            "comment": "comment",
        }

        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")
            api_key = mapping[k]
            if k == "expiry_ms":
                update_data[api_key] = int(v) if v > 0 else 0
            elif k == "total_bytes":
                update_data[api_key] = int(v) if v > 0 else 0
            else:
                update_data[api_key] = v

        self._request("PUT", f"/admin/user/{uuid}", json_body=update_data)

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("کلاینت پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        current = self._raw_record(email)
        uuid = current.get("uuid", "")
        if uuid:
            self._request("DELETE", f"/admin/user/{uuid}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        if reset_traffic:
            try:
                current = self._raw_record(email)
                uuid = current.get("uuid", "")
                if uuid:
                    self._request("POST", f"/admin/user/{uuid}/reset-traffic")
            except VPNProviderError:
                pass
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        try:
            user = self._raw_record(email)
            sub_id = user.get("sub_id", "")
            if sub_id and self.config.sub_url_base:
                return [self.config.sub_url_base.rstrip("/") + "/" + sub_id]
            # Fallback: try to get subscription link from user data
            links = user.get("links", [])
            if isinstance(links, list):
                return [str(x) for x in links if isinstance(x, str)]
        except VPNProviderError:
            pass
        return []

    def get_subscription_url(self, sub_id: str) -> Optional[str]:
        base = self.config.sub_url_base
        if not base or not sub_id:
            return None
        return base.rstrip("/") + "/" + quote(sub_id, safe="")

    def reset_traffic(self, email: str) -> None:
        try:
            current = self._raw_record(email)
            uuid = current.get("uuid", "")
            if uuid:
                self._request("POST", f"/admin/user/{uuid}/reset-traffic")
        except VPNProviderError:
            raise ProviderRejectedError("ریست ترافیک ناموفق بود")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> HiddifyProvider:
    return HiddifyProvider(HiddifyConfig.from_env())