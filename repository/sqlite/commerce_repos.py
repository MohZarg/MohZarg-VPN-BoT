"""Repositoryهای Coupon / Reseller / Referral / Dice (SQLite)."""
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence

from repository.interface import (
    CouponRecord, ResellerTierRecord, ReferralRewardRecord, DiceRollRecord,
)
from repository.sqlite._util import paged

_CPN = ("id, code, kind, value, currency, max_uses, per_user_limit, expires_at, is_active, created_at, "
        "min_order_minor, product_ids")


def _cpn(r) -> CouponRecord:
    return CouponRecord(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], bool(r[8]), r[9], r[10], r[11])


class SqliteCouponsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, code, kind, value, currency, max_uses, per_user_limit, expires_at, created_by,
               min_order_minor=None, product_ids=None):
        cur = self._c.execute(
            "INSERT INTO coupons (code, kind, value, currency, max_uses, per_user_limit, expires_at, "
            "created_by, created_at, min_order_minor, product_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)",
            (code, kind, value, currency, max_uses, per_user_limit, expires_at, created_by,
             min_order_minor, product_ids))
        return self.get(cur.lastrowid)

    def get(self, coupon_id: int) -> Optional[CouponRecord]:
        r = self._c.execute(f"SELECT {_CPN} FROM coupons WHERE id=?", (coupon_id,)).fetchone()
        return _cpn(r) if r else None

    def get_by_code(self, code: str) -> Optional[CouponRecord]:
        r = self._c.execute(f"SELECT {_CPN} FROM coupons WHERE code=?", (code,)).fetchone()
        return _cpn(r) if r else None

    def set_active(self, coupon_id: int, active: bool) -> None:
        self._c.execute("UPDATE coupons SET is_active=? WHERE id=?", (int(active), coupon_id))

    def page(self, *, page: int = 0, per_page: int = 8):
        return paged(self._c, columns=_CPN, frm="coupons", where="", params=[], order="id DESC",
                     page=page, per_page=per_page, mapper=_cpn)

    def count_uses(self, coupon_id: int) -> int:
        return self._c.execute("SELECT COUNT(*) FROM coupon_redemptions WHERE coupon_id=?",
                               (coupon_id,)).fetchone()[0]

    def count_uses_by_user(self, coupon_id: int, user_id: int) -> int:
        return self._c.execute(
            "SELECT COUNT(*) FROM coupon_redemptions WHERE coupon_id=? AND user_id=?",
            (coupon_id, user_id)).fetchone()[0]

    def record_redemption(self, coupon_id, user_id, order_id, discount_minor) -> int:
        return self._c.execute(
            "INSERT INTO coupon_redemptions (coupon_id, user_id, order_id, discount_minor, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (coupon_id, user_id, order_id, discount_minor)).lastrowid


class SqliteResellersRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    @staticmethod
    def _t(r):
        return ResellerTierRecord(r[0], r[1], r[2], bool(r[3]), r[4])

    def create_tier(self, name: str, discount_percent: int) -> ResellerTierRecord:
        cur = self._c.execute(
            "INSERT INTO reseller_tiers (name, discount_percent, created_at) VALUES (?, ?, datetime('now'))",
            (name, discount_percent))
        return self.get_tier(cur.lastrowid)

    def get_tier(self, tier_id: int) -> Optional[ResellerTierRecord]:
        r = self._c.execute(
            "SELECT id, name, discount_percent, is_active, created_at FROM reseller_tiers WHERE id=?",
            (tier_id,)).fetchone()
        return self._t(r) if r else None

    def list_tiers(self) -> Sequence[ResellerTierRecord]:
        return [self._t(r) for r in self._c.execute(
            "SELECT id, name, discount_percent, is_active, created_at FROM reseller_tiers ORDER BY id"
        ).fetchall()]

    def set_tier_active(self, tier_id: int, active: bool) -> None:
        self._c.execute("UPDATE reseller_tiers SET is_active=? WHERE id=?", (int(active), tier_id))

    def count_users_in_tier(self, tier_id: int) -> int:
        return self._c.execute("SELECT COUNT(*) FROM users WHERE reseller_tier_id=?", (tier_id,)).fetchone()[0]


class SqliteReferralsRepository:
    _COLS = "id, referrer_id, referred_id, amount_minor, currency, status, created_at"

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def get(self, reward_id: int):
        r = self._c.execute(f"SELECT {self._COLS} FROM referral_rewards WHERE id=?", (reward_id,)).fetchone()
        return ReferralRewardRecord(*r) if r else None

    def get_reward_for_referred(self, referred_id: int):
        r = self._c.execute(f"SELECT {self._COLS} FROM referral_rewards WHERE referred_id=?",
                            (referred_id,)).fetchone()
        return ReferralRewardRecord(*r) if r else None

    def record_reward(self, referrer_id, referred_id, amount_minor, currency, notified: bool = True):
        """اتمیک به‌کمک UNIQUE(referred_id): اگر قبلاً پاداش داده شده باشد None.
        notified=False → حلقهٔ نگهداری بعداً به معرف اطلاع می‌دهد."""
        try:
            cur = self._c.execute(
                "INSERT INTO referral_rewards (referrer_id, referred_id, amount_minor, currency, created_at, notified) "
                "VALUES (?, ?, ?, ?, datetime('now'), ?)",
                (referrer_id, referred_id, amount_minor, currency, int(notified)))
        except sqlite3.IntegrityError:
            return None
        return self.get(cur.lastrowid)

    def list_unnotified(self, limit: int = 50):
        return [(r[0], r[1], r[2]) for r in self._c.execute(
            "SELECT id, referrer_id, amount_minor FROM referral_rewards WHERE notified=0 AND status='PAID' "
            "ORDER BY id LIMIT ?", (limit,)).fetchall()]

    def mark_notified(self, reward_id: int) -> None:
        self._c.execute("UPDATE referral_rewards SET notified=1 WHERE id=?", (reward_id,))

    def mark_reversed(self, reward_id: int) -> bool:
        cur = self._c.execute(
            "UPDATE referral_rewards SET status='REVERSED' WHERE id=? AND status='PAID'", (reward_id,))
        return cur.rowcount > 0

    def count_rewards_today(self, referrer_id: int) -> int:
        return self._c.execute(
            "SELECT COUNT(*) FROM referral_rewards WHERE referrer_id=? AND status='PAID' "
            "AND date(created_at)=date('now')", (referrer_id,)).fetchone()[0]

    def top_referrers(self, limit: int = 5):
        return self._c.execute(
            "SELECT referrer_id, COUNT(*), SUM(amount_minor) FROM referral_rewards WHERE status='PAID' "
            "GROUP BY referrer_id ORDER BY COUNT(*) DESC, referrer_id LIMIT ?", (limit,)).fetchall()

    def totals(self) -> dict:
        r = self._c.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount_minor),0) FROM referral_rewards WHERE status='PAID'"
        ).fetchone()
        return {"count": r[0], "paid_minor": r[1]}

    def page_for_referrer(self, referrer_id: int, *, page: int = 0, per_page: int = 8):
        return paged(self._c, columns=self._COLS, frm="referral_rewards", where="WHERE referrer_id=?",
                     params=[referrer_id], order="id DESC", page=page, per_page=per_page,
                     mapper=lambda r: ReferralRewardRecord(*r))


class SqliteDiceRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def record(self, user_id: int, value: int, reward_minor: int) -> DiceRollRecord:
        cur = self._c.execute(
            "INSERT INTO dice_rolls (user_id, value, reward_minor, created_at) VALUES (?, ?, ?, datetime('now'))",
            (user_id, value, reward_minor))
        r = self._c.execute("SELECT id, user_id, value, reward_minor, created_at FROM dice_rolls WHERE id=?",
                            (cur.lastrowid,)).fetchone()
        return DiceRollRecord(*r)

    def set_reward(self, roll_id: int, reward_minor: int) -> None:
        self._c.execute("UPDATE dice_rolls SET reward_minor=? WHERE id=?", (reward_minor, roll_id))

    def payout_today(self) -> int:
        return self._c.execute(
            "SELECT COALESCE(SUM(reward_minor),0) FROM dice_rolls WHERE date(created_at)=date('now')"
        ).fetchone()[0]

    def stats(self) -> dict:
        r = self._c.execute(
            "SELECT COUNT(*), COALESCE(SUM(reward_minor),0), COALESCE(SUM(value=6),0) FROM dice_rolls"
        ).fetchone()
        return {"rolls": r[0], "paid_minor": r[1], "wins": r[2], "today_minor": self.payout_today()}
