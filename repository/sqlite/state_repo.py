"""
GhYiAb V2 — Persistent State Repository
==========================================

جایگزین مستقیم `user_states = {}` سراسری قدیمی. تفاوت کلیدی: این حالت در
SQLite ذخیره می‌شود، پس با ری‌استارت پردازه از بین نمی‌رود (رفع P0-5 در
Audit). فرمت داده (JSON دلخواه: رشته یا dict) دقیقاً همان چیزی است که ربات
فعلی در `user_states[user_id]` می‌گذاشت — فقط جایگاه ذخیره عوض شده، نه شکل آن.
"""

from __future__ import annotations

import json
from typing import Optional

from repository.sqlite.connection import get_conn


class SqliteStateRepository:
    def __init__(self, db_path: str):
        self._db_path = db_path

    def get(self, user_id: int):
        with get_conn(self._db_path) as conn:
            row = conn.execute(
                "SELECT state_json FROM user_states WHERE user_id=?", (user_id,)
            ).fetchone()
        if not row or row[0] is None:
            return None
        return json.loads(row[0])

    def set(self, user_id: int, state) -> None:
        payload: Optional[str] = None if state is None else json.dumps(state, ensure_ascii=False)
        with get_conn(self._db_path) as conn:
            conn.execute(
                "INSERT INTO user_states (user_id, state_json, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json, "
                "updated_at=excluded.updated_at",
                (user_id, payload),
            )
            conn.commit()

    def clear(self, user_id: int) -> None:
        self.set(user_id, None)

    def purge_stale(self, hours: int) -> int:
        """TTL: حالت‌های قدیمی/خالی حذف می‌شوند تا جدول و رفتار کاربر «گیرکرده» نماند."""
        with get_conn(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM user_states WHERE state_json IS NULL OR updated_at <= datetime('now', ?)",
                (f"-{int(hours)} hours",))
            conn.commit()
            return cur.rowcount
