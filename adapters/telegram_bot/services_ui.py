"""
GhYiAb V2 — «سرویس‌های من» (Adapter تلگرام؛ بدون منطق کسب‌وکار)

تمام تصمیم‌ها (وضعیت، قیمت، تمدید، Idempotency) در core است؛ اینجا فقط رندر و
مسیریابی Callback با اعتبارسنجی سخت‌گیرانهٔ الگو (`svc:<action>:<order_id>`).
تماس‌های شبکه‌ای (Provider) با ``asyncio.to_thread`` اجرا می‌شوند تا Event loop ربات
قفل نشود. هیچ استثنای داخلی/توکنی به کاربر نشان داده نمی‌شود.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bootstrap import AppContext
from core.errors import (
    ConflictError, DomainError, InsufficientBalanceError, NotFoundError, ProviderNotReadyError,
    ProvisioningFailedError, ValidationError,
)
from core.orders import service as orders_service
from core.provisioning import service as prov
from core.vpn_services import service as svc
from shared.i18n import t
from adapters.telegram_bot.util import esc

logger = logging.getLogger("ghyiab.bot.services")

CB_RE = re.compile(r"^svc:(v|l|r|rc|ar|g|x):(\d{1,12})$")
GB = 1024 ** 3


def is_service_callback(data: str) -> bool:
    return isinstance(data, str) and data.startswith("svc:")


def parse_callback(data: str) -> Optional[tuple[str, int]]:
    m = CB_RE.match(data or "")
    return (m.group(1), int(m.group(2))) if m else None


# ---------------- فرمت‌دهی (توابع خالص، قابل تست) ----------------

def fmt_bytes(n: Optional[int], lang: str) -> str:
    if n is None or n <= 0:
        return t("svc.unlimited", lang)
    if n >= GB:
        return f"{n / GB:.2f} GB"
    return f"{n / (1024 ** 2):.0f} MB"


def fmt_used(n: int) -> str:
    return f"{n / GB:.2f} GB" if n >= GB else f"{n / (1024 ** 2):.0f} MB"


def fmt_expiry(ms: int, lang: str) -> str:
    if ms <= 0:
        return t("svc.no_expiry", lang)
    date = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    days = max(0, int((ms / 1000 - datetime.now(timezone.utc).timestamp()) // 86400))
    return f"{date} ({t('svc.days_left', lang, days=days)})"


def render_view(v: svc.ServiceView, lang: str) -> str:
    text = t("svc.detail", lang, name=esc(v.product_name), state=t(f"svc.state.{v.state}", lang),
             used=fmt_used(v.used_bytes), total=fmt_bytes(v.total_bytes, lang),
             expiry=fmt_expiry(v.expires_at_ms, lang),
             auto=t("svc.on" if v.auto_renew else "svc.off", lang))
    if not v.live and v.state in ("ACTIVE", "EXPIRED", "SUSPENDED"):
        text += t("svc.stale", lang)
    return text


def keyboard_for(v: svc.ServiceView, lang: str, auto_feature: bool) -> InlineKeyboardMarkup:
    oid = v.order_id
    rows = []
    if v.state in ("ACTIVE", "EXPIRED", "SUSPENDED"):
        rows.append([InlineKeyboardButton(t("svc.btn.links", lang), callback_data=f"svc:l:{oid}"),
                     InlineKeyboardButton(t("svc.btn.renew", lang), callback_data=f"svc:r:{oid}")])
        if auto_feature or v.auto_renew:
            rows.append([InlineKeyboardButton(
                t("svc.btn.auto_off" if v.auto_renew else "svc.btn.auto_on", lang), callback_data=f"svc:ar:{oid}")])
    rows.append([InlineKeyboardButton(t("svc.btn.refresh", lang), callback_data=f"svc:v:{oid}"),
                 InlineKeyboardButton(t("svc.btn.guide", lang), callback_data=f"svc:g:{oid}")])
    return InlineKeyboardMarkup(rows)


def qr_png(text: str) -> Optional[bytes]:
    """QR اختیاری (کتابخانهٔ کوچک و خالص-پایتون segno). نبودنش فقط QR را حذف می‌کند، نه لینک را."""
    try:
        import segno
    except ImportError:
        return None
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=6, border=2)
    return buf.getvalue()


# ---------------- ورودی‌ها ----------------

def _lang(app_ctx: AppContext, user_id: int) -> str:
    with app_ctx.unit_of_work() as uow:
        return uow.users.get_lang(user_id)


async def show_my_services(app_ctx: AppContext, message, user_id: int) -> None:
    lang = _lang(app_ctx, user_id)
    with app_ctx.unit_of_work() as uow:
        views = svc.list_user_services(uow, user_id)
        provisioned = {v.order_id for v in views}
        legacy = [o for o in uow.orders.list_by_user(user_id)
                  if o.id not in provisioned and o.inventory_item_id != prov.NO_INVENTORY]
        legacy_names = {o.id: (uow.products.get(o.product_id).name if uow.products.get(o.product_id) else "?")
                        for o in legacy}
    if not views and not legacy:
        await message.reply_text(t("svc.none", lang))
        return
    rows = [[InlineKeyboardButton(f"{t(f'svc.state.{v.state}', lang)[:2]} {v.product_name}",
                                  callback_data=f"svc:v:{v.order_id}")] for v in views[:20]]
    rows += [[InlineKeyboardButton(f"📦 {legacy_names[o.id]}", callback_data=f"view_order_{o.id}")]
             for o in legacy[:20]]
    await message.reply_text(t("svc.list_title", lang), reply_markup=InlineKeyboardMarkup(rows))


async def _show_view(query, app_ctx: AppContext, user_id: int, order_id: int, *, live: bool = True) -> None:
    lang = _lang(app_ctx, user_id)
    view = await asyncio.to_thread(svc.get_service_view, app_ctx.unit_of_work, user_id, order_id, live=live)
    with app_ctx.unit_of_work() as uow:
        from core.settings import service as settings_service
        auto_feature = settings_service.get_bool(uow, "auto_renewal_enabled")
    try:
        await query.edit_message_text(render_view(view, lang), parse_mode="HTML",
                                      reply_markup=keyboard_for(view, lang, auto_feature))
    except TelegramError as exc:  # «message is not modified» و مشابه آن بی‌ضرر است
        logger.debug("edit skipped: %s", exc)


async def handle_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app_ctx: AppContext = context.application.bot_data["app_ctx"]
    query = update.callback_query
    user_id = query.from_user.id
    lang = _lang(app_ctx, user_id)
    parsed = parse_callback(query.data)
    if parsed is None:
        await query.answer(t("svc.invalid", lang), show_alert=True)
        return
    action, order_id = parsed
    try:
        if action in ("v", "x"):
            await _show_view(query, app_ctx, user_id, order_id)
        elif action == "g":
            await query.answer(t("svc.guide", lang), show_alert=True)
        elif action == "l":
            await _send_links(query, context, app_ctx, user_id, order_id, lang)
        elif action == "r":
            await _renew_summary(query, app_ctx, user_id, order_id, lang)
        elif action == "rc":
            await _renew_confirm(query, context, app_ctx, user_id, order_id, lang)
        elif action == "ar":
            await _toggle_auto(query, app_ctx, user_id, order_id, lang)
    except NotFoundError:
        await query.answer(t("svc.invalid", lang), show_alert=True)
    except InsufficientBalanceError:
        await query.answer(t("svc.insufficient", lang), show_alert=True)
    except ProviderNotReadyError:
        await query.answer(t("svc.not_ready", lang), show_alert=True)
    except (ProvisioningFailedError, ConflictError, ValidationError) as exc:
        # Conflict/Validation پیام‌های دامنه‌ای امن و فارسی دارند؛ خطای Provider عمومی می‌شود
        msg = str(exc) if isinstance(exc, (ConflictError, ValidationError)) else t("svc.error", lang)
        await query.answer(msg[:190], show_alert=True)
    except DomainError:
        await query.answer(t("svc.error", lang), show_alert=True)
    except Exception:
        logger.exception("service callback failed (action=%s order=%s)", action, order_id)
        await query.answer(t("svc.error", lang), show_alert=True)
    else:
        try:
            await query.answer()
        except TelegramError:
            pass


async def _send_links(query, context, app_ctx, user_id, order_id, lang) -> None:
    info = await asyncio.to_thread(svc.get_connection_info, app_ctx.unit_of_work, user_id, order_id)
    links = info["links"]
    sub = info["subscription_url"]
    body = "\n".join(f"<code>{esc(l)}</code>" for l in links[:5]) or t("svc.links_none", lang)
    text = t("svc.links_title", lang, sub=esc(sub or "—"), links=body)
    await context.bot.send_message(query.message.chat_id, text[:3900], parse_mode="HTML")
    target = sub or (links[0] if links else None)
    if target:
        png = await asyncio.to_thread(qr_png, target)
        if png:
            await context.bot.send_photo(query.message.chat_id, png, caption="QR")


async def _renew_summary(query, app_ctx, user_id, order_id, lang) -> None:
    with app_ctx.unit_of_work() as uow:
        rec, order = svc._load_owned(uow, user_id, order_id)
        product = uow.products.get(order.product_id)
        profile = prov.active_profile(uow, order.product_id)
        if product is None or profile is None or profile.duration_days <= 0:
            raise ValidationError(t("svc.not_ready", lang))
        price = orders_service.price_for_user(uow, user_id, product)  # همان تابعی که واقعاً کسر می‌کند
        balance = uow.wallet.get_balance(user_id, product.currency)
    text = t("svc.renew_summary", lang, name=esc(product.name), price=f"{price:,}", days=profile.duration_days,
             traffic=fmt_bytes(int(profile.traffic_gb * GB), lang), balance=f"{balance:,}")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t("svc.btn.confirm", lang), callback_data=f"svc:rc:{order_id}"),
                                InlineKeyboardButton(t("svc.btn.cancel", lang), callback_data=f"svc:x:{order_id}")]])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def _renew_confirm(query, context, app_ctx, user_id, order_id, lang) -> None:
    # کلید Idempotency = همین پیام تأیید: تپ دوباره روی همان دکمه هرگز دوبار کسر نمی‌کند.
    key = f"m:{user_id}:{order_id}:{query.message.message_id}"
    res = await asyncio.to_thread(svc.renew_service, app_ctx.unit_of_work, user_id, order_id,
                                  idempotency_key=key, source="manual")
    if res.status == "COMPLETED":
        text = t("svc.renew_ok", lang, expiry=fmt_expiry(res.new_expiry_ms, lang))
    elif res.status == "PENDING":
        text = t("svc.renew_pending", lang)
    else:
        text = t("svc.renew_refunded", lang)
    back = InlineKeyboardMarkup([[InlineKeyboardButton(t("svc.btn.back", lang), callback_data=f"svc:v:{order_id}")]])
    await query.edit_message_text(text, reply_markup=back)


async def _toggle_auto(query, app_ctx, user_id, order_id, lang) -> None:
    with app_ctx.unit_of_work() as uow:
        rec, _ = svc._load_owned(uow, user_id, order_id)
        new = not rec.auto_renew
        svc.set_auto_renew(uow, user_id, order_id, new)
    await query.answer(t("svc.auto_enabled" if new else "svc.auto_disabled", lang), show_alert=True)
    await _show_view(query, app_ctx, user_id, order_id, live=False)


# ---------------- تحویل سرویس بعد از صدور ----------------

async def deliver_ready(bot, app_ctx: AppContext, user_id: int, order_id: int) -> None:
    """بعد از صدور موفق: خلاصهٔ سرویس + لینک‌ها (+QR). خطای تحویل هرگز صدور را باطل نمی‌کند."""
    from adapters.telegram_bot.bot import safe_send
    lang = _lang(app_ctx, user_id)
    try:
        view = await asyncio.to_thread(svc.get_service_view, app_ctx.unit_of_work, user_id, order_id, live=False)
        await safe_send(app_ctx, bot, user_id,
                        t("svc.ready", lang, name=esc(view.product_name),
                          expiry=fmt_expiry(view.expires_at_ms, lang),
                          total=fmt_bytes(view.total_bytes, lang)), parse_mode="HTML")
        info = await asyncio.to_thread(svc.get_connection_info, app_ctx.unit_of_work, user_id, order_id)
        links, sub = info["links"], info["subscription_url"]
        body = "\n".join(f"<code>{esc(l)}</code>" for l in links[:5]) or t("svc.links_none", lang)
        await safe_send(app_ctx, bot, user_id,
                        t("svc.links_title", lang, sub=esc(sub or "—"), links=body)[:3900],
                        parse_mode="HTML")
        target = sub or (links[0] if links else None)
        png = await asyncio.to_thread(qr_png, target) if target else None
        if png:
            await bot.send_photo(user_id, png, caption="QR")
    except Exception:
        logger.exception("deliver_ready failed (order=%s)", order_id)


async def provision_and_deliver(bot, app_ctx: AppContext, user_id: int, order_id: int,
                                notify_admin=None) -> str:
    """بعد از خرید Provider-backed: صدور واقعی → تحویل. خروجی: READY | WAIT."""
    lang = _lang(app_ctx, user_id)
    try:
        await asyncio.to_thread(prov.provision_order, app_ctx.unit_of_work, order_id)
    except (ProviderNotReadyError, ProvisioningFailedError) as exc:
        logger.warning("provisioning deferred for order %s: %s", order_id, type(exc).__name__)
        from adapters.telegram_bot.bot import safe_send
        await safe_send(app_ctx, bot, user_id, t("svc.provisioning_wait", lang))
        if notify_admin:
            await notify_admin(f"⚠️ سفارش #{order_id} پرداخت شد ولی صدور سرویس انجام نشد ({type(exc).__name__}). "
                               "Retry خودکار فعال است؛ در صورت تداوم از پنل ادمین رسیدگی کنید.")
        return "WAIT"
    await deliver_ready(bot, app_ctx, user_id, order_id)
    return "READY"
