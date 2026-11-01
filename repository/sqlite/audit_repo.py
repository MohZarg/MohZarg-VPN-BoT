from __future__ import annotations
import json
import sqlite3
from typing import Optional, Sequence
from repository.interface import AuditLogRecord
from repository.sqlite._util import paged, like_escape


class SqliteAuditRepository:
    """
    پیاده‌سازی AuditLog — طبق تصمیم Owner یک P0 فیکس اجباری است، نه اختیاری.
    هر رکورد شامل actor، action، entity، و حالت قبل/بعد (برای Rollback دستی).
    """

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def append(self, actor_id: int, action: str, entity_type: str, entity_id: str,
               before: Optional[dict], after: Optional[dict]) -> int:
        cur = self._c.execute(
            "INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, "
            "before_json, after_json, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                actor_id, action, entity_type, str(entity_id),
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None,
            ),
        )
        return cur.lastrowid

    def list_recent(self, limit: int = 50) -> Sequence[AuditLogRecord]:
        rows = self._c.execute(
            "SELECT id, actor_id, action, entity_type, entity_id, before_json, "
            "after_json, created_at FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [AuditLogRecord(*r) for r in rows]

    def get(self, log_id: int) -> Optional[AuditLogRecord]:
        row = self._c.execute(
            "SELECT id, actor_id, action, entity_type, entity_id, before_json, "
            "after_json, created_at FROM audit_logs WHERE id=?", (log_id,)).fetchone()
        return AuditLogRecord(*row) if row else None

    def page(self, *, action_prefix=None, actor_id=None, entity_type=None,
             page: int = 0, per_page: int = 8):
        conds, params = [], []
        if action_prefix:
            conds.append("action LIKE ? ESCAPE '\\'"); params.append(like_escape(action_prefix) + "%")
        if actor_id is not None:
            conds.append("actor_id=?"); params.append(actor_id)
        if entity_type:
            conds.append("entity_type=?"); params.append(entity_type)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return paged(
            self._c, columns="id, actor_id, action, entity_type, entity_id, before_json, after_json, created_at",
            frm="audit_logs", where=where, params=params, order="id DESC", page=page,
            per_page=per_page, mapper=lambda r: AuditLogRecord(*r))
