"""
GhYiAb V2 — VPN Service Lifecycle (وضعیت، ترافیک، لینک، تمدید، تمدید خودکار، عملیات ادمین)
==========================================================================================

وضعیت‌ها: PENDING | ACTIVE | EXPIRED | SUSPENDED | FAILED | CANCELLED
(PENDING/FAILED/ACTIVE/CANCELLED در DB؛ EXPIRED/SUSPENDED هم ذخیره می‌شوند و هم
هنگام همگام‌سازی زنده از پنل مشتق می‌شوند.)

اصل‌ها:
- هیچ تماس شبکه‌ای داخل تراکنش DB انجام نمی‌شود (قفل نوشتن SQLite).
- شکست Provider هرگز موفقیت نمی‌شود: در نمایش، «cached» با ``live=False`` برچسب می‌خورد.
- تمدید دو‌فازی و Idempotent:
    فاز۱ (تراکنش): کسر اتمیک کیف پول + ثبت ``service_renewals(CHARGED)`` با انقضای *مطلق*
    فاز۲ (بدون تراکنش): Provider.renew_client(مقدار مطلق)
    فاز۳ (تراکنش): COMPLETED + انقضای جدید  |  رد قطعی پنل → بازپرداخت اتمیک (REFUNDED)
  خطای مبهم (timeout/۵xx) → CHARGED می‌ماند و ``recover_stuck_renewals`` دوباره تلاش می‌کند
  (مقدار مطلق ⇒ تکرار بی‌خطر)؛ فقط پس از ``REFUND_AFTER_MINUTES`` بازپرداخت می‌شود.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.audit import service as audit_service
from core.auth import rbac
from core.errors import (
    ConflictError, InsufficientBalanceError, NotFoundError,
    ProviderNotReadyError, ProvisioningFailedError, ValidationError,
)
from core.provisioning import service as prov
from core.settings import service as settings_service
from core.wallet import service as wallet_service
from providers.vpn.base import (
    NotConfiguredError, ProviderRejectedError, ProviderAuthError, VPNProviderError,
)

logger = logging.getLogger("ghyiab.vpn_services")

DAY_MS = 86400 * 1000
BYTES_PER_GB = 1024 ** 3
REFUND_AFTER_MINUTES = 60 * 24
RENEWABLE = ("ACTIVE", "EXPIRED", "SUSPENDED")


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ServiceView:
    order_id: int
    product_name: str
    state: str
    email: str
    expires_at_ms: int
    total_bytes: int
    used_bytes: int
    live: bool
    auto_renew: bool
    error: Optional[str] = None
    synced_at: Optional[str] = None
    enabled: bool = True

    @property
    def remaining_bytes(self) -> Optional[int]:
        return None if self.total_bytes <= 0 else max(0, self.total_bytes - self.used_bytes)

    @property
    def remaining_days(self) -> Optional[int]:
        if self.expires_at_ms <= 0:
            return None
        return max(0, int((self.expires_at_ms - now_ms()) // DAY_MS))


def derive_state(db_status: str, *, enabled: bool, expires_at_ms: int, used: int, total: int,
                 at_ms: Optional[int] = None) -> str:
    """مشتق‌سازی خالص (بدون I/O) — قابل تست."""
    if db_status in ("PENDING", "FAILED", "CANCELLED"):
        return db_status
    at = at_ms if at_ms is not None else now_ms()
    if expires_at_ms > 0 and at >= expires_at_ms:
        return "EXPIRED"
    if total > 0 and used >= total:
        return "SUSPENDED"  # حجم تمام شد
    if not enabled:
        return "SUSPENDED"
    return "ACTIVE" if db_status in ("ACTIVE", "EXPIRED", "SUSPENDED") else db_status


# --------------------------------------------------------------------------
# مشاهده
# --------------------------------------------------------------------------

def _product_name(uow, order) -> str:
    p = uow.products.get(order.product_id)
    return p.name if p else f"#{order.product_id}"


def list_user_services(uow, user_id: int) -> list[ServiceView]:
    """فقط DB (بدون تماس با پنل) → سریع و کم‌هزینه؛ جزئیات زنده در get_service_view."""
    out = []
    for rec in uow.provisioning.list_by_user(user_id):
        order = uow.orders.get_by_id(rec.order_id)
        if order is None:
            continue
        state = derive_state(rec.status, enabled=rec.status != "SUSPENDED", expires_at_ms=rec.expires_at_ms,
                             used=rec.cached_used_bytes, total=rec.cached_total_bytes)
        out.append(ServiceView(
            order_id=rec.order_id, product_name=_product_name(uow, order), state=state, email=rec.email,
            expires_at_ms=rec.expires_at_ms, total_bytes=rec.cached_total_bytes,
            used_bytes=rec.cached_used_bytes, live=False, auto_renew=rec.auto_renew,
            error=rec.last_error, synced_at=rec.synced_at, enabled=rec.status != "SUSPENDED"))
    return out


def _load_owned(uow, user_id: Optional[int], order_id: int):
    rec = uow.provisioning.get_client_by_order(order_id)
    order = uow.orders.get_by_id(order_id)
    if rec is None or order is None or (user_id is not None and order.user_id != user_id):
        raise NotFoundError("سرویس یافت نشد")  # عمداً یکسان: افشای وجود سفارش دیگران ممنوع
    return rec, order


def get_service_view(uow_factory, user_id: Optional[int], order_id: int, *, live: bool = True) -> ServiceView:
    with uow_factory() as uow:
        rec, order = _load_owned(uow, user_id, order_id)
        name = _product_name(uow, order)
    base = ServiceView(
        order_id=order_id, product_name=name, state=derive_state(
            rec.status, enabled=rec.status != "SUSPENDED", expires_at_ms=rec.expires_at_ms,
            used=rec.cached_used_bytes, total=rec.cached_total_bytes),
        email=rec.email, expires_at_ms=rec.expires_at_ms, total_bytes=rec.cached_total_bytes,
        used_bytes=rec.cached_used_bytes, live=False, auto_renew=rec.auto_renew, error=rec.last_error,
        synced_at=rec.synced_at, enabled=rec.status != "SUSPENDED")
    if not live or rec.status in ("PENDING", "FAILED", "CANCELLED"):
        return base
    try:
        st = prov.get_provider(rec.provider_name).get_traffic(rec.email)
    except VPNProviderError as exc:
        base.error = f"{type(exc).__name__}"  # جزئیات داخلی به کاربر نمی‌رسد
        return base
    if st is None:
        base.error = "NOT_FOUND_ON_PROVIDER"
        return base
    new_state = derive_state("ACTIVE", enabled=st.enable, expires_at_ms=st.expiry_ms,
                             used=st.used_bytes, total=st.total_bytes)
    with uow_factory() as uow:
        uow.provisioning.set_cache(order_id, st.used_bytes, st.total_bytes, st.expiry_ms)
        if new_state != rec.status and new_state in ("ACTIVE", "EXPIRED", "SUSPENDED"):
            uow.provisioning.set_client_status(order_id, new_state)
    base.state, base.expires_at_ms, base.total_bytes = new_state, st.expiry_ms, st.total_bytes
    base.used_bytes, base.live, base.error, base.enabled = st.used_bytes, True, None, st.enable
    return base


def get_connection_info(uow_factory, user_id: Optional[int], order_id: int) -> dict:
    """لینک‌های اتصال + ساب‌اسکریپشن (زنده؛ هرگز ذخیره/حدس زده نمی‌شود)."""
    with uow_factory() as uow:
        rec, _ = _load_owned(uow, user_id, order_id)
    if rec.status in ("PENDING", "FAILED", "CANCELLED"):
        raise ConflictError("این سرویس هنوز فعال نیست")
    provider = prov.get_provider(rec.provider_name)
    try:
        links = provider.get_links(rec.email)
    except NotConfiguredError as exc:
        raise ProviderNotReadyError(str(exc)) from exc
    except VPNProviderError as exc:
        raise ProvisioningFailedError("دریافت لینک از پنل ممکن نشد") from exc
    return {"links": links, "subscription_url": provider.get_subscription_url(rec.sub_id)}


# --------------------------------------------------------------------------
# تمدید
# --------------------------------------------------------------------------

@dataclass
class RenewResult:
    status: str            # COMPLETED | PENDING | REFUNDED
    new_expiry_ms: int
    amount_minor: int
    currency: str
    renewal_id: int


def _phase1(uow, user_id: int, order_id: int, key: str, source: str):
    rec, order = _load_owned(uow, user_id, order_id)
    existing = uow.renewals.get_by_key(key)
    if existing is not None:
        if existing.order_id != order_id or existing.user_id != user_id:
            raise ConflictError("کلید Idempotency متعلق به عملیات دیگری است")
        return rec, existing, False
    if rec.status not in RENEWABLE:
        raise ConflictError("این سرویس قابل تمدید نیست")
    profile = prov.active_profile(uow, order.product_id)
    if profile is None or profile.duration_days <= 0:
        raise ValidationError("پروفایل تمدید برای این محصول تعریف نشده")
    prov.assert_ready(uow, order.product_id)
    product = uow.products.get(order.product_id)
    if product is None:
        raise NotFoundError("محصول یافت نشد")
    from core.orders import service as orders_service
    price = orders_service.price_for_user(uow, user_id, product)  # تنها منبع قیمت
    wallet_service.debit_for_purchase(
        uow, user_id, price, f"تمدید {product.name} (#{order_id})",
        currency=product.currency, idempotency_key=f"renew-debit:{key}")
    base = max(now_ms(), rec.expires_at_ms)
    renewal = uow.renewals.create(
        order_id, user_id, price, product.currency, key, base + profile.duration_days * DAY_MS,
        int(profile.traffic_gb * BYTES_PER_GB), source)
    audit_service.record(uow, actor_id=user_id if source == "manual" else 0, action="service.renew_charged",
                         entity_type="order", entity_id=order_id,
                         after={"amount_minor": price, "key": key, "source": source,
                                "new_expiry_ms": renewal.new_expiry_ms})
    return rec, renewal, True


def _apply_provider(rec, renewal):
    prov.get_provider(rec.provider_name).renew_client(
        rec.email, new_expiry_ms=renewal.new_expiry_ms, total_bytes=renewal.total_bytes, reset_traffic=True)


def _complete(uow, rec, renewal) -> None:
    uow.renewals.set_status(renewal.id, "COMPLETED")
    uow.provisioning.set_expiry(rec.order_id, renewal.new_expiry_ms)
    uow.provisioning.set_cache(rec.order_id, 0, renewal.total_bytes, renewal.new_expiry_ms)
    uow.provisioning.set_client_status(rec.order_id, "ACTIVE")
    uow.provisioning.set_notified(rec.order_id, 0)
    audit_service.record(uow, actor_id=0, action="service.renewed", entity_type="order",
                         entity_id=rec.order_id,
                         after={"renewal_id": renewal.id, "new_expiry_ms": renewal.new_expiry_ms})


def _refund(uow, renewal, reason: str) -> None:
    wallet_service.adjust_balance(
        uow, renewal.user_id, renewal.amount_minor, f"بازگشت وجه تمدید ناموفق (#{renewal.order_id})",
        currency=renewal.currency, actor_id=0, idempotency_key=f"renew-refund:{renewal.idempotency_key}")
    uow.renewals.set_status(renewal.id, "REFUNDED", reason[:200])
    audit_service.record(uow, actor_id=0, action="service.renew_refunded", entity_type="order",
                         entity_id=renewal.order_id, after={"renewal_id": renewal.id, "reason": reason[:200]})


def renew_service(uow_factory, user_id: int, order_id: int, *, idempotency_key: str,
                  source: str = "manual") -> RenewResult:
    with uow_factory() as uow:
        rec, renewal, _created = _phase1(uow, user_id, order_id, idempotency_key, source)
    if renewal.status == "COMPLETED":
        return RenewResult("COMPLETED", renewal.new_expiry_ms, renewal.amount_minor, renewal.currency, renewal.id)
    if renewal.status == "REFUNDED":
        return RenewResult("REFUNDED", renewal.new_expiry_ms, renewal.amount_minor, renewal.currency, renewal.id)
    return _finish_renewal(uow_factory, rec, renewal)


def _finish_renewal(uow_factory, rec, renewal) -> RenewResult:
    try:
        _apply_provider(rec, renewal)
    except (NotConfiguredError, ProviderRejectedError, ProviderAuthError) as exc:
        # رد قطعی (هیچ اثری روی پنل نداشت) → بازپرداخت اتمیک؛ هرگز «تمدیدشده» ثبت نمی‌شود.
        with uow_factory() as uow:
            _refund(uow, renewal, f"{type(exc).__name__}")
        return RenewResult("REFUNDED", renewal.new_expiry_ms, renewal.amount_minor, renewal.currency, renewal.id)
    except VPNProviderError as exc:
        # خطای مبهم: ممکن است پنل اعمال کرده باشد → نه تمدیدشده، نه بازپرداخت؛ Recovery تصمیم می‌گیرد.
        with uow_factory() as uow:
            uow.renewals.set_status(renewal.id, "CHARGED", f"{type(exc).__name__}")
        return RenewResult("PENDING", renewal.new_expiry_ms, renewal.amount_minor, renewal.currency, renewal.id)
    with uow_factory() as uow:
        _complete(uow, rec, renewal)
    return RenewResult("COMPLETED", renewal.new_expiry_ms, renewal.amount_minor, renewal.currency, renewal.id)


def recover_stuck_renewals(uow_factory, *, older_than_minutes: int = 5) -> dict:
    """بعد از ری‌استارت/خطای مبهم: تمدیدهای CHARGED را دوباره اجرا می‌کند (مقدار مطلق ⇒ Idempotent)."""
    with uow_factory() as uow:
        stuck = list(uow.renewals.list_stuck(older_than_minutes))
    out = {"completed": 0, "refunded": 0, "pending": 0}
    for r in stuck:
        with uow_factory() as uow:
            rec = uow.provisioning.get_client_by_order(r.order_id)
        if rec is None:
            continue
        res = _finish_renewal(uow_factory, rec, r)
        if res.status == "PENDING":
            age_ok = False
            with uow_factory() as uow:
                old = [x for x in uow.renewals.list_stuck(REFUND_AFTER_MINUTES) if x.id == r.id]
                if old:
                    _refund(uow, old[0], "recovery_timeout")
                    age_ok = True
            out["refunded" if age_ok else "pending"] += 1
        else:
            out["completed" if res.status == "COMPLETED" else "refunded"] += 1
    return out


# --------------------------------------------------------------------------
# تمدید خودکار (Opt-in) و یادآوری
# --------------------------------------------------------------------------

def set_auto_renew(uow, user_id: int, order_id: int, enabled: bool) -> bool:
    rec, _ = _load_owned(uow, user_id, order_id)
    if enabled:
        if not settings_service.get_bool(uow, "auto_renewal_enabled"):
            raise ValidationError("تمدید خودکار در این ربات فعال نشده است")
        if rec.status not in RENEWABLE:
            raise ConflictError("این سرویس قابل تمدید خودکار نیست")
        if prov.active_profile(uow, uow.orders.get_by_id(order_id).product_id) is None:
            raise ValidationError("پروفایل تمدید تعریف نشده")
    consent = datetime.now(timezone.utc).isoformat() if enabled else None
    uow.provisioning.set_auto_renew(order_id, enabled, consent)
    audit_service.record(uow, actor_id=user_id, action="service.auto_renew_set", entity_type="order",
                         entity_id=order_id, after={"enabled": enabled})
    return enabled


def run_auto_renewals(uow_factory, *, at_ms: Optional[int] = None) -> list[dict]:
    """خروجی: لیست رویدادها برای اعلان (user_id, order_id, outcome)."""
    at = at_ms if at_ms is not None else now_ms()
    with uow_factory() as uow:
        if not settings_service.get_bool(uow, "auto_renewal_enabled"):
            return []
        window = settings_service.get_int(uow, "auto_renewal_window_hours")
        due = list(uow.provisioning.list_expiring(at + window * 3600 * 1000))
        owners = {r.order_id: uow.orders.get_by_id(r.order_id).user_id for r in due}
    events = []
    for rec in due:
        uid = owners[rec.order_id]
        key = f"auto:{rec.order_id}:{rec.expires_at_ms}"  # یک تلاش به‌ازای هر دورهٔ انقضا
        try:
            res = renew_service(uow_factory, uid, rec.order_id, idempotency_key=key, source="auto")
            outcome = {"COMPLETED": "renewed", "PENDING": "pending", "REFUNDED": "failed_refunded"}[res.status]
        except InsufficientBalanceError:
            outcome = "insufficient_balance"
        except (ProviderNotReadyError, ConflictError, ValidationError, NotFoundError):
            outcome = "skipped"
        events.append({"user_id": uid, "order_id": rec.order_id, "outcome": outcome})
    return events


def expiry_reminders(uow_factory, *, at_ms: Optional[int] = None) -> list[dict]:
    at = at_ms if at_ms is not None else now_ms()
    with uow_factory() as uow:
        hours = settings_service.get_int(uow, "expiry_reminder_hours")
        if hours <= 0:
            return []
        soon = list(uow.provisioning.list_active_expiring_soon(at + hours * 3600 * 1000, at))
        events = []
        for rec in soon:
            if rec.auto_renew:
                continue  # مسیر خودکار خودش اعلان می‌دهد
            uow.provisioning.set_notified(rec.order_id, rec.expires_at_ms)
            events.append({"user_id": uow.orders.get_by_id(rec.order_id).user_id,
                           "order_id": rec.order_id, "expires_at_ms": rec.expires_at_ms})
    return events


def mark_expired(uow_factory, *, at_ms: Optional[int] = None) -> int:
    at = at_ms if at_ms is not None else now_ms()
    with uow_factory() as uow:
        rows = uow.provisioning.list_active_expired(at)
        for r in rows:
            uow.provisioning.set_client_status(r.order_id, "EXPIRED")
        return len(rows)


# --------------------------------------------------------------------------
# عملیات ادمین (services.manage) — Permission → اعتبارسنجی → Provider → ثبت → Audit
# --------------------------------------------------------------------------

def admin_list(uow, actor_id: int, status: Optional[str] = None):
    rbac.require(uow, actor_id, "services.view")
    if status:
        return uow.provisioning.list_clients(status)
    return [r for st in ("ACTIVE", "EXPIRED", "SUSPENDED", "PENDING", "FAILED") for r in uow.provisioning.list_clients(st)]


def _admin_provider_op(uow_factory, actor_id: int, order_id: int, action: str, op, new_status: Optional[str]):
    with uow_factory() as uow:
        rbac.require(uow, actor_id, "services.manage")
        rec, _ = _load_owned(uow, None, order_id)
    try:
        op(prov.get_provider(rec.provider_name), rec)
    except NotConfiguredError as exc:
        raise ProviderNotReadyError(str(exc)) from exc
    except VPNProviderError as exc:
        with uow_factory() as uow:
            audit_service.record(uow, actor_id=actor_id, action=f"service.{action}_failed",
                                 entity_type="order", entity_id=order_id, after={"kind": type(exc).__name__})
        raise ProvisioningFailedError(f"عملیات روی پنل انجام نشد ({type(exc).__name__})") from exc
    with uow_factory() as uow:
        if new_status:
            uow.provisioning.set_client_status(order_id, new_status)
        audit_service.record(uow, actor_id=actor_id, action=f"service.{action}", entity_type="order",
                             entity_id=order_id, after={"status": new_status})


def admin_set_enabled(uow_factory, actor_id: int, order_id: int, enabled: bool) -> None:
    _admin_provider_op(uow_factory, actor_id, order_id, "enable" if enabled else "suspend",
                       lambda p, r: p.set_enabled(r.email, enabled), "ACTIVE" if enabled else "SUSPENDED")


def admin_reset_traffic(uow_factory, actor_id: int, order_id: int) -> None:
    def op(p, r):
        p.reset_traffic(r.email)
    _admin_provider_op(uow_factory, actor_id, order_id, "reset_traffic", op, None)
    with uow_factory() as uow:
        rec = uow.provisioning.get_client_by_order(order_id)
        uow.provisioning.set_cache(order_id, 0, rec.cached_total_bytes, rec.expires_at_ms)


def admin_cancel(uow_factory, actor_id: int, order_id: int, *, refund: bool = False) -> None:
    """حذف کلاینت از پنل + CANCELLED (+ اختیاری بازپرداخت اتمیک سفارش). حذف ناموفق → بدون بازپرداخت."""
    _admin_provider_op(uow_factory, actor_id, order_id, "cancel", lambda p, r: p.delete_client(r.email), None)
    with uow_factory() as uow:
        uow.provisioning.set_client_status(order_id, "CANCELLED")
        if refund:
            rbac.require(uow, actor_id, "orders.refund")
            order = uow.orders.get_by_id(order_id)
            if uow.orders.mark_refunded(order_id):
                wallet_service.adjust_balance(
                    uow, order.user_id, order.price_minor, f"بازپرداخت سفارش #{order_id}",
                    currency=order.currency, actor_id=actor_id, idempotency_key=f"order-refund:{order_id}")
                audit_service.record(uow, actor_id=actor_id, action="order.refund", entity_type="order",
                                     entity_id=order_id, after={"via": "service_cancel"})
