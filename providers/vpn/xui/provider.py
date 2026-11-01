"""
GhYiAb V2 — 3x-ui Provider Adapter (REST API مدرن)
====================================================

مرز معماری:  V2 Core → VPNProvider → این Adapter → 3x-ui REST API → Xray

قواعد سخت
---------
- فقط از طریق REST API پنل (``/panel/api/...``) با توکن Bearer. هرگز به
  دیتابیس 3x-ui، فایل‌های داخلی آن (``/etc/x-ui``) یا مستقیماً به Xray دسترسی ندارد.
- تغییر مکان 3x-ui به سرور دیگر = فقط تغییر ``XUI_BASE_URL`` (و توکن).
- NOT_CONFIGURED/BLOCKED هرگز شبیه‌سازی نمی‌شود: ``NotConfiguredError``.
- توکن هرگز لاگ/نمایش داده نمی‌شود؛ پیام خطاها فقط وضعیت HTTP و ``msg`` پنل را
  دارند (``msg`` کوتاه و پاک‌سازی می‌شود).
- Retry محدود و Exponential backoff فقط برای درخواست‌های GET (بی‌اثر). POSTهای
  تغییردهنده (create/update/delete) خودکار Retry نمی‌شوند؛ Idempotency در لایهٔ core
  (ایمیل قطعی + adopt-if-exists + مقدار مطلق انقضا) تأمین می‌شود.
- Circuit breaker سبک: پس از N شکست پیاپی، تا پایان Cooldown درخواست جدید به پنلِ
  خراب فرستاده نمی‌شود (کاهش بار/تایم‌اوت‌های پشت‌سرهم روی VPS ارزان).

مرجع API: 3x-ui v3.x — ``internal/web/controller/client.go`` و ``inbound.go``.
واحدها: ``totalGB`` در پنل **بایت** است (با وجود نام)؛ ``expiryTime`` epoch میلی‌ثانیه.

متغیرهای محیطی
--------------
XUI_BASE_URL     مثال: https://panel.example.com:2053/secretpath  (الزامی)
XUI_API_TOKEN    توکن API با scope ادمین (الزامی)
XUI_TIMEOUT      ثانیه، پیش‌فرض 10
XUI_VERIFY_TLS   پیش‌فرض 1 (فقط برای تست لوکال self-signed → 0)
XUI_SUB_URL_BASE اختیاری؛ پایهٔ لینک ساب‌اسکریپشن (subId به انتها اضافه می‌شود)
XUI_MAX_RETRIES  پیش‌فرض 2 (فقط GET)
(نام‌های قدیمی XUI_PANEL_URL / XUI_PANEL_TIMEOUT هنوز به‌عنوان Fallback خوانده می‌شوند.)
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

logger = logging.getLogger("ghyiab.providers.xui")

# سازگاری با نام‌های قبلی (core/provisioning و تست‌های قدیمی)
XuiProviderError = VPNProviderError
XuiNotConfiguredError = NotConfiguredError

# فقط فیلدهایی که هنگام Read-Modify-Write به پنل پس فرستاده می‌شوند (جلوگیری از
# صفر شدن ناخواستهٔ فیلدهایی مثل flow/security در update).
_ROUNDTRIP_FIELDS = (
    "email", "subId", "password", "auth", "flow", "security", "limitIp", "totalGB",
    "expiryTime", "enable", "tgId", "group", "comment", "reset", "resetDay",
    "resetWeekday", "resetMax", "trafficReset",
)


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
class XuiConfig:
    base_url: str = ""
    api_token: str = ""
    timeout: int = 10
    verify_tls: bool = True
    sub_url_base: str = ""
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "XuiConfig":
        base = (os.getenv("XUI_BASE_URL") or os.getenv("XUI_PANEL_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            api_token=os.getenv("XUI_API_TOKEN", "").strip(),
            timeout=_env_int("XUI_TIMEOUT", "XUI_PANEL_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("XUI_VERIFY_TLS", "1")),
            sub_url_base=os.getenv("XUI_SUB_URL_BASE", "").strip(),
            max_retries=min(5, _env_int("XUI_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_token)

    def __repr__(self) -> str:  # هرگز توکن در repr/لاگ نیاید
        return (f"XuiConfig(base_url={self.base_url!r}, api_token={'***' if self.api_token else ''!r}, "
                f"timeout={self.timeout}, verify_tls={self.verify_tls})")


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@\u0600-\u06FF]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class ThreeXUIProvider:
    name = "3x-ui"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30

    def __init__(self, config: Optional[XuiConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or XuiConfig.from_env()
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
                "NOT_CONFIGURED: XUI_BASE_URL و XUI_API_TOKEN تنظیم نشده‌اند؛ عملیات BLOCKED است.")

    # ---- HTTP -------------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل 3x-ui موقتاً در دسترس نیست (circuit open)")

    def _breaker_record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._fails = 0
                self._open_until = 0.0
            else:
                self._fails += 1
                if self._fails >= self.BREAKER_THRESHOLD:
                    self._open_until = time.monotonic() + self.BREAKER_COOLDOWN_S

    def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        """خروجی: فیلد ``obj`` پاسخ پنل. هر شکست → استثنای typed (هرگز None جعلی)."""
        self._require_configured()
        self._breaker_check()
        url = f"{self.config.base_url}/panel/api{path}"
        headers = {"Authorization": f"Bearer {self.config.api_token}", "Accept": "application/json"}
        attempts = (self.config.max_retries + 1) if method == "GET" else 1
        last_exc: Optional[Exception] = None
        for i in range(attempts):
            try:
                resp = self._session.request(
                    method, url, json=json_body, headers=headers,
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
            raise ProviderRejectedError("مسیر/منبع یافت نشد (آدرس پنل یا نسخهٔ 3x-ui را بررسی کنید)", status=404)
        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(
                f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code) from None
        if not isinstance(payload, dict) or not payload.get("success", False):
            raise ProviderRejectedError(
                f"پنل درخواست را رد کرد: {_clean(payload.get('msg') if isinstance(payload, dict) else '')}",
                status=resp.status_code)
        return payload.get("obj")

    # ---- سلامت ------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/inbounds/list/slim")
        except ProviderRejectedError:
            try:  # نسخه‌های قدیمی‌تر endpoint slim ندارند
                self._request("GET", "/inbounds/list")
            except VPNProviderError as exc:
                return {"status": "BLOCKED", "detail": _clean(exc)}
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound ----------------------------------------------------------
    def list_inbounds(self) -> list[dict]:
        obj = self._request("GET", "/inbounds/list/slim")
        return obj or []

    # ---- کلاینت -----------------------------------------------------------
    def get_traffic(self, email: str) -> Optional[ClientState]:
        """یک درخواست سبک؛ ``None`` یعنی پنل صراحتاً کلاینتی با این ایمیل ندارد
        (``obj=null`` با success=true — رفتار مستند 3x-ui)، نه خطا."""
        t = self._request("GET", f"/clients/traffic/{quote(email, safe='')}")
        if not t:
            return None
        return ClientState(
            email=t.get("email", email), enable=bool(t.get("enable", False)),
            expiry_ms=int(t.get("expiryTime", 0) or 0), total_bytes=int(t.get("total", 0) or 0),
            up_bytes=int(t.get("up", 0) or 0), down_bytes=int(t.get("down", 0) or 0),
            sub_id=t.get("subId", "") or "", uuid=t.get("uuid", "") or "")

    def get_client(self, email: str) -> Optional[ClientState]:
        traffic = self.get_traffic(email)
        if traffic is None:
            return None
        obj = self._request("GET", f"/clients/get/{quote(email, safe='')}")
        rec = (obj or {}).get("client") or {}
        return ClientState(
            email=traffic.email, enable=bool(rec.get("enable", traffic.enable)),
            expiry_ms=int(rec.get("expiryTime", traffic.expiry_ms) or 0),
            total_bytes=int(rec.get("totalGB", traffic.total_bytes) or 0),
            up_bytes=traffic.up_bytes, down_bytes=traffic.down_bytes,
            sub_id=rec.get("subId", traffic.sub_id) or "", uuid=rec.get("uuid") or traffic.uuid,
            inbound_ids=tuple((obj or {}).get("inboundIds") or ()))

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        if not inbound_ids:
            raise ProviderRejectedError("حداقل یک inbound لازم است")
        client = {
            "id": spec.client_uuid or str(_uuid.uuid4()), "email": spec.email, "subId": spec.sub_id,
            "enable": spec.enable, "totalGB": int(spec.total_bytes), "expiryTime": int(spec.expiry_ms),
            "limitIp": int(spec.limit_ip), "tgId": int(spec.telegram_id), "comment": spec.comment,
        }
        self._request("POST", "/clients/add", json_body={"client": client, "inboundIds": list(inbound_ids)})
        created = self.get_client(spec.email)
        if created is None:
            # پنل success داد ولی کلاینت قابل خواندن نیست → موفقیت فرض نمی‌شود.
            raise ProviderUnavailableError("کلاینت پس از ساخت قابل تأیید نبود")
        return created

    def _raw_record(self, email: str) -> dict:
        obj = self._request("GET", f"/clients/get/{quote(email, safe='')}")
        if not obj or not obj.get("client"):
            raise ProviderRejectedError("کلاینت یافت نشد", status=404)
        return obj

    def update_client(self, email: str, **changes) -> ClientState:
        """Read-Modify-Write. کلیدهای مجاز: enable, expiry_ms, total_bytes, limit_ip, comment."""
        obj = self._raw_record(email)
        rec = obj["client"]
        body = {k: rec[k] for k in _ROUNDTRIP_FIELDS if k in rec}
        body["id"] = rec.get("uuid") or rec.get("id") or ""
        mapping = {"enable": "enable", "expiry_ms": "expiryTime", "total_bytes": "totalGB",
                   "limit_ip": "limitIp", "comment": "comment"}
        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")
            body[mapping[k]] = v
        self._request("POST", f"/clients/update/{quote(email, safe='')}", json_body=body)
        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("کلاینت پس از بروزرسانی قابل تأیید نبود")
        for k, v in changes.items():  # تأیید واقعی، نه اعتماد کورکورانه
            attr = {"enable": "enable", "expiry_ms": "expiry_ms", "total_bytes": "total_bytes"}.get(k)
            if attr and getattr(fresh, attr) != v:
                raise ProviderUnavailableError(f"تغییر {k} روی پنل اعمال نشد")
        return fresh

    def delete_client(self, email: str) -> None:
        self._request("POST", f"/clients/del/{quote(email, safe='')}")

    def reset_traffic(self, email: str) -> None:
        self._request("POST", f"/clients/resetTraffic/{quote(email, safe='')}")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        """
        تمدید با مقدار **مطلق** انقضا → Retry امن است (اجرای دوباره همان نتیجه را می‌دهد).
        ترتیب: ابتدا Reset ترافیک (در صورت نیاز) سپس تنظیم انقضا/سقف/enable — اگر
        مرحلهٔ دوم شکست بخورد استثنا بالا می‌رود و core سرویس را «تمدیدشده» ثبت نمی‌کند.
        """
        if reset_traffic:
            self.reset_traffic(email)
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        return self.update_client(email, **changes)

    # ---- لینک‌ها ----------------------------------------------------------
    def get_links(self, email: str) -> list[str]:
        obj = self._request("GET", f"/clients/links/{quote(email, safe='')}")
        return [str(x) for x in (obj or []) if isinstance(x, str)]

    def get_subscription_url(self, sub_id: str) -> Optional[str]:
        """لینک ساب‌اسکریپشن فقط وقتی XUI_SUB_URL_BASE تنظیم شده؛ حدس زده نمی‌شود."""
        base = self.config.sub_url_base
        if not base or not sub_id:
            return None
        return base.rstrip("/") + "/" + quote(sub_id, safe="")


def new_sub_id() -> str:
    return _uuid.uuid4().hex[:16]


def build_default_provider() -> ThreeXUIProvider:
    return ThreeXUIProvider(XuiConfig.from_env())
