"""
GhYiAb V2 — Orders Core Service
==================================

پورت مستقیمِ رفتاری دو مسیر مالی حساس قدیمی:
  - `purchase_with_wallet`   → purchase_with_wallet()
  - `claim_free_test`        → claim_free_test()

به‌علاوهٔ create/resolve pending request (کارت‌به‌کارت/خرید مستقیم/نمایندگی)
که در V1 پراکنده داخل هندلرها بود، اینجا یکجا شده — دقیقاً همان قوانین
Idempotency قبلی (`status='pending'` قبل از تغییر) حفظ شده.

تخفیف نماینده اکنون فقط از `core.pricing.service` خوانده می‌شود (رفع تکرار
P0-4 در Audit) — نه اینجا و نه در هیچ Adapter دیگر دوباره محاسبه نمی‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from repository.interface import UnitOfWork, OrderRecord, InventoryItemRecord
from core.audit import service as audit_service
from core.pricing import service as pricing_service
from core.auth import rbac
from core.errors import (
    ProductNotFoundError,
    OutOfStockError,
    InsufficientBalanceError,
    AlreadyClaimedTestError,
    DailyTestLimitError,
    ConflictError,
)

TEST_PRODUCT_ID = 0  # همان قرارداد V1: محصول با id=0 یعنی «اکانت تست»


def price_for_user(uow: UnitOfWork, user_id: int, product) -> int:
    """
    تنها نقطهٔ محاسبهٔ قیمت نهایی برای یک کاربر (نماینده ۱۰٪ و سطح Reseller؛ بهترین تخفیف، نه جمع —
    طبق قاعدهٔ مستند README/ROADMAP). نمایش قیمت، خرید با کیف پول و تأیید دستی همه از اینجا می‌گذرند.
    """
    from core.reseller import service as reseller_service
    user = uow.users.get_or_create(user_id)
    return pricing_service.price_with_tier(
        product.price_minor, user.is_agent, reseller_service.tier_discount_for(uow, user_id))


@dataclass(frozen=True)
class Quote:
    base_minor: int
    role_price_minor: int          # بعد از تخفیف نماینده/سطح (بدون کوپن)
    final_minor: int
    coupon_discount_minor: int     # سهم کوپن؛ ۰ یعنی کوپنی اعمال نشده
    coupon_code: Optional[str]


def quote(uow: UnitOfWork, user_id: int, product, coupon_code: Optional[str] = None,
          *, count_pending: bool = False) -> Quote:
    """
    قیمت نهایی با کوپن اختیاری. قاعدهٔ ترکیب از تنظیم `coupon_stacking` (README/ROADMAP):
      best  (پیش‌فرض): کوپن روی قیمت پایه سنجیده می‌شود و فقط اگر از تخفیف نقش/سطح بهتر باشد
                       جایگزین آن می‌شود؛ وگرنه CouponError('not_better') و کوپن مصرف نمی‌شود.
      stack: کوپن روی قیمتِ بعد از تخفیف نقش/سطح اعمال می‌شود.
    """
    from core.coupons import service as coupons_service
    from core.errors import CouponError
    from core.settings import service as settings_service
    role_price = price_for_user(uow, user_id, product)
    if not coupon_code:
        return Quote(product.price_minor, role_price, role_price, 0, None)

    coupon = coupons_service.validate_for_use(
        uow, coupon_code, user_id, product.currency, count_pending=count_pending,
        product_id=product.id, order_amount_minor=product.price_minor)
    if settings_service.get(uow, "coupon_stacking") == "stack":
        final, disc = pricing_service.apply_coupon(role_price, coupon)
    else:
        cp_final, cp_disc = pricing_service.apply_coupon(product.price_minor, coupon)
        if cp_final >= role_price:
            raise CouponError("not_better", "این کد تخفیف از تخفیف فعلی شما بهتر نیست و اعمال نشد")
        final, disc = cp_final, cp_disc
    if disc <= 0:
        raise CouponError("not_better", "این کد تخفیف روی این محصول تخفیفی ایجاد نمی‌کند")
    return Quote(product.price_minor, role_price, final, disc, coupon.code)


def _redeem_if_any(uow: UnitOfWork, q_code: Optional[str], disc: int, order, user_id: int) -> None:
    if not q_code or disc <= 0:
        return
    from core.coupons import service as coupons_service
    coupon = uow.coupons.get_by_code(q_code)
    if coupon is not None:
        uow.orders.set_discount(order.id, disc, q_code)
        coupons_service.redeem(uow, coupon, user_id, order.id, disc)


def register_receipt(uow: UnitOfWork, req_id: int, file_id: str, unique_id: Optional[str]) -> None:
    uow.pending_requests.set_receipt(req_id, file_id, unique_id)


def find_active_duplicate_receipt(uow: UnitOfWork, unique_id: Optional[str]):
    """رسید (عکس) تکراری: فقط اگر درخواست pending/approved با همان رسید وجود داشته باشد."""
    if not unique_id:
        return None
    return uow.pending_requests.find_active_by_receipt_unique_id(unique_id)


def purchase_with_wallet(uow: UnitOfWork, user_id: int, product_id: int,
                         coupon_code: Optional[str] = None,
                         idempotency_key: Optional[str] = None) -> OrderRecord:
    if idempotency_key is not None:
        existing = uow.orders.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.user_id != user_id:
                raise ConflictError("کلید Idempotency متعلق به عملیات دیگری است")
            return existing  # تپ دوباره روی همان دکمه: بدون کسر دوباره

    product = uow.products.get(product_id)
    if product is None:
        raise ProductNotFoundError(f"محصول {product_id} یافت نشد")

    uow.users.get_or_create(user_id)
    from core.provisioning import service as provisioning_service
    provisioned = provisioning_service.active_profile(uow, product_id) is not None
    if provisioned:
        provisioning_service.assert_ready(uow, product_id)  # قبل از کسر پول؛ NOT_CONFIGURED → بدون هیچ کسری
    q = quote(uow, user_id, product, coupon_code)
    price = q.final_minor

    ok = uow.wallet.debit_if_sufficient(user_id, product.currency, price)
    if not ok:
        raise InsufficientBalanceError(f"موجودی کاربر {user_id} برای خرید {product_id} کافی نیست")

    if provisioned:
        item = None  # سرویس از Provider صادر می‌شود، نه مخزن متنی
    else:
        item = uow.inventory.claim_one(product_id, user_id)
        if item is None:
            # جبران کسر انجام‌شده — دقیقاً هم‌ارزِ rollback تراکنش SQL قدیمی،
            # اما اینجا چون خودِ debit هم در همین UoW اتمیک است، بازگردانی صریح لازم است
            uow.wallet.adjust(user_id, product.currency, price)
            raise OutOfStockError(f"مخزن محصول {product_id} خالی است")

    balance_after = uow.wallet.get_balance(user_id, product.currency)
    uow.wallet.record_transaction(
        user_id, product.currency, -price, balance_after, f"خرید {product.name}"
    )

    order = uow.orders.create(
        user_id=user_id, product_id=product_id,
        inventory_item_id=item.id if item else provisioning_service.NO_INVENTORY,
        price_minor=price, currency=product.currency,
        status="PROVISIONING" if provisioned else "COMPLETED",
        idempotency_key=idempotency_key,
    )
    _redeem_if_any(uow, q.coupon_code, q.coupon_discount_minor, order, user_id)
    audit_service.record(
        uow, actor_id=user_id, action="order.purchase_with_wallet", entity_type="order",
        entity_id=order.id,
        after={"product_id": product_id, "price_minor": price, "item_id": item.id if item else None,
               "provisioned": provisioned,
               "coupon": q.coupon_code, "coupon_discount_minor": q.coupon_discount_minor},
    )
    if not provisioned:  # Provider-backed: پاداش بعد از صدور موفق (provisioning.finish_success)
        from core.reseller import service as reseller_service
        reseller_service.reward_for_paid_order(uow, user_id)
    return uow.orders.get_by_id(order.id)


def claim_free_test(uow: UnitOfWork, user_id: int, today_str: str) -> InventoryItemRecord:
    user = uow.users.get_or_create(user_id)

    if not user.is_agent and user.last_test_date is not None:
        raise AlreadyClaimedTestError("سهمیه تست رایگان قبلاً استفاده شده")
    if user.is_agent and user.last_test_date == today_str:
        raise DailyTestLimitError("سهمیهٔ روزانهٔ تست نماینده استفاده شده")

    item = uow.inventory.claim_one(TEST_PRODUCT_ID, user_id)
    if item is None:
        raise OutOfStockError("مخزن تست رایگان خالی است")

    uow.users.set_last_test_date(user_id, today_str)
    order = uow.orders.create(
        user_id=user_id, product_id=TEST_PRODUCT_ID, inventory_item_id=item.id,
        price_minor=0, currency=pricing_service_default_currency(),
    )
    audit_service.record(
        uow, actor_id=user_id, action="order.claim_free_test", entity_type="order",
        entity_id=order.id, after={"item_id": item.id},
    )
    return item


def pricing_service_default_currency() -> str:
    from core.wallet.service import DEFAULT_CURRENCY
    return DEFAULT_CURRENCY


def create_pending_request(uow: UnitOfWork, req_type: str, user_id: int,
                            product_id: Optional[int] = None,
                            amount_minor: Optional[int] = None,
                            currency: Optional[str] = None,
                            idempotency_key: Optional[str] = None) -> int:
    """
    ایجاد Idempotent درخواست (Phase 5 — Payments v2, بخش ساختاری). اگر
    idempotency_key داده شود و قبلاً همین کلید ثبت شده باشد، رکورد قبلی
    برگردانده می‌شود، نه یک درخواست تکراری — دقیقاً همان الگوی
    `core/wallet/service.credit`/`debit`. این مانع سناریوی واقعی «Telegram
    همان photo update را دوباره تحویل می‌دهد / کاربر عکس را دوبار می‌فرستد»
    می‌شود که می‌توانست به تأیید دوگانه توسط ادمین و تخصیص/شارژ دوبرابر منجر شود.
    """
    if idempotency_key is not None:
        existing = uow.pending_requests.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing.id

    req_id = uow.pending_requests.create(
        req_type, user_id, product_id, amount_minor, currency, idempotency_key,
    )
    audit_service.record(
        uow, actor_id=user_id, action="pending_request.create", entity_type="pending_request",
        entity_id=req_id,
        after={"type": req_type, "product_id": product_id, "amount_minor": amount_minor},
    )
    return req_id


def find_pending_agency_request(uow: UnitOfWork, user_id: int):
    return uow.pending_requests.find_pending_by_type_and_user("agency", user_id)


def _resolve_typed(uow: UnitOfWork, req_id: int, expected_type: str, new_status: str):
    """
    حل درخواست فقط اگر نوعش با عملیات می‌خواند. قبلاً resolve نوع را نمی‌سنجید و تأیید
    با نوع اشتباه (مثلاً شارژ روی درخواست خرید) با خطای خام DB/TypeError می‌ترکید.
    """
    from core.errors import RequestAlreadyResolvedError, ValidationError
    existing = uow.pending_requests.get(req_id)
    if existing is None or existing.status != "pending":
        raise RequestAlreadyResolvedError(f"درخواست {req_id} قبلاً پردازش شده")
    if existing.type != expected_type:
        raise ValidationError(f"نوع درخواست {req_id} با این عملیات نمی‌خواند")
    row = uow.pending_requests.resolve(req_id, new_status)
    if row is None:
        raise RequestAlreadyResolvedError(f"درخواست {req_id} قبلاً پردازش شده")
    return row


def approve_agency_request(uow: UnitOfWork, req_id: int, actor_id: int):
    """تأیید درخواست نمایندگی (قبلاً inline در bot.py و بدون بررسی نوع)."""
    rbac.require(uow, actor_id, "orders.approve")
    row = _resolve_typed(uow, req_id, "agency", "approved")
    uow.users.get_or_create(row.user_id)
    uow.users.set_agent(row.user_id, True)
    audit_service.record(
        uow, actor_id=actor_id, action="agency.approve", entity_type="user",
        entity_id=row.user_id, after={"is_agent": True},
    )
    return row


def approve_charge_request(uow: UnitOfWork, req_id: int, actor_id: int):
    """تأیید شارژ کارت‌به‌کارت توسط ادمین → واریز به کیف‌پول کاربر."""
    rbac.require(uow, actor_id, "wallet.adjust")
    row = _resolve_typed(uow, req_id, "charge", "approved")
    if not row.amount_minor or row.amount_minor <= 0:
        from core.errors import ValidationError
        raise ValidationError("مبلغ درخواست شارژ نامعتبر است")
    from core.wallet.service import adjust_balance
    new_balance = adjust_balance(
        uow, row.user_id, row.amount_minor, "شارژ کیف پول (کارت به کارت)",
        currency=row.currency or "TOMAN", actor_id=actor_id,
    )
    audit_service.record(
        uow, actor_id=actor_id, action="pending_request.approve_charge",
        entity_type="pending_request", entity_id=req_id,
        after={"user_id": row.user_id, "amount_minor": row.amount_minor,
               "balance_after_minor": new_balance},
    )
    return row


def reject_request(uow: UnitOfWork, req_id: int, actor_id: int):
    from core.errors import RequestAlreadyResolvedError
    rbac.require(uow, actor_id, "orders.approve")
    row = uow.pending_requests.resolve(req_id, "rejected")
    if row is None:
        raise RequestAlreadyResolvedError(f"درخواست {req_id} قبلاً پردازش شده")
    audit_service.record(
        uow, actor_id=actor_id, action="pending_request.reject",
        entity_type="pending_request", entity_id=req_id, after={"user_id": row.user_id},
    )
    return row


def approve_direct_purchase(uow: UnitOfWork, req_id: int, actor_id: int):
    """تأیید فیش خرید مستقیم (کارت‌به‌کارت) توسط ادمین → صدور کانفیگ بدون کسر کیف‌پول."""
    rbac.require(uow, actor_id, "orders.approve")
    row = _resolve_typed(uow, req_id, "buy", "approved")

    product = uow.products.get(row.product_id)
    if product is None:
        raise ProductNotFoundError(f"محصول {row.product_id} یافت نشد")

    from core.provisioning import service as provisioning_service
    provisioned = provisioning_service.active_profile(uow, row.product_id) is not None
    if provisioned:
        provisioning_service.assert_ready(uow, row.product_id)  # خطا → کل تأیید Rollback؛ درخواست pending می‌ماند
        item = None
    else:
        item = uow.inventory.claim_one(row.product_id, row.user_id)
        if item is None:
            raise OutOfStockError(f"مخزن محصول {row.product_id} خالی است")

    coupon_disc = 0
    if row.coupon_code and row.expected_price_minor is not None:
        # کاربر دقیقاً همین مبلغ را (با کوپن) پرداخته؛ قیمتِ لحظهٔ تأیید جایگزین آن نمی‌شود
        price = row.expected_price_minor
        coupon_disc = max(0, product.price_minor - price)
    else:
        price = price_for_user(uow, row.user_id, product)

    order = uow.orders.create(
        user_id=row.user_id, product_id=row.product_id,
        inventory_item_id=item.id if item else provisioning_service.NO_INVENTORY,
        price_minor=price, currency=product.currency,
        status="PROVISIONING" if provisioned else "COMPLETED",
    )
    _redeem_if_any(uow, row.coupon_code, coupon_disc, order, row.user_id)
    audit_service.record(
        uow, actor_id=actor_id, action="pending_request.approve_direct_purchase",
        entity_type="order", entity_id=order.id,
        after={"pending_request_id": req_id, "item_id": item.id if item else None, "provisioned": provisioned},
    )
    if not provisioned:
        from core.reseller import service as reseller_service
        reseller_service.reward_for_paid_order(uow, row.user_id)
    return item, product, order


def refund_order(uow: UnitOfWork, actor_id: int, order_id: int, *, restock: bool = False) -> int:
    """
    بازپرداخت سفارش تکمیل‌شده: مبلغ به کیف‌پول کاربر برمی‌گردد؛ اتمیک به‌کمک
    `mark_refunded` (که فقط از COMPLETED عبور می‌کند) — جلوگیری از بازپرداخت دوبار.
    اگر `restock=True`، آیتم مصرف‌شده به مخزن برنمی‌گردد (کانفیگ‌های VPN معمولاً
    قابل استفادهٔ مجدد نیستند)؛ فقط برای صراحت پارامتر گذاشته شده — پیاده‌سازی
    واقعی restock در صورت نیاز به Provider بستگی دارد و اینجا هرگز شبیه‌سازی
    نمی‌شود.
    """
    from core.errors import NotFoundError, ConflictError
    from core.wallet.service import adjust_balance
    rbac.require(uow, actor_id, "orders.refund")
    order = uow.orders.get_by_id(order_id)
    if order is None:
        raise NotFoundError(f"سفارش {order_id} یافت نشد")
    pc = uow.provisioning.get_client_by_order(order_id)
    if pc is not None and pc.status in ("ACTIVE", "EXPIRED", "SUSPENDED"):
        raise ConflictError("این سفارش سرویس فعالِ Provider دارد؛ از «لغو و بازپرداخت سرویس» استفاده کنید")
    if not uow.orders.mark_refunded(order_id):
        raise ConflictError("این سفارش قابل بازپرداخت نیست (وضعیت فعلی مناسب نیست)")
    if pc is not None:
        uow.provisioning.set_client_status(order_id, "CANCELLED")
    new_balance = adjust_balance(
        uow, order.user_id, order.price_minor, f"بازپرداخت سفارش #{order_id}",
        currency=order.currency, actor_id=actor_id,
    )
    audit_service.record(
        uow, actor_id=actor_id, action="order.refund", entity_type="order", entity_id=order_id,
        before={"status": "COMPLETED"}, after={"status": "REFUNDED", "balance_after_minor": new_balance},
    )
    return new_balance


def list_page(uow: UnitOfWork, actor_id: int, *, status=None, user_id=None, page: int = 0):
    rbac.require(uow, actor_id, "orders.view")
    return uow.orders.page(status=status, user_id=user_id, page=page)
