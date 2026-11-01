"""
GhYiAb V2 — Provider Failover Service
======================================

سیستم تبدیل خودکار به پنل پشتیبان (Emergency Panel Fallback):
- مانیتورینگ سلامت پنل‌ها
- تبدیل خودکار به پنل پیش‌فرض در صورت خرابی
- مدیریت قواعد Failover
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from bootstrap import AppContext
from core.errors import ValidationError, NotFoundError, DomainError
from core.audit import service as audit_service
from providers.vpn import get_provider

logger = logging.getLogger("ghyiab.core.provider_failover")


class FailoverError(DomainError):
    pass


@dataclass(frozen=True)
class FailoverRule:
    id: int
    primary_provider_id: int
    fallback_provider_id: int
    trigger_condition: str
    max_retries: int
    cooldown_minutes: int
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class FailoverEvent:
    id: int
    rule_id: int
    primary_provider_id: int
    fallback_provider_id: int
    trigger_reason: Optional[str]
    status: str
    created_at: str
    recovered_at: Optional[str]


# =============================================================================
# Rule Management
# =============================================================================

def create_failover_rule(
    app_ctx: AppContext,
    actor_id: int,
    primary_provider_id: int,
    fallback_provider_id: int,
    trigger_condition: str = "health_check_failed",
    max_retries: int = 3,
    cooldown_minutes: int = 5
) -> FailoverRule:
    """Create a failover rule."""
    if primary_provider_id == fallback_provider_id:
        raise ValidationError("Primary and fallback providers must be different")

    with app_ctx.unit_of_work() as uow:
        # Verify both providers exist
        for pid in (primary_provider_id, fallback_provider_id):
            row = uow.conn.execute("SELECT id FROM providers WHERE id = ?", (pid,)).fetchone()
            if not row:
                raise NotFoundError(f"Provider {pid} not found")

        cursor = uow.conn.execute("""
            INSERT INTO provider_failover_rules
            (primary_provider_id, fallback_provider_id, trigger_condition, max_retries, cooldown_minutes, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, datetime('now'))
        """, (primary_provider_id, fallback_provider_id, trigger_condition, max_retries, cooldown_minutes))
        rule_id = cursor.lastrowid
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="failover_rule_created",
            entity_type="provider_failover_rules", entity_id=str(rule_id),
            after_json={
                "primary": primary_provider_id, "fallback": fallback_provider_id,
                "trigger": trigger_condition, "max_retries": max_retries
            }
        )

        return get_failover_rule(app_ctx, rule_id)


def get_failover_rule(app_ctx: AppContext, rule_id: int) -> FailoverRule:
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM provider_failover_rules WHERE id = ?", (rule_id,)).fetchone()
        if not row:
            raise NotFoundError("Failover rule not found")
        return _row_to_rule(row)


def list_failover_rules(app_ctx: AppContext, active_only: bool = True) -> list[FailoverRule]:
    with app_ctx.unit_of_work() as uow:
        if active_only:
            rows = uow.conn.execute("SELECT * FROM provider_failover_rules WHERE is_active = 1").fetchall()
        else:
            rows = uow.conn.execute("SELECT * FROM provider_failover_rules").fetchall()
        return [_row_to_rule(r) for r in rows]


def delete_failover_rule(app_ctx: AppContext, actor_id: int, rule_id: int) -> None:
    with app_ctx.unit_of_work() as uow:
        uow.conn.execute("DELETE FROM provider_failover_rules WHERE id = ?", (rule_id,))
        uow.conn.commit()
        audit_service.log(
            uow, actor_id=actor_id, action="failover_rule_deleted",
            entity_type="provider_failover_rules", entity_id=str(rule_id)
        )


# =============================================================================
# Failover Logic
# =============================================================================

def check_and_trigger_failover(app_ctx: AppContext) -> list[FailoverEvent]:
    """Check all active failover rules and trigger if needed."""
    triggered_events = []

    with app_ctx.unit_of_work() as uow:
        rules = uow.conn.execute("""
            SELECT * FROM provider_failover_rules WHERE is_active = 1
        """).fetchall()

    for rule_row in rules:
        rule = _row_to_rule(rule_row)

        # Check cooldown
        recent_event = get_latest_failover_event(app_ctx, rule.id)
        if recent_event and recent_event.status in ("triggered", "switched"):
            # Check if cooldown passed
            from datetime import datetime
            created = datetime.fromisoformat(recent_event.created_at.replace("Z", "+00:00"))
            cooldown_end = created.replace(minute=created.minute + rule.cooldown_minutes)
            if datetime.now() < cooldown_end:
                continue  # Still in cooldown

        # Check trigger condition
        should_failover = False
        reason = ""

        if rule.trigger_condition == "health_check_failed":
            should_failover, reason = _check_health_failover(app_ctx, rule)
        elif rule.trigger_condition == "provisioning_failed":
            should_failover, reason = _check_provisioning_failover(app_ctx, rule)

        if should_failover:
            event = trigger_failover(app_ctx, 0, rule.id, reason)  # 0 = system
            triggered_events.append(event)

    return triggered_events


def _check_health_failover(app_ctx: AppContext, rule: FailoverRule) -> tuple[bool, str]:
    """Check if primary provider health warrants failover."""
    health = get_provider(f"provider_{rule.primary_provider_id}").health_check()
    status = health.get("status", "UNKNOWN")

    if status in ("BLOCKED", "ERROR", "NOT_CONFIGURED"):
        return True, f"Health check failed: {status} - {health.get('detail', '')}"

    return False, ""


def _check_provisioning_failover(app_ctx: AppContext, rule: FailoverRule) -> tuple[bool, str]:
    """Check if recent provisioning failures warrant failover."""
    with app_ctx.unit_of_work() as uow:
        # Check last few provisioning attempts for this provider
        rows = uow.conn.execute("""
            SELECT status FROM provisioned_clients
            WHERE provider_name = (SELECT name FROM providers WHERE id = ?)
            ORDER BY created_at DESC LIMIT ?
        """, (rule.primary_provider_id, rule.max_retries)).fetchall()

        failed_count = sum(1 for r in rows if r[0] == "FAILED")
        if failed_count >= rule.max_retries:
            return True, f"{failed_count} consecutive provisioning failures"

    return False, ""


def trigger_failover(app_ctx: AppContext, actor_id: int, rule_id: int, reason: str = "") -> FailoverEvent:
    """Manually trigger a failover."""
    rule = get_failover_rule(app_ctx, rule_id)

    with app_ctx.unit_of_work() as uow:
        # Create event
        cursor = uow.conn.execute("""
            INSERT INTO provider_failover_events
            (rule_id, primary_provider_id, fallback_provider_id, trigger_reason, status, created_at)
            VALUES (?, ?, ?, ?, 'triggered', datetime('now'))
        """, (rule_id, rule.primary_provider_id, rule.fallback_provider_id, reason))
        event_id = cursor.lastrowid

        # Update provider statuses
        uow.conn.execute("UPDATE providers SET status = 'FAILOVER_ACTIVE' WHERE id = ?", (rule.fallback_provider_id,))
        uow.conn.execute("UPDATE providers SET status = 'FAILED' WHERE id = ?", (rule.primary_provider_id,))

        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="failover_triggered",
            entity_type="provider_failover_events", entity_id=str(event_id),
            after_json={
                "primary": rule.primary_provider_id, "fallback": rule.fallback_provider_id,
                "reason": reason
            }
        )

        return get_failover_event(app_ctx, event_id)


def recover_failover(app_ctx: AppContext, actor_id: int, event_id: int) -> FailoverEvent:
    """Recover from failover (switch back to primary)."""
    with app_ctx.unit_of_work() as uow:
        event_row = uow.conn.execute("SELECT * FROM provider_failover_events WHERE id = ?", (event_id,)).fetchone()
        if not event_row:
            raise NotFoundError("Failover event not found")

        primary_id = event_row[2]
        fallback_id = event_row[3]

        if event_row[5] == "recovered":
            raise ValidationError("Failover already recovered")

        # Update event
        uow.conn.execute("""
            UPDATE provider_failover_events SET status = 'recovered', recovered_at = datetime('now')
            WHERE id = ?
        """, (event_id,))

        # Restore provider statuses
        uow.conn.execute("UPDATE providers SET status = 'OK' WHERE id = ?", (primary_id,))
        uow.conn.execute("UPDATE providers SET status = 'STANDBY' WHERE id = ?", (fallback_id,))

        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="failover_recovered",
            entity_type="provider_failover_events", entity_id=str(event_id)
        )

        return get_failover_event(app_ctx, event_id)


def get_failover_event(app_ctx: AppContext, event_id: int) -> FailoverEvent:
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM provider_failover_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise NotFoundError("Failover event not found")
        return _row_to_event(row)


def get_latest_failover_event(app_ctx: AppContext, rule_id: int) -> Optional[FailoverEvent]:
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("""
            SELECT * FROM provider_failover_events
            WHERE rule_id = ? ORDER BY created_at DESC LIMIT 1
        """, (rule_id,)).fetchone()
        return _row_to_event(row) if row else None


def get_failover_history(app_ctx: AppContext, rule_id: Optional[int] = None, limit: int = 50) -> list[FailoverEvent]:
    with app_ctx.unit_of_work() as uow:
        if rule_id:
            rows = uow.conn.execute("""
                SELECT * FROM provider_failover_events WHERE rule_id = ? ORDER BY created_at DESC LIMIT ?
            """, (rule_id, limit)).fetchall()
        else:
            rows = uow.conn.execute("SELECT * FROM provider_failover_events ORDER BY created_at DESC LIMIT ?").fetchall()
        return [_row_to_event(r) for r in rows]


# =============================================================================
# Get Active Provider (with failover consideration)
# =============================================================================

def get_active_provider_for_inbound(app_ctx: AppContext, inbound_id: int) -> int:
    """
    Get the active provider ID for an inbound, considering failover.
    Returns provider ID that should be used for new provisions.
    """
    with app_ctx.unit_of_work() as uow:
        # Check if there's an active failover for this provider
        row = uow.conn.execute("""
            SELECT f.fallback_provider_id
            FROM provider_failover_rules f
            JOIN provider_failover_events e ON e.rule_id = f.id
            WHERE f.primary_provider_id = (SELECT provider_id FROM provisioning_profiles WHERE inbound_id = ?)
            AND f.is_active = 1
            AND e.status IN ('triggered', 'switched')
            ORDER BY e.created_at DESC LIMIT 1
        """, (inbound_id,)).fetchone()

        if row:
            return row[0]

        # No active failover, return primary
        row = uow.conn.execute("SELECT provider_id FROM provisioning_profiles WHERE inbound_id = ?", (inbound_id,)).fetchone()
        return row[0] if row else 1


# =============================================================================
# Helper Functions
# =============================================================================

def _row_to_rule(row: tuple) -> FailoverRule:
    return FailoverRule(
        id=row[0], primary_provider_id=row[1], fallback_provider_id=row[2],
        trigger_condition=row[3], max_retries=row[4], cooldown_minutes=row[5],
        is_active=bool(row[6]), created_at=row[7]
    )


def _row_to_event(row: tuple) -> FailoverEvent:
    return FailoverEvent(
        id=row[0], rule_id=row[1], primary_provider_id=row[2],
        fallback_provider_id=row[3], trigger_reason=row[4], status=row[5],
        created_at=row[6], recovered_at=row[7]
    )