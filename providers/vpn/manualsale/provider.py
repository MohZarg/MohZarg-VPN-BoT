"""
GhYiAb V2 — Manualsale Provider Adapter
========================================

مرز معماری: V2 Core → VPNProvider → این Adapter → Manualsale Panel API

Manualsale پنل فروش دستی/استوک است که از استوک کانفیگ‌ها استفاده می‌کند.
این پنل برای مدیریت استوک‌های آماده (pre-generated configs) طراحی شده.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import requests

from providers.vpn.base import (
    ClientSpec, ClientState, NotConfiguredError, ProviderAuthError,
    ProviderRejectedError, ProviderUnavailableError, VPNProviderError,
)

logger = logging.getLogger("ghyiab.providers.manualsale")


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
class ManualsaleConfig:
    base_url: str = ""
    api_key: str = ""
    timeout: int = 10
    verify_tls: bool = True
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "ManualsaleConfig":
        base = (os.getenv("MANUALSALE_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            api_key=os.getenv("MANUALSALE_API_KEY", "").strip(),
            timeout=_env_int("MANUALSALE_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("MANUALSALE_VERIFY_TLS", "1")),
            max_retries=min(5, _env_int("MANUALSALE_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def __repr__(self) -> str:
        return f"ManualsaleConfig(base_url={self.base_url!r}, timeout={self.timeout})"


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class ManualsaleProvider:
    name = "manualsale"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30

    def __init__(self, config: Optional[ManualsaleConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or ManualsaleConfig.from_env()
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
                "NOT_CONFIGURED: MANUALSALE_BASE_URL و MANUALSALE_API_KEY تنظیم نشده‌اند؛ عملیات BLOCKED است.")

    # ---- HTTP -------------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل Manualsale موقتاً در دسترس نیست (circuit open)")

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

    # ---- استوک (Stock) ----------------------------------------------------
    def list_stock(self, provider_id: Optional[int] = None, inbound_id: Optional[int] = None,
                   protocol: Optional[str] = None, unused_only: bool = True) -> list[dict]:
        """Get available stock configs."""
        params = {}
        if provider_id:
            params["provider_id"] = provider_id
        if inbound_id:
            params["inbound_id"] = inbound_id
        if protocol:
            params["protocol"] = protocol
        if unused_only:
            params["used"] = "false"

        try:
            data = self._request("GET", "/stock", params=params)
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    def reserve_stock(self, count: int, provider_id: int, inbound_id: int,
                      protocol: str) -> list[dict]:
        """Reserve stock configs for a user."""
        try:
            data = self._request("POST", "/stock/reserve", json_body={
                "count": count,
                "provider_id": provider_id,
                "inbound_id": inbound_id,
                "protocol": protocol,
            })
            return data if isinstance(data, list) else []
        except VPNProviderError as e:
            raise ProviderRejectedError(f"رزرو استوک ناموفق: {_clean(e)}")

    def release_stock(self, config_ids: list[int]) -> None:
        """Release reserved stock configs."""
        try:
            self._request("POST", "/stock/release", json_body={"config_ids": config_ids})
        except VPNProviderError as e:
            raise ProviderRejectedError(f"انتخاب استوک ناموفق: {_clean(e)}")

    # ---- سلامت ------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/health")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound (Not applicable for Manualsale) --------------------------
    def list_inbounds(self) -> list[dict]:
        """Manualsale doesn't manage inbounds directly."""
        return []

    # ---- کلاینت (Client - using stock) ------------------------------------
    def get_traffic(self, email: str) -> Optional[ClientState]:
        """Manualsale doesn't track traffic per client (uses pre-generated configs)."""
        return None

    def get_client(self, email: str) -> Optional[ClientState]:
        """Manualsale doesn't track clients in the traditional sense."""
        return None

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        """
        Manualsale: This means assigning a stock config to a user.
        Returns a ClientState with the config string.
        """
        # This should be called via National Net Stock service
        # which handles the stock reservation logic
        raise ProviderRejectedError("Manualsale: استفاده مستقیم create_client پشتیبانی نمی‌شود. از سرویس National Net Stock استفاده کنید.")

    def update_client(self, email: str, **changes) -> ClientState:
        raise ProviderRejectedError("Manualsale: بروزرسانی کلاینت مستقیم پشتیبانی نمی‌شود.")

    def delete_client(self, email: str) -> None:
        raise ProviderRejectedError("Manualsale: حذف کلاینت مستقیم پشتیبانی نمی‌شود.")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        raise ProviderRejectedError("Manualsale: تمدید مستقیم پشتیبانی نمی‌شود.")

    def get_links(self, email: str) -> list[str]:
        """Manualsale provides config strings, not subscription links."""
        return []

    def get_subscription_url(self, sub_id: str) -> Optional[str]:
        return None

    def reset_traffic(self, email: str) -> None:
        raise ProviderRejectedError("Manualsale: ریست ترافیک مستقیم پشتیبانی نمی‌شود.")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        raise ProviderRejectedError("Manualsale: تغییر وضعیت مستقیم پشتیبانی نمی‌شود.")


def build_default_provider() -> ManualsaleProvider:
    return ManualsaleProvider(ManualsaleConfig.from_env())