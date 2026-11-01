"""
GhYiAb V2 — IBSng Provider Adapter (SOAP/REST)
===============================================

مرز معماری: V2 Core → VPNProvider → این Adapter → IBSng SOAP/REST API → Radius/Xray

IBSng یک سیستم بیلینگ و مدیریت ISP است که از SOAP API پشتیبانی می‌کند.
این adapter برای یکپارچه‌سازی با IBSng به عنوان پنل VPN طراحی شده.

مرجع API: IBSng SOAP API Documentation
واحدها: ترافیک بایت، expire بر اساس روز/ماه.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import requests
from requests.auth import HTTPBasicAuth

# Use defusedxml for secure XML parsing (prevents XXE attacks)
try:
    from defusedxml import ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET
    logger = logging.getLogger("ghyiab.providers.ibsng")
    logger.warning("defusedxml not installed, using stdlib XML parser (vulnerable to XXE)")

from providers.vpn.base import (
    ClientSpec, ClientState, NotConfiguredError, ProviderAuthError,
    ProviderRejectedError, ProviderUnavailableError, VPNProviderError,
)

logger = logging.getLogger("ghyiab.providers.ibsng")


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
class IBSngConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    domain: str = ""
    timeout: int = 30  # SOAP can be slower
    verify_tls: bool = True
    max_retries: int = 1  # SOAP operations shouldn't be retried as much
    use_soap: bool = True

    @classmethod
    def from_env(cls) -> "IBSngConfig":
        base = (os.getenv("IBSNG_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            username=os.getenv("IBSNG_USERNAME", "").strip(),
            password=os.getenv("IBSNG_PASSWORD", "").strip(),
            domain=os.getenv("IBSNG_DOMAIN", "").strip(),
            timeout=_env_int("IBSNG_TIMEOUT", default=30),
            verify_tls=_truthy(os.getenv("IBSNG_VERIFY_TLS", "1")),
            max_retries=min(3, _env_int("IBSNG_MAX_RETRIES", default=1)),
            use_soap=_truthy(os.getenv("IBSNG_USE_SOAP", "1")),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def __repr__(self) -> str:
        return f"IBSngConfig(base_url={self.base_url!r}, username={self.username!r}, use_soap={self.use_soap})"


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class IBSngProvider:
    name = "ibsng"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 60  # Longer cooldown for SOAP

    def __init__(self, config: Optional[IBSngConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or IBSngConfig.from_env()
        self._session = session or requests.Session()
        self._sleep = sleep
        self._lock = threading.Lock()
        self._fails = 0
        self._open_until = 0.0

        # Setup auth
        if self.config.use_soap:
            self._session.auth = HTTPBasicAuth(self.config.username, self.config.password)
        else:
            # REST API with token
            self._session.headers.update({"Authorization": f"Basic {base64.b64encode(f'{self.config.username}:{self.config.password}'.encode()).decode()}"})

    # ---- پیکربندی ---------------------------------------------------------
    def is_configured(self) -> bool:
        return self.config.is_configured

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise NotConfiguredError(
                "NOT_CONFIGURED: IBSNG_BASE_URL، IBSNG_USERNAME و IBSNG_PASSWORD تنظیم نشده‌اند؛ عملیات BLOCKED است.")

    # ---- HTTP/SOAP --------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل IBSng موقتاً در دسترس نیست (circuit open)")

    def _breaker_record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._fails = 0
                self._open_until = 0.0
            else:
                self._fails += 1
                if self._fails >= self.BREAKER_THRESHOLD:
                    self._open_until = time.monotonic() + self.BREAKER_COOLDOWN_S

    def _soap_request(self, method: str, params: dict) -> Any:
        """Send SOAP request to IBSng."""
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <{method} xmlns="http://tempuri.org/">
"""
        for key, value in params.items():
            soap_body += f"      <{key}>{value}</{key}>\n"
        soap_body += f"""    </{method}>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f"http://tempuri.org/{method}",
        }

        url = f"{self.config.base_url}/IBSng.asmx"
        attempts = self.config.max_retries + 1
        last_exc: Optional[Exception] = None

        for i in range(attempts):
            try:
                resp = self._session.post(url, data=soap_body.encode('utf-8'), headers=headers,
                                          timeout=self.config.timeout, verify=self.config.verify_tls)
            except requests.RequestException as exc:
                last_exc = ProviderUnavailableError(f"اتصال به پنل IBSng ناموفق ({type(exc).__name__})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(5.0, 1.0 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc from None

            if resp.status_code >= 500:
                last_exc = ProviderUnavailableError(f"خطای سرور پنل (HTTP {resp.status_code})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(5.0, 1.0 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc

            if resp.status_code == 401:
                raise ProviderAuthError("احراز هویت ناموفق (HTTP 401)")

            break

        self._breaker_record(True)

        if resp.status_code != 200:
            raise ProviderRejectedError(f"خطای HTTP {resp.status_code}", status=resp.status_code)

        # Parse SOAP response
        try:
            root = ET.fromstring(resp.content)
            # Find the result element
            ns = {"soap": "http://schemas.xmlsoap.org/soap/envelope/"}
            body = root.find("soap:Body", ns)
            if body is not None:
                result = body.find(f".//{{http://tempuri.org/}}{method}Result")
                if result is not None:
                    return result.text
            return resp.text
        except Exception as e:
            logger.warning("Failed to parse SOAP response: %s", e)
            return resp.text

    def _rest_request(self, method: str, path: str, *, json_body: Any = None, params: Any = None) -> Any:
        """Send REST request to IBSng (if available)."""
        self._require_configured()
        self._breaker_check()
        url = f"{self.config.base_url}/api{path}"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
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
                raise ProviderAuthError("توکن نامعتبر (HTTP 401)")

            break

        self._breaker_record(True)

        if resp.status_code == 403:
            raise ProviderAuthError("دسترسی ناکافی (HTTP 403)")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر/منبع یافت نشد", status=404)

        try:
            return resp.json()
        except ValueError:
            raise ProviderRejectedError("پاسخ نامعتبر از پنل", status=resp.status_code) from None

    def _call(self, method: str, **params) -> Any:
        """Call IBSng method via SOAP or REST."""
        if self.config.use_soap:
            return self._soap_request(method, params)
        else:
            return self._rest_request("POST", f"/{method}", json_body=params)

    # ---- سلامت ------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            # Try a simple SOAP call
            self._call("GetServerStatus")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound/Plans ----------------------------------------------------
    def list_inbounds(self) -> list[dict]:
        """Get ISP plans/packages from IBSng."""
        try:
            self._call("GetISPList")
            # Parse result to list of dicts
            # IBSng returns XML string, need to parse
            return []  # Simplified
        except VPNProviderError:
            return []

    # ---- کلاینت (User) ----------------------------------------------------
    def _to_client_state(self, user_data: dict) -> ClientState:
        enable = user_data.get("IsActive", True)
        expiry = user_data.get("ExpireDate", 0)
        total_bytes = int(user_data.get("TotalTraffic", 0) or 0)
        used_bytes = int(user_data.get("UsedTraffic", 0) or 0)

        return ClientState(
            email=user_data.get("UserName", ""),
            enable=enable,
            expiry_ms=int(expiry) if expiry else 0,
            total_bytes=total_bytes,
            up_bytes=0,
            down_bytes=used_bytes,
            sub_id="",
            uuid=user_data.get("UserId", ""),
            inbound_ids=(),
        )

    def get_traffic(self, username: str) -> Optional[ClientState]:
        try:
            self._call("GetUserDetails", UserName=username)
            # Parse XML result to dict
            # Simplified for now
            return None
        except ProviderRejectedError as e:
            if e.status == 404:
                return None
            raise

    def get_client(self, username: str) -> Optional[ClientState]:
        return self.get_traffic(username)

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        """Create user in IBSng."""
        # IBSng uses ISP packages, not inbound_ids directly
        # We need to map inbound_id to ISP package
        isp_name = str(inbound_ids[0]) if inbound_ids else "default"

        params = {
            "UserName": spec.email,
            "Password": spec.client_uuid or "auto",
            "ISPName": isp_name,
            "ExpireDate": self._ms_to_ibsng_date(spec.expiry_ms) if spec.expiry_ms > 0 else "",
            "TotalTraffic": int(spec.total_bytes) if spec.total_bytes > 0 else 0,
            "IsActive": spec.enable,
        }

        try:
            self._call("AddUser", **params)
        except VPNProviderError as e:
            raise ProviderRejectedError(f"ساخت کاربر در IBSng ناموفق: {_clean(e)}")

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("کاربر پس از ساخت قابل تأیید نبود")
        return created

    def _ms_to_ibsng_date(self, ms: int) -> str:
        """Convert milliseconds to IBSng date format."""
        from datetime import datetime
        dt = datetime.fromtimestamp(ms / 1000)
        return dt.strftime("%Y/%m/%d")

    def _raw_record(self, username: str) -> dict:
        result = self._call("GetUserDetails", UserName=username)
        if not result:
            raise ProviderRejectedError("کاربر یافت نشد", status=404)
        # Parse XML to dict - simplified
        return {"UserName": username}

    def update_client(self, email: str, **changes) -> ClientState:
        params = {"UserName": email}
        mapping = {
            "enable": "IsActive",
            "expiry_ms": "ExpireDate",
            "total_bytes": "TotalTraffic",
        }

        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")
            api_key = mapping[k]
            if k == "enable":
                params[api_key] = v
            elif k == "expiry_ms":
                params[api_key] = self._ms_to_ibsng_date(v) if v > 0 else ""
            elif k == "total_bytes":
                params[api_key] = int(v) if v > 0 else 0

        try:
            self._call("EditUser", **params)
        except VPNProviderError as e:
            raise ProviderRejectedError(f"بروزرسانی کاربر در IBSng ناموفق: {_clean(e)}")

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("کاربر پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        try:
            self._call("DeleteUser", UserName=email)
        except VPNProviderError as e:
            raise ProviderRejectedError(f"حذف کاربر در IBSng ناموفق: {_clean(e)}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        if reset_traffic:
            try:
                self._call("ResetUserTraffic", UserName=email)
            except VPNProviderError:
                pass
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        """IBSng doesn't provide subscription links directly."""
        return []

    def get_subscription_url(self, sub_id: str) -> Optional[str]:
        return None

    def reset_traffic(self, email: str) -> None:
        try:
            self._call("ResetUserTraffic", UserName=email)
        except VPNProviderError as e:
            raise ProviderRejectedError(f"ریست ترافیک در IBSng ناموفق: {_clean(e)}")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> IBSngProvider:
    return IBSngProvider(IBSngConfig.from_env())