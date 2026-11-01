"""
GhYiAb V2 — Scheduled Jobs / Cron Service
==========================================

سیستم مدیریت Cron Jobها برای وظایف زمان‌بندی شده:
- مانیتورینگ سلامت پنل‌ها
- تمدید خودکار سرویس‌ها
- پردازش پرداخت‌های معوق
- بک‌آپ دیتابیس
- تمیزکاری لاگ‌ها
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from bootstrap import AppContext
from core.audit import service as audit_service

logger = logging.getLogger("ghyiab.core.scheduled_jobs")


class ScheduledJobError(Exception):
    pass


@dataclass(frozen=True)
class ScheduledJob:
    id: int
    name: str
    cron_expression: Optional[str]
    fire_at: Optional[str]
    handler: str
    payload: Optional[str]
    enabled: bool
    last_run_at: Optional[str]
    next_run_at: Optional[str]
    last_status: Optional[str]
    last_detail: Optional[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class JobRun:
    id: int
    job_id: int
    status: str
    started_at: str
    finished_at: Optional[str]
    detail: Optional[str]
    error: Optional[str]


# =============================================================================
# Built-in Job Handlers
# =============================================================================

def _import_handler(handler_path: str) -> Callable:
    """Import handler function from string path."""
    try:
        module_path, func_name = handler_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except (ImportError, AttributeError, ValueError) as e:
        raise ScheduledJobError(f"Cannot import handler {handler_path}: {e}")


# Built-in handlers (can be referenced by short names)
BUILTIN_HANDLERS = {
    "panel_health_check": "core.scheduled_jobs.handlers:panel_health_check",
    "auto_renew_services": "core.scheduled_jobs.handlers:auto_renew_services",
    "process_pending_payments": "core.scheduled_jobs.handlers:process_pending_payments",
    "backup_database": "core.scheduled_jobs.handlers:backup_database",
    "cleanup_old_logs": "core.scheduled_jobs.handlers:cleanup_old_logs",
    "sync_provisioned_clients": "core.scheduled_jobs.handlers:sync_provisioned_clients",
    "check_crypto_invoices": "core.scheduled_jobs.handlers:check_crypto_invoices",
    "send_expiry_notifications": "core.scheduled_jobs.handlers:send_expiry_notifications",
}


def resolve_handler(handler: str) -> Callable:
    """Resolve handler string to callable."""
    if handler in BUILTIN_HANDLERS:
        handler = BUILTIN_HANDLERS[handler]
    return _import_handler(handler)


# =============================================================================
# Job Management
# =============================================================================

def create_job(
    app_ctx: AppContext,
    actor_id: int,
    name: str,
    handler: str,
    cron_expression: Optional[str] = None,
    fire_at: Optional[str] = None,
    payload: Optional[dict] = None,
    enabled: bool = True
) -> ScheduledJob:
    """Create a new scheduled job."""
    if not cron_expression and not fire_at:
        raise ValueError("Either cron_expression or fire_at must be provided")
    if cron_expression and fire_at:
        raise ValueError("Cannot provide both cron_expression and fire_at")

    import json
    with app_ctx.unit_of_work() as uow:
        # Validate cron expression format (basic)
        if cron_expression:
            parts = cron_expression.split()
            if len(parts) != 5:
                raise ValueError("Cron expression must have 5 fields (minute hour day month weekday)")

        cursor = uow.conn.execute("""
            INSERT INTO scheduled_jobs
            (name, cron_expression, fire_at, handler, payload, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (name, cron_expression, fire_at, handler, json.dumps(payload) if payload else None, 1 if enabled else 0))
        job_id = cursor.lastrowid
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="scheduled_job_created",
            entity_type="scheduled_jobs", entity_id=str(job_id),
            after_json={"name": name, "handler": handler, "cron": cron_expression, "fire_at": fire_at}
        )

        return get_job(app_ctx, job_id)


def get_job(app_ctx: AppContext, job_id: int) -> ScheduledJob:
    """Get job by ID."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise ScheduledJobError(f"Job {job_id} not found")
        return _row_to_job(row)


def get_job_by_name(app_ctx: AppContext, name: str) -> Optional[ScheduledJob]:
    """Get job by name."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM scheduled_jobs WHERE name = ?", (name,)).fetchone()
        return _row_to_job(row) if row else None


def list_jobs(app_ctx: AppContext, enabled_only: bool = False) -> list[ScheduledJob]:
    """List all scheduled jobs."""
    with app_ctx.unit_of_work() as uow:
        if enabled_only:
            rows = uow.conn.execute("SELECT * FROM scheduled_jobs WHERE enabled = 1 ORDER BY name").fetchall()
        else:
            rows = uow.conn.execute("SELECT * FROM scheduled_jobs ORDER BY name").fetchall()
        return [_row_to_job(r) for r in rows]


def update_job(
    app_ctx: AppContext,
    actor_id: int,
    job_id: int,
    **kwargs
) -> ScheduledJob:
    """Update job fields."""
    allowed = {"cron_expression", "fire_at", "handler", "payload", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}

    if not updates:
        return get_job(app_ctx, job_id)

    import json
    with app_ctx.unit_of_work() as uow:
        # Build dynamic update
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())
        if "payload" in updates and updates["payload"] is not None:
            values[list(updates.keys()).index("payload")] = json.dumps(updates["payload"])
        values.append(job_id)

        uow.conn.execute(f"UPDATE scheduled_jobs SET {set_clause}, updated_at = datetime('now') WHERE id = ?", values)
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="scheduled_job_updated",
            entity_type="scheduled_jobs", entity_id=str(job_id),
            after_json=updates
        )

        return get_job(app_ctx, job_id)


def delete_job(app_ctx: AppContext, actor_id: int, job_id: int) -> None:
    """Delete a scheduled job."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT name FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise ScheduledJobError(f"Job {job_id} not found")

        uow.conn.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="scheduled_job_deleted",
            entity_type="scheduled_jobs", entity_id=str(job_id),
            before_json={"name": row[0]}
        )


def toggle_job(app_ctx: AppContext, actor_id: int, job_id: int, enabled: bool) -> ScheduledJob:
    """Enable/disable a job."""
    return update_job(app_ctx, actor_id, job_id, enabled=enabled)


# =============================================================================
# Job Execution
# =============================================================================

def run_job_now(app_ctx: AppContext, actor_id: int, job_id: int) -> JobRun:
    """Manually trigger a job run."""
    job = get_job(app_ctx, job_id)
    return _execute_job(app_ctx, job, actor_id=actor_id, manual=True)


def _execute_job(app_ctx: AppContext, job: ScheduledJob, actor_id: int = 0, manual: bool = False) -> JobRun:
    """Execute a job and record the run."""
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    with app_ctx.unit_of_work() as uow:
        # Create run record
        cursor = uow.conn.execute("""
            INSERT INTO job_runs (job_id, status, started_at, detail)
            VALUES (?, 'running', ?, ?)
        """, (job.id, started_at, "Manual run" if manual else "Scheduled run"))
        run_id = cursor.lastrowid
        uow.conn.commit()

    try:
        # Import and execute handler
        handler_func = resolve_handler(job.handler)
        payload = {}
        if job.payload:
            import json
            payload = json.loads(job.payload)

        # Execute handler with app_ctx and payload
        result = handler_func(app_ctx, **payload)

        finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        detail = str(result) if result else "Completed successfully"

        with app_ctx.unit_of_work() as uow:
            uow.conn.execute("""
                UPDATE job_runs SET status = 'succeeded', finished_at = ?, detail = ?
                WHERE id = ?
            """, (finished_at, detail, run_id))

            # Update job last run info
            uow.conn.execute("""
                UPDATE scheduled_jobs SET last_run_at = ?, last_status = 'succeeded', last_detail = ?
                WHERE id = ?
            """, (started_at, detail[:500], job.id))
            uow.conn.commit()

        return JobRun(id=run_id, job_id=job.id, status='succeeded', started_at=started_at, finished_at=finished_at, detail=detail, error=None)

    except Exception as e:
        finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        error_msg = str(e)
        logger.exception("Job %s failed: %s", job.name, e)

        with app_ctx.unit_of_work() as uow:
            uow.conn.execute("""
                UPDATE job_runs SET status = 'failed', finished_at = ?, detail = ?, error = ?
                WHERE id = ?
            """, (finished_at, "Job failed", error_msg, run_id))

            uow.conn.execute("""
                UPDATE scheduled_jobs SET last_run_at = ?, last_status = 'failed', last_detail = ?
                WHERE id = ?
            """, (started_at, error_msg[:500], job.id))
            uow.conn.commit()

        return JobRun(id=run_id, job_id=job.id, status='failed', started_at=started_at, finished_at=finished_at, detail="Job failed", error=error_msg)


def process_due_jobs(app_ctx: AppContext) -> list[JobRun]:
    """Process all due jobs (called by scheduler)."""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    results = []

    with app_ctx.unit_of_work() as uow:
        # Get jobs that are due (cron-based - simplified, real impl would use croniter)
        # For now, we'll check fire_at for one-time jobs
        rows = uow.conn.execute("""
            SELECT * FROM scheduled_jobs
            WHERE enabled = 1
            AND (fire_at IS NOT NULL AND fire_at <= ?)
        """, (now,)).fetchall()

        jobs_to_run = [_row_to_job(r) for r in rows]

    for job in jobs_to_run:
        result = _execute_job(app_ctx, job, manual=False)
        results.append(result)

        # Disable one-time jobs after run
        if job.fire_at:
            update_job(app_ctx, 0, job.id, enabled=False)

    return results


def get_job_runs(app_ctx: AppContext, job_id: int, limit: int = 50) -> list[JobRun]:
    """Get recent runs for a job."""
    with app_ctx.unit_of_work() as uow:
        rows = uow.conn.execute("""
            SELECT * FROM job_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT ?
        """, (job_id, limit)).fetchall()
        return [_row_to_run(r) for r in rows]


# =============================================================================
# Default Job Setup
# =============================================================================

def ensure_default_jobs(app_ctx: AppContext) -> None:
    """Ensure default scheduled jobs exist (idempotent)."""
    defaults = [
        {
            "name": "panel_health_check",
            "handler": "panel_health_check",
            "cron_expression": "*/5 * * * *",  # Every 5 minutes
            "enabled": True,
            "payload": {}
        },
        {
            "name": "auto_renew_services",
            "handler": "auto_renew_services",
            "cron_expression": "0 2 * * *",  # Daily at 2 AM
            "enabled": True,
            "payload": {}
        },
        {
            "name": "process_pending_payments",
            "handler": "process_pending_payments",
            "cron_expression": "*/10 * * * *",  # Every 10 minutes
            "enabled": True,
            "payload": {}
        },
        {
            "name": "sync_provisioned_clients",
            "handler": "sync_provisioned_clients",
            "cron_expression": "*/15 * * * *",  # Every 15 minutes
            "enabled": True,
            "payload": {}
        },
        {
            "name": "check_crypto_invoices",
            "handler": "check_crypto_invoices",
            "cron_expression": "*/5 * * * *",  # Every 5 minutes
            "enabled": True,
            "payload": {}
        },
        {
            "name": "send_expiry_notifications",
            "handler": "send_expiry_notifications",
            "cron_expression": "0 10 * * *",  # Daily at 10 AM
            "enabled": True,
            "payload": {}
        },
        {
            "name": "backup_database",
            "handler": "backup_database",
            "cron_expression": "0 3 * * *",  # Daily at 3 AM
            "enabled": False,  # Disabled by default - needs backup destination config
            "payload": {}
        },
        {
            "name": "cleanup_old_logs",
            "handler": "cleanup_old_logs",
            "cron_expression": "0 4 * * 0",  # Weekly on Sunday at 4 AM
            "enabled": True,
            "payload": {"days_to_keep": 30}
        },
    ]

    for job_def in defaults:
        existing = get_job_by_name(app_ctx, job_def["name"])
        if not existing:
            create_job(app_ctx, 0, **job_def)


# =============================================================================
# Helper Functions
# =============================================================================

def _row_to_job(row: tuple) -> ScheduledJob:
    return ScheduledJob(
        id=row[0], name=row[1], cron_expression=row[2], fire_at=row[3],
        handler=row[4], payload=row[5], enabled=bool(row[6]),
        last_run_at=row[7], next_run_at=row[8], last_status=row[9],
        last_detail=row[10], created_at=row[11], updated_at=row[12]
    )


def _row_to_run(row: tuple) -> JobRun:
    return JobRun(
        id=row[0], job_id=row[1], status=row[2], started_at=row[3],
        finished_at=row[4], detail=row[5], error=row[6]
    )