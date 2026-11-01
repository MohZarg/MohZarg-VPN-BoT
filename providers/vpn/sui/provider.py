"""
GhYiAb V2 — S-UI Provider Adapter (REST API)
=============================================

مرز معماری: V2 Core → VPNProvider → این Adapter → S-UI REST API → Xray

S-UI (Sanaei UI) یک پنل مدیریت مبتنی بر Xray است که API مشابه 3x-ui دارد.

مرجع API: S-UI API — /api/docs (OpenAPI/Swagger)
واحدها: data_limit در پنل بایت است؛ expire epoch میلی‌ثانیه (Unix timestamp ms).
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

logger = logging.getLogger("ghyiab.providers.sui")


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
class SUIConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    timeout: int = 10
    verify_tls: bool = True
    sub_url_base: str = ""
    max_retries: int = 2

    # Cached token (session-based)
    _token: str = ""
    _token_expires: float = 0.0

    @classmethod
    def from_env(cls) -> "SUIConfig":
        base = (os.getenv("SUI_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            username=os.getenv("SUI_USERNAME", "").strip(),
            password=os.getenv("SUI_PASSWORD", "").strip(),
            timeout=_env_int("SUI_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("SUI_VERIFY_TLS", "1")),
            sub_url_base=os.getenv("SUI_SUB_URL_BASE", "").strip(),
            max_retries=min(5, _env_int("SUI_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def __repr__(self) -> str:
        return (f"SUIConfig(base_url={self.base_url!r}, username={self.username!r}, "
                f"timeout={self.timeout}, verify_tls={self.verify_tls})")


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class SUIProvider:
    name = "sui"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30
    TOKEN_BUFFER_S = 60

    def __init__(self, config: Optional[SUIConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or SUIConfig.from_env()
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
                "NOT_CONFIGURED: SUI_BASE_URL، SUI_USERNAME و SUI_PASSWORD تنظیم نشده‌اند؛ عملیات BLOCKED است.")

    # ---- Authentication ----------------------------------------------------
    def _get_token(self) -> str:
        """Get or refresh session token from S-UI."""
        now = time.monotonic()
        if self.config._token and now < self.config._token_expires - self.TOKEN_BUFFER_S:
            return self.config._token

        self._require_configured()
        url = f"{self.config.base_url}/login"
        data = {"username": self.config.username, "password": self.config.password}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            resp = self._session.post(url, data=data, headers=headers,
                                      timeout=self.config.timeout, verify=self.config.verify_tls)
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"اتصال به پنل S-UI ناموفق ({type(exc).__name__})") from exc

        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"خطای سرور پنل (HTTP {resp.status_code})")
        if resp.status_code in (401, 403):
            raise ProviderAuthError("نام کاربری یا رمز عبور S-UI نامعتبر است")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر login یافت نشد (آدرس پنل را بررسی کنید)", status=404)

        # S-UI uses session cookies, not JWT
        if "session" in self._session.cookies:
            self.config._token = self._session.cookies["session"]
            self.config._token_expires = now + 3600  # 1 hour default
            return self.config._token

        raise ProviderRejectedError("پنل نشست صادر نکرد", status=resp.status_code)

    # ---- HTTP -------------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل S-UI موقتاً در دسترس نیست (circuit open)")

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
        # S-UI uses /panel/api/... for admin endpoints
        url = f"{self.config.base_url}/panel/api{path}"
        headers = {"Accept": "application/json"}
        # S-UI uses cookie-based auth
        self._get_token()  # Ensure session is valid
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
                if i == 0:
                    self.config._token = ""
                    self.config._token_expires = 0.0
                    # Clear cookies
                    self._session.cookies.clear()
                    continue
                raise ProviderAuthError("نشست منقضی شده یا نامعتبر (HTTP 401)")

            break

        self._breaker_record(True)

        if resp.status_code == 403:
            raise ProviderAuthError("دسترسی ادمین ناکافی (HTTP 403)")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر/منبع یافت نشد", status=404)
        if resp.status_code == 422:
            try:
                detail = resp.json().get("msg", "")
            except Exception:
                detail = resp.text
            raise ProviderRejectedError(f"پنل درخواست را رد کرد: {_clean(detail)}", status=422)

        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(
                f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code) from None

        # S-UI returns {success: bool, msg: str, obj: data}
        if isinstance(payload, dict) and not payload.get("success", True):
            msg = payload.get("msg", "خطای ناشناخته")
            if "not found" in msg.lower() or "یافت نشد" in msg:
                raise ProviderRejectedError(msg, status=404)
            raise ProviderRejectedError(msg, status=422)

        return payload.get("obj", payload)

    # ---- سلامت ------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/server/get")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound ----------------------------------------------------------
    def list_inbounds(self) -> list[dict]:
        """Get all inbounds from S-UI."""
        try:
            data = self._request("GET", "/inbound/list")
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    # ---- کلاینت -----------------------------------------------------------
    def _to_client_state(self, client_data: dict, inbound_id: int) -> ClientState:
        """Convert S-UI client object to ClientState."""
        enable = client_data.get("enable", True)
        expiry = client_data.get("expiryTime", 0)
        # S-UI uses milliseconds
        expiry_ms = int(expiry) if expiry > 0 else 0
        total_bytes = int(client_data.get("totalGB", 0) or 0) * (1024 ** 3)
        up_bytes = int(client_data.get("up", 0) or 0)
        down_bytes = int(client_data.get("down", 0) or 0)

        sub_id = client_data.get("email", "")  # S-UI uses email as sub_id
        uuid = client_data.get("id", "")

        return ClientState(
            email=client_data.get("email", ""),
            enable=enable,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
            up_bytes=up_bytes,
            down_bytes=down_bytes,
            sub_id=str(sub_id),
            uuid=str(uuid),
            inbound_ids=(inbound_id,),
        )

    def get_traffic(self, email: str) -> Optional[ClientState]:
        """Get user traffic info from all inbounds."""
        inbounds = self.list_inbounds()
        for inbound in inbounds:
            try:
                clients = self._request("GET", f"/inbound/getClientTraffics/{inbound['id']}")
                for client in clients if isinstance(clients, list) else []:
                    if client.get("email") == email:
                        return self._to_client_state(client, inbound['id'])
            except VPNProviderError:
                continue
        return None

    def get_client(self, email: str) -> Optional[ClientState]:
        """Get full client info."""
        return self.get_traffic(email)

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        """Create a new user in S-UI."""
        if not inbound_ids:
            raise ProviderRejectedError("حداقل یک inbound لازم است")

        inbound_id = inbound_ids[0]  # S-UI adds to one inbound at a time

        client_data = {
            "id": spec.client_uuid or "",
            "email": spec.email,
            "enable": spec.enable,
            "expiryTime": spec.expiry_ms if spec.expiry_ms > 0 else 0,
            "totalGB": spec.total_bytes / (1024 ** 3) if spec.total_bytes > 0 else 0,
            "limitIp": 0,
            "subId": "",
            "flow": "",
            "tgId": "",
        }

        self._request("POST", f"/inbound/addClient/{inbound_id}", json_body=client_data)

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("کلاینت پس از ساخت قابل تأیید نبود")
        return created

    def _raw_record(self, email: str) -> tuple[dict, int]:
        """Get raw client record and inbound_id."""
        inbounds = self.list_inbounds()
        for inbound in inbounds:
            try:
                clients = self._request("GET", f"/inbound/getClientTraffics/{inbound['id']}")
                for client in clients if isinstance(clients, list) else []:
                    if client.get("email") == email:
                        return client, inbound['id']
            except VPNProviderError:
                continue
        raise ProviderRejectedError("کلاینت یافت نشد", status=404)

    def update_client(self, email: str, **changes) -> ClientState:
        """Update client in S-UI."""
        current, inbound_id = self._raw_record(email)

        update_data = {
            "id": current.get("id", ""),
            "email": email,
            "enable": current.get("enable", True),
            "expiryTime": current.get("expiryTime", 0),
            "totalGB": current.get("totalGB", 0),
            "limitIp": current.get("limitIp", 0),
        }

        mapping = {
            "enable": "enable",
            "expiry_ms": "expiryTime",
            "total_bytes": "totalGB",
            "limit_ip": "limitIp",
            "comment": "note",  # Not directly supported
        }

        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")

            api_key = mapping[k]
            if k == "enable":
                update_data[api_key] = bool(v)
            elif k == "expiry_ms":
                update_data[api_key] = int(v) if v > 0 else 0
            elif k == "total_bytes":
                update_data[api_key] = v / (1024 ** 3) if v > 0 else 0
            else:
                update_data[api_key] = v

        self._request("POST", f"/inbound/updateClient/{inbound_id}", json_body=update_data)

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("کلاینت پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        _, inbound_id = self._raw_record(email)
        self._request("POST", f"/inbound/delClient/{inbound_id}/{email}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        """Extend user with absolute expiry."""
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        if reset_traffic:
            # Reset traffic by updating up/down to 0
            current, inbound_id = self._raw_record(email)
            update_data = {
                "id": current.get("id", ""),
                "email": email,
                "enable": True,
                "expiryTime": int(new_expiry_ms),
                "totalGB": current.get("totalGB", 0),
                "limitIp": current.get("limitIp", 0),
                "up": 0,
                "down": 0,
            }
            self._request("POST", f"/inbound/updateClient/{inbound_id}", json_body=update_data)
            return self.get_client(email)
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        """Get subscription links for user."""
        try:
            # S-UI subscription is per inbound
            inbounds = self.list_inbounds()
            links = []
            for inbound in inbounds:
                sub = self._request("GET", f"/inbound/getSubscription/{inbound['id']}/{email}")
                if sub and isinstance(sub, str):
                    links.append(sub)
            return links
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
            current, inbound_id = self._raw_record(email)
            update_data = {
                "id": current.get("id", ""),
                "email": email,
                "enable": current.get("enable", True),
                "expiryTime": current.get("expiryTime", 0),
                "totalGB": current.get("totalGB", 0),
                "limitIp": current.get("limitIp", 0),
                "up": 0,
                "down": 0,
            }
            self._request("POST", f"/inbound/updateClient/{inbound_id}", json_body=update_data)
        except VPNProviderError:
            raise ProviderRejectedError("ریست ترافیک ناموفق بود")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> SUIProvider:
    return SUIProvider(SUIConfig.from_env())