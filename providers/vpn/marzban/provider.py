"""
GhYiAb V2 — Marzban Provider Adapter (REST API)
================================================

مرز معماری: V2 Core → VPNProvider → این Adapter → Marzban REST API → Xray

قواعد سخت
---------
- فقط از طریق REST API پنل (``/api/...``) با توکن Bearer (JWT).
- تغییر مکان Marzban به سرور دیگر = فقط تغییر ``MARZBAN_BASE_URL`` (و توکن).
- NOT_CONFIGURED/BLOCKED هرگز شبیه‌سازی نمی‌شود: ``NotConfiguredError``.
- توکن هرگز لاگ/نمایش داده نمی‌شود؛ پیام خطاها فقط وضعیت HTTP و ``detail`` پنل را دارند.
- Retry محدود و Exponential backoff فقط برای درخواست‌های GET (بی‌اثر). POSTهای
  تغییردهنده (create/update/delete) خودکار Retry نمی‌شوند؛ Idempotency در لایهٔ core
  (ایمیل قطعی + adopt-if-exists + مقدار مطلق انقضا) تأمین می‌شود.
- Circuit breaker سبک: پس از N شکست پیاپی، تا پایان Cooldown درخواست جدید به پنلِ
  خراب فرستاده نمی‌شود.

مرجع API: Marzban API — ``/api/docs`` (OpenAPI/Swagger)
واحدها: ``data_limit`` در پنل **بایت** است؛ ``expire`` epoch ثانیه (Unix timestamp).
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

logger = logging.getLogger("ghyiab.providers.marzban")


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
class MarzbanConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    timeout: int = 10
    verify_tls: bool = True
    sub_url_base: str = ""
    max_retries: int = 2

    # Cached JWT token
    _token: str = ""
    _token_expires: float = 0.0

    @classmethod
    def from_env(cls) -> "MarzbanConfig":
        base = (os.getenv("MARZBAN_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            username=os.getenv("MARZBAN_USERNAME", "").strip(),
            password=os.getenv("MARZBAN_PASSWORD", "").strip(),
            timeout=_env_int("MARZBAN_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("MARZBAN_VERIFY_TLS", "1")),
            sub_url_base=os.getenv("MARZBAN_SUB_URL_BASE", "").strip(),
            max_retries=min(5, _env_int("MARZBAN_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def __repr__(self) -> str:
        return (f"MarzbanConfig(base_url={self.base_url!r}, username={self.username!r}, "
                f"timeout={self.timeout}, verify_tls={self.verify_tls})")


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class MarzbanProvider:
    name = "marzban"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30
    TOKEN_BUFFER_S = 60  # Refresh token 60s before expiry

    def __init__(self, config: Optional[MarzbanConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or MarzbanConfig.from_env()
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
                "NOT_CONFIGURED: MARZBAN_BASE_URL، MARZBAN_USERNAME و MARZBAN_PASSWORD تنظیم نشده‌اند؛ عملیات BLOCKED است.")

    # ---- Authentication ----------------------------------------------------
    def _get_token(self) -> str:
        """Get or refresh JWT token from Marzban."""
        now = time.monotonic()
        if self.config._token and now < self.config._token_expires - self.TOKEN_BUFFER_S:
            return self.config._token

        self._require_configured()
        url = f"{self.config.base_url}/api/admin/token"
        data = {"username": self.config.username, "password": self.config.password}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            resp = self._session.post(url, data=data, headers=headers,
                                      timeout=self.config.timeout, verify=self.config.verify_tls)
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"اتصال به پنل Marzban ناموفق ({type(exc).__name__})") from exc

        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"خطای سرور پنل (HTTP {resp.status_code})")
        if resp.status_code in (401, 403):
            raise ProviderAuthError("نام کاربری یا رمز عبور Marzban نامعتبر است")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر API یافت نشد (آدرس پنل یا نسخه Marzban را بررسی کنید)", status=404)

        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code)

        if not isinstance(payload, dict) or "access_token" not in payload:
            raise ProviderRejectedError(
                f"پنل توکن صادر نکرد: {_clean(payload.get('detail') if isinstance(payload, dict) else '')}",
                status=resp.status_code)

        # Token expires in ~30 minutes (1800s) by default
        expires_in = payload.get("expires_in", 1800)
        self.config._token = payload["access_token"]
        self.config._token_expires = now + expires_in
        return self.config._token

    # ---- HTTP -------------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل Marzban موقتاً در دسترس نیست (circuit open)")

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
        """خروجی: فیلد داده پاسخ پنل. هر شکست → استثنای typed."""
        self._require_configured()
        self._breaker_check()
        url = f"{self.config.base_url}/api{path}"
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
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
                # Token might have expired, force refresh and retry once
                if i == 0:
                    self.config._token = ""
                    self.config._token_expires = 0.0
                    continue
                raise ProviderAuthError("توکن منقضی شده یا نامعتبر (HTTP 401)")

            break

        self._breaker_record(True)

        if resp.status_code == 403:
            raise ProviderAuthError("دسترسی ادمین ناکافی (HTTP 403)")
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
            self._request("GET", "/api/system/status")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound ----------------------------------------------------------
    def list_inbounds(self) -> list[dict]:
        """Get all inbounds from Marzban."""
        try:
            data = self._request("GET", "/api/inbounds")
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    # ---- کلاینت -----------------------------------------------------------
    def _to_client_state(self, user_data: dict) -> ClientState:
        """Convert Marzban user object to ClientState."""
        # Marzban returns: username, status, used_traffic, data_limit, expire, inbounds, etc.
        enable = user_data.get("status", "active") == "active"
        expiry = user_data.get("expire", 0)
        # Convert to milliseconds if in seconds
        expiry_ms = int(expiry * 1000) if expiry and expiry < 1e12 else int(expiry or 0)
        total_bytes = int(user_data.get("data_limit", 0) or 0)
        used_bytes = int(user_data.get("used_traffic", 0) or 0)

        # Get sub_id from subscription_url if available
        sub_id = ""
        sub_url = user_data.get("subscription_url", "")
        if sub_url:
            sub_id = sub_url.rstrip("/").split("/")[-1]

        return ClientState(
            email=user_data.get("username", ""),
            enable=enable,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
            up_bytes=0,  # Marzban doesn't separate up/down in user list
            down_bytes=used_bytes,
            sub_id=sub_id,
            uuid=user_data.get("uuid", "") or "",
            inbound_ids=tuple(user_data.get("inbounds", {}).keys()) if user_data.get("inbounds") else (),
        )

    def get_traffic(self, email: str) -> Optional[ClientState]:
        """Get user traffic info."""
        try:
            user = self._request("GET", f"/api/user/{quote(email, safe='')}")
            return self._to_client_state(user)
        except ProviderRejectedError as e:
            if e.status == 404:
                return None
            raise

    def get_client(self, email: str) -> Optional[ClientState]:
        """Get full client info."""
        return self.get_traffic(email)

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        """Create a new user in Marzban."""
        if not inbound_ids:
            raise ProviderRejectedError("حداقل یک inbound لازم است")

        # Marzban uses inbound names, not IDs. We'll pass the inbound names.
        # For now, we'll use the inbound IDs as names (common pattern).
        inbound_names = [str(i) for i in inbound_ids]

        user_data = {
            "username": spec.email,
            "proxies": {
                "vmess": {},
                "vless": {},
                "trojan": {},
                "shadowsocks": {},
            },
            "inbounds": inbound_names,
            "expire": int(spec.expiry_ms / 1000) if spec.expiry_ms > 0 else 0,
            "data_limit": int(spec.total_bytes) if spec.total_bytes > 0 else 0,
            "data_limit_reset_strategy": "no_reset",
            "note": spec.comment or "",
            "status": "active" if spec.enable else "disabled",
        }

        # Generate UUID if not provided
        if spec.client_uuid:
            user_data["uuid"] = spec.client_uuid

        self._request("POST", "/api/user", json_body=user_data)

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("کلاینت پس از ساخت قابل تأیید نبود")
        return created

    def _raw_record(self, email: str) -> dict:
        user = self._request("GET", f"/api/user/{quote(email, safe='')}")
        if not user:
            raise ProviderRejectedError("کلاینت یافت نشد", status=404)
        return user

    def update_client(self, email: str, **changes) -> ClientState:
        """Update client in Marzban (PATCH)."""
        # Build update payload - Marzban uses PATCH with only changed fields
        update_data = {}
        mapping = {
            "enable": "status",
            "expiry_ms": "expire",
            "total_bytes": "data_limit",
            "limit_ip": "limit_ip",  # Not directly supported, would need custom field
            "comment": "note",
        }

        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")

            api_key = mapping[k]
            if k == "enable":
                update_data[api_key] = "active" if v else "disabled"
            elif k == "expiry_ms":
                update_data[api_key] = int(v / 1000) if v > 0 else 0
            elif k == "total_bytes":
                update_data[api_key] = int(v) if v > 0 else 0
            else:
                update_data[api_key] = v

        self._request("PUT", f"/api/user/{quote(email, safe='')}", json_body=update_data)

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("کلاینت پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        self._request("DELETE", f"/api/user/{quote(email, safe='')}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        """Extend user with absolute expiry."""
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        if reset_traffic:
            # Marzban: reset traffic by setting data_limit to current limit (no change)
            # but we can use the reset endpoint
            try:
                self._request("POST", f"/api/user/{quote(email, safe='')}/reset")
            except VPNProviderError:
                pass  # Ignore reset failure, continue with renew
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        """Get subscription links for user."""
        try:
            user = self._request("GET", f"/api/user/{quote(email, safe='')}")
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
            self._request("POST", f"/api/user/{quote(email, safe='')}/reset")
        except VPNProviderError:
            raise ProviderRejectedError("ریست ترافیک ناموفق بود")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> MarzbanProvider:
    return MarzbanProvider(MarzbanConfig.from_env())