from __future__ import annotations
import sqlite3
from typing import Optional
from repository.interface import PendingRequestRecord
from repository.sqlite._util import paged

_COLUMNS = (
    "id, type, user_id, product_id, amount_minor, currency, status, created_at, "
    "idempotency_key, resolution_note, resolved_by, receipt_file_id, receipt_unique_id, "
    "coupon_code, expected_price_minor"
)


class SqlitePendingRequestsRepository:
    """پورت مستقیم `create_pending_request`/`resolve_pending_request` قدیمی + امکانات Phase 5."""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, req_type: str, user_id: int, product_id: Optional[int] = None,
               amount_minor: Optional[int] = None, currency: Optional[str] = None,
               idempotency_key: Optional[str] = None) -> int:
        cur = self._c.execute(
            "INSERT INTO pending_requests (type, user_id, product_id, amount_minor, "
            "currency, status, idempotency_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, datetime('now'))",
            (req_type, user_id, product_id, amount_minor, currency, idempotency_key),
        )
        return cur.lastrowid

    def resolve(self, req_id: int, new_status: str) -> Optional[PendingRequestRecord]:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM pending_requests WHERE id=? AND status='pending'", (req_id,)
        ).fetchone()
        if not row:
            return None
        self._c.execute(
            "UPDATE pending_requests SET status=?, resolved_at=datetime('now') WHERE id=?",
            (new_status, req_id),
        )
        return PendingRequestRecord(*row)

    def get(self, req_id: int) -> Optional[PendingRequestRecord]:
        row = self._c.execute(f"SELECT {_COLUMNS} FROM pending_requests WHERE id=?", (req_id,)).fetchone()
        return PendingRequestRecord(*row) if row else None

    def find_pending_by_type_and_user(self, req_type: str, user_id: int) -> Optional[PendingRequestRecord]:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM pending_requests WHERE type=? AND user_id=? AND status='pending'",
            (req_type, user_id),
        ).fetchone()
        return PendingRequestRecord(*row) if row else None

    def find_by_idempotency_key(self, key: str) -> Optional[PendingRequestRecord]:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM pending_requests WHERE idempotency_key=?", (key,)).fetchone()
        return PendingRequestRecord(*row) if row else None

    def find_by_receipt_unique_id(self, unique_id: str) -> Optional[PendingRequestRecord]:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM pending_requests WHERE receipt_unique_id=? ORDER BY id LIMIT 1",
            (unique_id,)).fetchone()
        return PendingRequestRecord(*row) if row else None

    def count_pending(self) -> int:
        return self._c.execute("SELECT COUNT(*) FROM pending_requests WHERE status='pending'").fetchone()[0]

    def page(self, *, status: Optional[str] = None, req_type: Optional[str] = None,
             page: int = 0, per_page: int = 8):
        conds, params = [], []
        if status:
            conds.append("status=?"); params.append(status)
        if req_type:
            conds.append("type=?"); params.append(req_type)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return paged(self._c, columns=_COLUMNS, frm="pending_requests", where=where, params=params,
                     order="id DESC", page=page, per_page=per_page,
                     mapper=lambda r: PendingRequestRecord(*r))

    def count_pending_with_coupon(self, coupon_code: str, user_id: Optional[int] = None) -> int:
        sql = "SELECT COUNT(*) FROM pending_requests WHERE coupon_code=? AND status='pending'"
        args = [coupon_code]
        if user_id is not None:
            sql += " AND user_id=?"
            args.append(user_id)
        return self._c.execute(sql, args).fetchone()[0]

    def find_active_by_receipt_unique_id(self, unique_id: str) -> Optional[PendingRequestRecord]:
        row = self._c.execute(
            f"SELECT {_COLUMNS} FROM pending_requests WHERE receipt_unique_id=? "
            "AND status IN ('pending','approved') ORDER BY id LIMIT 1", (unique_id,),
        ).fetchone()
        return PendingRequestRecord(*row) if row else None

    def set_receipt(self, req_id: int, file_id: str, unique_id: Optional[str]) -> None:
        self._c.execute("UPDATE pending_requests SET receipt_file_id=?, receipt_unique_id=? WHERE id=?",
                        (file_id, unique_id, req_id))

    def set_coupon(self, req_id: int, coupon_code: Optional[str], expected_price_minor: Optional[int]) -> None:
        self._c.execute("UPDATE pending_requests SET coupon_code=?, expected_price_minor=? WHERE id=?",
                        (coupon_code, expected_price_minor, req_id))

    def set_resolution(self, req_id: int, actor_id: int, note: Optional[str]) -> None:
        self._c.execute("UPDATE pending_requests SET resolved_by=?, resolution_note=? WHERE id=?",
                        (actor_id, note, req_id))

    def expire_older_than(self, hours: int) -> int:
        cur = self._c.execute(
            "UPDATE pending_requests SET status='expired', resolved_at=datetime('now') "
            "WHERE status='pending' AND created_at < datetime('now', ?)", (f"-{int(hours)} hours",))
        return cur.rowcount
