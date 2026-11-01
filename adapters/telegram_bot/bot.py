"""
GhYiAb V2 — Telegram Bot Adapter
====================================

توسعه‌دهنده: MohZarg — https://github.com/MohZarg
حمایت مالی: https://github.com/MohZarg

این فایل معادل Adapter کانال تلگرام است: طبق قانون سخت معماری، هیچ منطق
کسب‌وکاری اینجا نیست — فقط ترجمهٔ ورودی/خروجی تلگرام به/از توابع `core/*`.
همهٔ مسیرهای مالی/موجودی حساس (کیف‌پول، خرید، تست رایگان، گردونه، تأیید/رد
درخواست، اعطای نمایندگی/ادمین) از `core` عبور می‌کنند تا AuditLog و Pricing
یکپارچه به‌صورت خودکار اعمال شوند.

تفاوت رفتاری عمدی نسبت به V1: **هیچ.** تنها تغییرِ قابل‌مشاهده این است که
State کاربر با ری‌استارت از بین نمی‌رود (چون از `core.state` پایدار استفاده
می‌شود، نه دیکشنری سراسری).
"""

from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
    ReactionTypeEmoji,
    Update,
)
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

from adapters.telegram_bot import services_ui
from bootstrap import build_app_context, AppContext
from security.secret_loader import BotSecrets, secrets as secret_provider
from core.wallet import service as wallet_service
from core.inventory import service as inventory_service
from core.orders import service as orders_service
from core.reseller import service as reseller_service
from core.tickets import service as tickets_service
from core.settings import service as settings_service
from core.dice import service as dice_service
from core.audit import service as audit_service
from core.catalog import service as catalog_service
from core.auth import rbac
from core.errors import (
    InsufficientBalanceError, OutOfStockError, AlreadyClaimedTestError,
    DailyTestLimitError, DiceCooldownError, DiceDisabledError, DiceBudgetExceededError,
    RequestAlreadyResolvedError,
    ProductNotFoundError, DomainError, CouponError, ValidationError, ConflictError,
    ProviderNotReadyError,
)
from adapters.telegram_bot import texts as T
from adapters.telegram_bot import admin_panel
from adapters.telegram_bot.util import (
    to_en_digits, parse_positive_int, parse_signed_int, parse_user_id, normalize_ir_phone, esc,
)

logger = logging.getLogger("ghyiab.bot")


# --------------------------------------------------------------------------
# کیبوردها
# --------------------------------------------------------------------------

def get_main_reply_keyboard(ctx: AppContext, user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(T.BTN_BUY), KeyboardButton(T.BTN_TEST)],
        [KeyboardButton(T.BTN_SERVICES), KeyboardButton(T.BTN_WALLET)],
        [KeyboardButton(T.BTN_DICE), KeyboardButton(T.BTN_TUTORIALS)],
        [KeyboardButton(T.BTN_REF), KeyboardButton(T.BTN_AGENCY)],
        [KeyboardButton(T.BTN_SUPPORT), KeyboardButton(T.BTN_DONATE)],
    ]
    with ctx.unit_of_work() as uow:
        if rbac.is_admin(uow, user_id):
            rows.append([KeyboardButton(T.BTN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def get_phone_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(T.BTN_SHARE_PHONE, request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def get_admin_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 مخزن", callback_data="adm_makhzan"),
         InlineKeyboardButton("📊 آمار ربات", callback_data="adm_stats")],
        [InlineKeyboardButton("⚙️ تنظیمات عمومی", callback_data="adm_settings"),
         InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="adm_broadcast")],
        [InlineKeyboardButton("✖️ بستن", callback_data="close_inline")],
    ])


def get_settings_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تغییر کارت بانکی", callback_data="adm_change_card")],
        [InlineKeyboardButton("➕ ساخت پلن جدید", callback_data="adm_add_product")],
        [InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm_add_admin")],
        [InlineKeyboardButton("💰 تغییر موجودی کاربر", callback_data="adm_balance_adjust")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_admin_inline")],
    ])


def get_receipt_management_keyboard(req_id: int, action_type: str) -> InlineKeyboardMarkup:
    mapping = {
        "charge": (f"ok_dp_{req_id}", f"no_dp_{req_id}"),
        "buy": (f"ok_by_{req_id}", f"no_by_{req_id}"),
        "agency_req": (f"ok_ag_{req_id}", f"no_ag_{req_id}"),
    }
    approve, reject = mapping[action_type]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data=approve),
         InlineKeyboardButton("❌ رد", callback_data=reject)],
    ])


# --------------------------------------------------------------------------
# کمکی‌های عمومی (safe_send، بررسی عضویت، ری‌اکشن)
# --------------------------------------------------------------------------

async def safe_send(ctx: AppContext, bot, chat_id: int, *args, **kwargs):
    try:
        return await bot.send_message(chat_id, *args, **kwargs)
    except Forbidden:
        with ctx.unit_of_work() as uow:
            uow.users.get_or_create(chat_id)
            uow.users.set_blocked_by_bot(chat_id, True)
        return None
    except TelegramError as e:
        logger.warning("خطا در ارسال پیام به %s: %s", chat_id, e)
        return None


async def safe_edit_admin(query, text: str, *, caption: bool = False) -> None:
    """
    ویرایش پیام ادمین «بهترین‌تلاش» است: تراکنش از قبل commit شده و کاربر باید اول خبردار شود.
    خطای ویرایش (پیام قدیمی/پاک‌شده/بدون تغییر) نباید اطلاع‌رسانی به کاربر را از بین ببرد.
    """
    try:
        if caption:
            await query.edit_message_caption(caption=text)
        else:
            await query.edit_message_text(text)
    except TelegramError as e:
        logger.warning("ویرایش پیام ادمین ناموفق بود: %s", e)


async def react_heart(update: Update) -> None:
    try:
        await update.message.set_reaction(reaction=[ReactionTypeEmoji(emoji="❤️")])
    except Exception as e:
        logger.warning("امکان ارسال ری‌اکشن وجود نداشت: %s", e)


async def check_join(bot, channel_id: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in ("creator", "administrator", "member")
    except TelegramError as e:
        logger.warning("خطا در بررسی عضویت کاربر %s: %s", user_id, e)
        return False


# --------------------------------------------------------------------------
# دستورات
# --------------------------------------------------------------------------


# ---------------- Rate limiting (رفع debounce سراسری نشت‌دار V1) ----------------
import functools
from security.rate_limit import RateLimiter

RATE_LIMITER = RateLimiter.from_env()


def throttled(fn):
    """Token-bucket به‌ازای کاربر؛ Owner معاف است. خارج از حد: callback پاسخ کوتاه می‌گیرد، پیام متنی نادیده می‌شود."""
    @functools.wraps(fn)
    async def wrapper(update, context, *a, **kw):
        import os
        user = update.effective_user if hasattr(update, "effective_user") else None
        uid = getattr(user, "id", None)
        if uid is None and getattr(update, "callback_query", None) is not None:
            uid = update.callback_query.from_user.id
        app_ctx = context.application.bot_data.get("app_ctx")
        if (uid is not None and os.getenv("GHIYAB_RL_DISABLED") != "1"
                and not (app_ctx and uid == app_ctx.owner_id) and not RATE_LIMITER.allow(uid)):
            q = getattr(update, "callback_query", None)
            if q is not None:
                try:
                    await q.answer("⏳", show_alert=False)
                except TelegramError:
                    pass
            return
        return await fn(update, context, *a, **kw)
    return wrapper


@throttled
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    bot_secrets: BotSecrets = context.application.bot_data["bot_secrets"]
    user_id = update.effective_user.id
    try:
        app_ctx.state.clear(user_id)
        with app_ctx.unit_of_work() as uow:
            user = uow.users.get_or_create(user_id)
        if user.is_banned:
            return

        await react_heart(update)

        with app_ctx.unit_of_work() as uow:
            uow.users.get_or_create(user_id)
            uow.users.set_blocked_by_bot(user_id, False)

        with app_ctx.unit_of_work() as uow:
            is_admin_user = rbac.is_admin(uow, user_id)
        if app_ctx.settings.get("locked", "0") == "1" and not is_admin_user:
            await update.message.reply_html("🚧 <b>ربات موقتاً در دست تعمیرات است</b>")
            return

        if user.referred_by == 0 and context.args:
            ref_id = to_en_digits(context.args[0])
            if ref_id.isdigit() and int(ref_id) != user_id:
                with app_ctx.unit_of_work() as uow:
                    uow.users.get_or_create(user_id)
                    uow.users.set_referred_by(user_id, int(ref_id))

        if not await check_join(context.bot, bot_secrets.channel_id, user_id):
            keyboard = [
                [InlineKeyboardButton("📢 عضویت در کانال",
                                       url=f"https://t.me/{bot_secrets.channel_id.replace('@', '')}")],
                [InlineKeyboardButton("✅ تایید عضویت مکرر", callback_data="check_membership")],
            ]
            await update.message.reply_html(
                f"👋 <b>درود بر شما مشترک گرامی</b>\n\nجهت استفاده از خدمات شبکه ابتدا در کانال زیر عضو شوید 🙏\n\n{bot_secrets.channel_id}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        with app_ctx.unit_of_work() as uow:
            user = uow.users.get_or_create(user_id)
        if not user.has_accepted_rules:
            keyboard = [[InlineKeyboardButton("✅ ضوابط را می‌پذیرم", callback_data="accept_rules")]]
            await update.message.reply_html(T.RULES_TEXT, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        await update.message.reply_html(T.START_TEXT, reply_markup=get_main_reply_keyboard(app_ctx, user_id))
    except Exception:
        logger.exception("خطا در پردازش /start برای کاربر %s", user_id)
        try:
            await update.message.reply_text("⚠️ خطایی در پردازش درخواست رخ داد. لطفاً به ادمین اطلاع دهید.")
        except Exception:
            pass


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    user_id = update.effective_user.id
    app_ctx.state.clear(user_id)
    await update.message.reply_text("✅ عملیات جاری لغو شد.", reply_markup=get_main_reply_keyboard(app_ctx, user_id))


async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/lang → جابه‌جایی fa ⇄ en (فقط صفحه‌های سرویس/اعلان‌ها؛ منوی V1 فعلاً فارسی است)."""
    from shared.i18n import t
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    uid = update.effective_user.id
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(uid)
        new = "en" if uow.users.get_lang(uid) == "fa" else "fa"
        uow.users.set_lang(uid, new)
    await update.message.reply_text(t("lang.set", new))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(T.HELP_TEXT)


# --------------------------------------------------------------------------
# منوهای مشترک
# --------------------------------------------------------------------------

async def show_buy_menu(app_ctx: AppContext, message) -> None:
    with app_ctx.unit_of_work() as uow:
        products = uow.products.list_all()
        stock_by_id = {p.id: inventory_service.count_available(uow, p.id) for p in products}
    if not products:
        await message.reply_text("🙁 در حال حاضر هیچ پلنی برای فروش تعریف نشده است.")
        return
    keyboard = []
    for p in products:
        stock = stock_by_id[p.id]
        label = f"📦 {p.name} - {p.price_minor:,} تومان" + ("" if stock > 0 else " (ناموجود ❌)")
        keyboard.append([InlineKeyboardButton(label, callback_data=f"buy_prod_{p.id}")])
    await message.reply_html("🛒 <b>لیست پلن‌های ارتباطی موجود</b>\n\nیک پلن را انتخاب کنید 👇",
                              reply_markup=InlineKeyboardMarkup(keyboard))


async def show_wallet_menu(app_ctx: AppContext, message, user_id: int) -> None:
    with app_ctx.unit_of_work() as uow:
        balance = wallet_service.get_balance(uow, user_id)
    keyboard = [
        [InlineKeyboardButton("➕ افزایش موجودی (کارت به کارت)", callback_data="wallet_charge")],
        [InlineKeyboardButton("📜 تاریخچه تراکنش‌ها", callback_data="wallet_history")],
    ]
    text = (
        f"🏦 <b>میز کار و مدیریت تراز مالی حساب کاربر</b>\n\n"
        f"💰 موجودى فعلى حساب شما: <b>{balance:,} تومان</b>\n\n"
        f"✅ وضعیت دسترسی: معتبر و فعال\n\nجهت افزایش اعتبار از دکمه زیر استفاده فرمایید 👇"
    )
    await message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_dice_play(app_ctx: AppContext, update: Update, user_id: int) -> None:
    try:
        with app_ctx.unit_of_work() as uow:
            if not settings_service.get_bool(uow, "dice_enabled"):
                raise DiceDisabledError("گردونهٔ شانس موقتاً غیرفعال است")
            cooldown_hours = settings_service.get_int(uow, "dice_cooldown_hours")
            dice_service.claim_dice_turn(uow, user_id, cooldown_hours)
    except DiceDisabledError:
        await update.message.reply_text("⛔ گردونهٔ شانس موقتاً غیرفعال است.")
        return
    except DiceCooldownError as e:
        hours = e.remaining_seconds // 3600
        minutes = (e.remaining_seconds % 3600) // 60
        await update.message.reply_text(f"⏳ نوبت بعدی شما تا {hours} ساعت و {minutes} دقیقه دیگر است.")
        return

    await update.message.reply_text("🎲 در حال پرتاب تاس توسط ربات...")
    dice_message = await update.get_bot().send_dice(update.effective_chat.id, emoji="🎲")
    value = dice_message.dice.value

    try:
        with app_ctx.unit_of_work() as uow:
            reward = dice_service.play(uow, user_id, value, claim_turn=False)
    except DiceDisabledError:
        await update.message.reply_text("⛔ گردونهٔ شانس موقتاً غیرفعال است.")
        return
    except DiceBudgetExceededError:
        await update.message.reply_text("🎯 سقف بودجهٔ روزانهٔ جایزه تکمیل شده؛ فردا دوباره تلاش کنید.")
        return

    if reward:
        await update.message.reply_html(
            f"🎉 <b>تبریک! عدد ۶ آوردید</b>\n\n💰 مبلغ {reward:,} تومان به کیف پول شما اضافه شد."
        )
    else:
        await update.message.reply_text(f"🙁 عدد {value} آمد. جایزه فقط برای عدد ۶ است — فردا دوباره امتحان کنید!")


async def request_agency(app_ctx: AppContext, context, message, user_id: int,
                         username: Optional[str]) -> None:
    """ثبت درخواست نمایندگی (هم از دکمهٔ منو و هم از callback).

    بررسی تکراری‌بودن و ساخت درخواست داخل یک تراکنش انجام می‌شود، اما همهٔ
    `await`ها بیرون از آن هستند تا I/O تلگرام تراکنش SQLite را باز نگه ندارد.
    """
    bot_secrets: BotSecrets = context.application.bot_data["bot_secrets"]
    req_id = None
    with app_ctx.unit_of_work() as uow:
        u = uow.users.get_or_create(user_id)
        if u.is_agent:
            outcome = "agent"
        elif orders_service.find_pending_agency_request(uow, user_id):
            outcome = "pending"
        else:
            req_id = orders_service.create_pending_request(uow, "agency", user_id)
            outcome = "created"
    if outcome == "agent":
        await message.reply_text("👑 حساب شما هم‌اکنون روی وضعیت همکاری تنظیم است.")
        return
    if outcome == "pending":
        await message.reply_text("⏳ درخواست نمایندگی قبلی شما در حال بررسی است.")
        return
    await message.reply_html(
        "🙋 <b>تقاضای شما جهت ارتقای حساب ثبت شد</b>\n\nاین درخواست جهت بررسی سوابق ارسال گردید 📨"
    )
    user_label = f"@{username}" if username else "فاقد شناسه"
    markup = get_receipt_management_keyboard(req_id, "agency_req")
    await safe_send(app_ctx, context.bot, bot_secrets.owner_id,
                    f"🙋 درخواست نمایندگی\n\nآیدی: {user_id}\n\nیوزرنیم: {user_label}", reply_markup=markup)


# --------------------------------------------------------------------------
# دیسپچر دکمه‌های کیبورد منویی
# --------------------------------------------------------------------------

async def dispatch_menu_label(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user_id: int) -> bool:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]

    if text == T.BTN_BUY:
        app_ctx.state.clear(user_id)
        await show_buy_menu(app_ctx, update.message)
        return True

    if text == T.BTN_TEST:
        app_ctx.state.clear(user_id)
        today_str = datetime.now().strftime("%Y-%m-%d")
        try:
            with app_ctx.unit_of_work() as uow:
                item = orders_service.claim_free_test(uow, user_id, today_str)
            await update.message.reply_html(f"🔑 <b>پروفایل اتصال آزمایشی صادر شد</b>\n\n<code>{esc(item.content)}</code>")
        except AlreadyClaimedTestError:
            await update.message.reply_text("⚠️ شما قبلاً سهمیه تست رایگان خود را دریافت کرده‌اید")
        except DailyTestLimitError:
            await update.message.reply_text(
                "👑 نماینده گرامی، شما سهمیهٔ امروز خود (1 اکانت تست در روز) را دریافت کرده‌اید. فردا مجدداً تلاش کنید."
            )
        except OutOfStockError:
            await update.message.reply_text("📭 در حال حاضر اکانت تستی در مخزن موجود نیست")
        return True

    if text == T.BTN_SERVICES:
        app_ctx.state.clear(user_id)
        await services_ui.show_my_services(app_ctx, update.message, user_id)
        return True

    if text == T.BTN_WALLET:
        app_ctx.state.clear(user_id)
        await show_wallet_menu(app_ctx, update.message, user_id)
        return True

    if text == T.BTN_TUTORIALS:
        app_ctx.state.clear(user_id)
        await update.message.reply_html(T.TUTORIAL_TEXT)
        return True

    if text == T.BTN_DICE:
        app_ctx.state.clear(user_id)
        await handle_dice_play(app_ctx, update, user_id)
        return True

    if text == T.BTN_SUPPORT:
        app_ctx.state.set(user_id, "waiting_for_support_msg")
        await update.message.reply_html(
            "☎️ <b>بخش ارتباط با پشتیبانی</b>\n\nلطفاً پیام خود را بنویسید تا در اسرع وقت پاسخگوی شما باشیم 🙏\n\n(برای انصراف /cancel را بزنید)"
        )
        return True

    if text == T.BTN_ADMIN:
        with app_ctx.unit_of_work() as uow:
            is_admin_user = rbac.is_admin(uow, user_id)
        if is_admin_user:
            app_ctx.state.clear(user_id)
            await admin_panel.open_home(update, context)
        return True

    if text == T.BTN_AGENCY:
        app_ctx.state.clear(user_id)
        await request_agency(app_ctx, context, update.message, user_id, update.effective_user.username)
        return True

    if text == T.BTN_REF:
        app_ctx.state.clear(user_id)
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        with app_ctx.unit_of_work() as uow:
            bonus = settings_service.get_int(uow, "referral_bonus_minor")
        await update.message.reply_html(
            f"👥 <b>بخش کسب درآمد و دعوت از دوستان</b>\n\n"
            f"با اشتراک‌گذاری لینک خود دوستانتان را دعوت کنید 🤝\n\n"
            f"🎁 پاداش مالی هر دعوت موفق: <b>{bonus:,} تومان</b> اعتبار آنی\n\n"
            f"🔗 لینک دعوت اختصاصی شما:\n{ref_link}"
        )
        return True

    if text == T.BTN_DONATE:
        app_ctx.state.clear(user_id)
        with app_ctx.unit_of_work() as uow:
            credits_url = settings_service.get(uow, "credits_url")
            developer_name = settings_service.get(uow, "developer_name")
        await update.message.reply_html(
            f"💝 <b>حمایت از توسعه‌دهنده</b>\n\n"
            f"این ربات توسط <b>{esc(developer_name)}</b> توسعه یافته است.\n\n"
            f"اگر از این پروژه راضی هستید، می‌توانید از طریق لینک زیر از توسعه‌دهنده حمایت کنید:\n\n"
            f"🔗 <a href=\"{esc(credits_url)}\">صفحه حمایت مالی</a>\n\n"
            f"با سپاس از همراهی شما ❤️"
        )
        return True

    return False


# --------------------------------------------------------------------------
# کال‌بک‌های اینلاین (فقط مسیرهای حیاتی مالی/موجودی — طبق دستور Owner در
# Phase 1: «هیچ Feature جدیدی خارج از Phase 1 نساز»، پس فقط چیزی که در V1
# بود پورت شده)
# --------------------------------------------------------------------------

@throttled
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    bot_secrets: BotSecrets = context.application.bot_data["bot_secrets"]
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    with app_ctx.unit_of_work() as uow:
        user = uow.users.get_or_create(user_id)
        is_admin_user = rbac.is_admin(uow, user_id)
        # Phase 3 Hardening: Permissionهای دقیق برای هر عملیات حساس، به‌جای
        # چک تخت is_admin_user. تا وقتی نقشی محدودتر از ADMIN تعریف نشده
        # (TODO #4)، هیچ رفتاری برای OWNER/ADMIN فعلی تغییر نمی‌کند — چون
        # هر دو نقش هنوز کل این Permissionها را دارند (seed در Phase 3).
        # بهینه‌سازی: کاربر عادی (اکثریت) هیچ Permission ای ندارد → ۷ کوئری RBAC برای هر Callback حذف شد
        _perm = (lambda p: rbac.has_permission(uow, user_id, p)) if is_admin_user else (lambda p: False)
        can_adjust_wallet = _perm("wallet.adjust")
        can_manage_inventory = _perm("inventory.manage")
        can_manage_products = _perm("products.manage")
        can_approve_orders = _perm("orders.approve")
        can_manage_rbac = _perm("rbac.manage")
        can_manage_settings = _perm("settings.manage")
        can_broadcast = _perm("broadcast.send")
    if user.is_banned:
        return

    if services_ui.is_service_callback(data):
        await services_ui.handle_service_callback(update, context)
        return

    if admin_panel.is_relevant_callback(data):
        await admin_panel.handle_callback(update, context)
        return

    if data == "close_inline":
        try:
            await query.message.delete()
        except Exception:
            await query.edit_message_reply_markup(reply_markup=None)
        return

    if data == "check_membership":
        if await check_join(context.bot, bot_secrets.channel_id, user_id):
            try:
                await query.message.delete()
            except Exception:
                pass
            with app_ctx.unit_of_work() as uow:
                user2 = uow.users.get_or_create(user_id)
            if not user2.has_accepted_rules:
                keyboard = [[InlineKeyboardButton("✅ ضوابط را می‌پذیرم", callback_data="accept_rules")]]
                await safe_send(app_ctx, context.bot, query.message.chat_id, T.RULES_TEXT,
                                 reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            else:
                await safe_send(app_ctx, context.bot, query.message.chat_id, "✅ سیستم آماده بهره‌برداری است",
                                 reply_markup=get_main_reply_keyboard(app_ctx, user_id))
        else:
            await query.answer("❌ عضویت شما در کانال تایید نشد", show_alert=True)
        return

    if data == "accept_rules":
        with app_ctx.unit_of_work() as uow:
            uow.users.get_or_create(user_id)
            first_time = not uow.users.get_or_create(user_id).has_accepted_rules
            uow.users.set_accepted_rules(user_id)
            fresh_user = uow.users.get_or_create(user_id)
        try:
            await query.message.delete()
        except Exception:
            pass
        # پاداش فقط در اولین پذیرش و فقط از مسیر اتمیک reseller (UNIQUE/سقف روزانه/سوئیچ ادمین)
        with app_ctx.unit_of_work() as uow:
            signup_trigger = settings_service.get(uow, "referral_trigger") == "signup"
        if first_time and fresh_user.referred_by != 0 and signup_trigger:
            with app_ctx.unit_of_work() as uow:
                paid = reseller_service.pay_referral_reward(uow, fresh_user.referred_by, user_id)
                amount = settings_service.get_int(uow, "referral_bonus_minor") if paid else 0
            if paid:
                await safe_send(
                    app_ctx, context.bot, fresh_user.referred_by,
                    f"🎁 <b>پاداش دعوت کاربر جدید</b>\n\nیک کاربر از طریق لینک شما وارد شد\n\n"
                    f"مبلغ {amount:,} تومان به کیف پول شما افزوده شد",
                    parse_mode="HTML",
                )
        await safe_send(app_ctx, context.bot, query.message.chat_id,
                         f"✅ ضوابط با موفقیت تایید شد\n\n{T.START_TEXT}",
                         reply_markup=get_main_reply_keyboard(app_ctx, user_id))
        return

    if data.startswith("buy_prod_"):
        p_id = int(data.split("_")[2])
        with app_ctx.unit_of_work() as uow:
            product = uow.products.get(p_id)
            u = uow.users.get_or_create(user_id)
            balance = wallet_service.get_balance(uow, user_id)
            final_price = orders_service.price_for_user(uow, user_id, product) if product else 0
        if product is None:
            await query.answer("این محصول دیگر موجود نیست.", show_alert=True)
            return
        role_label = "👑 نماینده (10% تخفیف ویژه)" if u.is_agent else "👤 کاربر عادی"
        keyboard = [
            [InlineKeyboardButton("💳 کارت به کارت (ارسال فیش)", callback_data=f"direct_pay_{p_id}")],
            [InlineKeyboardButton("🏦 پرداخت آنلاین از کیف پول", callback_data=f"wallet_pay_{p_id}")],
            [InlineKeyboardButton("🎟 کد تخفیف دارم", callback_data=f"cpn_ask_{p_id}")],
        ]
        text = (
            f"📦 <b>پلن انتخابی:</b> {esc(product.name)}\n\n"
            f"💵 <b>قیمت اصلی:</b> {product.price_minor:,} تومان\n\n"
            f"💰 <b>قیمت برای شما:</b> {final_price:,} تومان ({role_label})\n\n"
            f"🏦 <b>تراز مالی شما:</b> {balance:,} تومان"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if data.startswith("cpn_ask_"):
        p_id = int(data.split("_")[2])
        app_ctx.state.set(user_id, {"action": "waiting_coupon", "product_id": p_id})
        await context.bot.send_message(query.message.chat_id, "🎟 کد تخفیف خود را ارسال کنید (برای انصراف /cancel):")
        return

    if data.startswith("dpc:") or data.startswith("wpc:"):
        kind, p_raw, code = data.split(":", 2)
        p_id = int(p_raw)
        if kind == "wpc":
            await _wallet_purchase(update, context, app_ctx, user_id, p_id, code)
            return
        try:
            with app_ctx.unit_of_work() as uow:
                product = uow.products.get(p_id)
                if product is None:
                    raise ProductNotFoundError(str(p_id))
                q = orders_service.quote(uow, user_id, product, code, count_pending=True)
        except ProductNotFoundError:
            await query.answer("این محصول دیگر موجود نیست.", show_alert=True)
            return
        except CouponError as exc:
            await query.answer(f"⚠️ {exc}", show_alert=True)
            return
        app_ctx.state.set(user_id, {"action": "direct_buy_receipt", "product_id": p_id, "coupon": q.coupon_code})
        await _send_direct_invoice(app_ctx, context, query.message.chat_id, q.final_minor)
        return

    if data.startswith("direct_pay_"):
        p_id = int(data.split("_")[2])
        app_ctx.state.set(user_id, {"action": "direct_buy_receipt", "product_id": p_id})
        card_number = app_ctx.settings.get("card_number", T.DEFAULT_CARD_NUMBER)
        card_name = app_ctx.settings.get("card_name", T.DEFAULT_CARD_NAME)
        await context.bot.send_message(
            query.message.chat_id,
            f"💳 <b>صورت‌حساب واریز مستقیم</b>\n\nلطفاً مبلغ را به حساب زیر واریز نموده و فقط تصویر رسید را بفرستید 🧾\n\n"
            f"شماره کارت:\n<code>{card_number}</code>\n\nدارنده حساب: {esc(card_name)}",
            parse_mode="HTML",
        )
        return

    if data.startswith("wallet_pay_"):
        await _wallet_purchase(update, context, app_ctx, user_id, int(data.split("_")[2]), None)
        return

    if data.startswith("view_order_"):
        order_id = int(data.split("_")[2])
        with app_ctx.unit_of_work() as uow:
            order = uow.orders.get_by_id(order_id)
            if order is None or order.user_id != user_id:
                return
            item = uow.inventory.get_by_id(order.inventory_item_id)
            product = uow.products.get(order.product_id)
        await context.bot.send_message(
            query.message.chat_id,
            f"🔍 <b>اطلاعات فنی سرویس</b>\n\n📦 نوع: {esc(product.name) if product else '?'}\n\n"
            f"🔑 کلید دسترسی:\n<code>{esc(item.content) if item else '?'}</code>",
            parse_mode="HTML",
        )
        return

    if data == "wallet_charge":
        app_ctx.state.set(user_id, "waiting_for_charge_amount")
        await context.bot.send_message(
            query.message.chat_id,
            "💳 <b>بخش افزایش موجودی حساب</b>\n\nلطفاً مبلغ مورد نظر خود را به تومان و به عدد وارد نمایید:",
            parse_mode="HTML",
        )
        return

    if data == "wallet_history":
        with app_ctx.unit_of_work() as uow:
            txs = wallet_service.list_recent_transactions(uow, user_id, limit=10)
        if txs:
            lines = ["📜 <b>۱۰ تراکنش اخیر شما:</b>\n"]
            for tx in txs:
                sign = "+" if tx.amount_minor >= 0 else ""
                when = tx.created_at.split(" ")[0] if tx.created_at else ""
                lines.append(f"{sign}{tx.amount_minor:,} تومان — {esc(tx.reason)} ({when})")
            text = "\n".join(lines)
        else:
            text = "📭 هیچ تراکنشی برای شما ثبت نشده است."
        await query.edit_message_text(text, parse_mode="HTML")
        return

    # --- تأیید/رد درخواست‌های ادمین (شارژ/خرید مستقیم/نمایندگی) ---
    if data.startswith("ok_dp_") or data.startswith("no_dp_"):
        if not can_adjust_wallet:
            return
        req_id = int(data.split("_")[2])
        try:
            if data.startswith("ok_dp_"):
                with app_ctx.unit_of_work() as uow:
                    row = orders_service.approve_charge_request(uow, req_id, actor_id=user_id)
                await safe_send(app_ctx, context.bot, row.user_id,
                                 f"💰 <b>اطلاعیه واریز وجه</b>\n\nکیف پول شما با موفقیت شارژ شد ✅\n\nمبلغ {row.amount_minor:,} تومان به حساب شما اضافه گردید",
                                 parse_mode="HTML")
                await safe_edit_admin(query, f"✅ تراکنش مالی تایید شد\n\nموجودی کاربر {row.user_id} به مبلغ {row.amount_minor:,} ارتقا یافت.", caption=True)
            else:
                with app_ctx.unit_of_work() as uow:
                    row = orders_service.reject_request(uow, req_id, actor_id=user_id)
                await safe_send(app_ctx, context.bot, row.user_id,
                                 "❌ <b>اطلاعیه عدم تایید رسید</b>\n\nتراکنش ارسالی شما مورد تایید قرار نگرفت",
                                 parse_mode="HTML")
                await safe_edit_admin(query, f"❌ رسید تراکنش مالی کاربر {row.user_id} رد شد.", caption=True)
        except RequestAlreadyResolvedError:
            await query.answer("⏱️ این درخواست قبلاً پردازش شده است.", show_alert=True)
        except DomainError as exc:
            await query.answer(f"⚠️ {exc}", show_alert=True)
        return

    if data.startswith("ok_by_") or data.startswith("no_by_"):
        if not can_approve_orders:
            return
        req_id = int(data.split("_")[2])
        try:
            if data.startswith("ok_by_"):
                with app_ctx.unit_of_work() as uow:
                    item, product, order = orders_service.approve_direct_purchase(uow, req_id, actor_id=user_id)
                if item is None:  # محصول Provider-backed: صدور واقعی از 3x-ui (خارج از تراکنش DB)
                    async def _alert_owner(msg: str) -> None:
                        await safe_send(app_ctx, context.bot, app_ctx.owner_id, msg)
                    outcome = await services_ui.provision_and_deliver(
                        context.bot, app_ctx, order.user_id, order.id, notify_admin=_alert_owner)
                    await safe_edit_admin(
                        query, "✅ فیش خرید تایید و سرویس صادر شد." if outcome == "READY"
                        else "✅ فیش تایید شد؛ صدور سرویس معوق ماند (Retry خودکار فعال است).", caption=True)
                else:
                    await safe_send(
                        app_ctx, context.bot, order.user_id,
                        f"🎉 <b>سرویس شما با موفقیت فعال شد</b>\n\n📦 نوع اشتراک: {esc(product.name)}\n\n"
                        f"🔑 کلید اتصال:\n<code>{esc(item.content)}</code>",
                        parse_mode="HTML",
                    )
                    await safe_edit_admin(query, "✅ فیش خرید تایید و اشتراک صادر شد.", caption=True)
            else:
                with app_ctx.unit_of_work() as uow:
                    row = orders_service.reject_request(uow, req_id, actor_id=user_id)
                await safe_send(app_ctx, context.bot, row.user_id,
                                 "❌ <b>درخواست خرید شما به دلیل اشکال در رسید رد شد</b>", parse_mode="HTML")
                await safe_edit_admin(query, f"❌ فیش خرید کاربر {row.user_id} رد شد.", caption=True)
        except RequestAlreadyResolvedError:
            await query.answer("⏱️ این درخواست قبلاً پردازش شده است.", show_alert=True)
        except OutOfStockError:
            await query.answer("⚠️ مخزن محصول خالی است. ابتدا کانفیگ اضافه کنید.", show_alert=True)
        except ProviderNotReadyError:
            await query.answer("🚧 NOT_CONFIGURED: 3x-ui پیکربندی نشده؛ تأیید انجام نشد و درخواست در انتظار ماند.",
                               show_alert=True)
        except ProductNotFoundError:
            await query.answer("این محصول دیگر موجود نیست.", show_alert=True)
        except DomainError as exc:
            await query.answer(f"⚠️ {exc}", show_alert=True)
        return

    if data.startswith("ok_ag_") or data.startswith("no_ag_"):
        # NEED-INFO: تأیید/رد نمایندگی هیچ‌کدام از Permissionهای فعلی نیست؛ فعلاً روی is_admin_user
        # (تصمیم Owner لازم است). سرویس خودش orders.approve را هم می‌سنجد.
        if not is_admin_user:
            return
        req_id = int(data.split("_")[2])
        try:
            if data.startswith("ok_ag_"):
                with app_ctx.unit_of_work() as uow:
                    resolved = orders_service.approve_agency_request(uow, req_id, actor_id=user_id)
                await safe_send(app_ctx, context.bot, resolved.user_id, T.AGENCY_SUCCESS_TEXT, parse_mode="HTML")
                await safe_edit_admin(query, f"👑 سطح کاربری {resolved.user_id} به وضعیت همکاری تغییر یافت.")
            else:
                with app_ctx.unit_of_work() as uow:
                    resolved = orders_service.reject_request(uow, req_id, actor_id=user_id)
                await safe_send(app_ctx, context.bot, resolved.user_id,
                                 "❌ <b>درخواست نمایندگی شما مورد تایید قرار نگرفت</b>", parse_mode="HTML")
                await safe_edit_admin(query, f"❌ درخواست نمایندگی کاربر {resolved.user_id} رد شد.")
        except RequestAlreadyResolvedError:
            await query.answer("⏱️ این درخواست قبلاً پردازش شده است.", show_alert=True)
        except DomainError as exc:
            await query.answer(f"⚠️ {exc}", show_alert=True)
        return

    # --- پنل مدیریت (طبق V1 پورت‌شده — قبلاً دکمه‌ها ساخته می‌شدند اما هیچ
    # هندلری نداشتند؛ این بخش دقیقاً همان قابلیت‌های V1 را به core وصل می‌کند)
    if data == "menu_admin_inline":
        # فقط ناوبری/بازکردن پنل — عملیات حساس واقعی هرکدام Permission
        # مخصوص خودشان را جدا چک می‌کنند؛ اینجا صرفاً «آیا ادمین است».
        if not is_admin_user:
            return
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await context.bot.send_message(query.message.chat_id, "🛠️ به میز کار مدیریت خوش آمدید:",
                                         reply_markup=get_admin_inline_keyboard())
        return

    if data == "adm_makhzan":
        if not can_manage_inventory:
            return
        with app_ctx.unit_of_work() as uow:
            products = uow.products.list_all()
            stock_by_id = {p.id: inventory_service.count_available(uow, p.id) for p in products}
        keyboard = [
            [InlineKeyboardButton(f"📦 {p.name} (موجود: {stock_by_id[p.id]})", callback_data=f"m_add_{p.id}")]
            for p in products
        ]
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_admin_inline")])
        await query.edit_message_text(
            "📦 انبار مرکزی؛ برای افزودن کانفیگ روی پلن مورد نظر بزنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("m_add_"):
        if not can_manage_inventory:
            return
        p_id = int(data.split("_")[2])
        app_ctx.state.set(user_id, {"action": "waiting_for_configs_reply", "product_id": p_id})
        await context.bot.send_message(query.message.chat_id,
                                        "📥 لطفاً کلیدهای اتصال را ارسال فرمایید (هر خط یک کانفیگ):")
        return

    if data == "adm_stats":
        # عمداً روی is_admin_user باقی می‌ماند: این یک نمای فقط‌خواندنی
        # چند-دامنه‌ای است (کاربران+ادمین‌ها+درخواست‌ها+موجودی هر محصول)؛
        # مقیدکردنش به یکی از ۱۰ Permission، انتخابی حدسی/تحمیلی می‌بود.
        if not is_admin_user:
            return
        with app_ctx.unit_of_work() as uow:
            total_users = uow.users.count_all()
            total_admins = len(uow.rbac.list_admins())
            pending_count = uow.pending_requests.count_pending()
            products = uow.products.list_all()
            stock_lines = [
                f"📦 {esc(p.name)}: {inventory_service.count_available(uow, p.id)} موجود" for p in products
            ]
        text = (
            f"📊 <b>آمار ربات</b>\n\n👥 کاربران: {total_users}\n\n👨‍💼 ادمین‌ها: {total_admins}\n\n"
            f"⏳ درخواست‌های در انتظار: {pending_count}\n\n" + "\n".join(stock_lines)
        )
        await query.edit_message_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_admin_inline")]]),
        )
        return

    if data == "adm_settings":
        # فقط ناوبری به زیرمنو — دکمه‌های داخل زیرمنو (تغییر کارت/ساخت پلن/
        # افزودن ادمین/تنظیم موجودی) هرکدام Permission مخصوص خودشان را دارند.
        if not is_admin_user:
            return
        await query.edit_message_text("⚙️ کنترلر تنظیمات عمومی:", reply_markup=get_settings_inline_keyboard())
        return

    if data == "adm_change_card":
        if not can_manage_settings:
            return
        app_ctx.state.set(user_id, "waiting_for_new_card")
        await context.bot.send_message(query.message.chat_id, "💳 شماره کارت 16 رقمی مقصد جدید را بفرستید:")
        return

    if data == "adm_add_product":
        if not can_manage_products:
            return
        app_ctx.state.set(user_id, "waiting_new_product_name")
        await context.bot.send_message(query.message.chat_id, "✍️ نام پلن جدید را وارد کنید:")
        return

    if data == "adm_add_admin":
        if not can_manage_rbac:
            return
        app_ctx.state.set(user_id, "waiting_for_new_admin_id")
        await context.bot.send_message(query.message.chat_id, "➕ آیدی عددی کاربر جهت افزودن به کادر ادمین‌ها را بفرستید:")
        return

    if data == "adm_balance_adjust":
        if not can_adjust_wallet:
            return
        app_ctx.state.set(user_id, "waiting_for_balance_adjust")
        await context.bot.send_message(
            query.message.chat_id,
            "➕ فرمت افزایش موجودی: «آیدی مقدار» را بفرستید (برای کسر، مقدار منفی وارد کنید):",
        )
        return

    if data == "adm_broadcast":
        if not can_broadcast:
            return
        app_ctx.state.set(user_id, "waiting_for_broadcast")
        await context.bot.send_message(query.message.chat_id, "✍️ پیام همگانی خود را بنویسید:")
        return

    if data == "menu_agency":
        await request_agency(app_ctx, context, query.message, user_id, query.from_user.username)
        return

    await query.answer()


# --------------------------------------------------------------------------
# پیام‌های متنی (روتینگ به دیسپچر منو یا State جاری)
# --------------------------------------------------------------------------

async def _send_direct_invoice(app_ctx: AppContext, context, chat_id: int, amount_minor: int) -> None:
    card_number = app_ctx.settings.get("card_number", T.DEFAULT_CARD_NUMBER)
    card_name = app_ctx.settings.get("card_name", T.DEFAULT_CARD_NAME)
    await context.bot.send_message(
        chat_id,
        f"💳 <b>صورت‌حساب واریز مستقیم</b>\n\nمبلغ قابل پرداخت: <b>{amount_minor:,} تومان</b>\n\n"
        f"لطفاً مبلغ را به حساب زیر واریز نموده و فقط تصویر رسید را بفرستید 🧾\n\n"
        f"شماره کارت:\n<code>{card_number}</code>\n\nدارنده حساب: {esc(card_name)}",
        parse_mode="HTML",
    )


async def _wallet_purchase(update, context, app_ctx: AppContext, user_id: int, p_id: int,
                           coupon_code: Optional[str]) -> None:
    query = update.callback_query
    msg_id = getattr(query.message, "message_id", None) if query.message else None
    key = f"buy:{user_id}:{msg_id}" if msg_id is not None else None
    try:
        with app_ctx.unit_of_work() as uow:
            order = orders_service.purchase_with_wallet(
                uow, user_id, p_id, coupon_code, idempotency_key=key)
            item = uow.inventory.get_by_id(order.inventory_item_id) if order.status != "PROVISIONING" else None
            product = uow.products.get(p_id)
        if item is None:  # Provider-backed: صدور واقعی بعد از commit پرداخت
            await query.edit_message_text(f"✅ پرداخت {order.price_minor:,} تومان ثبت شد؛ در حال آماده‌سازی سرویس…")

            async def _alert_owner(msg: str) -> None:
                await safe_send(app_ctx, context.bot, app_ctx.owner_id, msg)
            await services_ui.provision_and_deliver(context.bot, app_ctx, user_id, order.id, notify_admin=_alert_owner)
            return
        coupon_line = (f"🎟 کوپن {order.coupon_code}: {order.discount_minor:,} تومان تخفیف\n\n"
                       if order.coupon_code else "")
        text = (
            f"🎉 <b>سرویس شما با موفقیت فعال شد</b>\n\n"
            f"📦 نوع اشتراک: {esc(product.name)}\n\n"
            f"{coupon_line}"
            f"💰 مبلغ کسر شده: {order.price_minor:,} تومان\n\n"
            f"🔑 کلید اتصال:\n<code>{esc(item.content)}</code>"
        )
        await query.edit_message_text(text, parse_mode="HTML")
    except InsufficientBalanceError:
        await query.answer("💸 تراز مالی شما برای خرید کافی نیست", show_alert=True)
    except OutOfStockError:
        await query.answer("📭 مخزن این سرویس موقتاً خالی است", show_alert=True)
    except ProviderNotReadyError:
        await query.answer("🚧 فروش این سرویس موقتاً متوقف است (NOT_CONFIGURED). مبلغی کسر نشد.", show_alert=True)
    except ProductNotFoundError:
        await query.answer("این محصول دیگر موجود نیست.", show_alert=True)
    except CouponError as exc:
        await query.answer(f"⚠️ {exc}", show_alert=True)


@throttled
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    bot_secrets: BotSecrets = context.application.bot_data["bot_secrets"]
    user_id = update.effective_user.id
    with app_ctx.unit_of_work() as uow:
        user = uow.users.get_or_create(user_id)
        can_adjust_wallet = rbac.has_permission(uow, user_id, "wallet.adjust")
        can_manage_inventory = rbac.has_permission(uow, user_id, "inventory.manage")
        can_manage_products = rbac.has_permission(uow, user_id, "products.manage")
        can_manage_rbac = rbac.has_permission(uow, user_id, "rbac.manage")
        can_manage_settings = rbac.has_permission(uow, user_id, "settings.manage")
        can_broadcast = rbac.has_permission(uow, user_id, "broadcast.send")
    if user.is_banned:
        return

    text = update.message.text
    if await dispatch_menu_label(update, context, text, user_id):
        return

    current_state = app_ctx.state.get(user_id)

    if isinstance(current_state, dict) and current_state.get("acc"):
        await admin_panel.handle_text(update, context, current_state)
        return

    if isinstance(current_state, dict) and current_state.get("action") == "waiting_coupon":
        p_id = current_state["product_id"]
        code = (text or "").strip().upper()
        try:
            with app_ctx.unit_of_work() as uow:
                product = uow.products.get(p_id)
                if product is None:
                    raise ProductNotFoundError(str(p_id))
                q = orders_service.quote(uow, user_id, product, code)
                balance = wallet_service.get_balance(uow, user_id)
        except ProductNotFoundError:
            app_ctx.state.clear(user_id)
            await update.message.reply_text("این محصول دیگر موجود نیست.")
            return
        except CouponError as exc:
            await update.message.reply_text(f"⚠️ {exc}\nکد دیگری بفرستید یا /cancel بزنید.")
            return
        app_ctx.state.clear(user_id)
        keyboard = [
            [InlineKeyboardButton("💳 کارت به کارت (ارسال فیش)", callback_data=f"dpc:{p_id}:{q.coupon_code}")],
            [InlineKeyboardButton("🏦 پرداخت از کیف پول", callback_data=f"wpc:{p_id}:{q.coupon_code}")],
        ]
        await update.message.reply_html(
            f"🎟 <b>کد {esc(q.coupon_code)} اعمال شد</b>\n\n📦 {esc(product.name)}\n\n"
            f"💵 قیمت قبل: {q.role_price_minor:,} تومان\n\n"
            f"💰 <b>قیمت نهایی: {q.final_minor:,} تومان</b>\n\n🏦 موجودی شما: {balance:,} تومان",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if current_state == "waiting_for_charge_amount":
        amount = parse_positive_int(text)
        if amount is None:
            await update.message.reply_text("لطفاً فقط مبلغ را به عدد وارد کنید")
            return
        app_ctx.state.set(user_id, {"action": "send_charge_receipt", "amount": amount})
        card_number = app_ctx.settings.get("card_number", T.DEFAULT_CARD_NUMBER)
        card_name = app_ctx.settings.get("card_name", T.DEFAULT_CARD_NAME)
        await update.message.reply_html(
            f"💳 <b>بخش افزایش موجودی حساب</b>\n\nلطفاً مبلغ واریزی را به مقدار دقیق {amount:,} تومان کارت به کارت نموده\n\n"
            f"و تصویر رسید فیش خود را در پاسخ به این پیام ارسال فرمایید 🧾\n\n"
            f"شماره کارت: <code>{card_number}</code>\n\nبنام: {esc(card_name)}"
        )
        return

    if current_state == "waiting_for_support_msg":
        # قبلاً فقط به OWNER فوروارد می‌شد: ماژول تیکت (tickets_max_open، تاریخچه، پاسخ از پنل) هیچ‌وقت داده نمی‌گرفت
        body = (text or "").strip()
        try:
            with app_ctx.unit_of_work() as uow:
                ticket = tickets_service.open_ticket(uow, user_id, body[:40], body)
        except (ValidationError, ConflictError) as exc:
            await update.message.reply_text(f"⚠️ {exc}")
            return
        app_ctx.state.clear(user_id)
        username = f"@{update.effective_user.username}" if update.effective_user.username else "فاقد شناسه"
        await safe_send(app_ctx, context.bot, bot_secrets.owner_id,
                         f"☎️ تیکت جدید #{ticket.id}\n\nکاربر: {user_id} ({username})\n\n{body}\n\n"
                         "پاسخ از «پنل مدیریت ← پشتیبانی»")
        await update.message.reply_text(f"✅ پیام شما با شماره تیکت #{ticket.id} ثبت شد و به زودی پاسخ می‌دهیم.")
        return

    if can_manage_rbac and current_state == "waiting_for_new_admin_id":
        app_ctx.state.clear(user_id)
        target = parse_user_id(text)
        if target is None:
            await update.message.reply_text("خطا: آیدی نامعتبر است")
            return
        with app_ctx.unit_of_work() as uow:
            rbac.grant_admin(uow, target, actor_id=user_id)
        await update.message.reply_text(f"✅ کاربر {target} به کادر ادمین‌ها ملحق شد.")
        return

    if can_adjust_wallet and current_state == "waiting_for_balance_adjust":
        app_ctx.state.clear(user_id)
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("فرمت صحیح: آیدی مقدار (مثبت=افزایش، منفی=کسر — مثلاً 12345 -5000)")
            return
        target = parse_user_id(parts[0])
        amount = parse_signed_int(parts[1])
        if target is None or amount is None:
            await update.message.reply_text("ساختار ورودی نادرست است.")
            return
        reason = "افزایش موجودی توسط ادمین" if amount > 0 else "کسر موجودی توسط ادمین"
        try:
            with app_ctx.unit_of_work() as uow:
                wallet_service.admin_adjust(uow, user_id, target, amount, reason)
        except DomainError as exc:
            await update.message.reply_text(f"⚠️ {exc}")
            return
        await update.message.reply_text("✅ تراز مالی با موفقیت به‌روزرسانی شد")
        notice = (
            f"💰 <b>اطلاعیه واریز وجه</b>\n\nمبلغ {amount:,} تومان به موجودی جاری حساب شما اضافه گردید"
            if amount > 0 else
            f"⚠️ <b>اطلاعیه مالی</b>\n\nمبلغ {abs(amount):,} تومان از حساب کاربری شما کسر گردید"
        )
        await safe_send(app_ctx, context.bot, target, notice, parse_mode="HTML")
        return

    if can_manage_settings and current_state == "waiting_for_new_card":
        digits = to_en_digits(text).replace(" ", "").replace("-", "")
        if not (digits.isdigit() and len(digits) == 16):
            await update.message.reply_text("شماره کارت باید دقیقاً ۱۶ رقم باشد. مجدداً تلاش کنید:")
            return
        app_ctx.state.set(user_id, {"action": "waiting_for_new_card_name", "card_num": digits})
        await update.message.reply_text("👤 اکنون نام صاحب حساب جدید را وارد نمایید:")
        return

    if (can_manage_settings and isinstance(current_state, dict)
            and current_state.get("action") == "waiting_for_new_card_name"):
        app_ctx.state.clear(user_id)
        card_name = text.strip()
        app_ctx.settings.set("card_number", current_state["card_num"])
        app_ctx.settings.set("card_name", card_name)
        with app_ctx.unit_of_work() as uow:
            audit_service.record(
                uow, actor_id=user_id, action="settings.change_card",
                entity_type="setting", entity_id="card",
                after={"card_number": current_state["card_num"], "card_name": card_name},
            )
        await update.message.reply_text("✅ اطلاعات حساب بانکی با موفقیت به‌روزرسانی شد.")
        return

    if can_manage_products and current_state == "waiting_new_product_name":
        name = text.strip()
        if not name:
            await update.message.reply_text("نام نمی‌تواند خالی باشد.")
            return
        app_ctx.state.set(user_id, {"action": "waiting_new_product_price", "name": name})
        await update.message.reply_text("💰 بهای محصول جدید را به تومان وارد نمایید:")
        return

    if (can_manage_products and isinstance(current_state, dict)
            and current_state.get("action") == "waiting_new_product_price"):
        price = parse_positive_int(text)
        if price is None:
            await update.message.reply_text("❌ مقدار ورودی نامعتبر است.")
            return
        with app_ctx.unit_of_work() as uow:
            catalog_service.create_product(uow, user_id, current_state["name"], price, "TOMAN")
        app_ctx.state.clear(user_id)
        await update.message.reply_text("✅ محصول جدید با موفقیت اضافه شد.")
        return

    if (can_manage_inventory and isinstance(current_state, dict)
            and current_state.get("action") == "waiting_for_configs_reply"):
        p_id = current_state.get("product_id")
        app_ctx.state.clear(user_id)
        lines = inventory_service.parse_config_text(text)
        with app_ctx.unit_of_work() as uow:
            added = inventory_service.add_items(
                uow, p_id, inventory_service.default_item_type(p_id), lines, actor_id=user_id)
        await update.message.reply_text(f"✅ تعداد {added} اکانت با موفقیت به انبار افزوده شد.")
        return

    if can_broadcast and current_state == "waiting_for_broadcast":
        app_ctx.state.clear(user_id)
        with app_ctx.unit_of_work() as uow:
            target_ids = uow.users.list_ids_not_blocked()
        sent = 0
        for target_id in target_ids:
            res = await safe_send(app_ctx, context.bot, target_id,
                                   f"📢 <b>اطلاعیه جدید مدیریت</b>\n\n{esc(text)}", parse_mode="HTML")
            if res is not None:
                sent += 1
        await update.message.reply_text(f"✅ پیام همگانی با موفقیت به {sent} کاربر ارسال شد.")
        return

    if isinstance(current_state, dict) and current_state.get("action") == "direct_buy_receipt":
        # منتظر تصویر رسید هستیم؛ متن اضافه نادیده گرفته می‌شود (رفتار V1)
        pass

    await update.message.reply_text("لطفاً از دکمه‌های پایین صفحه استفاده نمایید 👇",
                                     reply_markup=get_main_reply_keyboard(app_ctx, user_id))


@throttled
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    user_id = update.effective_user.id
    contact = update.message.contact
    if contact.user_id != user_id:
        await update.message.reply_text("⚠️ لطفاً فقط شماره تلفن متعلق به خودتان را ارسال کنید.")
        return
    normalized = normalize_ir_phone(contact.phone_number)
    if not normalized:
        await update.message.reply_text("❌ فقط شماره‌های ایران (+98) پذیرفته می‌شود.")
        return
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(user_id)
        uow.users.set_phone(user_id, normalized)
    await update.message.reply_text("✅ شماره شما با موفقیت و به‌صورت خودکار تایید شد.",
                                     reply_markup=get_main_reply_keyboard(app_ctx, user_id))


@throttled
async def handle_documents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فایل فقط برای فلوهای ادمین (ورود دسته‌ای کانفیگ) پذیرفته می‌شود؛ بقیه نادیده."""
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    user_id = update.effective_user.id
    with app_ctx.unit_of_work() as uow:
        user = uow.users.get_or_create(user_id)
        allowed = rbac.has_permission(uow, user_id, "inventory.manage")
    if user.is_banned or not allowed:
        return
    state = app_ctx.state.get(user_id)
    if isinstance(state, dict) and state.get("acc"):
        await admin_panel.handle_document(update, context, state)


@throttled
async def handle_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    bot_secrets: BotSecrets = context.application.bot_data["bot_secrets"]
    user_id = update.effective_user.id
    state = app_ctx.state.get(user_id)
    if not state:
        await update.message.reply_text("در حال حاضر منتظر دریافت تصویر از شما نبودیم.")
        return

    if isinstance(state, dict) and state.get("action") == "send_charge_receipt":
        amount = state.get("amount", 0)
        idem_key = f"charge:{user_id}:{update.message.message_id}"
        photo = update.message.photo[-1]
        with app_ctx.unit_of_work() as uow:
            if orders_service.find_active_duplicate_receipt(uow, photo.file_unique_id):
                dup = True
            else:
                dup = False
                req_id = orders_service.create_pending_request(
                    uow, "charge", user_id, amount_minor=amount, currency="TOMAN",
                    idempotency_key=idem_key,
                )
                orders_service.register_receipt(uow, req_id, photo.file_id, photo.file_unique_id)
        if dup:
            await update.message.reply_text("⚠️ این رسید قبلاً ثبت شده است و نمی‌تواند دوباره ارسال شود.")
            return
        await update.message.reply_text("🧾 تصویر فیش دریافت شد و در صف بررسی قرار گرفت.")
        markup = get_receipt_management_keyboard(req_id, "charge")
        await context.bot.send_photo(
            bot_secrets.owner_id, update.message.photo[-1].file_id,
            caption=f"💳 درخواست تایید واریزی\n\nکاربر: {user_id}\n\nمبلغ: {amount:,} تومان", reply_markup=markup,
        )
        app_ctx.state.clear(user_id)

    elif isinstance(state, dict) and state.get("action") == "direct_buy_receipt":
        prod_id = state.get("product_id")
        coupon_code = state.get("coupon")
        idem_key = f"buy:{user_id}:{update.message.message_id}"
        photo = update.message.photo[-1]
        try:
            with app_ctx.unit_of_work() as uow:
                if orders_service.find_active_duplicate_receipt(uow, photo.file_unique_id):
                    dup = True
                else:
                    dup = False
                    expected = None
                    if coupon_code:
                        product = uow.products.get(prod_id)
                        expected = orders_service.quote(
                            uow, user_id, product, coupon_code, count_pending=True).final_minor
                    req_id = orders_service.create_pending_request(
                        uow, "buy", user_id, product_id=prod_id, idempotency_key=idem_key,
                    )
                    orders_service.register_receipt(uow, req_id, photo.file_id, photo.file_unique_id)
                    if coupon_code:
                        uow.pending_requests.set_coupon(req_id, coupon_code, expected)
        except CouponError as exc:
            app_ctx.state.clear(user_id)
            await update.message.reply_text(f"⚠️ {exc}\nرسید ثبت نشد؛ از ابتدا خرید را انجام دهید.")
            return
        if dup:
            await update.message.reply_text("⚠️ این رسید قبلاً ثبت شده است و نمی‌تواند دوباره ارسال شود.")
            return
        await update.message.reply_text("🧾 تصویر فیش خرید دریافت شد و پس از تایید سرویس صادر می‌شود.")
        markup = get_receipt_management_keyboard(req_id, "buy")
        await context.bot.send_photo(
            bot_secrets.owner_id, update.message.photo[-1].file_id,
            caption=f"🛒 فیش خرید مستقیم\n\nکاربر: {user_id}\n\nکد محصول: {prod_id}"
                    + (f"\n\n🎟 کوپن: {coupon_code}" if coupon_code else ""), reply_markup=markup,
        )
        app_ctx.state.clear(user_id)
    else:
        await update.message.reply_text("در این مرحله نیازی به ارسال تصویر نیست.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("خطای پیش‌بینی‌نشده در پردازش آپدیت", exc_info=context.error)


# --------------------------------------------------------------------------
# اجرای اصلی
# --------------------------------------------------------------------------

def build_application() -> Application:
    bot_secrets = BotSecrets(secret_provider)
    app_ctx = build_app_context(bot_secrets)

    from adapters.telegram_bot import maintenance
    app = (Application.builder().token(bot_secrets.bot_token)
           .post_init(maintenance.start).post_shutdown(maintenance.stop).build())
    app.bot_data["app_ctx"] = app_ctx
    app.bot_data["bot_secrets"] = bot_secrets

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photos))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_documents))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    from security.env_file import load_env_file
    from security.logging_setup import setup_logging
    load_env_file()
    global RATE_LIMITER
    RATE_LIMITER = RateLimiter.from_env()  # ساختِ import-time قبل از بارگذاری .env بود
    setup_logging()
    app = build_application()
    logger.info("✅ ربات آماده به کار است.")
    app.run_polling()


if __name__ == "__main__":
    main()
