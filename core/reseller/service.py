"""Reseller Tiers + Referral rewards/anti-abuse — با سقف‌های قابل‌تنظیم از core/settings."""

from __future__ import annotations

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ValidationError, NotFoundError, ConflictError


# ---- Reseller tiers ----

def create_tier(uow: UnitOfWork, actor_id: int, name: str, discount_percent: int):
    rbac.require(uow, actor_id, "reseller.manage")
    name = (name or "").strip()
    if not name or len(name) > 40:
        raise ValidationError("نام سطح باید بین ۱ تا ۴۰ کاراکتر باشد")
    if not (0 <= discount_percent <= 100):
        raise ValidationError("درصد تخفیف باید بین ۰ تا ۱۰۰ باشد")
    tier = uow.resellers.create_tier(name, discount_percent)
    audit_service.record(uow, actor_id=actor_id, action="reseller.tier_create", entity_type="reseller_tier",
                         entity_id=tier.id, after={"name": name, "discount_percent": discount_percent})
    return tier


def assign_tier(uow: UnitOfWork, actor_id: int, user_id: int, tier_id) -> None:
    rbac.require(uow, actor_id, "reseller.manage")
    if not uow.users.exists(user_id):
        raise NotFoundError("کاربر یافت نشد")
    if tier_id is not None and uow.resellers.get_tier(tier_id) is None:
        raise NotFoundError("سطح یافت نشد")
    before = uow.users.get_or_create(user_id).reseller_tier_id
    uow.users.set_reseller_tier(user_id, tier_id)
    audit_service.record(uow, actor_id=actor_id, action="reseller.assign", entity_type="user",
                         entity_id=user_id, before={"tier_id": before}, after={"tier_id": tier_id})


def tier_discount_for(uow: UnitOfWork, user_id: int) -> int:
    u = uow.users.get_or_create(user_id)
    if not u.reseller_tier_id:
        return 0
    tier = uow.resellers.get_tier(u.reseller_tier_id)
    return tier.discount_percent if (tier and tier.is_active) else 0


# ---- Referral rewards (ضد سوءاستفاده: سقف روزانه + قابل غیرفعال‌سازی، طبق core/settings) ----

def pay_referral_reward(uow: UnitOfWork, referrer_id: int, referred_id: int, *, notify_later: bool = False) -> bool:
    """
    اتمیک: هر referred_id فقط یک‌بار پاداش می‌دهد (UNIQUE در schema).
    سقف روزانه/غیرفعال‌سازی سراسری از core/settings خوانده می‌شود (پیش‌فرض‌ها
    دقیقاً معادل رفتار V1: فعال، بدون سقف، مبلغ ۵۰۰۰ تومان) — طبق TODO #6،
    سیاست دقیق ضدسوءاستفادهٔ نهایی هنوز از Owner دریافت نشده؛ این سقف‌ها
    صرفاً امکان کنترل را فراهم می‌کنند، نه یک قاعدهٔ تجاری حدسی جدید.
    """
    from core.settings import service as settings_service
    from core.wallet.service import adjust_balance, DEFAULT_CURRENCY
    if not settings_service.get_bool(uow, "referral_enabled"):
        return False
    if referrer_id == referred_id or not referrer_id:  # بدون خود-ارجاعی
        return False
    if settings_service.get_bool(uow, "referral_require_phone") and not uow.users.get_or_create(referred_id).phone_verified:
        return False
    cap = settings_service.get_int(uow, "referral_daily_cap")
    if cap > 0 and uow.referrals.count_rewards_today(referrer_id) >= cap:
        return False
    amount = settings_service.get_int(uow, "referral_bonus_minor")
    reward = uow.referrals.record_reward(referrer_id, referred_id, amount, DEFAULT_CURRENCY, notified=not notify_later)
    if reward is None:  # UNIQUE(referred_id) violated → پاداش قبلاً پرداخت شده
        return False
    adjust_balance(uow, referrer_id, amount, f"پاداش دعوت کاربر {referred_id}", actor_id=0)
    audit_service.record(uow, actor_id=0, action="referral.reward_paid", entity_type="user",
                         entity_id=referrer_id, after={"referred_id": referred_id, "amount_minor": amount})
    return True


def reverse_reward(uow: UnitOfWork, actor_id: int, reward_id: int) -> None:
    """بازپس‌گیری پاداش رفرال (مثلاً به‌خاطر فراخ‌درخواست جعلی) — موجودی را هم کسر می‌کند."""
    from core.wallet.service import adjust_balance
    rbac.require(uow, actor_id, "referral.manage")
    reward = uow.referrals.get(reward_id)
    if reward is None:
        raise NotFoundError("رکورد پاداش یافت نشد")
    if not uow.referrals.mark_reversed(reward_id):
        raise ConflictError("این پاداش قبلاً برگشت خورده است")
    adjust_balance(uow, reward.referrer_id, -reward.amount_minor,
                   f"برگشت پاداش رفرال #{reward_id}", currency=reward.currency, actor_id=actor_id)
    audit_service.record(uow, actor_id=actor_id, action="referral.reward_reversed", entity_type="user",
                         entity_id=reward.referrer_id, after={"reward_id": reward_id})


def reward_for_paid_order(uow: UnitOfWork, user_id: int) -> bool:
    """
    پاداش رفرال پس از اولین سفارش *پرداخت‌شدهٔ موفق* (trigger=first_order). Idempotent:
    UNIQUE(referred_id) مانع پاداش دوباره می‌شود، بنابراین فراخوانی در هر سفارش بی‌خطر است.
    فقط برای سفارش‌های COMPLETED فراخوانی می‌شود (صدور ناموفق/بازپرداخت‌شده پاداش نمی‌دهد).
    """
    from core.settings import service as settings_service
    if settings_service.get(uow, "referral_trigger") != "first_order":
        return False
    u = uow.users.get_or_create(user_id)
    if not u.referred_by:
        return False
    return pay_referral_reward(uow, u.referred_by, user_id, notify_later=True)
