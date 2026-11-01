"""
Typed Settings Registry — همهٔ تنظیمات قابل‌مدیریت از پنل، با اعتبارسنجی، Permission
و Audit (before/after). هیچ مقدار کسب‌وکاری حدسی seed نمی‌شود: مقادیر «۰ = غیرفعال/بدون سقف»
تا Owner تصمیم بگیرد. مقدار پیش‌فرض referral/dice همان مقادیر V1 است.

توسعه‌دهنده: MohZarg — https://github.com/MohZarg
حمایت مالی: https://github.com/MohZarg
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ValidationError, NotFoundError

_MAX_INT = 10 ** 12


@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    kind: str                     # int | bool | text | card | enum
    default: str
    permission: str = "settings.manage"
    min: int = 0
    max: int = _MAX_INT
    choices: tuple = ()
    mask_in_audit: bool = False
    group: str = "general"
    hint: str = ""


SETTINGS: dict[str, SettingDef] = {d.key: d for d in [
    SettingDef("locked", "حالت تعمیرات ربات", "bool", "0", group="general"),
    SettingDef("phone_verify_required", "احراز شماره پیش از شارژ", "bool", "0", group="general"),
    SettingDef("card_number", "شمارهٔ کارت مقصد", "card", "شماره کارت", mask_in_audit=True, group="payments"),
    SettingDef("card_name", "نام دارندهٔ کارت", "text", "نام دارنده کارت", group="payments"),
    SettingDef("min_charge_minor", "حداقل مبلغ شارژ (۰=بدون حد)", "int", "0", group="payments"),
    SettingDef("max_charge_minor", "حداکثر مبلغ شارژ (۰=بدون حد)", "int", "0", group="payments"),
    SettingDef("pending_expiry_hours", "انقضای خودکار درخواست‌های معلق (ساعت، ۰=غیرفعال)", "int", "0",
               max=24 * 365, group="payments"),
    SettingDef("wallet_adjust_max_minor", "سقف هر تنظیم دستی موجودی (۰=بدون سقف)", "int", "0", group="wallet",
               permission="settings.manage"),
    SettingDef("low_stock_threshold", "آستانهٔ هشدار کمبود موجودی", "int", "0", group="inventory", max=100000),
    SettingDef("tickets_max_open", "حداکثر تیکت باز هر کاربر", "int", "3", min=1, max=100, group="tickets"),
    SettingDef("coupon_stacking", "ترکیب کوپن با تخفیف نقش", "enum", "best", choices=("best", "stack"),
               permission="coupons.manage", group="coupons",
               hint="best=فقط مناسب‌ترین قیمت؛ stack=کوپن روی قیمت نقش"),
    SettingDef("referral_enabled", "پاداش رفرال فعال", "bool", "1", permission="referral.manage", group="referral"),
    SettingDef("referral_bonus_minor", "پاداش هر دعوت (تومان)", "int", "5000", permission="referral.manage",
               group="referral"),
    SettingDef("referral_trigger", "زمان پرداخت پاداش رفرال", "enum", "first_order",
               choices=("first_order", "signup"), permission="referral.manage", group="referral",
               hint="first_order = پس از اولین سفارش پرداخت‌شدهٔ موفق (ضدسوءاستفاده)؛ signup = رفتار قدیمی V1"),
    SettingDef("referral_require_phone", "پاداش فقط اگر دعوت‌شده شماره ایران تأییدشده دارد", "bool", "0",
               permission="referral.manage", group="referral"),
    SettingDef("referral_daily_cap", "سقف پاداش روزانهٔ هر معرف (تعداد، ۰=بدون سقف)", "int", "0",
               permission="referral.manage", group="referral"),
    SettingDef("dice_enabled", "گردونه شانس فعال", "bool", "1", permission="promotions.manage", group="dice"),
    SettingDef("dice_reward", "جایزهٔ تاس ۶ (تومان)", "int", "20000", permission="promotions.manage", group="dice"),
    SettingDef("dice_cooldown_hours", "کول‌داون گردونه (ساعت)", "int", "24", min=1, max=24 * 30,
               permission="promotions.manage", group="dice"),
    SettingDef("dice_daily_budget_minor", "سقف بودجهٔ روزانهٔ جایزه (۰=بدون سقف)", "int", "0",
               permission="promotions.manage", group="dice"),
    SettingDef("auto_renewal_enabled", "تمدید خودکار (غیرفعال تا تصمیم Owner)", "bool", "0",
               permission="settings.manage", group="renewal"),
    SettingDef("auto_renewal_window_hours", "تمدید خودکار: چند ساعت قبل از انقضا", "int", "24", min=1, max=24 * 14,
               permission="settings.manage", group="renewal"),
    SettingDef("expiry_reminder_hours", "یادآوری انقضا: چند ساعت قبل (۰=خاموش)", "int", "72", max=24 * 30,
               permission="settings.manage", group="renewal"),
    SettingDef("provision_max_attempts", "حداکثر تلاش خودکار صدور سرویس", "int", "5", min=1, max=50,
               permission="settings.manage", group="system"),
    SettingDef("backup_daily_enabled", "Backup روزانهٔ خودکار", "bool", "1",
               permission="backup.create", group="system"),
    SettingDef("backup_retention_count", "تعداد Backup نگهداری‌شده (۰=همه)", "int", "7", max=1000,
               permission="backup.create", group="system"),
    SettingDef("credits_url", "لینک حمایت/دونیت (نمایش در منو و پنل)", "text", "https://github.com/MohZarg",
               permission="settings.manage", group="branding",
               hint="لینک صفحه حمایت مالی — در منوی ادمین و فوتر نمایش داده می‌شود"),
    SettingDef("developer_name", "نام توسعه‌دهنده (نمایش در فوتر/منو)", "text", "MohZarg",
               permission="settings.manage", group="branding",
               hint="نام یا نام‌نمای توسعه‌دهنده برای نمایش در 크دیت‌ها"),
]}


def definition(key: str) -> SettingDef:
    d = SETTINGS.get(key)
    if d is None:
        raise NotFoundError(f"تنظیم ناشناس: {key}")
    return d


def get(uow: UnitOfWork, key: str) -> str:
    d = definition(key)
    return uow.settings.get(key, d.default) or d.default


def get_int(uow: UnitOfWork, key: str) -> int:
    try:
        return int(get(uow, key))
    except ValueError:
        return int(definition(key).default)


def get_bool(uow: UnitOfWork, key: str) -> bool:
    return get(uow, key) == "1"


def normalize(d: SettingDef, raw: str) -> str:
    raw = (raw or "").strip()
    if d.kind == "bool":
        if raw not in ("0", "1"):
            raise ValidationError("مقدار باید 0 یا 1 باشد")
        return raw
    if d.kind == "int":
        digits = _en_digits(raw)
        if not digits.isdigit():
            raise ValidationError("فقط عدد صحیح غیرمنفی مجاز است")
        v = int(digits)
        if not (d.min <= v <= d.max):
            raise ValidationError(f"مقدار باید بین {d.min} و {d.max} باشد")
        return str(v)
    if d.kind == "enum":
        if raw not in d.choices:
            raise ValidationError(f"مقدار مجاز: {', '.join(d.choices)}")
        return raw
    if d.kind == "card":
        digits = _en_digits(raw).replace(" ", "").replace("-", "")
        if not (digits.isdigit() and len(digits) == 16):
            raise ValidationError("شمارهٔ کارت باید دقیقاً ۱۶ رقم باشد")
        return digits
    # text
    if not raw or len(raw) > 100:
        raise ValidationError("متن باید بین ۱ تا ۱۰۰ کاراکتر باشد")
    return raw


_P = "۰۱۲۳۴۵۶۷۸۹"
_A = "٠١٢٣٤٥٦٧٨٩"


def _en_digits(s: str) -> str:
    return "".join(str(_P.index(c)) if c in _P else str(_A.index(c)) if c in _A else c for c in s)


def _mask(d: SettingDef, v: Optional[str]) -> Optional[str]:
    if v is None or not d.mask_in_audit:
        return v
    return "*" * max(0, len(v) - 4) + v[-4:]


def set_value(uow: UnitOfWork, actor_id: int, key: str, raw: str) -> str:
    d = definition(key)
    rbac.require(uow, actor_id, d.permission)
    value = normalize(d, raw)
    before = uow.settings.get(key, d.default)
    if before == value:
        return value
    uow.settings.set(key, value)
    audit_service.record(
        uow, actor_id=actor_id, action="settings.change", entity_type="setting", entity_id=key,
        before={"value": _mask(d, before)}, after={"value": _mask(d, value)},
    )
    return value


def toggle_bool(uow: UnitOfWork, actor_id: int, key: str) -> bool:
    d = definition(key)
    if d.kind != "bool":
        raise ValidationError("این تنظیم Boolean نیست")
    new = "0" if get_bool(uow, key) else "1"
    set_value(uow, actor_id, key, new)
    return new == "1"


def list_group(group: str) -> list[SettingDef]:
    return [d for d in SETTINGS.values() if d.group == group]


def display(uow: UnitOfWork, key: str) -> str:
    d = definition(key)
    v = get(uow, key)
    if d.kind == "card":
        return _mask(SettingDef(**{**d.__dict__, "mask_in_audit": True}), v) or v
    if d.kind == "bool":
        return "فعال ✅" if v == "1" else "غیرفعال ⛔"
    return v
