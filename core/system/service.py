"""
System Health & Backup — SQLite VACUUM INTO برای Backup اتمیک بدون قفل کردن
DB زندهٔ ربات؛ مقصد فعلاً فقط Local (`GHIYAB_BACKUP_DIR`) است — مقصد ابری هنوز
NEED-INFO (TODO #10) و اینجا حدس زده نشده.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac


def health(uow_factory, actor_id: int) -> dict:
    """RBAC/خواندن DB در تراکنش کوتاه؛ تماس شبکه با Provider بیرون از تراکنش SQLite."""
    with uow_factory() as uow:
        rbac.require(uow, actor_id, "system.health")
        pending = uow.pending_requests.count_pending()
        services = uow.provisioning.count_by_status()
    from core.provisioning import service as provisioning_service
    try:
        xui = provisioning_service.provider_health("3x-ui")
    except Exception:  # سلامت‌سنجی هرگز نباید پنل ادمین را بشکند
        xui = {"status": "BLOCKED", "detail": "health_check_error"}
    return {
        "db": "OK",
        "xui": xui,
        "services": services,
        "pending_requests": pending,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def create_backup(uow: UnitOfWork, actor_id: int, db_path: str, backup_dir: str) -> str:
    rbac.require(uow, actor_id, "backup.create")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"ghyiab_backup_{ts}.db")
    # VACUUM INTO یک snapshot سازگار می‌سازد حتی اگر DB زندهٔ ربات همزمان در حال نوشتن باشد
    src = sqlite3.connect(db_path)
    try:
        src.execute("VACUUM INTO ?", (dest,))
    finally:
        src.close()
    from core.settings import service as settings_service
    retention = settings_service.get_int(uow, "backup_retention_count")
    if retention > 0:
        _apply_retention(backup_dir, retention)
    audit_service.record(uow, actor_id=actor_id, action="backup.create", entity_type="system",
                         entity_id="db", after={"file": os.path.basename(dest)})
    return dest


def _apply_retention(backup_dir: str, keep: int) -> None:
    files = sorted(
        (f for f in os.listdir(backup_dir) if f.startswith("ghyiab_backup_") and f.endswith(".db")),
        reverse=True,
    )
    for stale in files[keep:]:
        try:
            os.remove(os.path.join(backup_dir, stale))
        except OSError:
            pass


def require_download_permission(uow: UnitOfWork, actor_id: int) -> None:
    rbac.require(uow, actor_id, "backup.download")


def dashboard(uow: UnitOfWork, actor_id: int) -> dict:
    rbac.require(uow, actor_id, "dashboard.view")
    d = uow.reports.dashboard()
    d["revenue"] = uow.reports.revenue()
    return d


# --------------------------------------------------------------------------
# Backup: تأیید، بازیابی، Backup روزانهٔ سبک (فایل‌محور، بدون زیرساخت اضافه)
# --------------------------------------------------------------------------

_REQUIRED_TABLES = ("users", "wallets", "wallet_transactions", "orders", "audit_logs", "settings")


def verify_backup(path: str) -> dict:
    """بررسی واقعی فایل: integrity_check + وجود جدول‌های حیاتی. هرگز فرض سالم بودن نمی‌کند."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return {"ok": False, "reason": "missing_or_empty"}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"ok": False, "reason": "cannot_open"}
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            return {"ok": False, "reason": "integrity_check_failed"}
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in _REQUIRED_TABLES if t not in have]
        if missing:
            return {"ok": False, "reason": "missing_tables", "tables": missing}
        return {"ok": True, "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]}
    except sqlite3.Error:
        return {"ok": False, "reason": "query_failed"}
    finally:
        conn.close()


def restore_backup(backup_path: str, db_path: str) -> str:
    """
    رویهٔ بازیابی (آفلاین — ربات باید متوقف باشد، نگاه کنید BACKUP.md): ابتدا Backup را
    تأیید می‌کند، DB فعلی را به ``<db>.pre-restore-<ts>`` کنار می‌گذارد، سپس جایگزین اتمیک
    (os.replace) انجام می‌دهد. خروجی: مسیر نسخهٔ کنار گذاشته‌شده.
    """
    import shutil
    check = verify_backup(backup_path)
    if not check["ok"]:
        raise ValueError(f"Backup معتبر نیست: {check['reason']}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    aside = f"{db_path}.pre-restore-{ts}"
    if os.path.exists(db_path):
        shutil.copy2(db_path, aside)
    tmp = f"{db_path}.restore-tmp"
    shutil.copy2(backup_path, tmp)
    for ext in ("-wal", "-shm"):  # فایل‌های WAL قدیمی نباید روی DB بازیابی‌شده اعمال شوند
        try:
            os.remove(db_path + ext)
        except OSError:
            pass
    os.replace(tmp, db_path)
    return aside


def latest_backup_age_hours(backup_dir: str):
    try:
        files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
                 if f.startswith("ghyiab_backup_") and f.endswith(".db")]
    except OSError:
        return None
    if not files:
        return None
    newest = max(os.path.getmtime(f) for f in files)
    return (datetime.now(timezone.utc).timestamp() - newest) / 3600


def daily_backup_if_due(uow_factory, owner_id: int, db_path: str, backup_dir: str, *, every_hours: float = 24):
    """اگر Backup روزانه روشن و سررسید است می‌سازد و بلافاصله تأیید می‌کند؛ مسیر یا None."""
    from core.settings import service as settings_service
    with uow_factory() as uow:
        if not settings_service.get_bool(uow, "backup_daily_enabled"):
            return None
    age = latest_backup_age_hours(backup_dir)
    if age is not None and age < every_hours:
        return None
    with uow_factory() as uow:
        dest = create_backup(uow, owner_id, db_path, backup_dir)
    check = verify_backup(dest)
    with uow_factory() as uow:
        audit_service.record(uow, actor_id=owner_id, action="backup.verify", entity_type="system",
                             entity_id="db", after={"file": os.path.basename(dest), **check})
    if not check["ok"]:
        raise RuntimeError(f"Backup ساخته شد اما تأیید نشد: {check['reason']}")
    return dest
