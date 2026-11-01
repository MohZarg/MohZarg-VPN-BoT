"""
GhYiAb V2 — Admin Control Center (Telegram Adapter)
======================================================

توسعه‌دهنده: MohZarg — https://github.com/MohZarg
حمایت مالی: https://github.com/MohZarg

پنل کامل مدیریت روی تلگرام. طبق قانون سخت معماری («Telegram فقط UI است»)،
هیچ منطق کسب‌وکاری اینجا نیست: هر عملیات از یک تابع `core/*` عبور می‌کند که
خودش Permission را چک و AuditLog را ثبت می‌کند (Defense-in-depth: اینجا هم
یک‌بار چک می‌شود تا پیام خطای فارسیِ مناسب نشان داده شود، نه فقط برای امنیت).

معماری این فایل:
  * فضای نام callback: هر callback_data با پیشوند ``acc:`` شروع می‌شود
    (Admin Control Center) — کاملاً مجزا از callbackهای قدیمی V1 در bot.py
    که زیرخط‌دار هستند (adm_*, ok_dp_*, ...) و دست‌نخورده باقی می‌مانند.
  * State: یک دیکشنری با کلید ``acc`` در `app_ctx.state` ذخیره می‌شود، پس با
    Stateهای متنی قدیمی V1 (`"waiting_for_charge_amount"`) هرگز تداخل ندارد.
  * `handle_callback` / `handle_text` از bot.py با یک بررسی ارزان (پیشوند)
    صدا زده می‌شوند و اگر مسیر مربوط به این پنل نبود فوراً کنترل را پس
    می‌دهند — صفر ریسک رگرسیون روی مسیرهای موجود.
  * Confirmation دومرحله‌ای (core.confirm) برای هر عملیات مخرب/مالی حساس:
    Refund، بازپرداخت، حذف پلن، حذف کانفیگ، Revoke ادمین، تغییر Permission،
    ساخت Backup سنگین، ارسال Broadcast، بن کاربر ادمین. کلیک تکراری روی یک
    دکمهٔ قبلاً اجراشده چیزی جز «⏱️ این عملیات قبلاً اجرا/منقضی شده» تولید
    نمی‌کند (idempotent از دید کاربر).
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from bootstrap import AppContext
from security.secret_loader import BotSecrets
from core.auth import rbac
from core.audit import service as audit_service
from core.confirm import service as confirm_service
from core.settings import service as settings_service
from core.users import service as users_service
from core.catalog import service as catalog_service
from core.inventory import service as inventory_service
from core.orders import service as orders_service
from core.wallet import service as wallet_service
from core.coupons import service as coupons_service
from core.reseller import service as reseller_service
from core.tickets import service as tickets_service
from core.broadcast import service as broadcast_service
from core.jobs import service as jobs_service
from core.system import service as system_service
from core.provisioning import service as provisioning_service
from core.vpn_services import service as vpn_service
from core.errors import (
    DomainError, ValidationError, NotFoundError, ConflictError, NotAuthorizedError,
    ConfirmationInvalidError, CouponError, ProviderNotReadyError, ProvisioningFailedError,
    RequestAlreadyResolvedError,
)
from adapters.telegram_bot.util import (
    esc, to_en_digits, parse_positive_int, parse_signed_int, parse_user_id,
)
from shared.i18n import t
from providers.vpn.base import VPNProviderError as vpn_errors

logger = logging.getLogger("ghyiab.bot.admin_panel")

PREFIX = "acc:"
PER_PAGE = 8


def _ctx(context: ContextTypes.DEFAULT_TYPE) -> AppContext:
    return context.application.bot_data["app_ctx"]


def _actor_id(update: Update) -> int:
    """هماهنگ با سبک bot.py: در Callback از ``query.from_user.id`` و در پیام
    متنی از ``update.effective_user.id`` استفاده می‌شود (Callbackهای فیک تست
    همیشه ``effective_user`` را ست نمی‌کنند، پس این تابع مسیر درست را انتخاب می‌کند)."""
    if update.callback_query is not None:
        return update.callback_query.from_user.id
    return update.effective_user.id


def _secrets(context: ContextTypes.DEFAULT_TYPE) -> BotSecrets:
    return context.application.bot_data["bot_secrets"]


def _state(app_ctx: AppContext, user_id: int) -> Optional[dict]:
    s = app_ctx.state.get(user_id)
    return s if isinstance(s, dict) and s.get("acc") else None


# Permissionِ لازم برای ورود به هر فلوی چندمرحله‌ای. قبلاً فقط is_admin چک می‌شد و ادمینِ بدون دسترسی
# تا لحظهٔ ثبت نهایی در فلو می‌ماند (سرویس رد می‌کرد، ولی UI و state نشت می‌کرد).
# setting_edit عمداً نیست: هر تنظیم Permission خودش را دارد و سرویس تنظیمات آن را می‌سنجد.
_FLOW_PERMISSION = {
    "wallet_amount": "wallet.adjust", "wallet_reason": "wallet.adjust",
    "broadcast_text": "broadcast.send", "ticket_reply": "tickets.reply",
    "new_admin_id": "rbac.manage", "user_search": "users.view",
    "product_new_name": "catalog.manage", "product_rename": "catalog.manage",
    "product_reprice": "catalog.manage", "product_new_price": "catalog.manage",
    "inventory_add": "inventory.manage", "inventory_purge": "inventory.manage",
    "prov_inbound": "providers.manage", "prov_duration": "providers.manage", "prov_traffic": "providers.manage",
    "coupon_code": "coupons.manage", "coupon_kind": "coupons.manage", "coupon_value": "coupons.manage",
    "tier_name": "reseller.manage", "tier_discount": "reseller.manage",
}


def _set_state(app_ctx: AppContext, user_id: int, flow: str, **extra) -> None:
    perm = _FLOW_PERMISSION.get(flow)
    if perm:
        with app_ctx.unit_of_work() as uow:
            rbac.require(uow, user_id, perm)
    app_ctx.state.set(user_id, {"acc": flow, **extra})


def _carry(state: dict) -> dict:
    """مقادیر یک state چندمرحله‌ای را بدون کلید ``acc`` برمی‌گرداند تا هنگام
    Spread شدن (``**_carry(state)``) به مرحلهٔ بعد، فلوی جدید را با فلوی قبلی
    جایگزین نکند (باگ واقعی که در تست پیدا شد: ``**state`` خام کلید ``acc``ِ
    قدیمی را در دیکشنری نهایی override می‌کرد)."""
    return {k: v for k, v in state.items() if k != "acc"}


def _clear(app_ctx: AppContext, user_id: int) -> None:
    app_ctx.state.clear(user_id)


def is_relevant_callback(data: str) -> bool:
    return data.startswith(PREFIX)


def is_relevant_state(app_ctx: AppContext, user_id: int) -> bool:
    return _state(app_ctx, user_id) is not None


def money(minor: int) -> str:
    return f"{minor:,}"


def kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(rows)


def back_row(target: str, label: str = None) -> list:
    label = label or t("common.back")
    return [InlineKeyboardButton(label, callback_data=f"{PREFIX}{target}")]


def home_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(t("common.home"), callback_data=f"{PREFIX}home")


ERROR_MESSAGES = {
    ValidationError: "⚠️ {}",
    NotFoundError: "❌ {}",
    ConflictError: "⚠️ {}",
    NotAuthorizedError: "⛔ {}",
    ConfirmationInvalidError: "⏱️ {}",
    CouponError: "🎫 {}",
    ProviderNotReadyError: "🚫 سرویس Provider آماده نیست: {}",
    ProvisioningFailedError: "🚫 خطای Provisioning: {}",
    RequestAlreadyResolvedError: "⏱️ {}",
}


def _fmt_error(exc: Exception) -> str:
    for cls, fmt in ERROR_MESSAGES.items():
        if isinstance(exc, cls):
            return fmt.format(str(exc))
    if isinstance(exc, DomainError):
        return f"⚠️ {exc}"
    logger.exception("خطای پیش‌بینی‌نشده در پنل ادمین")
    return "⚠️ خطای داخلی؛ به لاگ سرور مراجعه کنید."


async def _answer_error(update: Update, exc: Exception) -> None:
    text = _fmt_error(exc)
    if update.callback_query:
        try:
            await update.callback_query.answer(text[:200], show_alert=True)
        except TelegramError:
            pass
    elif update.message:
        await update.message.reply_text(text)


# ==========================================================================
# صفحهٔ خانه
# ==========================================================================

MODULES = [
    [(t("module.dashboard"), "dash"), (t("module.users"), "usr")],
    [(t("module.catalog"), "cat"), (t("module.inventory"), "inv")],
    [(t("module.providers"), "prov"), (t("module.orders"), "ord")],
    [(t("module.payments"), "pay"), (t("module.wallet"), "wal")],
    [(t("module.coupons"), "cpn"), (t("module.referral"), "ref")],
    [(t("module.broadcast"), "bro"), (t("module.tickets"), "tic")],
    [(t("module.dice"), "dice"), (t("module.settings"), "set")],
    [(t("module.admins"), "adm"), (t("module.audit"), "aud")],
    [(t("module.services"), "svcs"), (t("module.jobs"), "job")],
    [(t("module.backup"), "bak")],
]


async def open_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx = _ctx(context)
    user_id = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        if not rbac.is_admin(uow, user_id):
            return
        my_perms = set(rbac.list_my_permissions(uow, user_id))
        is_owner = rbac.is_owner(uow, user_id)
    rows = []
    for line in MODULES:
        row = [InlineKeyboardButton(label, callback_data=f"{PREFIX}{code}:home")
               for label, code in line]
        rows.append(row)
    rows.append([InlineKeyboardButton(t("common.close"), callback_data=f"{PREFIX}close")])
    text = "🏛️ <b>مرکز کنترل ادمین GhYiAb</b>\n\nیک بخش را انتخاب کنید:"
    if not is_owner:
        text += f"\n\n<i>سطح دسترسی شما: {len(my_perms)} Permission از OWNER دریافت‌شده</i>"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb(rows), parse_mode="HTML")
    else:
        await update.message.reply_html(text, reply_markup=kb(rows))


# ==========================================================================
# داشبورد
# ==========================================================================

async def open_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx = _ctx(context)
    user_id = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        d = system_service.dashboard(uow, user_id)
    rev = d.pop("revenue", {})
    lines = [
        "📊 <b>داشبورد GhYiAb</b>",
        f"👥 کاربران: {d['users_total']} (امروز: +{d['users_today']}) | 🚫 بن: {d['users_banned']} | 👑 نماینده: {d['agents']}",
        f"🧾 سفارش‌ها: {d['orders_total']} (امروز: {d['orders_today']}) | ⚠️ نیاز رسیدگی: {d['orders_problem']}",
        f"⏳ معلق: شارژ {d['pending_charge']} / خرید {d['pending_buy']} / نمایندگی {d['pending_agency']}",
        f"🎫 تیکت باز: {d['tickets_open']} | 📦 موجودی کل: {d['stock_total']}",
    ]
    for cur, v in rev.items():
        lines.append(f"💰 درآمد {cur}: امروز {money(v['today'])} / کل {money(v['total'])}")
    await update.callback_query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=kb([[InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"{PREFIX}dash:home")],
                        back_row("home")]))


# ==========================================================================
# ابزار عمومی صفحه‌بندی
# ==========================================================================

def pagination_row(base: str, page_obj) -> list:
    row = []
    if page_obj.page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"{base}:{page_obj.page - 1}"))
    row.append(InlineKeyboardButton(f"{page_obj.page + 1}/{page_obj.pages}", callback_data="acc:noop"))
    if page_obj.page + 1 < page_obj.pages:
        row.append(InlineKeyboardButton("▶️", callback_data=f"{base}:{page_obj.page + 1}"))
    return row


# ==========================================================================
# کاربران
# ==========================================================================

USER_FILTERS = [("all", t("filter.all")), ("banned", t("filter.banned")), ("agents", t("filter.agents")), ("blocked", t("filter.blocked"))]


async def open_users(update, context, flt: str = "all", page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        result = users_service.list_users(uow, actor, flt=flt, page=page)
    rows = [[InlineKeyboardButton(f"👤 {u.user_id}" + (" 🚫" if u.is_banned else "") + (" 👑" if u.is_agent else ""),
                                   callback_data=f"{PREFIX}usr:d:{u.user_id}")]
            for u in result.items]
    filt_row = [InlineKeyboardButton(("• " if f == flt else "") + label, callback_data=f"{PREFIX}usr:f:{f}:0")
                for f, label in USER_FILTERS]
    rows.append(filt_row)
    rows.append([InlineKeyboardButton("🔍 جستجو با آیدی/شماره", callback_data=f"{PREFIX}usr:search")])
    rows.append(pagination_row(f"{PREFIX}usr:f:{flt}", result))
    rows.append(back_row("home"))
    text = f"👥 <b>کاربران</b> — فیلتر: {dict(USER_FILTERS)[flt]} ({result.total} نفر)"
    await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb(rows))


async def open_user_detail(update, context, target_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        d = users_service.detail(uow, actor, target_id)
        can_ban = rbac.has_permission(uow, actor, "users.ban")
        can_agent = rbac.has_permission(uow, actor, "users.agent")
        can_reseller = rbac.has_permission(uow, actor, "reseller.manage")
        can_wallet = rbac.has_permission(uow, actor, "wallet.adjust")
    u = d["user"]
    lines = [
        f"🔍 <b>کاربر {target_id}</b>",
        f"💰 موجودی: {money(d['balance'])} تومان | 🧾 سفارش: {d['orders']} | 👥 زیرمجموعه: {d['referrals']}",
        f"🚫 بن: {'بله' if u.is_banned else 'خیر'} | 👑 نماینده: {'بله' if u.is_agent else 'خیر'}",
        f"📱 احراز شماره: {'بله' if u.phone_verified else 'خیر'}",
        f"🏷️ سطح Reseller: {esc(d['tier'].name) if d['tier'] else '—'}",
    ]
    if d["is_admin"]:
        lines.append("👮 این کاربر ادمین است" + (" (OWNER)" if d["is_owner"] else ""))
    rows = []
    if can_ban and not d["is_owner"]:
        rows.append([InlineKeyboardButton("🟢 رفع مسدودی" if u.is_banned else "🚫 مسدود کردن",
                                           callback_data=f"{PREFIX}usr:ban:{target_id}:{0 if u.is_banned else 1}")])
    if can_agent:
        rows.append([InlineKeyboardButton("👤 لغو نمایندگی" if u.is_agent else "👑 اعطای نمایندگی",
                                           callback_data=f"{PREFIX}usr:agent:{target_id}:{0 if u.is_agent else 1}")])
    if can_wallet:
        rows.append([InlineKeyboardButton("💰 تنظیم موجودی", callback_data=f"{PREFIX}wal:adj:{target_id}")])
    if can_reseller:
        rows.append([InlineKeyboardButton("🏷️ تعیین سطح Reseller", callback_data=f"{PREFIX}ref:assign:{target_id}")])
    rows.append(back_row("usr:f:all:0"))
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# پلن‌ها / دسته‌ها (Catalog)
# ==========================================================================

async def open_catalog(update, context, page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        result = catalog_service.list_products_page(uow, actor, page=page)
    rows = [[InlineKeyboardButton(
        f"{'✅' if p.is_active else '⛔'} {p.name} — {money(p.price_minor)} {p.currency}",
        callback_data=f"{PREFIX}cat:d:{p.id}")] for p in result.items]
    rows.append([InlineKeyboardButton("➕ پلن جدید", callback_data=f"{PREFIX}cat:new")])
    rows.append(pagination_row(f"{PREFIX}cat:p", result))
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"🛍️ <b>پلن‌ها</b> ({result.total})", parse_mode="HTML", reply_markup=kb(rows))


async def open_product_detail(update, context, product_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        p = uow.products.get(product_id)
        if p is not None:
            stock = inventory_service.stock_overview(uow, actor)
            avail = next((c for pid, _, c in stock if pid == product_id), 0)
            orders_count = uow.products.count_orders(product_id)
    if p is None:
        await update.callback_query.answer("محصول یافت نشد", show_alert=True)
        return
    lines = [
        f"📦 <b>{esc(p.name)}</b>", f"💵 قیمت: {money(p.price_minor)} {p.currency}",
        f"📊 موجودی: {avail} | 🧾 سفارش‌های ثبت‌شده: {orders_count}",
        f"وضعیت: {'✅ فعال' if p.is_active else '⛔ غیرفعال'}",
    ]
    rows = [
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"{PREFIX}cat:rn:{product_id}"),
         InlineKeyboardButton("💵 ویرایش قیمت", callback_data=f"{PREFIX}cat:rp:{product_id}")],
        [InlineKeyboardButton("⛔ غیرفعال‌سازی" if p.is_active else "✅ فعال‌سازی",
                              callback_data=f"{PREFIX}cat:act:{product_id}:{0 if p.is_active else 1}")],
        [InlineKeyboardButton("📦 مدیریت مخزن", callback_data=f"{PREFIX}inv:home:{product_id}:0")],
        [InlineKeyboardButton("🌐 پروفایل Provisioning", callback_data=f"{PREFIX}prov:pf:{product_id}")],
        [InlineKeyboardButton("🗑️ حذف پلن", callback_data=f"{PREFIX}cat:del:{product_id}")],
        back_row("cat:p:0"),
    ]
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# مخزن (Inventory)
# ==========================================================================

async def open_inventory_overview(update, context) -> None:
    """صفحهٔ اصلی ماژول «مخزن»: موجودی همهٔ محصولات + مخزن تست."""
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rows_data = inventory_service.stock_overview(uow, actor)
    rows = [[InlineKeyboardButton(f"{name} — موجود: {count}", callback_data=f"{PREFIX}inv:home:{pid}:0")]
            for pid, name, count in rows_data]
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        "📦 <b>مخزن</b>\n\nیک مخزن را برای افزودن یا مدیریت کانفیگ انتخاب کنید:",
        parse_mode="HTML", reply_markup=kb(rows))


async def open_inventory(update, context, product_id: int, page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        result = inventory_service.list_items(uow, actor, product_id, status="AVAILABLE", page=page)
    rows = [[InlineKeyboardButton(f"#{it.id} {inventory_service.mask(it.content)}",
                                  callback_data=f"{PREFIX}inv:i:{it.id}:{product_id}")]
            for it in result.items]
    rows.append([InlineKeyboardButton("➕ افزودن کانفیگ", callback_data=f"{PREFIX}inv:add:{product_id}")])
    rows.append([InlineKeyboardButton("🗑️ پاکسازی چند مورد", callback_data=f"{PREFIX}inv:purge:{product_id}")])
    rows.append(pagination_row(f"{PREFIX}inv:home:{product_id}", result))
    rows.append(back_row("inv:home" if product_id == 0 else f"cat:d:{product_id}"))
    title = "🔑 <b>مخزن تست</b>" if product_id == 0 else f"📦 <b>مخزن محصول #{product_id}</b>"
    await update.callback_query.edit_message_text(
        f"{title} — موجود: {result.total}", parse_mode="HTML", reply_markup=kb(rows))


async def open_inventory_item(update, context, item_id: int, product_id: int) -> None:
    rows = [
        [InlineKeyboardButton("👁️ نمایش کامل (حساس)", callback_data=f"{PREFIX}inv:reveal:{item_id}:{product_id}")],
        [InlineKeyboardButton("🗑️ حذف این آیتم", callback_data=f"{PREFIX}inv:delitem:{item_id}:{product_id}")],
        back_row(f"inv:home:{product_id}:0"),
    ]
    await update.callback_query.edit_message_text(
        f"🔎 آیتم #{item_id} — برای نمایش محتوای کامل (Sensitive) دکمهٔ زیر را بزنید.",
        reply_markup=kb(rows))


# ==========================================================================
# Providers / Provisioning
# ==========================================================================

async def open_providers(update, context) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "providers.view")
        profiles = uow.provisioning.list_profiles()
    health = provisioning_service.provider_health("3x-ui")
    status_txt = {"OK": "🟢 آماده", "NOT_CONFIGURED": "⚪ پیکربندی‌نشده", "BLOCKED": "🔴 خطا"}.get(
        health["status"], health["status"])
    lines = ["🌐 <b>Providerها</b>", f"3x-ui: {status_txt}"]
    if health.get("detail"):
        lines.append(f"جزئیات: {esc(health['detail'][:150])}")
    lines.append(f"\nپروفایل‌های تعریف‌شده: {len(profiles)}")
    rows = [[InlineKeyboardButton(f"محصول #{pf.product_id} → inbound {pf.inbound_id}",
                                  callback_data=f"{PREFIX}prov:pf:{pf.product_id}")] for pf in profiles]
    rows.append([InlineKeyboardButton("🔄 بررسی مجدد سلامت", callback_data=f"{PREFIX}prov:home")])
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


async def open_provisioning_profile(update, context, product_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "providers.view")
        pf = uow.provisioning.get_profile(product_id)
    if pf is None:
        text = (f"🌐 محصول #{product_id} هنوز پروفایل Provisioning ندارد؛ سفارش‌های آن با مسیر "
                "دستی/متنی V1 ادامه می‌یابند (No Fake Integration — چیزی حدس زده نمی‌شود).")
        rows = [[InlineKeyboardButton("➕ تعریف پروفایل (نیاز به Inbound واقعی)",
                                      callback_data=f"{PREFIX}prov:new:{product_id}")]]
    else:
        text = (f"🌐 محصول #{product_id}\nProvider: {pf.provider_name} | Inbound: {pf.inbound_id}\n"
                f"مدت: {pf.duration_days} روز | ترافیک: {pf.traffic_gb} GB | حداکثر IP: {pf.limit_ip}\n"
                f"وضعیت: {'✅ فعال' if pf.is_active else '⛔ غیرفعال'}")
        rows = [[InlineKeyboardButton("⛔ غیرفعال‌سازی" if pf.is_active else "✅ فعال‌سازی",
                                      callback_data=f"{PREFIX}prov:tgl:{product_id}:{0 if pf.is_active else 1}")],
                [InlineKeyboardButton("✏️ بازتعریف", callback_data=f"{PREFIX}prov:new:{product_id}")]]
    rows.append(back_row(f"cat:d:{product_id}"))
    await update.callback_query.edit_message_text(text, reply_markup=kb(rows))


# ==========================================================================
# سفارش‌ها
# ==========================================================================

ORDER_STATUSES = [(None, t("filter.all")), ("COMPLETED", t("order_status.completed")),
                  ("PROVISIONING", t("order_status.provisioning")),
                  ("REFUNDED", t("order_status.refunded"))]


async def open_orders(update, context, status: Optional[str] = None, page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        result = orders_service.list_page(uow, actor, status=status, page=page)
    rows = [[InlineKeyboardButton(f"#{o.id} کاربر {o.user_id} — {money(o.price_minor)} {o.currency} [{o.status}]",
                                  callback_data=f"{PREFIX}ord:d:{o.id}")] for o in result.items]
    filt_row = [InlineKeyboardButton(("• " if s == status else "") + label,
                                     callback_data=f"{PREFIX}ord:f:{s or '-'}:0")
                for s, label in ORDER_STATUSES]
    rows.append(filt_row)
    rows.append(pagination_row(f"{PREFIX}ord:f:{status or '-'}", result))
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"🧾 <b>سفارش‌ها</b> ({result.total})", parse_mode="HTML", reply_markup=kb(rows))


async def open_order_detail(update, context, order_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        o = uow.orders.get_by_id(order_id)
        can_refund = rbac.has_permission(uow, actor, "orders.refund") if o is not None else False
    if o is None:
        await update.callback_query.answer("سفارش یافت نشد", show_alert=True)
        return
    lines = [f"🧾 <b>سفارش #{order_id}</b>", f"کاربر: {o.user_id} | محصول: {o.product_id}",
             f"قیمت: {money(o.price_minor)} {o.currency} | وضعیت: {o.status}"]
    if o.coupon_code:
        lines.append(f"کوپن: {o.coupon_code} (تخفیف {money(o.discount_minor)})")
    rows = []
    if can_refund and o.status in ("COMPLETED", "PROVISIONING"):
        rows.append([InlineKeyboardButton("↩️ بازپرداخت", callback_data=f"{PREFIX}ord:refund:{order_id}")])
    if o.status == "PROVISIONING":
        rows.append([InlineKeyboardButton("🔁 تلاش مجدد Provisioning",
                                          callback_data=f"{PREFIX}ord:retry:{order_id}")])
    rows.append(back_row("ord:f:-:0"))
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# پرداخت‌های معلق — لیست جدید که به دکمه‌های تأیید/رد V1 لینک می‌شود
# ==========================================================================

PAY_TYPES = [(None, t("filter.all")), ("charge", t("pay_type.charge")), ("buy", t("pay_type.buy")), ("agency", t("pay_type.agency"))]
_APPROVE_CB = {"charge": "ok_dp_", "buy": "ok_by_", "agency": "ok_ag_"}
_REJECT_CB = {"charge": "no_dp_", "buy": "no_by_", "agency": "no_ag_"}


async def open_pending(update, context, req_type: Optional[str] = None, page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "payments.view")
        result = uow.pending_requests.page(status="pending", req_type=req_type, page=page)
    rows = [[InlineKeyboardButton(f"#{r.id} [{r.type}] کاربر {r.user_id}"
                                  + (f" {money(r.amount_minor)}" if r.amount_minor else ""),
                                  callback_data=f"{PREFIX}pay:d:{r.id}")] for r in result.items]
    filt_row = [InlineKeyboardButton(("• " if t == req_type else "") + label,
                                     callback_data=f"{PREFIX}pay:f:{t or '-'}:0")
                for t, label in PAY_TYPES]
    rows.append(filt_row)
    rows.append(pagination_row(f"{PREFIX}pay:f:{req_type or '-'}", result))
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"💳 <b>درخواست‌های معلق</b> ({result.total})", parse_mode="HTML", reply_markup=kb(rows))


async def open_pending_detail(update, context, req_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "payments.view")
        r = uow.pending_requests.get(req_id)
    if r is None:
        await update.callback_query.answer("یافت نشد", show_alert=True)
        return
    lines = [f"💳 <b>درخواست #{req_id}</b> [{r.type}]", f"کاربر: {r.user_id} | وضعیت: {r.status}"]
    if r.amount_minor:
        lines.append(f"مبلغ: {money(r.amount_minor)}")
    if r.product_id is not None:
        lines.append(f"محصول: {r.product_id}")
    rows = []
    if r.status == "pending":
        approve_cb = _APPROVE_CB.get(r.type)
        reject_cb = _REJECT_CB.get(r.type)
        if approve_cb:
            # از همان callback_data قدیمی V1 استفاده می‌کنیم تا منطق تأیید/رد
            # دوباره‌نویسی نشود؛ handle_callbacks قدیمی این را با Permission
            # مربوطه (`wallet.adjust`/`orders.approve`) پردازش می‌کند.
            rows.append([InlineKeyboardButton("✅ تأیید", callback_data=f"{approve_cb}{req_id}"),
                        InlineKeyboardButton("❌ رد", callback_data=f"{reject_cb}{req_id}")])
    rows.append(back_row("pay:f:-:0"))
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# کیف پول — تنظیم دستی موجودی (Confirmation دومرحله‌ای)
# ==========================================================================

async def start_wallet_adjust(update, context, target_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    denied = None
    with app_ctx.unit_of_work() as uow:
        try:
            rbac.require(uow, actor, "wallet.adjust")
        except NotAuthorizedError as exc:
            denied = str(exc)
    if denied is not None:
        await update.callback_query.answer(denied, show_alert=True)
        return
    _set_state(app_ctx, actor, "wallet_amount", target_id=target_id)
    await update.callback_query.edit_message_text(
        f"💰 مقدار تغییر موجودی کاربر {target_id} را وارد کنید (مثبت=افزایش، منفی=کسر، مثال: -5000):",
        reply_markup=kb([back_row(f"usr:d:{target_id}")]))


async def _wallet_amount_step(update, context, state: dict) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    amount = parse_signed_int(update.message.text)
    if amount is None:
        await update.message.reply_text("مقدار نامعتبر است؛ یک عدد صحیح غیرصفر وارد کنید.")
        return
    _set_state(app_ctx, actor, "wallet_reason", target_id=state["target_id"], amount=amount)
    await update.message.reply_text("دلیل این تغییر موجودی را بنویسید (اجباری، حداکثر ۲۰۰ کاراکتر):")


async def _wallet_reason_step(update, context, state: dict) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    reason = update.message.text.strip()
    target_id, amount = state["target_id"], state["amount"]
    payload = {"target_id": target_id, "amount": amount, "reason": reason}
    denied = None
    with app_ctx.unit_of_work() as uow:
        try:
            rbac.require(uow, actor, "wallet.adjust")
        except NotAuthorizedError as exc:
            denied = str(exc)
            token = None
        else:
            token = confirm_service.create(uow, actor, "wallet_adjust", payload)
    if denied is not None:
        _clear(app_ctx, actor)
        await update.message.reply_text(denied)
        return
    _clear(app_ctx, actor)
    sign = "افزایش" if amount > 0 else "کسر"
    await update.message.reply_text(
        f"⚠️ تأیید نهایی: {sign} {money(abs(amount))} برای کاربر {target_id}\nدلیل: {reason}",
        reply_markup=kb([[InlineKeyboardButton("✅ اجرا", callback_data=f"{PREFIX}confirm:{token}"),
                         InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}usr:d:{target_id}")]]))


async def open_wallet_home(update, context) -> None:
    rows = [[InlineKeyboardButton("👥 از طریق پروفایل کاربر (جستجو)", callback_data=f"{PREFIX}usr:search")],
            back_row("home")]
    await update.callback_query.edit_message_text(
        "🏦 برای تنظیم موجودی، ابتدا کاربر را از بخش «کاربران» پیدا کنید.", reply_markup=kb(rows))


# ==========================================================================
# کوپن
# ==========================================================================

async def open_coupons(update, context, page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "coupons.manage")
        result = uow.coupons.page(page=page)
    rows = [[InlineKeyboardButton(
        f"{'✅' if c.is_active else '⛔'} {c.code} ({c.kind} {c.value})",
        callback_data=f"{PREFIX}cpn:d:{c.id}")] for c in result.items]
    rows.append([InlineKeyboardButton("➕ کوپن جدید", callback_data=f"{PREFIX}cpn:new")])
    rows.append(pagination_row(f"{PREFIX}cpn:p", result))
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"🎫 <b>کوپن‌ها</b> ({result.total})", parse_mode="HTML", reply_markup=kb(rows))


async def open_coupon_detail(update, context, coupon_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "coupons.manage")
        c = uow.coupons.get(coupon_id)
        uses = uow.coupons.count_uses(coupon_id) if c else 0
    if c is None:
        await update.callback_query.answer("یافت نشد", show_alert=True)
        return
    text = (f"🎫 <b>{esc(c.code)}</b>\nنوع: {esc(c.kind)} | مقدار: {c.value}\nاستفاده: {uses}"
           + (f"/{c.max_uses}" if c.max_uses else "") + f"\nوضعیت: {'✅ فعال' if c.is_active else '⛔ غیرفعال'}")
    rows = [[InlineKeyboardButton("⛔ غیرفعال" if c.is_active else "✅ فعال",
                                  callback_data=f"{PREFIX}cpn:tgl:{coupon_id}:{0 if c.is_active else 1}")],
            back_row("cpn:p:0")]
    await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# رفرال / Reseller
# ==========================================================================

async def open_referral(update, context) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "referral.manage")
        totals = uow.referrals.totals()
        tiers = uow.resellers.list_tiers()
    lines = [f"🤝 <b>رفرال</b>: {totals['count']} پاداش پرداخت‌شده، جمعاً {money(totals['paid_minor'])}",
             "", "🏷️ <b>سطوح Reseller:</b>"]
    lines += [f"  • {esc(t.name)} — {t.discount_percent}٪ ({'فعال' if t.is_active else 'غیرفعال'})" for t in tiers] \
        or ["  (هیچ سطحی تعریف نشده)"]
    rows = [[InlineKeyboardButton("➕ سطح جدید", callback_data=f"{PREFIX}ref:newtier")], back_row("home")]
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


async def start_assign_tier(update, context, target_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    denied = None
    with app_ctx.unit_of_work() as uow:
        try:
            rbac.require(uow, actor, "reseller.manage")
        except NotAuthorizedError as exc:
            denied = str(exc)
        tiers = uow.resellers.list_tiers() if denied is None else []
    if denied is not None:
        await update.callback_query.answer(denied, show_alert=True)
        return
    rows = [[InlineKeyboardButton(t.name, callback_data=f"{PREFIX}ref:settier:{target_id}:{t.id}")]
            for t in tiers if t.is_active]
    rows.append([InlineKeyboardButton("🚫 حذف سطح (بدون تخفیف Reseller)",
                                      callback_data=f"{PREFIX}ref:settier:{target_id}:0")])
    rows.append(back_row(f"usr:d:{target_id}"))
    await update.callback_query.edit_message_text("یک سطح انتخاب کنید:", reply_markup=kb(rows))


# ==========================================================================
# پیام همگانی (Broadcast)
# ==========================================================================

async def start_broadcast(update, context) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    denied = None
    with app_ctx.unit_of_work() as uow:
        try:
            rbac.require(uow, actor, "broadcast.send")
        except NotAuthorizedError as exc:
            denied = str(exc)
    if denied is not None:
        await update.callback_query.answer(denied, show_alert=True)
        return
    _set_state(app_ctx, actor, "broadcast_text")
    await update.callback_query.edit_message_text(
        "📢 متن پیام همگانی را بنویسید:", reply_markup=kb([back_row("home")]))


async def _broadcast_text_step(update, context, state: dict) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    text = update.message.text.strip()
    with app_ctx.unit_of_work() as uow:
        recipients = uow.users.list_ids_not_blocked()
    token = None
    with app_ctx.unit_of_work() as uow:
        token = confirm_service.create(uow, actor, "broadcast_send", {"text": text})
    _clear(app_ctx, actor)
    await update.message.reply_html(
        f"⚠️ پیام برای <b>{len(recipients)}</b> کاربر ارسال می‌شود:\n\n{esc(text)}\n\nتأیید می‌کنید؟",
        reply_markup=kb([[InlineKeyboardButton("✅ ارسال", callback_data=f"{PREFIX}confirm:{token}"),
                         InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}home")]]))


async def _run_broadcast(update, context, payload: dict, actor_id: int) -> None:
    app_ctx = _ctx(context)
    text = payload["text"]
    with app_ctx.unit_of_work() as uow:
        recipients = uow.users.list_ids_not_blocked()
        b, ids = broadcast_service.start(uow, actor_id, text, recipients)
    sent = failed = 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, f"📢 <b>اطلاعیه جدید مدیریت</b>\n\n{esc(text)}", parse_mode="HTML")
            sent += 1
        except Forbidden:
            failed += 1
            with app_ctx.unit_of_work() as uow:
                uow.users.set_blocked_by_bot(uid, True)
        except TelegramError:
            failed += 1
    with app_ctx.unit_of_work() as uow:
        broadcast_service.record_batch_progress(uow, b.id, sent, failed)
        broadcast_service.finish(uow, b.id)
    if update.callback_query:
        await update.callback_query.edit_message_text(f"✅ پیام همگانی پایان یافت. ({sent} موفق، {failed} ناموفق)")


# ==========================================================================
# تیکت‌ها
# ==========================================================================

async def open_tickets(update, context, status: str = "OPEN", page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        result = tickets_service.list_page(uow, actor, status=status, page=page)
    rows = [[InlineKeyboardButton(f"#{t.id} {t.subject[:24]} — {t.status}",
                                  callback_data=f"{PREFIX}tic:d:{t.id}")] for t in result.items]
    rows.append(pagination_row(f"{PREFIX}tic:f:{status}", result))
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"🎫 <b>تیکت‌ها ({status})</b> — {result.total}", parse_mode="HTML", reply_markup=kb(rows))


async def open_ticket_detail(update, context, ticket_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "tickets.view")
        t = uow.tickets.get(ticket_id)
        msgs = uow.tickets.messages(ticket_id, limit=6) if t else []
    if t is None:
        await update.callback_query.answer("یافت نشد", show_alert=True)
        return
    body = "\n".join(f"{'👮' if m.is_staff else '👤'} {esc(m.body[:200])}" for m in msgs)
    rows = []
    if t.status != "CLOSED":
        rows.append([InlineKeyboardButton("✍️ پاسخ", callback_data=f"{PREFIX}tic:reply:{ticket_id}")])
        rows.append([InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"{PREFIX}tic:close:{ticket_id}")])
    rows.append(back_row(f"tic:f:{t.status if t.status != 'CLOSED' else 'OPEN'}:0"))
    await update.callback_query.edit_message_text(
        f"🎫 <b>#{ticket_id} — {esc(t.subject)}</b>\n\n{body}", parse_mode="HTML", reply_markup=kb(rows))


async def start_ticket_reply(update, context, ticket_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        try:
            rbac.require(uow, actor, "tickets.reply")
        except NotAuthorizedError as exc:
            await update.callback_query.answer(str(exc), show_alert=True)
            return
    _set_state(app_ctx, actor, "ticket_reply", ticket_id=ticket_id)
    await update.callback_query.edit_message_text("متن پاسخ را بنویسید:", reply_markup=kb([back_row(f"tic:d:{ticket_id}")]))


async def _ticket_reply_step(update, context, state: dict) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    ticket_id = state["ticket_id"]
    with app_ctx.unit_of_work() as uow:
        tickets_service.reply(uow, actor, ticket_id, update.message.text)
        t = uow.tickets.get(ticket_id)
    _clear(app_ctx, actor)
    try:
        await context.bot.send_message(t.user_id, f"☎️ پاسخ پشتیبانی برای تیکت #{ticket_id}:\n\n{update.message.text}")
    except TelegramError:
        pass
    await update.message.reply_text("✅ پاسخ ثبت و برای کاربر ارسال شد.")


# ==========================================================================
# تنظیمات (Typed Settings Registry)
# ==========================================================================

SETTING_GROUPS = [
    ("general", t("setting_group.general")), ("payments", t("setting_group.payments")),
    ("wallet", t("setting_group.wallet")), ("inventory", t("setting_group.inventory")),
    ("tickets", t("setting_group.tickets")), ("coupons", t("setting_group.coupons")),
    ("referral", t("setting_group.referral")), ("dice", t("setting_group.dice")),
    ("renewal", t("setting_group.renewal")), ("system", t("setting_group.system")),
    ("branding", t("setting_group.branding")),
]


async def open_settings_home(update, context) -> None:
    rows = [[InlineKeyboardButton(label, callback_data=f"{PREFIX}set:g:{g}")] for g, label in SETTING_GROUPS]
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text("⚙️ <b>تنظیمات</b>", parse_mode="HTML", reply_markup=kb(rows))


async def open_settings_group(update, context, group: str) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        defs = settings_service.list_group(group)
        rows = []
        for d in defs:
            try:
                rbac.require(uow, actor, d.permission)
            except NotAuthorizedError:
                continue
            val = settings_service.display(uow, d.key)
            if d.kind == "bool":
                rows.append([InlineKeyboardButton(f"{d.label}: {val}", callback_data=f"{PREFIX}set:tgl:{d.key}")])
            else:
                rows.append([InlineKeyboardButton(f"{d.label}: {val}", callback_data=f"{PREFIX}set:edit:{d.key}")])
    rows.append(back_row("set:home"))
    label = dict(SETTING_GROUPS).get(group, group)
    await update.callback_query.edit_message_text(f"⚙️ <b>{label}</b>", parse_mode="HTML", reply_markup=kb(rows))


async def start_setting_edit(update, context, key: str) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    try:
        d = settings_service.definition(key)
    except NotFoundError as exc:
        await update.callback_query.answer(str(exc), show_alert=True)
        return
    denied = None
    with app_ctx.unit_of_work() as uow:
        try:
            rbac.require(uow, actor, d.permission)
        except NotAuthorizedError as exc:
            denied = str(exc)
    if denied is not None:
        await update.callback_query.answer(denied, show_alert=True)
        return
    _set_state(app_ctx, actor, "setting_edit", key=key)
    hint = f"\n\n{d.hint}" if d.hint else ""
    await update.callback_query.edit_message_text(
        f"مقدار جدید «{d.label}» را وارد کنید:{hint}", reply_markup=kb([back_row(f"set:g:{d.group}")]))


async def _setting_edit_step(update, context, state: dict) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    key = state["key"]
    _clear(app_ctx, actor)
    try:
        with app_ctx.unit_of_work() as uow:
            new_val = settings_service.set_value(uow, actor, key, update.message.text)
        await update.message.reply_text(f"✅ تنظیم شد: {new_val}")
    except (ValidationError, NotAuthorizedError) as exc:
        await update.message.reply_text(_fmt_error(exc))


# ==========================================================================
# ادمین‌ها / RBAC
# ==========================================================================

async def open_admins(update, context) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require_owner(uow, actor)
        admins = rbac.list_admins(uow)
    rows = [[InlineKeyboardButton(f"👮 {a}", callback_data=f"{PREFIX}adm:d:{a}")] for a in admins]
    rows.append([InlineKeyboardButton("➕ افزودن ادمین", callback_data=f"{PREFIX}adm:new")])
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"👮 <b>ادمین‌ها</b> ({len(admins)})", parse_mode="HTML", reply_markup=kb(rows))


async def start_new_admin(update, context) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    denied = None
    with app_ctx.unit_of_work() as uow:
        try:
            rbac.require_owner(uow, actor)
        except NotAuthorizedError as exc:
            denied = str(exc)
    if denied is not None:
        await update.callback_query.answer(denied, show_alert=True)
        return
    _set_state(app_ctx, actor, "new_admin_id")
    await update.callback_query.edit_message_text("آیدی عددی کاربر جدید را وارد کنید:", reply_markup=kb([back_row("adm:home")]))


async def _new_admin_id_step(update, context, state: dict) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    target = parse_user_id(update.message.text)
    _clear(app_ctx, actor)
    if target is None:
        await update.message.reply_text("آیدی نامعتبر است.")
        return
    try:
        with app_ctx.unit_of_work() as uow:
            rbac.grant_admin(uow, target, actor_id=actor)
        await update.message.reply_text(f"✅ کاربر {target} به‌عنوان ADMIN اضافه شد (بدون هیچ Permission).")
        await open_admin_detail_by_id(update, context, target, as_message=True)
    except DomainError as exc:
        await update.message.reply_text(_fmt_error(exc))


async def open_admin_detail_by_id(update, context, target_id: int, as_message: bool = False) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require_owner(uow, actor)
        grants = set(rbac.grants_of(uow, target_id))
    rows = []
    from security.permissions_catalog import modules
    for mod, names in modules().items():
        for name in names:
            if name in rbac.grantable_permissions() and name in [n for n in names]:
                mark = "✅" if name in grants else "▫️"
                rows.append([InlineKeyboardButton(f"{mark} {name}", callback_data=f"{PREFIX}adm:tglp:{target_id}:{name}")])
    rows.append([InlineKeyboardButton("🗑️ حذف این ادمین", callback_data=f"{PREFIX}adm:rev:{target_id}")])
    rows.append(back_row("adm:home"))
    text = f"👮 <b>ادمین {target_id}</b> — {len(grants)} Permission فعال\nروی هرکدام بزنید تا تغییر کند:"
    if as_message:
        await update.message.reply_html(text, reply_markup=kb(rows))
    else:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# Audit Log
# ==========================================================================

AUDIT_CATS = [(None, "همه")] + [(k, k) for k in
    ["wallet", "payment", "order", "product", "inventory", "provider", "users", "rbac",
     "settings", "broadcast", "backup", "coupon", "referral", "ticket", "job"]]


async def open_audit(update, context, category: Optional[str] = None, page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        result = audit_service.query(uow, actor, category=category, page=page)
    rows = [[InlineKeyboardButton(f"#{r.id} {r.action} @{r.actor_id}", callback_data=f"{PREFIX}aud:d:{r.id}")]
            for r in result.items]
    rows.append(pagination_row(f"{PREFIX}aud:f:{category or '-'}", result))
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"📜 <b>Audit Log</b> ({result.total})", parse_mode="HTML", reply_markup=kb(rows))


async def open_audit_detail(update, context, log_id: int) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        r = audit_service.get(uow, actor, log_id)
    if r is None:
        await update.callback_query.answer("یافت نشد", show_alert=True)
        return
    text = (f"📜 <b>#{r.id}</b> — {esc(r.action)}\nActor: {r.actor_id} | {esc(r.entity_type)}#{r.entity_id}\n"
           f"before: <code>{esc((r.before_json or '—')[:300])}</code>\n"
           f"after: <code>{esc((r.after_json or '—')[:300])}</code>")
    await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb([back_row("aud:f:-:0")]))


# ==========================================================================
# Jobs
# ==========================================================================

async def open_jobs(update, context) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        jobs = jobs_service.list_jobs(uow, actor)
    rows = []
    for j in jobs:
        rows.append([InlineKeyboardButton(f"{'🟢' if j.enabled else '⚪'} {j.name}",
                                          callback_data=f"{PREFIX}job:tgl:{j.name}"),
                    InlineKeyboardButton("▶️ اجرا", callback_data=f"{PREFIX}job:run:{j.name}")])
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text("🧰 <b>Jobها</b>", parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# Backup / Health
# ==========================================================================

async def open_backup(update, context) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        can_download = rbac.is_owner(uow, actor)
    h = system_service.health(app_ctx.unit_of_work, actor)
    lines = ["🧰 <b>سلامت سیستم</b>", f"DB: {h['db']} | 3x-ui: {h['xui']['status']}",
             f"درخواست‌های معلق: {h['pending_requests']}",
             "سرویس‌ها: " + (" | ".join(f"{k}:{v}" for k, v in sorted(h.get("services", {}).items())) or "—"),
             f"بررسی‌شده در: {h['checked_at']}"]
    rows = [[InlineKeyboardButton("💾 ساخت Backup", callback_data=f"{PREFIX}bak:new")]]
    if can_download:
        rows.append([InlineKeyboardButton("📥 دریافت آخرین Backup", callback_data=f"{PREFIX}bak:dl")])
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# سرویس‌های VPN (services.view / services.manage) — Provider-backed
# ==========================================================================

SVC_STATUSES = [(None, "همه"), ("ACTIVE", "🟢"), ("EXPIRED", "🔴"), ("SUSPENDED", "🟠"), ("PENDING", "🟡"), ("FAILED", "⚠️")]
SVC_PAGE = 8


async def open_services(update, context, status: Optional[str] = None, page: int = 0) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        recs = list(vpn_service.admin_list(uow, actor, status))
    total = len(recs)
    chunk = recs[page * SVC_PAGE:(page + 1) * SVC_PAGE]
    rows = [[InlineKeyboardButton(f"#{r.order_id} {r.status} {r.email}", callback_data=f"{PREFIX}svcs:d:{r.order_id}")]
            for r in chunk]
    rows.append([InlineKeyboardButton(lbl, callback_data=f"{PREFIX}svcs:f:{st or '-'}:0") for st, lbl in SVC_STATUSES])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"{PREFIX}svcs:f:{status or '-'}:{page - 1}"))
    if (page + 1) * SVC_PAGE < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"{PREFIX}svcs:f:{status or '-'}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(back_row("home"))
    await update.callback_query.edit_message_text(
        f"🛰 <b>سرویس‌های VPN</b> ({total})", parse_mode="HTML", reply_markup=kb(rows))


async def open_service_detail(update, context, order_id: int) -> None:
    import asyncio
    from adapters.telegram_bot.services_ui import fmt_expiry, fmt_used, fmt_bytes
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    with app_ctx.unit_of_work() as uow:
        rbac.require(uow, actor, "services.view")
        can_manage = rbac.has_permission(uow, actor, "services.manage")
        can_refund = rbac.has_permission(uow, actor, "orders.refund")
    v = await asyncio.to_thread(vpn_service.get_service_view, app_ctx.unit_of_work, None, order_id)
    lines = [f"🛰 <b>سرویس سفارش #{order_id}</b>",
             f"محصول: {esc(v.product_name)} | ایمیل پنل: <code>{esc(v.email)}</code>",
             f"وضعیت: {v.state}{'' if v.live else ' (ذخیره‌شده)'}",
             f"مصرف: {fmt_used(v.used_bytes)} / {fmt_bytes(v.total_bytes, 'fa')}",
             f"انقضا: {fmt_expiry(v.expires_at_ms, 'fa')}", f"تمدید خودکار: {'روشن' if v.auto_renew else 'خاموش'}"]
    if v.error:
        lines.append(f"⚠️ {esc(v.error)}")
    rows = []
    if can_manage and v.state in ("ACTIVE", "EXPIRED", "SUSPENDED"):
        toggle = ("▶️ فعال‌سازی", "svc_enable") if v.state == "SUSPENDED" else ("⏸ تعلیق", "svc_suspend")
        rows.append([InlineKeyboardButton(toggle[0], callback_data=f"{PREFIX}svcs:act:{toggle[1]}:{order_id}"),
                     InlineKeyboardButton("♻️ ریست ترافیک", callback_data=f"{PREFIX}svcs:act:svc_reset:{order_id}")])
        rows.append([InlineKeyboardButton("🗑 لغو سرویس", callback_data=f"{PREFIX}svcs:act:svc_cancel:{order_id}")])
        if can_refund:
            rows.append([InlineKeyboardButton("🗑↩️ لغو + بازپرداخت", callback_data=f"{PREFIX}svcs:act:svc_cancel_refund:{order_id}")])
    rows.append([InlineKeyboardButton("♻️ بروزرسانی", callback_data=f"{PREFIX}svcs:d:{order_id}")])
    rows.append(back_row("svcs:f:-:0"))
    await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb(rows))


# ==========================================================================
# Confirmation دومرحله‌ای — اجرای واقعی عملیات پس از کلیک «✅ اجرا»
# ==========================================================================

async def _execute_confirmed(update, context, token: str) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    try:
        with app_ctx.unit_of_work() as uow:
            rec, payload = confirm_service.consume(uow, token, actor)
    except DomainError as exc:
        await _answer_error(update, exc)
        return

    action = rec.action
    try:
        if action == "wallet_adjust":
            with app_ctx.unit_of_work() as uow:
                wallet_service.admin_adjust(uow, actor, payload["target_id"], payload["amount"], payload["reason"])
            await update.callback_query.edit_message_text("✅ موجودی با موفقیت تنظیم شد.")
        elif action == "broadcast_send":
            await _run_broadcast(update, context, payload, actor)
        elif action == "product_delete":
            with app_ctx.unit_of_work() as uow:
                catalog_service.delete_product(uow, actor, payload["product_id"])
            await update.callback_query.edit_message_text("✅ پلن حذف شد.")
        elif action == "item_delete":
            with app_ctx.unit_of_work() as uow:
                inventory_service.delete_item(uow, actor, payload["item_id"])
            await update.callback_query.edit_message_text("✅ آیتم حذف شد.")
        elif action == "order_refund":
            with app_ctx.unit_of_work() as uow:
                orders_service.refund_order(uow, actor, payload["order_id"])
            await update.callback_query.edit_message_text("✅ بازپرداخت انجام شد.")
        elif action == "admin_revoke":
            with app_ctx.unit_of_work() as uow:
                rbac.revoke_admin(uow, payload["target_id"], actor_id=actor)
            await update.callback_query.edit_message_text("✅ ادمین حذف شد.")
        elif action == "user_ban":
            with app_ctx.unit_of_work() as uow:
                users_service.set_ban(uow, actor, payload["target_id"], bool(payload["banned"]))
            await update.callback_query.edit_message_text("✅ اعمال شد.")
        elif action in ("svc_enable", "svc_suspend", "svc_reset", "svc_cancel", "svc_cancel_refund"):
            import asyncio
            oid = payload["order_id"]
            uowf = app_ctx.unit_of_work
            if action == "svc_enable":
                await asyncio.to_thread(vpn_service.admin_set_enabled, uowf, actor, oid, True)
            elif action == "svc_suspend":
                await asyncio.to_thread(vpn_service.admin_set_enabled, uowf, actor, oid, False)
            elif action == "svc_reset":
                await asyncio.to_thread(vpn_service.admin_reset_traffic, uowf, actor, oid)
            else:
                await asyncio.to_thread(vpn_service.admin_cancel, uowf, actor, oid,
                                        refund=(action == "svc_cancel_refund"))
            await update.callback_query.edit_message_text("✅ انجام شد (Audit ثبت شد).")
        elif action == "backup_create":
            with app_ctx.unit_of_work() as uow:
                path = system_service.create_backup(uow, actor, app_ctx.db_path,
                                                     __import__("os").environ.get("GHIYAB_BACKUP_DIR", "backups"))
            await update.callback_query.edit_message_text(f"✅ Backup ساخته شد: {path}")
        else:
            await update.callback_query.edit_message_text("⚠️ عملیات ناشناخته.")
    except DomainError as exc:
        await _answer_error(update, exc)
    except vpn_errors:
        await update.callback_query.answer("⚠️ عملیات روی پنل 3x-ui انجام نشد.", show_alert=True)


# ==========================================================================
# دیسپچر اصلی Callback
# ==========================================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data[len(PREFIX):]
    parts = data.split(":")
    op = parts[0]
    app_ctx = _ctx(context)
    actor = _actor_id(update)

    with app_ctx.unit_of_work() as uow:
        is_admin_user = rbac.is_admin(uow, actor)
    if not is_admin_user:
        await query.answer("⛔ دسترسی ندارید", show_alert=True)
        return

    try:
        if op == "noop":
            return
        if op == "close":
            try:
                await query.message.delete()
            except TelegramError:
                await query.edit_message_reply_markup(reply_markup=None)
            return
        if op == "home":
            await open_home(update, context); return
        if op == "confirm":
            await _execute_confirmed(update, context, parts[1]); return

        if op == "dash":
            await open_dashboard(update, context); return

        if op == "usr":
            sub = parts[1]
            if sub == "home":
                await open_users(update, context); return
            if sub == "f":
                await open_users(update, context, flt=parts[2], page=int(parts[3])); return
            if sub == "d":
                await open_user_detail(update, context, int(parts[2])); return
            if sub == "search":
                _set_state(app_ctx, actor, "user_search")
                await query.edit_message_text("آیدی عددی یا بخشی از شماره تلفن را بفرستید:",
                                              reply_markup=kb([back_row("usr:home")]))
                return
            if sub == "ban":
                target_id, want = int(parts[2]), bool(int(parts[3]))
                with app_ctx.unit_of_work() as uow:
                    token = confirm_service.create(uow, actor, "user_ban",
                                                   {"target_id": target_id, "banned": want})
                verb = "مسدود" if want else "رفع مسدودی"
                await query.edit_message_text(
                    f"⚠️ کاربر {target_id} {verb} شود؟",
                    reply_markup=kb([[InlineKeyboardButton("✅ تأیید", callback_data=f"{PREFIX}confirm:{token}"),
                                     InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}usr:d:{target_id}")]]))
                return
            if sub == "agent":
                target_id, want = int(parts[2]), bool(int(parts[3]))
                with app_ctx.unit_of_work() as uow:
                    users_service.set_agent(uow, actor, target_id, want)
                await open_user_detail(update, context, target_id)
                return

        if op == "cat":
            sub = parts[1]
            if sub == "p":
                await open_catalog(update, context, page=int(parts[2])); return
            if sub == "d":
                await open_product_detail(update, context, int(parts[2])); return
            if sub == "new":
                _set_state(app_ctx, actor, "product_new_name")
                await query.edit_message_text("نام پلن جدید را وارد کنید:", reply_markup=kb([back_row("cat:p:0")]))
                return
            if sub == "rn":
                _set_state(app_ctx, actor, "product_rename", product_id=int(parts[2]))
                await query.edit_message_text("نام جدید را وارد کنید:", reply_markup=kb([back_row(f"cat:d:{parts[2]}")]))
                return
            if sub == "rp":
                _set_state(app_ctx, actor, "product_reprice", product_id=int(parts[2]))
                await query.edit_message_text("قیمت جدید (تومان) را وارد کنید:", reply_markup=kb([back_row(f"cat:d:{parts[2]}")]))
                return
            if sub == "act":
                pid, want = int(parts[2]), bool(int(parts[3]))
                with app_ctx.unit_of_work() as uow:
                    catalog_service.set_product_active(uow, actor, pid, want)
                await open_product_detail(update, context, pid)
                return
            if sub == "del":
                pid = int(parts[2])
                with app_ctx.unit_of_work() as uow:
                    token = confirm_service.create(uow, actor, "product_delete", {"product_id": pid})
                await query.edit_message_text(
                    f"⚠️ حذف پلن #{pid} + کل موجودی استفاده‌نشدهٔ آن — این عمل قابل بازگشت نیست.",
                    reply_markup=kb([[InlineKeyboardButton("✅ تأیید حذف", callback_data=f"{PREFIX}confirm:{token}"),
                                     InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}cat:d:{pid}")]]))
                return

        if op == "inv":
            sub = parts[1]
            if sub == "home":
                if len(parts) < 3:
                    await open_inventory_overview(update, context); return
                await open_inventory(update, context, int(parts[2]),
                                     page=int(parts[3]) if len(parts) > 3 else 0); return
            if sub == "i":
                await open_inventory_item(update, context, int(parts[2]), int(parts[3])); return
            if sub == "add":
                _set_state(app_ctx, actor, "inventory_add", product_id=int(parts[2]))
                await query.edit_message_text(
                    "📥 کانفیگ‌ها را ارسال کنید:\n"
                    "• متن: هر خط یک کانفیگ\n"
                    "• یا یک فایل «.txt» (UTF-8) با هر خط یک کانفیگ\n\n"
                    f"تکراری‌ها خودکار حذف می‌شوند. حداکثر {inventory_service.MAX_BATCH} مورد یکتا در هر ارسال. "
                    "برای انصراف /cancel.",
                    reply_markup=kb([back_row(f"inv:home:{parts[2]}:0")]))
                return
            if sub == "purge":
                _set_state(app_ctx, actor, "inventory_purge", product_id=int(parts[2]))
                await query.edit_message_text("تعداد آیتم موجود جهت حذف را وارد کنید:",
                                              reply_markup=kb([back_row(f"inv:home:{parts[2]}:0")]))
                return
            if sub == "reveal":
                item_id, pid = int(parts[2]), int(parts[3])
                with app_ctx.unit_of_work() as uow:
                    content = inventory_service.reveal_item(uow, actor, item_id)
                await query.message.reply_html(f"🔑 <code>{esc(content)}</code>")
                await query.answer()
                return
            if sub == "delitem":
                item_id, pid = int(parts[2]), int(parts[3])
                with app_ctx.unit_of_work() as uow:
                    token = confirm_service.create(uow, actor, "item_delete", {"item_id": item_id})
                await query.edit_message_text(
                    f"⚠️ حذف آیتم #{item_id} — قابل بازگشت نیست.",
                    reply_markup=kb([[InlineKeyboardButton("✅ تأیید", callback_data=f"{PREFIX}confirm:{token}"),
                                     InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}inv:home:{pid}:0")]]))
                return

        if op == "prov":
            sub = parts[1]
            if sub == "home":
                await open_providers(update, context); return
            if sub == "pf":
                await open_provisioning_profile(update, context, int(parts[2])); return
            if sub == "new":
                _set_state(app_ctx, actor, "prov_inbound", product_id=int(parts[2]))
                await query.edit_message_text(
                    "شمارهٔ Inbound واقعی 3x-ui را وارد کنید (باید از پیش در پنل ساخته شده باشد):",
                    reply_markup=kb([back_row(f"cat:d:{parts[2]}")]))
                return
            if sub == "tgl":
                pid, want = int(parts[2]), bool(int(parts[3]))
                with app_ctx.unit_of_work() as uow:
                    rbac.require(uow, actor, "providers.manage")
                    uow.provisioning.set_profile_active(pid, want)
                    audit_service.record(uow, actor_id=actor, action="provider.profile_toggle",
                                         entity_type="product", entity_id=pid, after={"active": want})
                await open_provisioning_profile(update, context, pid)
                return

        if op == "svcs":
            sub = parts[1]
            if sub in ("home", "f"):
                status = None if sub == "home" or parts[2] == "-" else parts[2]
                await open_services(update, context, status=status,
                                    page=int(parts[3]) if sub == "f" else 0); return
            if sub == "d":
                await open_service_detail(update, context, int(parts[2])); return
            if sub == "act":
                action, oid = parts[2], int(parts[3])
                if action not in ("svc_enable", "svc_suspend", "svc_reset", "svc_cancel", "svc_cancel_refund"):
                    await query.answer(); return
                with app_ctx.unit_of_work() as uow:
                    rbac.require(uow, actor, "services.manage")
                    token = confirm_service.create(uow, actor, action, {"order_id": oid})
                await query.edit_message_text(
                    f"⚠️ اجرای «{action}» روی سرویس سفارش #{oid}؟",
                    reply_markup=kb([[InlineKeyboardButton("✅ تأیید", callback_data=f"{PREFIX}confirm:{token}"),
                                     InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}svcs:d:{oid}")]]))
                return

        if op == "ord":
            sub = parts[1]
            if sub == "f":
                status = None if parts[2] == "-" else parts[2]
                await open_orders(update, context, status=status, page=int(parts[3])); return
            if sub == "d":
                await open_order_detail(update, context, int(parts[2])); return
            if sub == "refund":
                oid = int(parts[2])
                with app_ctx.unit_of_work() as uow:
                    token = confirm_service.create(uow, actor, "order_refund", {"order_id": oid})
                await query.edit_message_text(
                    f"⚠️ بازپرداخت سفارش #{oid} به کیف‌پول کاربر — قابل بازگشت نیست.",
                    reply_markup=kb([[InlineKeyboardButton("✅ تأیید", callback_data=f"{PREFIX}confirm:{token}"),
                                     InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}ord:d:{oid}")]]))
                return
            if sub == "retry":
                oid = int(parts[2])
                import asyncio
                from adapters.telegram_bot import services_ui
                try:
                    res = await asyncio.to_thread(provisioning_service.retry_failed, app_ctx.unit_of_work, actor, oid)
                except (DomainError, vpn_errors) as exc:
                    await query.answer("⚠️ " + (str(exc) if isinstance(exc, DomainError) else "خطای Provider")[:180],
                                       show_alert=True)
                    await open_order_detail(update, context, oid)
                    return
                if res:
                    with app_ctx.unit_of_work() as uow:
                        owner_uid = uow.orders.get_by_id(oid).user_id
                    await services_ui.deliver_ready(context.bot, app_ctx, owner_uid, oid)
                await open_order_detail(update, context, oid)
                return

        if op == "pay":
            sub = parts[1]
            if sub == "f":
                t = None if parts[2] == "-" else parts[2]
                await open_pending(update, context, req_type=t, page=int(parts[3])); return
            if sub == "d":
                await open_pending_detail(update, context, int(parts[2])); return

        if op == "wal":
            sub = parts[1]
            if sub == "home":
                await open_wallet_home(update, context); return
            if sub == "adj":
                await start_wallet_adjust(update, context, int(parts[2])); return

        if op == "cpn":
            sub = parts[1]
            if sub == "p":
                await open_coupons(update, context, page=int(parts[2])); return
            if sub == "d":
                await open_coupon_detail(update, context, int(parts[2])); return
            if sub == "tgl":
                cid, want = int(parts[2]), bool(int(parts[3]))
                with app_ctx.unit_of_work() as uow:
                    coupons_service.set_active(uow, actor, cid, want)
                await open_coupon_detail(update, context, cid)
                return
            if sub == "new":
                _set_state(app_ctx, actor, "coupon_code")
                await query.edit_message_text("کد کوپن را وارد کنید (مثلاً OFF20):", reply_markup=kb([back_row("cpn:p:0")]))
                return

        if op == "ref":
            sub = parts[1]
            if sub == "home":
                await open_referral(update, context); return
            if sub == "assign":
                await start_assign_tier(update, context, int(parts[2])); return
            if sub == "settier":
                target_id, tier_id = int(parts[2]), int(parts[3])
                with app_ctx.unit_of_work() as uow:
                    reseller_service.assign_tier(uow, actor, target_id, tier_id or None)
                await open_user_detail(update, context, target_id)
                return
            if sub == "newtier":
                _set_state(app_ctx, actor, "tier_name")
                await query.edit_message_text("نام سطح جدید Reseller را وارد کنید:", reply_markup=kb([back_row("ref:home")]))
                return

        if op == "bro":
            if parts[1] == "home":
                await start_broadcast(update, context); return

        if op == "tic":
            sub = parts[1]
            if sub == "f":
                await open_tickets(update, context, status=parts[2], page=int(parts[3])); return
            if sub == "d":
                await open_ticket_detail(update, context, int(parts[2])); return
            if sub == "reply":
                await start_ticket_reply(update, context, int(parts[2])); return
            if sub == "close":
                tid = int(parts[2])
                with app_ctx.unit_of_work() as uow:
                    tickets_service.close(uow, actor, tid)
                await open_ticket_detail(update, context, tid)
                return

        if op == "dice":
            if parts[1] == "home":
                await open_settings_group(update, context, "dice"); return

        if op == "set":
            sub = parts[1]
            if sub == "home":
                await open_settings_home(update, context); return
            if sub == "g":
                await open_settings_group(update, context, parts[2]); return
            if sub == "tgl":
                with app_ctx.unit_of_work() as uow:
                    settings_service.toggle_bool(uow, actor, parts[2])
                    d = settings_service.definition(parts[2])
                await open_settings_group(update, context, d.group)
                return
            if sub == "edit":
                await start_setting_edit(update, context, parts[2]); return

        if op == "adm":
            sub = parts[1]
            if sub == "home":
                await open_admins(update, context); return
            if sub == "new":
                await start_new_admin(update, context); return
            if sub == "d":
                await open_admin_detail_by_id(update, context, int(parts[2])); return
            if sub == "tglp":
                target_id, perm = int(parts[2]), parts[3]
                with app_ctx.unit_of_work() as uow:
                    rbac.toggle_admin_permission(uow, target_id, perm, actor_id=actor)
                await open_admin_detail_by_id(update, context, target_id)
                return
            if sub == "rev":
                target_id = int(parts[2])
                with app_ctx.unit_of_work() as uow:
                    token = confirm_service.create(uow, actor, "admin_revoke", {"target_id": target_id})
                await query.edit_message_text(
                    f"⚠️ حذف نقش ادمین از کاربر {target_id}؟",
                    reply_markup=kb([[InlineKeyboardButton("✅ تأیید", callback_data=f"{PREFIX}confirm:{token}"),
                                     InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}adm:d:{target_id}")]]))
                return

        if op == "aud":
            sub = parts[1]
            if sub == "f":
                cat = None if parts[2] == "-" else parts[2]
                await open_audit(update, context, category=cat, page=int(parts[3])); return
            if sub == "d":
                await open_audit_detail(update, context, int(parts[2])); return

        if op == "job":
            if parts[1] == "home":
                await open_jobs(update, context); return
            if parts[1] == "tgl":
                with app_ctx.unit_of_work() as uow:
                    j = uow.jobs.get(parts[2])
                    jobs_service.set_enabled(uow, actor, parts[2], not j.enabled)
                await open_jobs(update, context)
                return
            if parts[1] == "run":
                with app_ctx.unit_of_work() as uow:
                    detail = jobs_service.run_now(uow, actor, parts[2])
                await query.answer(detail[:200], show_alert=True)
                await open_jobs(update, context)
                return

        if op == "bak":
            sub = parts[1]
            if sub == "home":
                await open_backup(update, context); return
            if sub == "new":
                with app_ctx.unit_of_work() as uow:
                    token = confirm_service.create(uow, actor, "backup_create", {})
                await query.edit_message_text(
                    "⚠️ ساخت نسخهٔ Backup از دیتابیس زندهٔ ربات؟",
                    reply_markup=kb([[InlineKeyboardButton("✅ تأیید", callback_data=f"{PREFIX}confirm:{token}"),
                                     InlineKeyboardButton("❌ انصراف", callback_data=f"{PREFIX}bak:home")]]))
                return
            if sub == "dl":
                import os
                with app_ctx.unit_of_work() as uow:
                    system_service.require_download_permission(uow, actor)
                backup_dir = os.environ.get("GHIYAB_BACKUP_DIR", "backups")
                files = sorted([f for f in os.listdir(backup_dir) if f.endswith(".db")], reverse=True) \
                    if os.path.isdir(backup_dir) else []
                if not files:
                    await query.answer("هیچ Backupـی موجود نیست", show_alert=True)
                    return
                await context.bot.send_document(actor, open(os.path.join(backup_dir, files[0]), "rb"))
                return

        await query.answer()
    except DomainError as exc:
        await _answer_error(update, exc)


# ==========================================================================
# دیسپچر اصلی متن (چند-مرحله‌ای)
# ==========================================================================

MAX_INVENTORY_FILE_BYTES = 1_000_000


def _format_add_report(product_id: int, rep) -> str:
    lines = [f"✅ {rep.added} کانفیگ افزوده شد." if rep.added else "ℹ️ کانفیگ جدیدی افزوده نشد."]
    skipped = []
    if rep.duplicate_existing:
        skipped.append(f"• {rep.duplicate_existing} مورد از قبل در مخزن بود")
    if rep.duplicate_in_input:
        skipped.append(f"• {rep.duplicate_in_input} مورد تکراری در همین ارسال")
    if rep.too_long:
        skipped.append(f"• {rep.too_long} مورد بیش از حد طولانی (رد شد)")
    if skipped:
        lines.append("ردشده‌ها:\n" + "\n".join(skipped))
    lines.append(f"📊 موجودی فعلی این مخزن: {rep.available_after}")
    return "\n".join(lines)


async def _inventory_add_step(update, context, state: dict, configs: list) -> None:
    """مرحلهٔ مشترک افزودن (متن یا فایل). در خطای اعتبارسنجی state حفظ می‌شود تا ادمین دوباره بفرستد."""
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    product_id = state["product_id"]
    if not configs:
        await update.message.reply_text("⚠️ هیچ کانفیگی در ورودی پیدا نشد. دوباره بفرستید یا /cancel بزنید.")
        return
    try:
        with app_ctx.unit_of_work() as uow:
            rep = inventory_service.add_items_report(
                uow, product_id, inventory_service.default_item_type(product_id), configs, actor_id=actor)
    except ValidationError as exc:
        await update.message.reply_text(f"{_fmt_error(exc)}\nدوباره بفرستید یا /cancel بزنید.")
        return
    except Exception as exc:
        _clear(app_ctx, actor)
        await update.message.reply_text(_fmt_error(exc))
        return
    _clear(app_ctx, actor)
    await update.message.reply_text(
        _format_add_report(product_id, rep),
        reply_markup=kb([[InlineKeyboardButton("➕ افزودن بیشتر", callback_data=f"{PREFIX}inv:add:{product_id}")],
                         back_row(f"inv:home:{product_id}:0")]))


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    """ورود کانفیگ‌ها از فایل متنی در فلو inventory_add."""
    if state.get("acc") != "inventory_add":
        await update.message.reply_text("در این مرحله نیازی به ارسال فایل نیست.")
        return
    doc = update.message.document
    name = (doc.file_name or "").lower()
    if not name.endswith(".txt"):
        await update.message.reply_text("⚠️ فقط فایل «.txt» پذیرفته می‌شود.")
        return
    if doc.file_size is not None and doc.file_size > MAX_INVENTORY_FILE_BYTES:
        await update.message.reply_text("⚠️ حجم فایل بیش از ۱ مگابایت است.")
        return
    try:
        tg_file = await doc.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        await update.message.reply_text("⚠️ فایل باید با کدگذاری UTF-8 ذخیره شده باشد.")
        return
    except Exception:
        logger.exception("خطا در دریافت فایل مخزن")
        await update.message.reply_text("⚠️ دریافت فایل ناموفق بود؛ دوباره تلاش کنید.")
        return
    await _inventory_add_step(update, context, state, inventory_service.parse_config_text(text))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    app_ctx = _ctx(context)
    actor = _actor_id(update)
    flow = state.get("acc")
    text = update.message.text

    try:
        if flow == "wallet_amount":
            await _wallet_amount_step(update, context, state); return
        if flow == "wallet_reason":
            await _wallet_reason_step(update, context, state); return
        if flow == "broadcast_text":
            await _broadcast_text_step(update, context, state); return
        if flow == "ticket_reply":
            await _ticket_reply_step(update, context, state); return
        if flow == "setting_edit":
            await _setting_edit_step(update, context, state); return
        if flow == "new_admin_id":
            await _new_admin_id_step(update, context, state); return

        if flow == "user_search":
            _clear(app_ctx, actor)
            with app_ctx.unit_of_work() as uow:
                result = users_service.list_users(uow, actor, query=text.strip())
            if not result.items:
                await update.message.reply_text("چیزی یافت نشد.")
                return
            rows = [[InlineKeyboardButton(f"👤 {u.user_id}", callback_data=f"{PREFIX}usr:d:{u.user_id}")]
                    for u in result.items]
            await update.message.reply_text("نتایج:", reply_markup=kb(rows))
            return

        if flow == "product_new_name":
            name = text.strip()
            _set_state(app_ctx, actor, "product_new_price", name=name)
            await update.message.reply_text("قیمت (تومان) را وارد کنید:")
            return
        if flow == "product_new_price":
            price = parse_positive_int(text)
            _clear(app_ctx, actor)
            if price is None:
                await update.message.reply_text("قیمت نامعتبر است.")
                return
            with app_ctx.unit_of_work() as uow:
                p = catalog_service.create_product(uow, actor, state["name"], price)
            await update.message.reply_text(f"✅ پلن «{p.name}» با شناسهٔ #{p.id} ساخته شد.")
            return

        if flow == "product_rename":
            _clear(app_ctx, actor)
            with app_ctx.unit_of_work() as uow:
                catalog_service.update_product(uow, actor, state["product_id"], name=text.strip())
            await update.message.reply_text("✅ نام به‌روزرسانی شد.")
            return
        if flow == "product_reprice":
            price = parse_positive_int(text)
            _clear(app_ctx, actor)
            if price is None:
                await update.message.reply_text("قیمت نامعتبر است.")
                return
            with app_ctx.unit_of_work() as uow:
                catalog_service.update_product(uow, actor, state["product_id"], price_minor=price)
            await update.message.reply_text("✅ قیمت به‌روزرسانی شد.")
            return

        if flow == "inventory_add":
            await _inventory_add_step(update, context, state, inventory_service.parse_config_text(text))
            return
        if flow == "inventory_purge":
            count = parse_positive_int(text)
            _clear(app_ctx, actor)
            if count is None:
                await update.message.reply_text("عدد نامعتبر است.")
                return
            with app_ctx.unit_of_work() as uow:
                deleted = inventory_service.delete_unclaimed(uow, state["product_id"], count, actor_id=actor)
            await update.message.reply_text(f"🗑️ {deleted} آیتم حذف شد.")
            return

        if flow == "prov_inbound":
            inbound = parse_positive_int(text)
            if inbound is None:
                await update.message.reply_text("شمارهٔ Inbound نامعتبر است.")
                return
            _set_state(app_ctx, actor, "prov_duration", product_id=state["product_id"], inbound_id=inbound)
            await update.message.reply_text("مدت اعتبار به روز (0=بدون انقضا):")
            return
        if flow == "prov_duration":
            days = parse_positive_int(text) or 0
            _set_state(app_ctx, actor, "prov_traffic", **_carry(state), duration_days=days)
            await update.message.reply_text("ترافیک به گیگابایت (0=بدون محدودیت):")
            return
        if flow == "prov_traffic":
            try:
                gb = float(to_en_digits(text))
            except ValueError:
                await update.message.reply_text("مقدار نامعتبر است.")
                return
            _clear(app_ctx, actor)
            with app_ctx.unit_of_work() as uow:
                provisioning_service.set_profile(
                    uow, actor, state["product_id"], "3x-ui", state["inbound_id"],
                    state["duration_days"], gb, 0)
            await update.message.reply_text("✅ پروفایل Provisioning ثبت شد.")
            return

        if flow == "coupon_code":
            _set_state(app_ctx, actor, "coupon_kind", code=text.strip())
            await update.message.reply_text("نوع کوپن: PERCENT یا FIXED؟")
            return
        if flow == "coupon_kind":
            kind = text.strip().upper()
            if kind not in ("PERCENT", "FIXED"):
                await update.message.reply_text("فقط PERCENT یا FIXED مجاز است.")
                return
            _set_state(app_ctx, actor, "coupon_value", **_carry(state), kind=kind)
            await update.message.reply_text("مقدار تخفیف را وارد کنید (درصد یا مبلغ):")
            return
        if flow == "coupon_value":
            value = parse_positive_int(text)
            _clear(app_ctx, actor)
            if value is None:
                await update.message.reply_text("مقدار نامعتبر است.")
                return
            try:
                with app_ctx.unit_of_work() as uow:
                    c = coupons_service.create(uow, actor, state["code"], state["kind"], value)
                await update.message.reply_text(f"✅ کوپن {c.code} ساخته شد.")
            except DomainError as exc:
                await update.message.reply_text(_fmt_error(exc))
            return

        if flow == "tier_name":
            _set_state(app_ctx, actor, "tier_discount", name=text.strip())
            await update.message.reply_text("درصد تخفیف (۰ تا ۱۰۰) را وارد کنید:")
            return
        if flow == "tier_discount":
            pct = parse_positive_int(text)
            _clear(app_ctx, actor)
            if pct is None or pct > 100:
                await update.message.reply_text("درصد نامعتبر است.")
                return
            with app_ctx.unit_of_work() as uow:
                t = reseller_service.create_tier(uow, actor, state["name"], pct)
            await update.message.reply_text(f"✅ سطح «{t.name}» ({t.discount_percent}٪) ساخته شد.")
            return

        _clear(app_ctx, actor)
    except DomainError as exc:
        _clear(app_ctx, actor)
        await update.message.reply_text(_fmt_error(exc))
