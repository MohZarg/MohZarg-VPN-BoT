"""Coupon management — ساخت/غیرفعال‌سازی توسط ادمین، اعتبارسنجی و مصرف در جریان خرید."""

from __future__ import annotations

from typing import Optional

from repository.interface import UnitOfWork, CouponRecord
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ValidationError, ConflictError, CouponError

MAX_CODE_LEN = 32


def _norm_code(code: str) -> str:
    code = (code or "").strip().upper()
    if not code or len(code) > MAX_CODE_LEN or not code.replace("-", "").replace("_", "").isalnum():
        raise ValidationError("کد کوپن باید حروف/عدد/خط‌تیره و حداکثر ۳۲ کاراکتر باشد")
    return code


def create(uow: UnitOfWork, actor_id: int, code: str, kind: str, value: int,
           currency: Optional[str] = None, max_uses: Optional[int] = None,
           per_user_limit: Optional[int] = None, expires_at: Optional[str] = None,
           min_order_minor: Optional[int] = None, product_ids: Optional[list] = None) -> CouponRecord:
    rbac.require(uow, actor_id, "coupons.manage")
    if kind not in ("PERCENT", "FIXED"):
        raise ValidationError("نوع کوپن باید PERCENT یا FIXED باشد")
    if value <= 0 or (kind == "PERCENT" and value > 100):
        raise ValidationError("مقدار کوپن نامعتبر است")
    code = _norm_code(code)
    if uow.coupons.get_by_code(code) is not None:
        raise ConflictError("این کد کوپن از قبل وجود دارد")
    if min_order_minor is not None and min_order_minor < 0:
        raise ValidationError("حداقل سفارش نامعتبر است")
    csv = None
    if product_ids:
        if any((not isinstance(x, int)) or x <= 0 for x in product_ids):
            raise ValidationError("شناسهٔ محصول نامعتبر است")
        csv = ",".join(str(x) for x in sorted(set(product_ids)))
    coupon = uow.coupons.create(code, kind, value, currency, max_uses, per_user_limit, expires_at, actor_id,
                                min_order_minor, csv)
    audit_service.record(uow, actor_id=actor_id, action="coupon.create", entity_type="coupon",
                         entity_id=coupon.id, after={"code": code, "kind": kind, "value": value})
    return coupon


def set_active(uow: UnitOfWork, actor_id: int, coupon_id: int, active: bool) -> None:
    rbac.require(uow, actor_id, "coupons.manage")
    c = uow.coupons.get(coupon_id)
    if c is None:
        raise ValidationError("کوپن یافت نشد")
    uow.coupons.set_active(coupon_id, active)
    audit_service.record(uow, actor_id=actor_id, action="coupon.set_active", entity_type="coupon",
                         entity_id=coupon_id, before={"is_active": c.is_active}, after={"is_active": active})


def validate_for_use(uow: UnitOfWork, code: str, user_id: int, order_currency: str,
                     *, count_pending: bool = False, product_id: Optional[int] = None,
                     order_amount_minor: Optional[int] = None) -> CouponRecord:
    """
    فقط اعتبارسنجی (بدون مصرف) — برای پیش‌نمایش قیمت پیش از پرداخت.
    count_pending=True: رسیدهای کارت‌به‌کارتِ در انتظارِ همین کوپن هم «مصرف‌شده» حساب می‌شوند تا
    با چند رسید هم‌زمان نتوان از سقف استفاده عبور کرد.
    """
    code = (code or "").strip().upper()
    coupon = uow.coupons.get_by_code(code)
    if coupon is None or not coupon.is_active:
        raise CouponError("invalid", "کد کوپن نامعتبر یا غیرفعال است")
    if coupon.currency and coupon.currency != order_currency:
        raise CouponError("currency", "این کوپن برای این ارز معتبر نیست")
    if coupon.product_ids and product_id is not None and \
            str(product_id) not in coupon.product_ids.split(","):
        raise CouponError("product", "این کوپن برای این محصول معتبر نیست")
    if coupon.min_order_minor and order_amount_minor is not None and order_amount_minor < coupon.min_order_minor:
        raise CouponError("min_order", f"حداقل مبلغ سفارش برای این کوپن {coupon.min_order_minor:,} است")
    from datetime import datetime, timezone
    if coupon.expires_at and coupon.expires_at < datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"):
        raise CouponError("expired", "این کوپن منقضی شده است")
    reserved_all = uow.pending_requests.count_pending_with_coupon(coupon.code) if count_pending else 0
    reserved_user = uow.pending_requests.count_pending_with_coupon(coupon.code, user_id) if count_pending else 0
    if coupon.max_uses is not None and uow.coupons.count_uses(coupon.id) + reserved_all >= coupon.max_uses:
        raise CouponError("exhausted", "سقف استفادهٔ این کوپن تکمیل شده است")
    if coupon.per_user_limit is not None and \
       uow.coupons.count_uses_by_user(coupon.id, user_id) + reserved_user >= coupon.per_user_limit:
        raise CouponError("per_user_exhausted", "شما قبلاً از این کوپن استفاده کرده‌اید")
    return coupon


def redeem(uow: UnitOfWork, coupon: CouponRecord, user_id: int, order_id: Optional[int],
           discount_minor: int) -> None:
    """ثبت مصرف کوپن؛ باید داخل همان تراکنش خریدِ موفق صدا زده شود (atomic)."""
    uow.coupons.record_redemption(coupon.id, user_id, order_id, discount_minor)
