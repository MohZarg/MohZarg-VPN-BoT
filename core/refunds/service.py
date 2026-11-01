"""
GhYiAb V2 — Pro-Rata Refund Service
====================================

محاسبه و پردازش بازپرداخت نسبت‌بندی شده (Pro-Rata):
- محاسبه بر اساس روزهای باقی‌مانده
- محاسبه بر اساس ترافیک استفاده نشده
- بازگشت وجه به کیف پول کاربر
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from bootstrap import AppContext
from core.errors import ValidationError, NotFoundError, DomainError
from core.audit import service as audit_service
from core.wallet import service as wallet_service

logger = logging.getLogger("ghyiab.core.refunds")


class RefundError(DomainError):
    pass


@dataclass(frozen=True)
class ServiceRefund:
    id: int
    provisioned_client_id: int
    user_id: int
    order_id: Optional[int]
    original_amount_minor: int
    refund_amount_minor: int
    currency: str
    reason: str
    calculation_method: str  # 'pro_rata_time', 'pro_rata_traffic', 'pro_rata_min', 'full', 'partial'
    days_used: Optional[int]
    days_remaining: Optional[int]
    status: str  # 'pending', 'approved', 'rejected', 'processed'
    requested_by: Optional[int]
    approved_by: Optional[int]
    processed_at: Optional[str]
    created_at: str


# =============================================================================
# Refund Calculation
# =============================================================================

def calculate_pro_rata_refund(
    app_ctx: AppContext,
    provisioned_client_id: int,
    method: str = "pro_rata_time"
) -> dict:
    """
    Calculate pro-rata refund amount for a provisioned client.

    Methods:
    - pro_rata_time: Based on days remaining / total days
    - pro_rata_traffic: Based on unused traffic / total traffic
    - pro_rata_min: Minimum of time and traffic based
    - full: Full refund (admin only)
    - partial: Custom percentage (admin only)
    """
    with app_ctx.unit_of_work() as uow:
        # Get provisioned client with order info
        row = uow.conn.execute("""
            SELECT pc.*, o.price_minor, o.currency, o.created_at as order_created
            FROM provisioned_clients pc
            JOIN orders o ON o.id = pc.order_id
            WHERE pc.id = ?
        """, (provisioned_client_id,)).fetchone()

        if not row:
            raise NotFoundError("Provisioned client not found")

        provider_name = row[2]
        email = row[5]
        expires_at_ms = row[7]
        status = row[8]
        original_amount = row[18]  # price_minor from orders
        currency = row[19]
        order_created = row[20]

        if status not in ("ACTIVE", "EXPIRED"):
            raise ValidationError(f"Cannot refund service with status: {status}")

        # Get current usage from provider
        provider = __import__("providers.vpn", fromlist=[provider_name]).get_provider(provider_name)
        client_state = provider.get_client(email)

        if not client_state:
            raise ValidationError("Client not found on provider")

        now_ms = int(datetime.now().timestamp() * 1000)
        order_created_ms = int(datetime.fromisoformat(order_created).timestamp() * 1000)
        total_duration_ms = expires_at_ms - order_created_ms
        used_duration_ms = now_ms - order_created_ms
        remaining_duration_ms = max(0, expires_at_ms - now_ms)

        total_days = total_duration_ms / (24 * 60 * 60 * 1000)
        used_days = used_duration_ms / (24 * 60 * 60 * 1000)
        remaining_days = remaining_duration_ms / (24 * 60 * 60 * 1000)

        # Traffic info
        total_bytes = client_state.total_bytes
        used_bytes = client_state.used_bytes
        remaining_bytes = client_state.remaining_bytes or 0

        refund_amount = 0
        calculation_details = {}

        if method == "pro_rata_time":
            if total_days > 0:
                refund_ratio = remaining_days / total_days
                refund_amount = int(original_amount * refund_ratio)
            calculation_details = {
                "total_days": round(total_days, 2),
                "used_days": round(used_days, 2),
                "remaining_days": round(remaining_days, 2),
                "refund_ratio": round(refund_ratio, 4) if total_days > 0 else 0
            }

        elif method == "pro_rata_traffic":
            if total_bytes > 0:
                refund_ratio = remaining_bytes / total_bytes
                refund_amount = int(original_amount * refund_ratio)
            calculation_details = {
                "total_gb": round(total_bytes / (1024**3), 2),
                "used_gb": round(used_bytes / (1024**3), 2),
                "remaining_gb": round(remaining_bytes / (1024**3), 2),
                "refund_ratio": round(refund_ratio, 4) if total_bytes > 0 else 0
            }

        elif method == "pro_rata_min":
            # Minimum of time and traffic refund
            time_refund = 0
            traffic_refund = 0

            if total_days > 0:
                time_ratio = remaining_days / total_days
                time_refund = int(original_amount * time_ratio)

            if total_bytes > 0:
                traffic_ratio = remaining_bytes / total_bytes
                traffic_refund = int(original_amount * traffic_ratio)

            refund_amount = min(time_refund, traffic_refund)
            calculation_details = {
                "time_refund_minor": time_refund,
                "traffic_refund_minor": traffic_refund,
                "chosen_method": "time" if time_refund < traffic_refund else "traffic"
            }

        elif method == "full":
            refund_amount = original_amount
            calculation_details = {"method": "full"}

        elif method == "partial":
            # Requires percentage parameter
            raise ValidationError("Partial refund requires percentage parameter")

        else:
            raise ValidationError(f"Unknown calculation method: {method}")

        # Ensure refund doesn't exceed original amount
        refund_amount = min(refund_amount, original_amount)

        return {
            "provisioned_client_id": provisioned_client_id,
            "original_amount_minor": original_amount,
            "refund_amount_minor": refund_amount,
            "currency": currency,
            "method": method,
            "days_used": int(used_days),
            "days_remaining": int(remaining_days),
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "remaining_bytes": remaining_bytes,
            "calculation_details": calculation_details
        }


# =============================================================================
# Refund Management
# =============================================================================

def request_refund(
    app_ctx: AppContext,
    actor_id: int,
    provisioned_client_id: int,
    reason: str,
    method: str = "pro_rata_time"
) -> ServiceRefund:
    """Request a refund for a service."""
    calculation = calculate_pro_rata_refund(app_ctx, provisioned_client_id, method)

    if calculation["refund_amount_minor"] <= 0:
        raise ValidationError("Refund amount is zero or negative")

    with app_ctx.unit_of_work() as uow:
        # Get client info
        row = uow.conn.execute("""
            SELECT pc.user_id, pc.order_id FROM provisioned_clients pc WHERE pc.id = ?
        """, (provisioned_client_id,)).fetchone()

        if not row:
            raise NotFoundError("Provisioned client not found")

        user_id, order_id = row

        cursor = uow.conn.execute("""
            INSERT INTO service_refunds
            (provisioned_client_id, user_id, order_id, original_amount_minor, refund_amount_minor,
             currency, reason, calculation_method, days_used, days_remaining, status, requested_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, datetime('now'))
        """, (
            provisioned_client_id, user_id, order_id,
            calculation["original_amount_minor"], calculation["refund_amount_minor"],
            calculation["currency"], reason, method,
            calculation["days_used"], calculation["days_remaining"],
            actor_id
        ))
        refund_id = cursor.lastrowid
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="refund_requested",
            entity_type="service_refunds", entity_id=str(refund_id),
            after_json=calculation
        )

        return get_refund(app_ctx, refund_id)


def approve_refund(app_ctx: AppContext, actor_id: int, refund_id: int) -> ServiceRefund:
    """Approve a pending refund."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM service_refunds WHERE id = ?", (refund_id,)).fetchone()
        if not row:
            raise NotFoundError("Refund not found")

        if row[11] != 'pending':  # status
            raise ValidationError(f"Refund is not pending (status: {row[11]})")

        uow.conn.execute("""
            UPDATE service_refunds SET status = 'approved', approved_by = ? WHERE id = ?
        """, (actor_id, refund_id))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="refund_approved",
            entity_type="service_refunds", entity_id=str(refund_id)
        )

        return get_refund(app_ctx, refund_id)


def process_refund(app_ctx: AppContext, actor_id: int, refund_id: int) -> ServiceRefund:
    """Process (execute) an approved refund."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM service_refunds WHERE id = ?", (refund_id,)).fetchone()
        if not row:
            raise NotFoundError("Refund not found")

        if row[11] != 'approved':  # status
            raise ValidationError(f"Refund is not approved (status: {row[11]})")

        user_id = row[2]
        amount_minor = row[5]  # refund_amount_minor
        currency = row[6]

        # Credit user wallet
        wallet_service.add_funds(
            uow, user_id, amount_minor, currency,
            f"بازپرداخت سرویس (مرجع: {refund_id})",
            idempotency_key=f"refund_{refund_id}"
        )

        # Update refund status
        uow.conn.execute("""
            UPDATE service_refunds SET status = 'processed', processed_at = datetime('now') WHERE id = ?
        """, (refund_id,))

        # Update provisioned client status
        uow.conn.execute("UPDATE provisioned_clients SET status = 'REFUNDED' WHERE id = ?", (row[1],))

        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="refund_processed",
            entity_type="service_refunds", entity_id=str(refund_id),
            after_json={"user_id": user_id, "amount_minor": amount_minor}
        )

        return get_refund(app_ctx, refund_id)


def reject_refund(app_ctx: AppContext, actor_id: int, refund_id: int, reason: str = "") -> ServiceRefund:
    """Reject a pending refund."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM service_refunds WHERE id = ?", (refund_id,)).fetchone()
        if not row:
            raise NotFoundError("Refund not found")

        if row[11] != 'pending':
            raise ValidationError(f"Refund is not pending (status: {row[11]})")

        uow.conn.execute("UPDATE service_refunds SET status = 'rejected' WHERE id = ?", (refund_id,))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="refund_rejected",
            entity_type="service_refunds", entity_id=str(refund_id),
            after_json={"reason": reason}
        )

        return get_refund(app_ctx, refund_id)


def get_refund(app_ctx: AppContext, refund_id: int) -> ServiceRefund:
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM service_refunds WHERE id = ?", (refund_id,)).fetchone()
        if not row:
            raise NotFoundError("Refund not found")
        return _row_to_refund(row)


def list_refunds(app_ctx: AppContext, user_id: Optional[int] = None, status: Optional[str] = None) -> list[ServiceRefund]:
    with app_ctx.unit_of_work() as uow:
        query = "SELECT * FROM service_refunds WHERE 1=1"
        params = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"
        rows = uow.conn.execute(query, params).fetchall()
        return [_row_to_refund(r) for r in rows]


# =============================================================================
# Admin Functions
# =============================================================================

def admin_create_partial_refund(
    app_ctx: AppContext,
    actor_id: int,
    provisioned_client_id: int,
    refund_amount_minor: int,
    reason: str
) -> ServiceRefund:
    """Admin creates a custom partial refund."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("""
            SELECT pc.user_id, pc.order_id, o.price_minor, o.currency
            FROM provisioned_clients pc
            JOIN orders o ON o.id = pc.order_id
            WHERE pc.id = ?
        """, (provisioned_client_id,)).fetchone()

        if not row:
            raise NotFoundError("Provisioned client not found")

        user_id, order_id, original_amount, currency = row

        if refund_amount_minor > original_amount:
            raise ValidationError("Refund amount cannot exceed original amount")

        cursor = uow.conn.execute("""
            INSERT INTO service_refunds
            (provisioned_client_id, user_id, order_id, original_amount_minor, refund_amount_minor,
             currency, reason, calculation_method, days_used, days_remaining, status, requested_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'partial', 0, 0, 'pending', ?, datetime('now'))
        """, (provisioned_client_id, user_id, order_id, original_amount, refund_amount_minor, currency, reason, actor_id))
        refund_id = cursor.lastrowid
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="refund_partial_created",
            entity_type="service_refunds", entity_id=str(refund_id),
            after_json={"refund_amount_minor": refund_amount_minor}
        )

        return get_refund(app_ctx, refund_id)


# =============================================================================
# Helper Functions
# =============================================================================

def _row_to_refund(row: tuple) -> ServiceRefund:
    return ServiceRefund(
        id=row[0], provisioned_client_id=row[1], user_id=row[2], order_id=row[3],
        original_amount_minor=row[4], refund_amount_minor=row[5], currency=row[6],
        reason=row[7], calculation_method=row[8], days_used=row[9], days_remaining=row[10],
        status=row[11], requested_by=row[12], approved_by=row[13], processed_at=row[14],
        created_at=row[15]
    )