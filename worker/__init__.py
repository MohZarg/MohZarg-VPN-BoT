"""
GhYiAb V2 — Background Worker
=============================

این ماژول وظایف پس‌زمینه (background jobs) را اجرا می‌کند:
- بررسی سلامت پنل‌ها (Panel Health Check)
- تمدید خودکار سرویس‌ها
- پردازش پرداخت‌های در انتظار
- همگام‌سازی کلاینت‌های provisioend
- بررسی فاکتورهای کریپتو
- ارسال اعلان‌های انقضا
- پشتیبان‌گیری دیتابیس
- پاکسازی لاگ‌های قدیمی

این ماژول به عنوان یک سرویس جداگانه در Docker Compose و Railway اجرا می‌شود.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bootstrap import build_app_context, AppContext
from security.secret_loader import BotSecrets, secrets as secret_provider
from core.scheduled_jobs import service as scheduled_jobs_service
from core.scheduled_jobs.handlers import (
    panel_health_check,
    auto_renew_services,
    process_pending_payments,
    sync_provisioned_clients,
    check_crypto_invoices,
    send_expiry_notifications,
    backup_database,
    cleanup_old_logs,
)
from core.provider_failover import service as failover_service

logger = logging.getLogger("ghyiab.worker")


class Worker:
    """مدیر وظایف پس‌زمینه."""

    def __init__(self, app_ctx: AppContext):
        self.app_ctx = app_ctx
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._running = False

    def setup_jobs(self) -> None:
        """تنظیم وظایف زمان‌بندی شده از دیتابیس."""
        with self.app_ctx.unit_of_work() as uow:
            jobs = scheduled_jobs_service.list_jobs(uow, enabled_only=True)

        for job in jobs:
            try:
                if job.cron_expression:
                    trigger = CronTrigger.from_crontab(job.cron_expression, timezone="UTC")
                elif job.fire_at:
                    # برای one-shot jobs از date trigger استفاده می‌شود
                    # در اینجا از interval با یک بار اجرا استفاده می‌کنیم
                    # چون APScheduler date trigger را در اینجا به درستی مدیریت نمی‌کند
                    trigger = IntervalTrigger(seconds=86400, start_date=job.fire_at)
                else:
                    continue

                self.scheduler.add_job(
                    self._run_job,
                    trigger,
                    args=[job.name, job.handler, job.payload],
                    id=job.name,
                    name=job.name,
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )
                logger.info("Scheduled job registered: %s (%s)", job.name, job.cron_expression or job.fire_at)
            except Exception as e:
                logger.error("Failed to schedule job %s: %s", job.name, e)

    async def _run_job(self, job_name: str, handler_name: str, payload: dict) -> None:
        """اجرای یک جاب و ثبت نتیجه."""
        logger.info("Running job: %s", job_name)
        start_time = datetime.utcnow()
        status = "failed"
        detail = ""
        error = None

        try:
            # اجرای هندلر
            handler_func = self._get_handler(handler_name)
            if handler_func:
                result = await handler_func(self.app_ctx, payload)
                status = "succeeded"
                detail = str(result) if result else "Completed successfully"
            else:
                error = f"Handler not found: {handler_name}"
        except Exception as e:
            error = str(e)
            logger.exception("Job %s failed", job_name)

        # ثبت نتیجه در دیتابیس
        with self.app_ctx.unit_of_work() as uow:
            scheduled_jobs_service.record_run(
                uow,
                job_name=job_name,
                status=status,
                detail=detail,
                error=error,
            )

        logger.info("Job %s finished: %s", job_name, status)

    def _get_handler(self, handler_name: str):
        """دریافت تابع هندلر بر اساس نام."""
        handlers = {
            "panel_health_check": panel_health_check,
            "auto_renew_services": auto_renew_services,
            "process_pending_payments": process_pending_payments,
            "sync_provisioned_clients": sync_provisioned_clients,
            "check_crypto_invoices": check_crypto_invoices,
            "send_expiry_notifications": send_expiry_notifications,
            "backup_database": backup_database,
            "cleanup_old_logs": cleanup_old_logs,
            "provider_failover_check": failover_service.check_and_failover,
        }
        return handlers.get(handler_name)

    async def start(self) -> None:
        """شروعcheduler."""
        if self._running:
            return

        self.setup_jobs()
        self.scheduler.start()
        self._running = True
        logger.info("Worker started with %d jobs", len(self.scheduler.get_jobs()))

    async def stop(self) -> None:
        """توقفcheduler."""
        if not self._running:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("Worker stopped")


async def run_worker() -> None:
    """نقطه ورود اصلی worker."""
    # بارگذاری متغیرهای محیطی
    from security.env_file import load_env_file
    from security.logging_setup import setup_logging
    load_env_file()
    setup_logging()

    # ساخت context
    bot_secrets = BotSecrets(secret_provider)
    app_ctx = build_app_context(bot_secrets)

    # ایجاد و اجرای worker
    worker = Worker(app_ctx)

    # مدیریت سیگنال‌ها برای خاموش شدن تمیز
    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    await worker.start()

    # نگه داشتن worker در حال اجرا
    try:
        while worker._running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await worker.stop()


def main() -> None:
    """Entry point برای اجرا مستقیم."""
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker interrupted")
    except Exception as e:
        logger.exception("Worker failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()