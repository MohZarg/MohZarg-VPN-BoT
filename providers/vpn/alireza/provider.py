"""
GhYiAb V2 — Alireza Single Panel Provider Adapter
==================================================

مرز معماری: V2 Core → VPNProvider → این Adapter → Alireza Panel API → Xray

Alireza Single Panel یک پنل مدیریت ساده مبتنی بر Xray است.

مرجع API: API اختصاصی Alireza Panel
واحدها: data_limit بایت، expire epoch ثانیه/میلی‌ثانیه.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence
from urllib.parse import quote

import requests

from providers.vpn.base import (
    ClientSpec, ClientState, NotConfiguredError, ProviderAuthError,
    ProviderRejectedError, ProviderUnavailableError, VPNProviderError,
)

logger = logging.getLogger("ghyiab.providers.alireza")


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
class AlirezaConfig:
    base_url: str = ""
    api_key: str = ""
    timeout: int = 10
    verify_tls: bool = True
    sub_url_base: str = ""
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "AlirezaConfig":
        base = (os.getenv("ALIREZA_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            api_key=os.getenv("ALIREZA_API_KEY", "").strip(),
            timeout=_env_int("ALIREZA_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("ALIREZA_VERIFY_TLS", "1")),
            sub_url_base=os.getenv("ALIREZA_SUB_URL_BASE", "").strip(),
            max_retries=min(5, _env_int("ALIREZA_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def __repr__(self) -> str:
        return f"AlirezaConfig(base_url={self.base_url!r}, timeout={self.timeout}, verify_tls={self.verify_tls})"


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class AlirezaProvider:
    name = "alireza"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30

    def __init__(self, config: Optional[AlirezaConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or AlirezaConfig.from_env()
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
                "NOT_CONFIGURED: ALIREZA_BASE_URL و ALIREZA_API_KEY تنظیم نشده‌اند؛ عملیات BLOCKED است.")

    # ---- HTTP -------------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل Alireza موقتاً در دسترس نیست (circuit open)")

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
        url = f"{self.config.base_url}/api{path}"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
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

            if resp.status_code == 401:
                raise ProviderAuthError("API Key نامعتبر یا منقضی شده (HTTP 401)")

            break

        self._breaker_record(True)

        if resp.status_code == 403:
            raise ProviderAuthError("دسترسی ناکافی (HTTP 403)")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر/منبع یافت نشد", status=404)
        if resp.status_code == 422:
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = resp.text
            raise ProviderRejectedError(f"پنل درخواست را رد کرد: {_clean(detail)}", status=422)

        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(
                f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code) from None

        return payload

    # ---- سلامت ------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/status")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound ----------------------------------------------------------
    def list_inbounds(self) -> list[dict]:
        try:
            data = self._request("GET", "/inbounds")
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    # ---- کلاینت -----------------------------------------------------------
    def _to_client_state(self, user_data: dict) -> ClientState:
        enable = user_data.get("enable", True)
        expiry = user_data.get("expiry_time", 0)
        # Detect if seconds or milliseconds
        expiry_ms = int(expiry * 1000) if expiry and expiry < 1e12 else int(expiry or 0)
        total_bytes = int(user_data.get("total_bytes", 0) or 0)
        used_bytes = int(user_data.get("used_bytes", 0) or 0)

        sub_id = user_data.get("sub_id", "")
        uuid = user_data.get("uuid", "")

        return ClientState(
            email=user_data.get("email", ""),
            enable=enable,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
            up_bytes=0,
            down_bytes=used_bytes,
            sub_id=str(sub_id),
            uuid=str(uuid),
            inbound_ids=tuple(user_data.get("inbound_ids", [])),
        )

    def get_traffic(self, email: str) -> Optional[ClientState]:
        try:
            user = self._request("GET", f"/client/{quote(email, safe='')}")
            return self._to_client_state(user)
        except ProviderRejectedError as e:
            if e.status == 404:
                return None
            raise

    def get_client(self, email: str) -> Optional[ClientState]:
        return self.get_traffic(email)

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        if not inbound_ids:
            raise ProviderRejectedError("حداقل یک inbound لازم است")

        client_data = {
            "email": spec.email,
            "uuid": spec.client_uuid or "",
            "enable": spec.enable,
            "expiry_time": int(spec.expiry_ms / 1000) if spec.expiry_ms > 0 else 0,
            "total_bytes": int(spec.total_bytes) if spec.total_bytes > 0 else 0,
            "inbound_ids": [int(i) for i in inbound_ids],
            "note": spec.comment or "",
        }

        self._request("POST", "/client", json_body=client_data)

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("کلاینت پس از ساخت قابل تأیید نبود")
        return created

    def _raw_record(self, email: str) -> dict:
        user = self._request("GET", f"/client/{quote(email, safe='')}")
        if not user:
            raise ProviderRejectedError("کلاینت یافت نشد", status=404)
        return user

    def update_client(self, email: str, **changes) -> ClientState:
        update_data = {}
        mapping = {
            "enable": "enable",
            "expiry_ms": "expiry_time",
            "total_bytes": "total_bytes",
            "limit_ip": "limit_ip",
            "comment": "note",
        }

        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")

            api_key = mapping[k]
            if k == "enable":
                update_data[api_key] = bool(v)
            elif k == "expiry_ms":
                update_data[api_key] = int(v / 1000) if v > 0 else 0
            elif k == "total_bytes":
                update_data[api_key] = int(v) if v > 0 else 0
            else:
                update_data[api_key] = v

        self._request("PUT", f"/client/{quote(email, safe='')}", json_body=update_data)

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("کلاینت پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        self._request("DELETE", f"/client/{quote(email, safe='')}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        if reset_traffic:
            try:
                self._request("POST", f"/client/{quote(email, safe='')}/reset")
            except VPNProviderError:
                pass
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        try:
            user = self._request("GET", f"/client/{quote(email, safe='')}")
            sub_url = user.get("subscription_url", "")
            if sub_url:
                return [sub_url]
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
            self._request("POST", f"/client/{quote(email, safe='')}/reset")
        except VPNProviderError:
            raise ProviderRejectedError("ریست ترافیک ناموفق بود")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> AlirezaProvider:
    return AlirezaProvider(AlirezaConfig.from_env())