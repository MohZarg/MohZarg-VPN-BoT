"""
GhYiAb V2 — Provisioning Core Service (سه‌مرحله‌ای، بدون نگه‌داشتن قفل DB هنگام I/O)
=====================================================================================

مشکل نسخهٔ قبلی: تماس شبکه با 3x-ui داخل یک تراکنش `BEGIN IMMEDIATE` باز انجام
می‌شد؛ در SQLite این یعنی قفل نوشتن تا ۱۰–۱۵ ثانیه برای همهٔ کاربران نگه داشته می‌شد
(دلیل مستند تغییر این ماژول — منطق مالی/اتمیک دست‌نخورده است).

مراحل (هر مرحله تراکنش مستقل):
  1) ``begin``   : ثبت رکورد PENDING با ایمیل قطعی، sub_id و انقضای *مطلق* (Idempotent).
  2) ``execute`` : (بدون تراکنش) adopt-if-exists یا create روی Provider.
  3) ``finish``  : ACTIVE + سفارش COMPLETED، یا ثبت خطا (سفارش PROVISIONING می‌ماند).

No Fake Integration: Provider پیکربندی‌نشده/خراب هرگز «موفق» ثبت نمی‌شود. سفارشِ
پرداخت‌شدهٔ ناموفق با PROVISIONING می‌ماند → Retry خودکار محدود (``provision_max_attempts``)
یا اقدام ادمین (Retry/Refund). بازپرداخت خودکار عمداً انجام نمی‌شود (تصمیم مالی = ادمین).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import (
    ValidationError, NotFoundError, ProviderNotReadyError, ProvisioningFailedError,
)
from providers.vpn.base import ClientSpec, NotConfiguredError, VPNProviderError

logger = logging.getLogger("ghyiab.provisioning")

BYTES_PER_GB = 1024 ** 3
NO_INVENTORY = 0  # سفارش‌های Provider-backed آیتم مخزن ندارند (ستون NOT NULL → sentinel)
_ALIASES = {"xui_vpn": "3x-ui", "3x-ui": "3x-ui"}

# Registry قابل تزریق (تست‌ها Provider را جایگزین می‌کنند؛ تولید: ThreeXUIProvider از env)
_PROVIDER_FACTORIES: dict[str, Callable[[], object]] = {}
_PROVIDER_CACHE: dict[str, object] = {}


def _default_factory(name: str):
    if name == "3x-ui":
        from providers.vpn.xui.provider import build_default_provider
        return build_default_provider
    raise ValidationError(f"Provider ناشناس: {name}")


def get_provider(name: str):
    key = _ALIASES.get(name, name)
    if key in _PROVIDER_FACTORIES:
        return _PROVIDER_FACTORIES[key]()
    if key not in _PROVIDER_CACHE:  # نمونهٔ واحد: Session/Circuit-breaker مشترک → درخواست کمتر
        _PROVIDER_CACHE[key] = _default_factory(key)()
    return _PROVIDER_CACHE[key]


def set_provider_factory(name: str, factory: Optional[Callable[[], object]]) -> None:
    key = _ALIASES.get(name, name)
    if factory is None:
        _PROVIDER_FACTORIES.pop(key, None)
    else:
        _PROVIDER_FACTORIES[key] = factory
    _PROVIDER_CACHE.pop(key, None)


# --------------------------------------------------------------------------
# پروفایل محصول
# --------------------------------------------------------------------------

def set_profile(uow: UnitOfWork, actor_id: int, product_id: int, provider_name: str,
                inbound_id: int, duration_days: int, traffic_gb: float, limit_ip: int = 0):
    rbac.require(uow, actor_id, "providers.manage")
    if uow.products.get(product_id) is None:
        raise NotFoundError(f"محصول {product_id} یافت نشد")
    if duration_days < 0 or traffic_gb < 0 or limit_ip < 0 or inbound_id <= 0:
        raise ValidationError("مقادیر باید نامنفی (و inbound مثبت) باشند")
    provider_name = _ALIASES.get(provider_name)
    if provider_name is None:
        raise ValidationError("Provider ناشناس")
    profile = uow.provisioning.upsert_profile(
        product_id, provider_name, inbound_id, duration_days, traffic_gb, limit_ip)
    audit_service.record(
        uow, actor_id=actor_id, action="provider.profile_set", entity_type="product",
        entity_id=product_id, after={"provider": provider_name, "inbound_id": inbound_id,
                                     "duration_days": duration_days, "traffic_gb": traffic_gb},
    )
    return profile


def provider_health(provider_name: str) -> dict:
    return get_provider(provider_name).health_check()


def active_profile(uow: UnitOfWork, product_id: int):
    p = uow.provisioning.get_profile(product_id)
    return p if (p is not None and p.is_active) else None


def assert_ready(uow: UnitOfWork, product_id: int) -> None:
    """قبل از هر کسر پول برای محصول Provider-backed: اگر Provider پیکربندی نیست → BLOCKED."""
    profile = active_profile(uow, product_id)
    if profile is None:
        return
    if not get_provider(profile.provider_name).is_configured():
        raise ProviderNotReadyError(
            f"NOT_CONFIGURED: Provider «{profile.provider_name}» پیکربندی نشده؛ خرید این سرویس فعلاً ممکن نیست")


def _email_for(order_id: int) -> str:
    return f"gy{order_id}"


@dataclass(frozen=True)
class ProvisionPlan:
    order_id: int
    user_id: int
    provider_name: str
    inbound_id: int
    email: str
    sub_id: str
    client_uuid: str
    total_bytes: int
    expiry_ms: int
    limit_ip: int
    attempts: int


# --------------------------------------------------------------------------
# فاز ۱: begin
# --------------------------------------------------------------------------

def begin(uow: UnitOfWork, order_id: int) -> Optional[ProvisionPlan]:
    """None → کاری لازم نیست (پروفایل ندارد یا قبلاً ACTIVE است)."""
    from providers.vpn.xui.provider import new_sub_id
    order = uow.orders.get_by_id(order_id)
    if order is None:
        raise NotFoundError(f"سفارش {order_id} یافت نشد")
    profile = active_profile(uow, order.product_id)
    if profile is None:
        return None
    rec = uow.provisioning.get_client_by_order(order_id)
    if rec is not None and rec.status == "ACTIVE":
        return None
    if rec is None:
        expiry = int(time.time() * 1000) + profile.duration_days * 86400 * 1000 if profile.duration_days else 0
        import uuid as _u
        rec = uow.provisioning.create_client(
            order_id, profile.provider_name, profile.inbound_id, str(_u.uuid4()),
            _email_for(order_id), new_sub_id(), expiry)
        uow.provisioning.set_client_status(order_id, "PENDING")
    uow.orders.set_status(order_id, "PROVISIONING")
    attempts = uow.provisioning.bump_attempts(order_id)
    return ProvisionPlan(
        order_id=order_id, user_id=order.user_id, provider_name=rec.provider_name, inbound_id=rec.inbound_id,
        email=rec.email, sub_id=rec.sub_id, client_uuid=rec.client_uuid,
        total_bytes=int(profile.traffic_gb * BYTES_PER_GB), expiry_ms=rec.expires_at_ms,
        limit_ip=profile.limit_ip, attempts=attempts)


# --------------------------------------------------------------------------
# فاز ۲: execute (بدون تراکنش DB)
# --------------------------------------------------------------------------

def execute(plan: ProvisionPlan):
    provider = get_provider(plan.provider_name)
    existing = provider.get_client(plan.email)  # adopt-if-exists: Retry پس از موفقیتِ نیمه‌کاره امن است
    if existing is not None:
        return existing
    spec = ClientSpec(
        email=plan.email, sub_id=plan.sub_id, client_uuid=plan.client_uuid,
        total_bytes=plan.total_bytes, expiry_ms=plan.expiry_ms, limit_ip=plan.limit_ip,
        telegram_id=plan.user_id, comment="ghyiab-v2")
    return provider.create_client(spec, [plan.inbound_id])


# --------------------------------------------------------------------------
# فاز ۳: finish
# --------------------------------------------------------------------------

def finish_success(uow: UnitOfWork, plan: ProvisionPlan, state) -> None:
    uow.provisioning.reset_for_retry(plan.order_id, state.uuid or plan.client_uuid)
    uow.provisioning.set_client_status(plan.order_id, "ACTIVE")
    uow.provisioning.set_cache(plan.order_id, state.used_bytes, state.total_bytes,
                               state.expiry_ms or plan.expiry_ms)
    uow.orders.set_status(plan.order_id, "COMPLETED")
    audit_service.record(uow, actor_id=0, action="provider.provisioned", entity_type="order",
                         entity_id=plan.order_id,
                         after={"inbound_id": plan.inbound_id, "attempts": plan.attempts})
    from core.reseller import service as reseller_service  # پاداش رفرال فقط پس از صدور موفق
    reseller_service.reward_for_paid_order(uow, plan.user_id)


def finish_failure(uow: UnitOfWork, plan: ProvisionPlan, exc: Exception) -> None:
    status = "BLOCKED" if isinstance(exc, NotConfiguredError) else "FAILED"
    uow.provisioning.set_client_status(plan.order_id, "FAILED", f"{type(exc).__name__}: {str(exc)[:200]}")
    uow.orders.set_status(plan.order_id, "PROVISIONING")
    audit_service.record(uow, actor_id=0, action="provider.provision_failed", entity_type="order",
                         entity_id=plan.order_id,
                         after={"kind": type(exc).__name__, "state": status, "attempts": plan.attempts})


def provision_order(uow_factory, order_id: int) -> Optional[dict]:
    """
    Orchestrator کامل. ``uow_factory`` یک callable بدون آرگومان است که UnitOfWork می‌دهد.
    موفق → dict؛ بدون پروفایل/قبلاً ACTIVE → None؛ شکست → استثنای typed (سفارش PROVISIONING می‌ماند).
    """
    with uow_factory() as uow:
        plan = begin(uow, order_id)
    if plan is None:
        return None
    try:
        state = execute(plan)
    except NotConfiguredError as exc:
        with uow_factory() as uow:
            finish_failure(uow, plan, exc)
        raise ProviderNotReadyError(str(exc)) from exc
    except VPNProviderError as exc:
        with uow_factory() as uow:
            finish_failure(uow, plan, exc)
        raise ProvisioningFailedError(str(exc)) from exc
    with uow_factory() as uow:
        finish_success(uow, plan, state)
    return {"order_id": order_id, "email": plan.email, "sub_id": plan.sub_id, "expiry_ms": state.expiry_ms}


def retry_failed(uow_factory, actor_id: int, order_id: int) -> Optional[dict]:
    with uow_factory() as uow:
        rbac.require(uow, actor_id, "providers.manage")
    return provision_order(uow_factory, order_id)


def retry_pending(uow_factory, *, limit: int = 20) -> dict:
    """Job پس‌زمینه: سفارش‌های PENDING/FAILED با attempts < provision_max_attempts."""
    from core.settings import service as settings_service
    with uow_factory() as uow:
        max_attempts = settings_service.get_int(uow, "provision_max_attempts")
        todo = [r for st in ("PENDING", "FAILED") for r in uow.provisioning.list_clients(st)
                if r.attempts < max_attempts][:limit]
    out = {"ok": 0, "failed": 0, "skipped_not_configured": 0}
    for rec in todo:
        if not get_provider(rec.provider_name).is_configured():
            out["skipped_not_configured"] += 1  # attempts مصرف نمی‌شود
            continue
        try:
            provision_order(uow_factory, rec.order_id)
            out["ok"] += 1
        except ProviderNotReadyError:
            out["skipped_not_configured"] += 1
        except ProvisioningFailedError:
            out["failed"] += 1
    return out


def list_pending(uow: UnitOfWork, actor_id: int):
    rbac.require(uow, actor_id, "providers.view")
    return uow.orders.page(status="PROVISIONING")
