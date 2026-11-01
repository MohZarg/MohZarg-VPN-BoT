from __future__ import annotations
from typing import Optional
from repository.sqlite.connection import get_conn


class SqliteSettingsRepository:
    """پورت مستقیم get_setting/set_setting قدیمی."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with get_conn(self._db_path) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        with get_conn(self._db_path) as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            conn.commit()
