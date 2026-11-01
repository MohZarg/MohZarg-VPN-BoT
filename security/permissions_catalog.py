"""
GhYiAb V2 — Permission Catalog (منبع واحد نام‌های Permission)
================================================================

فرمت: ``module.action``. این ماژول عمداً هیچ وابستگی‌ای ندارد تا هم `core/*`
و هم `repository/sqlite/connection.py` (برای seed) بتوانند آن را import کنند
بدون نقض لایه‌بندی.

- OWNER همیشه همهٔ Permissionهای این کاتالوگ را دارد (sync در init_schema).
- ADMIN هیچ Permission پیش‌فرضی ندارد؛ فقط آنچه OWNER صریحاً بدهد
  (جدول user_permissions). تنها OWNER می‌تواند Permission بدهد/بگیرد.
- `OWNER_ONLY` هرگز قابل واگذاری نیست (جلوگیری از Privilege Escalation).
"""

from __future__ import annotations

# name -> (module, توضیح فارسی)
CATALOG: dict[str, tuple[str, str]] = {
    "dashboard.view": ("dashboard", "مشاهده داشبورد"),
    "users.view": ("users", "مشاهده/جستجوی کاربران"),
    "users.ban": ("users", "مسدود/رفع مسدودی کاربر"),
    "users.agent": ("users", "اعطا/لغو نمایندگی"),
    "wallet.view": ("wallet", "مشاهده کیف پول و تراکنش‌ها"),
    "wallet.adjust": ("wallet", "تنظیم موجودی + تأیید شارژ"),
    "catalog.manage": ("catalog", "دسته‌بندی و Variant"),
    "products.manage": ("catalog", "مدیریت پلن‌ها"),
    "inventory.view": ("inventory", "مشاهده مخزن"),
    "inventory.manage": ("inventory", "افزودن/حذف کانفیگ"),
    "inventory.reveal": ("inventory", "نمایش کامل محتوای کانفیگ"),
    "providers.view": ("providers", "مشاهده Providerها"),
    "providers.manage": ("providers", "مدیریت Provider و Provisioning"),
    "services.view": ("services", "مشاهده سرویس‌های VPN مشتریان"),
    "services.manage": ("services", "تمدید/تعلیق/فعال‌سازی/ریست ترافیک سرویس"),
    "orders.view": ("orders", "مشاهده سفارش‌ها"),
    "orders.approve": ("orders", "تأیید/رد خرید مستقیم"),
    "orders.refund": ("orders", "بازپرداخت سفارش"),
    "payments.view": ("payments", "مشاهده پرداخت‌ها"),
    "coupons.manage": ("coupons", "مدیریت کوپن"),
    "referral.manage": ("referral", "مدیریت رفرال"),
    "reseller.manage": ("referral", "مدیریت سطوح Reseller"),
    "broadcast.send": ("broadcast", "پیام همگانی"),
    "tickets.view": ("tickets", "مشاهده تیکت‌ها"),
    "tickets.reply": ("tickets", "پاسخ/بستن تیکت"),
    "promotions.manage": ("promotions", "گردونه شانس/تبلیغات"),
    "settings.view": ("settings", "مشاهده تنظیمات"),
    "settings.manage": ("settings", "تغییر تنظیمات"),
    "audit.view": ("audit", "مشاهده Audit Log"),
    "jobs.view": ("jobs", "مشاهده Jobها"),
    "jobs.manage": ("jobs", "اجرا/فعال‌سازی Jobها"),
    "backup.create": ("system", "ساخت/بررسی Backup"),
    "backup.download": ("system", "ارسال فایل Backup"),
    "system.health": ("system", "سلامت سیستم"),
    "admins.view": ("admins", "مشاهده ادمین‌ها"),
    "rbac.manage": ("admins", "مدیریت ادمین‌ها و Permissionها"),
}

# هرگز به ADMIN واگذار نمی‌شوند.
OWNER_ONLY: frozenset[str] = frozenset({"rbac.manage", "backup.download"})

# ده Permission قدیمی Phase 3 (برای سازگاری با نصب‌های قبلی)
LEGACY_BASE: tuple[str, ...] = (
    "wallet.adjust", "inventory.manage", "products.manage", "catalog.manage",
    "providers.manage", "orders.approve", "users.ban", "rbac.manage",
    "settings.manage", "broadcast.send",
)

GRANTABLE: frozenset[str] = frozenset(CATALOG) - OWNER_ONLY


def modules() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, (mod, _) in CATALOG.items():
        out.setdefault(mod, []).append(name)
    return out


# Presetهای نقش (قالب مجموعهٔ Permission). مدل واقعی همچنان per-user است؛ preset فقط
# میان‌بر Owner برای اعطای یک‌جا است. فقط نقش‌هایی که امروز لازم‌اند تعریف شده‌اند؛
# افزودن نقش جدید = افزودن یک ورودی (بدون تغییر اسکیما).
ROLE_PRESETS: dict[str, tuple[str, ...]] = {
    "SUPPORT": ("users.view", "tickets.view", "tickets.reply", "services.view", "orders.view", "wallet.view"),
    "FINANCE": ("wallet.view", "wallet.adjust", "orders.view", "orders.approve", "orders.refund",
                "payments.view", "coupons.manage", "dashboard.view"),
    "ADMIN": tuple(sorted(set(CATALOG) - OWNER_ONLY - {"rbac.manage"})),
}
