"""
Background Jobs — تعریف/فعال‌سازی توسط ادمین (jobs.manage)، اجرا توسط یک
اسکجولر بیرونی (n8n یا cron واقعی طبق معماری V2: تصمیم کسب‌وکاری همیشه در
core می‌ماند). هیچ Job ای در این فاز خودکار اجرا نمی‌شود مگر ادمین صریحاً
دکمهٔ «اجرای اکنون» را بزند یا اسکجولر بیرونی (خارج از این کد) آن را فراخوانی
کند — این فایل خودش Thread/Timer راه‌اندازی نمی‌کند.
"""

from __future__ import annotations

from repository.interface import UnitOfWork
from core.auth import rbac
from core.errors import NotFoundError

KNOWN_JOBS = {
    "expire_pending_requests": 60,
    "auto_renewal_scan": 1440,
    "referral_daily_reset_probe": 1440,
    "confirmations_gc": 1440,
}


def ensure_defaults(uow: UnitOfWork) -> None:
    for name, interval in KNOWN_JOBS.items():
        uow.jobs.ensure(name, interval)


def list_jobs(uow: UnitOfWork, actor_id: int):
    rbac.require(uow, actor_id, "jobs.view")
    ensure_defaults(uow)
    return uow.jobs.list_all()


def set_enabled(uow: UnitOfWork, actor_id: int, name: str, enabled: bool) -> None:
    rbac.require(uow, actor_id, "jobs.manage")
    if uow.jobs.get(name) is None:
        raise NotFoundError("Job ناشناس")
    uow.jobs.set_enabled(name, enabled)


def run_now(uow: UnitOfWork, actor_id: int, name: str) -> str:
    """اجرای دستی یک Job از پنل ادمین (jobs.manage). خروجی: خلاصهٔ نتیجه."""
    rbac.require(uow, actor_id, "jobs.manage")
    job = uow.jobs.get(name)
    if job is None:
        raise NotFoundError("Job ناشناس")
    if not job.enabled:
        return "غیرفعال است"
    if name == "expire_pending_requests":
        from core.settings import service as settings_service
        hours = settings_service.get_int(uow, "pending_expiry_hours")
        n = uow.pending_requests.expire_older_than(hours) if hours > 0 else 0
        detail = f"{n} درخواست منقضی شد" if hours > 0 else "غیرفعال (pending_expiry_hours=0)"
    elif name == "confirmations_gc":
        n = uow.confirmations.purge_expired()
        detail = f"{n} تأییدیهٔ منقضی پاک شد"
    elif name == "auto_renewal_scan":
        detail = "تمدید خودکار هنوز فعال نیست (auto_renewal_enabled=0 پیش‌فرض؛ TODO #8)"
    elif name == "referral_daily_reset_probe":
        detail = "سقف رفرال روزانه است و به‌صورت پویا محاسبه می‌شود؛ نیازی به ریست ندارد"
    else:
        detail = "پیاده‌سازی ندارد"
    uow.jobs.record_run(name, "OK", detail)
    return detail
