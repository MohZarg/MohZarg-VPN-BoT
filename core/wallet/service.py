"""
GhYiAb V2 — Wallet Core Service
==================================

پورت مستقیمِ رفتاری `adjust_balance` قدیمی، به‌علاوهٔ:
  - ستون currency صریح (رفع P0-1 در Audit — دیگر بدون چندارزی نیست)
  - AuditLog خودکار برای هر تغییر موجودی (رفع P0-2)
  - idempotency_key اختیاری (اگر صدازننده بدهد، تراکنش تکراری نادیده گرفته
    می‌شود؛ اگر ندهد رفتار دقیقاً مثل قبل است — بدون تغییر رفتاری اجباری)

هیچ‌کدام از این افزوده‌ها رفتار مشاهده‌پذیر مسیر فعلی (کاربر عادی شارژ/کسر
می‌شود، تراکنش ثبت می‌شود) را عوض نمی‌کنند؛ فقط سالم‌تر و قابل‌ردیابی‌ترش
می‌کنند — دقیقاً طبق دستور Owner در Phase 1.
"""

from __future__ import annotations

from typing import Optional

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import InsufficientBalanceError, ValidationError, NotFoundError

DEFAULT_CURRENCY = "TOMAN"


def get_balance(uow: UnitOfWork, user_id: int, currency: str = DEFAULT_CURRENCY) -> int:
    return uow.wallet.get_balance(user_id, currency)


def adjust_balance(uow: UnitOfWork, user_id: int, delta_minor: int, reason: str,
                    *, currency: str = DEFAULT_CURRENCY,
                    actor_id: Optional[int] = None,
                    idempotency_key: Optional[str] = None) -> int:
    """
    موجودی را تغییر می‌دهد (مثبت=افزایش، منفی=کسر بدون بررسی کفایت موجودی —
    دقیقاً معادل adjust_balance قدیمی که برای عملیات ادمین/رفرال/جایزه استفاده
    می‌شد). برای کسر مشروط به کفایت موجودی از `debit_for_purchase` استفاده کن.
    """
    if idempotency_key:
        existing = uow.wallet.find_transaction_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing.balance_after_minor

    new_balance = uow.wallet.adjust(user_id, currency, delta_minor)
    uow.wallet.record_transaction(
        user_id, currency, delta_minor, new_balance, reason,
        idempotency_key=idempotency_key,
    )
    audit_service.record(
        uow,
        actor_id=actor_id if actor_id is not None else user_id,
        action="wallet.adjust",
        entity_type="wallet",
        entity_id=user_id,
        before=None,
        after={"currency": currency, "delta_minor": delta_minor,
               "balance_after_minor": new_balance, "reason": reason},
    )
    return new_balance


def debit_for_purchase(uow: UnitOfWork, user_id: int, amount_minor: int, reason: str,
                        *, currency: str = DEFAULT_CURRENCY,
                        idempotency_key: Optional[str] = None) -> int:
    """
    کسر مشروط به کفایت موجودی — معادل بخش کسر داخل `purchase_with_wallet`
    قدیمی. اگر موجودی کافی نباشد InsufficientBalanceError پرتاب می‌شود.
    """
    if idempotency_key:
        existing = uow.wallet.find_transaction_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing.balance_after_minor

    ok = uow.wallet.debit_if_sufficient(user_id, currency, amount_minor)
    if not ok:
        raise InsufficientBalanceError(f"موجودی کاربر {user_id} کافی نیست")

    new_balance = uow.wallet.get_balance(user_id, currency)
    uow.wallet.record_transaction(
        user_id, currency, -amount_minor, new_balance, reason,
        idempotency_key=idempotency_key,
    )
    audit_service.record(
        uow, actor_id=user_id, action="wallet.debit", entity_type="wallet",
        entity_id=user_id,
        after={"currency": currency, "amount_minor": amount_minor,
               "balance_after_minor": new_balance, "reason": reason},
    )
    return new_balance


def list_recent_transactions(uow: UnitOfWork, user_id: int, limit: int = 10):
    return uow.wallet.list_recent_transactions(user_id, limit)


def admin_adjust(uow: UnitOfWork, actor_id: int, target_id: int, delta_minor: int, reason: str,
                 *, currency: str = DEFAULT_CURRENCY) -> int:
    """تنظیم دستی موجودی توسط ادمین: Permission، دلیل اجباری، سقف اختیاری، جلوگیری از منفی شدن."""
    from core.settings import service as settings_service
    rbac.require(uow, actor_id, "wallet.adjust")
    reason = (reason or "").strip()
    if not reason or len(reason) > 200:
        raise ValidationError("دلیل تنظیم موجودی الزامی است (حداکثر ۲۰۰ کاراکتر)")
    if delta_minor == 0:
        raise ValidationError("مبلغ نمی‌تواند صفر باشد")
    cap = settings_service.get_int(uow, "wallet_adjust_max_minor")
    if cap > 0 and abs(delta_minor) > cap:
        raise ValidationError(f"مبلغ از سقف مجاز تنظیم دستی ({cap:,}) بیشتر است")
    if not uow.users.exists(target_id):
        raise NotFoundError(f"کاربر {target_id} یافت نشد")
    if delta_minor < 0 and uow.wallet.get_balance(target_id, currency) + delta_minor < 0:
        raise InsufficientBalanceError("کسر بیش از موجودی کاربر ممکن نیست")
    return adjust_balance(uow, target_id, delta_minor, f"ادمین: {reason}",
                          currency=currency, actor_id=actor_id)
