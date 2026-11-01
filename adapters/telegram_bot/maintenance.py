"""
GhYiAb V2 — حلقهٔ نگهداری (یک Task واحد، بدون وابستگی اضافه مثل APScheduler/Redis/n8n)
===================================================================================

توسعه‌دهنده: MohZarg — https://github.com/MohZarg
حمایت مالی: https://github.com/MohZarg

هر ``GHIYAB_MAINTENANCE_INTERVAL`` ثانیه (پیش‌فرض ۳۰۰، حداقل ۶۰) به‌صورت *ترتیبی* اجرا می‌شود:
  1. بازیابی تمدیدهای نیمه‌کاره (CHARGED) — پس از ری‌استارت/خطای مبهم
  2. Retry صدور سرویس‌های معوق (محدود به provision_max_attempts) + تحویل به کاربر
  3. تمدید خودکار (Opt-in)    4. یادآوری انقضا (یک‌بار برای هر انقضا)
  5. علامت‌گذاری EXPIRED       6. پاک‌سازی حالت/تأییدیه‌های قدیمی + انقضای درخواست‌های معلق
  7. Backup روزانه + تأیید فوری

مصرف: وقتی کاری سررسید نیست فقط چند کوئری سبک SQLite؛ هیچ تماس شبکه‌ای نمی‌شود مگر کاری
واقعاً وجود داشته باشد. خطای هر مرحله لاگ می‌شود و بقیه مراحل ادامه می‌یابند.
"""

from __future__ import annotations

import asyncio
import logging
import os

from bootstrap import AppContext
from core.provisioning import service as prov
from core.settings import service as settings_service
from core.system import service as system_service
from core.vpn_services import service as svc
from shared.i18n import t
from adapters.telegram_bot.util import esc

logger = logging.getLogger("ghyiab.maintenance")

_TASK_KEY = "maintenance_task"


def interval_seconds() -> int:
    try:
        return max(60, int(os.getenv("GHIYAB_MAINTENANCE_INTERVAL", "300")))
    except ValueError:
        return 300


def _name(app_ctx: AppContext, order_id: int) -> tuple[str, str]:
    with app_ctx.unit_of_work() as uow:
        order = uow.orders.get_by_id(order_id)
        product = uow.products.get(order.product_id) if order else None
        lang = uow.users.get_lang(order.user_id) if order else "fa"
    return (product.name if product else f"#{order_id}"), lang


async def _notify(app_ctx: AppContext, bot, user_id: int, text: str) -> None:
    from adapters.telegram_bot.bot import safe_send
    await safe_send(app_ctx, bot, user_id, text, parse_mode="HTML")


async def run_once(app_ctx: AppContext, bot) -> dict:
    """یک دور کامل؛ جدا از حلقه تا تست‌پذیر باشد. خروجی: خلاصهٔ شمارش‌ها."""
    from adapters.telegram_bot import services_ui
    uowf = app_ctx.unit_of_work
    report: dict = {}

    async def step(name, fn, *a):
        try:
            report[name] = await asyncio.to_thread(fn, *a)
            return report[name]
        except Exception:
            logger.exception("maintenance step failed: %s", name)
            report[name] = "error"
            return None

    await step("recover_renewals", svc.recover_stuck_renewals, uowf)

    # Retry صدور؛ سفارش‌هایی که همین دور ACTIVE شدند به کاربر تحویل داده می‌شوند
    with uowf() as uow:
        before = {r.order_id for st in ("PENDING", "FAILED") for r in uow.provisioning.list_clients(st)}
    await step("retry_provisioning", prov.retry_pending, uowf)
    with uowf() as uow:
        now_active = []
        for oid in before:
            rec = uow.provisioning.get_client_by_order(oid)
            if rec is not None and rec.status == "ACTIVE":
                now_active.append(oid)
        owners = {oid: uow.orders.get_by_id(oid).user_id for oid in now_active}
    for oid in now_active:
        await services_ui.deliver_ready(bot, app_ctx, owners[oid], oid)

    events = await step("auto_renew", svc.run_auto_renewals, uowf) or []
    for ev in events:
        key = {"renewed": "svc.notify.renewed", "insufficient_balance": "svc.notify.insufficient",
               "failed_refunded": "svc.notify.failed"}.get(ev["outcome"])
        if key:
            name, lang = _name(app_ctx, ev["order_id"])
            await _notify(app_ctx, bot, ev["user_id"], t(key, lang, name=esc(name)))

    for ev in (await step("reminders", svc.expiry_reminders, uowf) or []):
        name, lang = _name(app_ctx, ev["order_id"])
        days = max(0, int((ev["expires_at_ms"] - svc.now_ms()) // svc.DAY_MS))
        await _notify(app_ctx, bot, ev["user_id"], t("svc.notify.expiring", lang, name=esc(name), days=days))

    await step("mark_expired", svc.mark_expired, uowf)

    def _pending_rewards():
        with uowf() as uow:
            return list(uow.referrals.list_unnotified())
    for rid, referrer, amount in (await step("referral_rewards", _pending_rewards) or []):
        await _notify(app_ctx, bot, referrer,
                      f"🎁 <b>پاداش دعوت</b>\n\nیکی از دعوت‌شده‌های شما اولین خریدش را انجام داد؛ "
                      f"{amount:,} تومان به کیف پول شما افزوده شد.")
        with uowf() as uow:
            uow.referrals.mark_notified(rid)

    def _gc():
        n_state = app_ctx.state.purge_stale(24)
        with uowf() as uow:
            n_conf = uow.confirmations.purge_expired()
            hours = settings_service.get_int(uow, "pending_expiry_hours")
            n_pend = uow.pending_requests.expire_older_than(hours) if hours > 0 else 0
        return {"state": n_state, "confirmations": n_conf, "pending": n_pend}
    await step("gc", _gc)

    backup_dir = os.getenv("GHIYAB_BACKUP_DIR", "backups")
    await step("backup", system_service.daily_backup_if_due, uowf, app_ctx.owner_id, app_ctx.db_path, backup_dir)
    return report


async def _loop(app_ctx: AppContext, bot) -> None:
    await asyncio.sleep(5)  # بعد از بالا آمدن polling
    while True:
        try:
            await run_once(app_ctx, bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("maintenance loop iteration failed")
        await asyncio.sleep(interval_seconds())


async def start(application) -> None:
    app_ctx: AppContext = application.bot_data["app_ctx"]
    application.bot_data[_TASK_KEY] = asyncio.create_task(_loop(app_ctx, application.bot), name="ghyiab-maintenance")
    logger.info("maintenance loop started (every %ss)", interval_seconds())


async def stop(application) -> None:
    task = application.bot_data.get(_TASK_KEY)
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
