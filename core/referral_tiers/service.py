"""
GhYiAb V2 — Referral Tier Service (N/N2/F)
===========================================

سیستم رفرال سه‌سطحی:
- N (سطح 1): رفرال مستقیم - 10% پیش‌فرض
- N2 (سطح 2): رفرال غیرمستقیم (رفرال رفرال) - 5% پیش‌فرض
- F (سطح 3): رفرال فرعی - 2% پیش‌فرض
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from bootstrap import AppContext
from core.errors import ValidationError, NotFoundError, DomainError
from core.audit import service as audit_service
from core.wallet import service as wallet_service

logger = logging.getLogger("ghyiab.core.referral_tiers")


class ReferralTierError(DomainError):
    pass


@dataclass(frozen=True)
class ReferralTier:
    id: int
    tier_name: str  # 'N', 'N2', 'F'
    level: int  # 1, 2, 3
    commission_rate: int  # basis points (1000 = 10%)
    description: str
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class ReferralEarning:
    id: int
    referrer_id: int
    referred_id: int
    tier_id: int
    order_id: Optional[int]
    commission_basis_minor: int
    commission_amount_minor: int
    currency: str
    status: str  # 'pending', 'paid', 'cancelled'
    created_at: str
    paid_at: Optional[str]


# =============================================================================
# Tier Management
# =============================================================================

def get_tier(app_ctx: AppContext, tier_name: str) -> ReferralTier:
    """Get tier by name (N, N2, F)."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute(
            "SELECT * FROM referral_tiers WHERE tier_name = ? AND is_active = 1",
            (tier_name.upper(),)
        ).fetchone()
        if not row:
            raise NotFoundError(f"Referral tier {tier_name} not found or inactive")
        return _row_to_tier(row)


def get_all_tiers(app_ctx: AppContext) -> list[ReferralTier]:
    """Get all active referral tiers ordered by level."""
    with app_ctx.unit_of_work() as uow:
        rows = uow.conn.execute(
            "SELECT * FROM referral_tiers WHERE is_active = 1 ORDER BY level"
        ).fetchall()
        return [_row_to_tier(r) for r in rows]


def admin_update_tier_rate(app_ctx: AppContext, actor_id: int, tier_name: str, commission_rate: int) -> ReferralTier:
    """Admin updates commission rate for a tier (in basis points)."""
    if not 0 <= commission_rate <= 10000:
        raise ValidationError("Commission rate must be between 0 and 10000 (basis points)")

    with app_ctx.unit_of_work() as uow:
        uow.conn.execute(
            "UPDATE referral_tiers SET commission_rate = ? WHERE tier_name = ?",
            (commission_rate, tier_name.upper())
        )
        uow.conn.commit()

        row = uow.conn.execute("SELECT * FROM referral_tiers WHERE tier_name = ?", (tier_name.upper(),)).fetchone()

        audit_service.log(
            uow, actor_id=actor_id, action="referral_tier_rate_updated",
            entity_type="referral_tiers", entity_id=tier_name.upper(),
            after_json={"commission_rate": commission_rate}
        )

        return _row_to_tier(row)


# =============================================================================
# Referral Tree & Earnings Calculation
# =============================================================================

def get_referrer_chain(app_ctx: AppContext, user_id: int, max_level: int = 3) -> list[tuple[int, int]]:
    """
    Get referrer chain for a user up to max_level.
    Returns list of (referrer_id, level) where level 1 = direct referrer (N), 2 = N2, 3 = F.
    """
    chain = []
    current_id = user_id

    with app_ctx.unit_of_work() as uow:
        for level in range(1, max_level + 1):
            row = uow.conn.execute(
                "SELECT referred_by FROM users WHERE user_id = ?", (current_id,)
            ).fetchone()
            if not row or not row[0]:
                break
            referrer_id = row[0]
            chain.append((referrer_id, level))
            current_id = referrer_id

    return chain


def calculate_referral_commission(
    app_ctx: AppContext,
    order_amount_minor: int,
    currency: str,
    referrer_id: int,
    tier_level: int
) -> int:
    """Calculate commission amount for a referral tier."""
    with app_ctx.unit_of_work() as uow:
        tier_row = uow.conn.execute(
            "SELECT commission_rate FROM referral_tiers WHERE level = ? AND is_active = 1",
            (tier_level,)
        ).fetchone()

        if not tier_row:
            return 0

        commission_rate = tier_row[0]  # basis points
        # Commission = order_amount * commission_rate / 10000
        commission = (order_amount_minor * commission_rate) // 10000
        return commission


def process_order_referral_rewards(app_ctx: AppContext, order_id: int) -> list[ReferralEarning]:
    """
    Process referral rewards for a completed order.
    Called when an order is marked COMPLETED.
    Returns list of created earnings.
    """
    with app_ctx.unit_of_work() as uow:
        # Get order details
        order_row = uow.conn.execute("""
            SELECT user_id, price_minor, currency FROM orders WHERE id = ?
        """, (order_id,)).fetchone()

        if not order_row:
            raise NotFoundError("Order not found")

        user_id, amount_minor, currency = order_row

        # Get referrer chain (N, N2, F)
        chain = get_referrer_chain(app_ctx, user_id, max_level=3)
        if not chain:
            return []  # No referrers

        earnings = []
        for referrer_id, level in chain:
            # Check if referrer is banned
            referrer_row = uow.conn.execute("SELECT is_banned FROM users WHERE user_id = ?", (referrer_id,)).fetchone()
            if referrer_row and referrer_row[0]:
                continue  # Skip banned referrers

            # Get tier
            tier_row = uow.conn.execute(
                "SELECT id, commission_rate FROM referral_tiers WHERE level = ? AND is_active = 1",
                (level,)
            ).fetchone()
            if not tier_row:
                continue

            tier_id, commission_rate = tier_row
            commission_amount = (amount_minor * commission_rate) // 10000

            if commission_amount <= 0:
                continue

            # Create earning record (initially pending)
            cursor = uow.conn.execute("""
                INSERT INTO referral_earnings
                (referrer_id, referred_id, tier_id, order_id, commission_basis_minor, commission_amount_minor, currency, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'))
            """, (referrer_id, user_id, tier_id, order_id, amount_minor, commission_amount, currency))
            earning_id = cursor.lastrowid

            earnings.append(ReferralEarning(
                id=earning_id, referrer_id=referrer_id, referred_id=user_id,
                tier_id=tier_id, order_id=order_id,
                commission_basis_minor=amount_minor, commission_amount_minor=commission_amount,
                currency=currency, status='pending', created_at='', paid_at=None
            ))

            audit_service.log(
                uow, actor_id=0, action="referral_earning_created",
                entity_type="referral_earnings", entity_id=str(earning_id),
                after_json={
                    "referrer_id": referrer_id, "referred_id": user_id,
                    "tier_level": level, "commission_amount_minor": commission_amount
                }
            )

        uow.conn.commit()
        return earnings


def pay_referral_earning(app_ctx: AppContext, actor_id: int, earning_id: int) -> ReferralEarning:
    """Mark a referral earning as paid and credit referrer's wallet."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM referral_earnings WHERE id = ?", (earning_id,)).fetchone()
        if not row:
            raise NotFoundError("Referral earning not found")

        if row[8] == 'paid':  # status
            raise ValidationError("Earning already paid")

        referrer_id = row[1]
        amount_minor = row[6]  # commission_amount_minor
        currency = row[7]

        # Credit referrer's wallet
        wallet_service.add_funds(
            uow, referrer_id, amount_minor, currency,
            f"پاداش رفرال سطح {row[3]} ( سفارش {row[4]} )",
            idempotency_key=f"ref_earning_{earning_id}"
        )

        # Update earning status
        uow.conn.execute("""
            UPDATE referral_earnings SET status = 'paid', paid_at = datetime('now') WHERE id = ?
        """, (earning_id,))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="referral_earning_paid",
            entity_type="referral_earnings", entity_id=str(earning_id),
            after_json={"referrer_id": referrer_id, "amount_minor": amount_minor}
        )

        row = uow.conn.execute("SELECT * FROM referral_earnings WHERE id = ?", (earning_id,)).fetchone()
        return _row_to_earning(row)


def cancel_referral_earning(app_ctx: AppContext, actor_id: int, earning_id: int, reason: str = "") -> ReferralEarning:
    """Cancel a referral earning (e.g., order refunded)."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM referral_earnings WHERE id = ?", (earning_id,)).fetchone()
        if not row:
            raise NotFoundError("Referral earning not found")

        if row[8] == 'cancelled':
            raise ValidationError("Earning already cancelled")

        uow.conn.execute("UPDATE referral_earnings SET status = 'cancelled' WHERE id = ?", (earning_id,))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="referral_earning_cancelled",
            entity_type="referral_earnings", entity_id=str(earning_id),
            after_json={"reason": reason}
        )

        row = uow.conn.execute("SELECT * FROM referral_earnings WHERE id = ?", (earning_id,)).fetchone()
        return _row_to_earning(row)


# =============================================================================
# Query Functions
# =============================================================================

def get_user_referral_earnings(app_ctx: AppContext, user_id: int, status: Optional[str] = None) -> list[ReferralEarning]:
    """Get referral earnings for a user (as referrer)."""
    with app_ctx.unit_of_work() as uow:
        if status:
            rows = uow.conn.execute("""
                SELECT re.*, rt.tier_name, rt.level
                FROM referral_earnings re
                JOIN referral_tiers rt ON rt.id = re.tier_id
                WHERE re.referrer_id = ? AND re.status = ?
                ORDER BY re.created_at DESC
            """, (user_id, status)).fetchall()
        else:
            rows = uow.conn.execute("""
                SELECT re.*, rt.tier_name, rt.level
                FROM referral_earnings re
                JOIN referral_tiers rt ON rt.id = re.tier_id
                WHERE re.referrer_id = ?
                ORDER BY re.created_at DESC
            """, (user_id,)).fetchall()
        return [_row_to_earning(r) for r in rows]


def get_user_referral_stats(app_ctx: AppContext, user_id: int) -> dict:
    """Get referral statistics for a user."""
    with app_ctx.unit_of_work() as uow:
        # Direct referrals (N)
        direct = uow.conn.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
        ).fetchone()[0]

        # Total earnings
        earnings = uow.conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN status = 'paid' THEN commission_amount_minor ELSE 0 END), 0) as paid,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN commission_amount_minor ELSE 0 END), 0) as pending
            FROM referral_earnings WHERE referrer_id = ?
        """, (user_id,)).fetchone()

        # Earnings by tier
        by_tier = uow.conn.execute("""
            SELECT rt.tier_name, rt.level,
                COALESCE(SUM(CASE WHEN re.status = 'paid' THEN re.commission_amount_minor ELSE 0 END), 0) as paid,
                COALESCE(SUM(CASE WHEN re.status = 'pending' THEN re.commission_amount_minor ELSE 0 END), 0) as pending
            FROM referral_earnings re
            JOIN referral_tiers rt ON rt.id = re.tier_id
            WHERE re.referrer_id = ?
            GROUP BY rt.tier_name, rt.level
        """, (user_id,)).fetchall()

        return {
            "direct_referrals": direct,
            "total_paid_minor": earnings[0] if earnings else 0,
            "total_pending_minor": earnings[1] if earnings else 0,
            "by_tier": [
                {"tier": r[0], "level": r[1], "paid_minor": r[2], "pending_minor": r[3]}
                for r in by_tier
            ]
        }


def get_referred_users(app_ctx: AppContext, user_id: int) -> list[dict]:
    """Get users referred by this user (direct only)."""
    with app_ctx.unit_of_work() as uow:
        rows = uow.conn.execute("""
            SELECT user_id, created_at, is_banned
            FROM users WHERE referred_by = ?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()
        return [{"user_id": r[0], "joined_at": r[1], "is_banned": bool(r[2])} for r in rows]


# =============================================================================
# Admin Functions
# =============================================================================

def admin_get_all_earnings(app_ctx: AppContext, status: Optional[str] = None, limit: int = 100) -> list[ReferralEarning]:
    """Admin: Get all referral earnings."""
    with app_ctx.unit_of_work() as uow:
        if status:
            rows = uow.conn.execute("""
                SELECT re.*, rt.tier_name, rt.level
                FROM referral_earnings re
                JOIN referral_tiers rt ON rt.id = re.tier_id
                WHERE re.status = ?
                ORDER BY re.created_at DESC LIMIT ?
            """, (status, limit)).fetchall()
        else:
            rows = uow.conn.execute("""
                SELECT re.*, rt.tier_name, rt.level
                FROM referral_earnings re
                JOIN referral_tiers rt ON rt.id = re.tier_id
                ORDER BY re.created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [_row_to_earning(r) for r in rows]


def admin_pay_all_pending(app_ctx: AppContext, actor_id: int) -> int:
    """Admin: Pay all pending referral earnings."""
    with app_ctx.unit_of_work() as uow:
        rows = uow.conn.execute("SELECT id FROM referral_earnings WHERE status = 'pending'").fetchall()
        count = 0
        for (eid,) in rows:
            try:
                pay_referral_earning(app_ctx, actor_id, eid)
                count += 1
            except Exception as e:
                logger.warning("Failed to pay referral earning %d: %s", eid, e)
        return count


# =============================================================================
# Helper Functions
# =============================================================================

def _row_to_tier(row: tuple) -> ReferralTier:
    return ReferralTier(
        id=row[0], tier_name=row[1], level=row[2], commission_rate=row[3],
        description=row[4], is_active=bool(row[5]), created_at=row[6]
    )


def _row_to_earning(row: tuple) -> ReferralEarning:
    return ReferralEarning(
        id=row[0], referrer_id=row[1], referred_id=row[2], tier_id=row[3],
        order_id=row[4] if row[4] else None,
        commission_basis_minor=row[5], commission_amount_minor=row[6],
        currency=row[7], status=row[8], created_at=row[9], paid_at=row[10]
    )