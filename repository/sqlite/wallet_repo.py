from __future__ import annotations
import sqlite3
from typing import Optional, Sequence
from repository.interface import WalletTransactionRecord


class SqliteWalletRepository:
    """
    پورت مستقیم منطق `adjust_balance` قدیمی، با افزودن ستون currency و
    idempotency_key — رفتار (اتمیک بودن داخل تراکنش UnitOfWork) بدون تغییر.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def get_balance(self, user_id: int, currency: str) -> int:
        row = self._c.execute(
            "SELECT amount_minor FROM wallets WHERE user_id=? AND currency=?",
            (user_id, currency),
        ).fetchone()
        return row[0] if row else 0

    def adjust(self, user_id: int, currency: str, delta_minor: int) -> int:
        self._c.execute(
            "INSERT INTO wallets (user_id, currency, amount_minor) VALUES (?, ?, 0) "
            "ON CONFLICT(user_id, currency) DO NOTHING",
            (user_id, currency),
        )
        self._c.execute(
            "UPDATE wallets SET amount_minor = amount_minor + ? WHERE user_id=? AND currency=?",
            (delta_minor, user_id, currency),
        )
        return self.get_balance(user_id, currency)

    def debit_if_sufficient(self, user_id: int, currency: str, amount_minor: int) -> bool:
        self._c.execute(
            "INSERT INTO wallets (user_id, currency, amount_minor) VALUES (?, ?, 0) "
            "ON CONFLICT(user_id, currency) DO NOTHING",
            (user_id, currency),
        )
        cur = self._c.execute(
            "UPDATE wallets SET amount_minor = amount_minor - ? "
            "WHERE user_id=? AND currency=? AND amount_minor >= ?",
            (amount_minor, user_id, currency, amount_minor),
        )
        return cur.rowcount > 0

    def record_transaction(self, user_id: int, currency: str, amount_minor: int,
                            balance_after_minor: int, reason: str,
                            idempotency_key: Optional[str] = None) -> int:
        cur = self._c.execute(
            "INSERT INTO wallet_transactions "
            "(user_id, currency, amount_minor, balance_after_minor, reason, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (user_id, currency, amount_minor, balance_after_minor, reason, idempotency_key),
        )
        return cur.lastrowid

    def find_transaction_by_idempotency_key(self, key: str) -> Optional[WalletTransactionRecord]:
        row = self._c.execute(
            "SELECT id, user_id, currency, amount_minor, balance_after_minor, reason, "
            "idempotency_key, created_at FROM wallet_transactions WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        return WalletTransactionRecord(*row)

    def list_recent_transactions(self, user_id: int, limit: int = 10) -> Sequence[WalletTransactionRecord]:
        rows = self._c.execute(
            "SELECT id, user_id, currency, amount_minor, balance_after_minor, reason, "
            "idempotency_key, created_at FROM wallet_transactions "
            "WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [WalletTransactionRecord(*r) for r in rows]
