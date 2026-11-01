"""
GhYiAb V2 — Guard Provider Adapter (REST API)
==============================================

مرز معماری: V2 Core → VPNProvider → این Adapter → Guard REST API → Xray/Sing-box

Guard یک پنل مدیریت VPN ایرانی است که از Xray/Sing-box پشتیبانی می‌کند.
API شبیه به 3x-ui/Marzban است.
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

logger = logging.getLogger("ghyiab.providers.guard")


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
class GuardConfig:
    base_url: str = ""
    api_token: str = ""
    timeout: int = 10
    verify_tls: bool = True
    sub_url_base: str = ""
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "GuardConfig":
        base = (os.getenv("GUARD_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            api_token=os.getenv("GUARD_API_TOKEN", "").strip(),
            timeout=_env_int("GUARD_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("GUARD_VERIFY_TLS", "1")),
            sub_url_base=os.getenv("GUARD_SUB_URL_BASE", "").strip(),
            max_retries=min(5, _env_int("GUARD_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_token)

    def __repr__(self) -> str:
        return (f"GuardConfig(base_url={self.base_url!r}, api_token={'***' if self.api_token else ''!r}, "
                f"timeout={self.timeout}, verify_tls={self.verify_tls})")


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class GuardProvider:
    name = "guard"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30

    def __init__(self, config: Optional[GuardConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or GuardConfig.from_env()
        self._session = session or requests.Session()
        self._sleep = sleep
        self._lock = threading.Lock()
        self._fails = 0
        self._open_until = 0.0

    def is_configured(self) -> bool:
        return self.config.is_configured

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise NotConfiguredError("NOT_CONFIGURED: GUARD_BASE_URL و GUARD_API_TOKEN تنظیم نشده‌اند.")

    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل Guard موقتاً در دسترس نیست (circuit open)")

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
        headers = {"Authorization": f"Bearer {self.config.api_token}", "Accept": "application/json"}
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
            raise ProviderAuthError(f"توکن نامعتبر یا بدون دسترسی (HTTP {resp.status_code})")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر/منبع یافت نشد", status=404)

        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(
                f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code) from None

        if isinstance(payload, dict) and not payload.get("success", True):
            raise ProviderRejectedError(
                f"پنل درخواست را رد کرد: {_clean(payload.get('msg', payload.get('message', '')))}",
                status=resp.status_code)

        return payload.get("data", payload) if isinstance(payload, dict) else payload

    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/system/status")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    def list_inbounds(self) -> list[dict]:
        try:
            data = self._request("GET", "/inbounds")
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    def _to_client_state(self, user_data: dict) -> ClientState:
        enable = user_data.get("enable", True)
        expiry_ms = int(user_data.get("expiry_time", user_data.get("expiryTime", 0)) or 0)
        total_bytes = int(user_data.get("total_gb", user_data.get("totalGB", 0)) or 0) * 1024 * 1024 * 1024
        up_bytes = int(user_data.get("up", 0) or 0)
        down_bytes = int(user_data.get("down", 0) or 0)

        return ClientState(
            email=user_data.get("email", user_data.get("username", "")),
            enable=enable,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
            up_bytes=up_bytes,
            down_bytes=down_bytes,
            sub_id=user_data.get("sub_id", user_data.get("subId", "")) or "",
            uuid=user_data.get("uuid", "") or "",
            inbound_ids=tuple(user_data.get("inbound_ids", [])) if user_data.get("inbound_ids") else (),
        )

    def get_traffic(self, email: str) -> Optional[ClientState]:
        try:
            user = self._request("GET", f"/clients/{quote(email, safe='')}")
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

        client = {
            "email": spec.email,
            "uuid": spec.client_uuid or str(_uuid.uuid4()),
            "sub_id": spec.sub_id,
            "enable": spec.enable,
            "total_gb": int(spec.total_bytes / (1024*1024*1024)) if spec.total_bytes > 0 else 0,
            "expiry_time": int(spec.expiry_ms),
            "limit_ip": int(spec.limit_ip),
            "tg_id": int(spec.telegram_id),
            "comment": spec.comment,
            "inbound_ids": list(inbound_ids),
        }

        self._request("POST", "/clients", json_body=client)

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("کلاینت پس از ساخت قابل تأیید نبود")
        return created

    def _raw_record(self, email: str) -> dict:
        user = self._request("GET", f"/clients/{quote(email, safe='')}")
        if not user:
            raise ProviderRejectedError("کلاینت یافت نشد", status=404)
        return user

    def update_client(self, email: str, **changes) -> ClientState:
        obj = self._raw_record(email)
        body = {k: obj[k] for k in ("email", "uuid", "sub_id", "enable", "total_gb", "expiry_time",
                                     "limit_ip", "tg_id", "comment", "inbound_ids") if k in obj}
        mapping = {"enable": "enable", "expiry_ms": "expiry_time", "total_bytes": "total_gb",
                   "limit_ip": "limit_ip", "comment": "comment"}
        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")
            body[mapping[k]] = v
        self._request("PUT", f"/clients/{quote(email, safe='')}", json_body=body)

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("کلاینت پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        self._request("DELETE", f"/clients/{quote(email, safe='')}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        if reset_traffic:
            try:
                self._request("POST", f"/clients/{quote(email, safe='')}/reset")
            except VPNProviderError:
                pass
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        try:
            obj = self._request("GET", f"/clients/{quote(email, safe='')}/links")
            return [str(x) for x in (obj or []) if isinstance(x, str)]
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
            self._request("POST", f"/clients/{quote(email, safe='')}/reset")
        except VPNProviderError:
            raise ProviderRejectedError("ریست ترافیک ناموفق بود")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> GuardProvider:
    return GuardProvider(GuardConfig.from_env())