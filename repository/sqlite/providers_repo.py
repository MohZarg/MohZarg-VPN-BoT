from __future__ import annotations
import sqlite3
from typing import Optional, Sequence
from repository.interface import ProviderRecord


class SqliteProvidersRepository:
    """
    ثبت وضعیت واقعی Providerها (طبق اصل No Fake Integration). این Repository
    هرگز به یک Provider واقعی متصل نمی‌شود — فقط وضعیتی که Adapter بیرونی
    (مثل xui_provider.py) گزارش می‌دهد را نگه می‌دارد.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def get_by_name(self, name: str) -> Optional[ProviderRecord]:
        row = self._c.execute(
            "SELECT id, name, type, status, config_ref, updated_at "
            "FROM providers WHERE name=?",
            (name,),
        ).fetchone()
        return ProviderRecord(*row) if row else None

    def list_all(self) -> Sequence[ProviderRecord]:
        rows = self._c.execute(
            "SELECT id, name, type, status, config_ref, updated_at FROM providers ORDER BY id"
        ).fetchall()
        return [ProviderRecord(*r) for r in rows]

    def set_status(self, name: str, status: str) -> None:
        self._c.execute(
            "UPDATE providers SET status=?, updated_at=datetime('now') WHERE name=?",
            (status, name),
        )

    def upsert(self, name: str, type_: str, status: str,
               config_ref: Optional[str] = None) -> ProviderRecord:
        self._c.execute(
            "INSERT INTO providers (name, type, status, config_ref, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET type=excluded.type, status=excluded.status, "
            "config_ref=excluded.config_ref, updated_at=datetime('now')",
            (name, type_, status, config_ref),
        )
        return self.get_by_name(name)
