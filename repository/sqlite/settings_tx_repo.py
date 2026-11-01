from __future__ import annotations
import sqlite3
from typing import Optional


class SqliteSettingsTxRepository:
    """تنظیمات داخل تراکنش UnitOfWork (تا تغییر تنظیم و AuditLog اتمیک باشند)."""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row and row[0] is not None else default

    def set(self, key: str, value: str) -> None:
        self._c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def all(self) -> dict:
        return {r[0]: r[1] for r in self._c.execute("SELECT key, value FROM settings").fetchall()}
