"""
GhYiAb V2 — Scheduled Job Handlers
===================================

Built-in handlers for scheduled jobs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from bootstrap import AppContext
from providers.vpn import health_check_all
from core.crypto_payments import service as crypto_service

logger = logging.getLogger("ghyiab.core.scheduled_jobs.handlers")


# =============================================================================
# Panel Health Check
# =============================================================================

def panel_health_check(app_ctx: AppContext, **kwargs) -> dict:
    """Check health of all configured VPN providers."""
    results = health_check_all()

    # Log health status to database
    with app_ctx.unit_of_work() as uow:
        for provider_name, health in results.items():
            uow.conn.execute("""
                INSERT INTO panel_health_logs (provider_id, status, latency_ms, error_message, checked_at)
                SELECT id, ?, ?, ?, datetime('now') FROM providers WHERE name = ?
            """, (health.get("status", "UNKNOWN"), health.get("latency_ms"), health.get("detail"), provider_name))

        uow.conn.commit()

    # Count unhealthy panels
    unhealthy = [name for name, h in results.items() if h.get("status") not in ("OK", "NOT_CONFIGURED")]

    logger.info("Panel health check completed: %d total, %d unhealthy", len(results), len(unhealthy))

    return {
        "checked": len(results),
        "unhealthy": len(unhealthy),
        "details": results
    }


# =============================================================================
# Auto Renew Services
# =============================================================================

def auto_renew_services(app_ctx: AppContext, **kwargs) -> dict:
    """Process auto-renewal for eligible services."""
    try:
        # This would call the provisioning service's auto-renewal logic
        # For now, return status
        return {"status": "checked", "renewed": 0, "failed": 0}
    except Exception as e:
        logger.exception("Auto renew failed: %s", e)
        return {"status": "error", "error": str(e)}


# =============================================================================
# Process Pending Payments
# =============================================================================

def process_pending_payments(app_ctx: AppContext, **kwargs) -> dict:
    """Process pending payment requests (charge/buy/agency)."""
    # This would be implemented to auto-process payments that have receipts
    # For now, just return status
    return {"status": "checked", "processed": 0}


# =============================================================================
# Backup Database
# =============================================================================

def backup_database(app_ctx: AppContext, **kwargs) -> dict:
    """Create a backup of the SQLite database."""
    try:
        db_path = app_ctx.db_path
        backup_dir = Path(kwargs.get("backup_dir", "./backups"))
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"ghyiab_backup_{timestamp}.db"
        backup_path = backup_dir / backup_name

        # Use SQLite backup API for consistent backup
        import sqlite3
        with sqlite3.connect(db_path) as src:
            with sqlite3.connect(str(backup_path)) as dst:
                src.backup(dst)

        # Clean old backups (keep last 30 days)
        retention_days = kwargs.get("retention_days", 30)
        cutoff = datetime.now() - timedelta(days=retention_days)
        for old_backup in backup_dir.glob("ghyiab_backup_*.db"):
            try:
                # Extract timestamp from filename
                ts_str = old_backup.stem.replace("ghyiab_backup_", "")
                backup_time = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                if backup_time < cutoff:
                    old_backup.unlink()
            except Exception:
                pass

        logger.info("Database backed up to %s", backup_path)
        return {"status": "success", "backup_path": str(backup_path)}

    except Exception as e:
        logger.exception("Database backup failed: %s", e)
        return {"status": "error", "error": str(e)}


# =============================================================================
# Cleanup Old Logs
# =============================================================================

def cleanup_old_logs(app_ctx: AppContext, **kwargs) -> dict:
    """Clean up old audit logs and job runs."""
    days_to_keep = kwargs.get("days_to_keep", 30)
    cutoff = datetime.now() - timedelta(days=days_to_keep)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    deleted = {}

    with app_ctx.unit_of_work() as uow:
        # Clean job_runs
        result = uow.conn.execute("DELETE FROM job_runs WHERE started_at < ?", (cutoff_str,))
        deleted["job_runs"] = result.rowcount

        # Clean panel_health_logs
        result = uow.conn.execute("DELETE FROM panel_health_logs WHERE checked_at < ?", (cutoff_str,))
        deleted["panel_health_logs"] = result.rowcount

        # Clean old audit_logs (keep longer - 90 days)
        audit_cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        result = uow.conn.execute("DELETE FROM audit_logs WHERE created_at < ?", (audit_cutoff,))
        deleted["audit_logs"] = result.rowcount

        uow.conn.commit()

    logger.info("Cleanup completed: %s", deleted)
    return {"status": "success", "deleted": deleted}


# =============================================================================
# Sync Provisioned Clients
# =============================================================================

def sync_provisioned_clients(app_ctx: AppContext, **kwargs) -> dict:
    """Sync provisioned client status with VPN providers."""
    try:
        # This would call provisioning_service.sync_all()
        # For now, return status
        return {"status": "checked", "synced": 0, "errors": 0}
    except Exception as e:
        logger.exception("Sync provisioned clients failed: %s", e)
        return {"status": "error", "error": str(e)}


# =============================================================================
# Check Crypto Invoices
# =============================================================================

def check_crypto_invoices(app_ctx: AppContext, **kwargs) -> dict:
    """Check and verify pending crypto invoices."""
    try:
        # Get all pending crypto invoices
        with app_ctx.unit_of_work() as uow:
            rows = uow.conn.execute("""
                SELECT id FROM crypto_invoices WHERE status = 'pending' AND tx_hash IS NOT NULL
            """).fetchall()

        verified = 0
        failed = 0

        for (invoice_id,) in rows:
            try:
                invoice = crypto_service.check_crypto_invoice(app_ctx, invoice_id)
                if invoice.status == "verified":
                    verified += 1
                elif invoice.status == "failed":
                    failed += 1
            except Exception as e:
                logger.warning("Failed to check crypto invoice %d: %s", invoice_id, e)
                failed += 1

        return {"status": "completed", "verified": verified, "failed": failed}

    except Exception as e:
        logger.exception("Check crypto invoices failed: %s", e)
        return {"status": "error", "error": str(e)}


# =============================================================================
# Send Expiry Notifications
# =============================================================================

def send_expiry_notifications(app_ctx: AppContext, **kwargs) -> dict:
    """Send notifications for expiring services."""
    # This would integrate with the bot to send Telegram messages
    # For now, return status
    return {"status": "checked", "notifications_sent": 0}