from __future__ import annotations
import sqlite3
from typing import Optional, Sequence
from repository.interface import InventoryItemRecord
from repository.sqlite._util import paged


class SqliteInventoryRepository:
    """
    پورت مستقیم `claim_config_locked` قدیمی. تضمین ضدِ race-condition دقیقاً
    حفظ شده: این Repository همیشه داخل تراکنش `BEGIN IMMEDIATE` صدا زده می‌شود
    (توسط SqliteUnitOfWork)، پس همان قفل نوشتن فوری قبلی برقرار است.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def claim_one(self, product_id: int, claimer_id: int) -> Optional[InventoryItemRecord]:
        row = self._c.execute(
            "SELECT id, product_id, item_type, content FROM inventory_items "
            "WHERE product_id=? AND status='AVAILABLE' ORDER BY id LIMIT 1",
            (product_id,),
        ).fetchone()
        if not row:
            return None
        item_id = row[0]
        self._c.execute(
            "UPDATE inventory_items SET status='CLAIMED', claimed_by=?, claimed_at=datetime('now') "
            "WHERE id=?",
            (claimer_id, item_id),
        )
        return InventoryItemRecord(
            id=item_id, product_id=row[1], item_type=row[2], content=row[3],
            status="CLAIMED", claimed_by=claimer_id, claimed_at=None,
        )

    def get_by_id(self, item_id: int) -> Optional[InventoryItemRecord]:
        row = self._c.execute(
            "SELECT id, product_id, item_type, content, status, claimed_by, claimed_at "
            "FROM inventory_items WHERE id=?",
            (item_id,),
        ).fetchone()
        return InventoryItemRecord(*row) if row else None

    def count_available(self, product_id: int) -> int:
        return self._c.execute(
            "SELECT COUNT(*) FROM inventory_items WHERE product_id=? AND status='AVAILABLE'",
            (product_id,),
        ).fetchone()[0]

    def add_items(self, product_id: int, item_type: str, contents: Sequence[str]) -> int:
        added = 0
        for content in contents:
            self._c.execute(
                "INSERT INTO inventory_items (product_id, item_type, content, status) "
                "VALUES (?, ?, ?, 'AVAILABLE')",
                (product_id, item_type, content),
            )
            added += 1
        return added

    def delete_unclaimed(self, product_id: int, limit: int) -> int:
        rows = self._c.execute(
            "SELECT id FROM inventory_items WHERE product_id=? AND status='AVAILABLE' LIMIT ?",
            (product_id, limit),
        ).fetchall()
        for (item_id,) in rows:
            self._c.execute("DELETE FROM inventory_items WHERE id=?", (item_id,))
        return len(rows)

    def existing_contents(self, product_id: int, contents: Sequence[str]) -> set:
        found = set()
        for c in contents:
            if self._c.execute(
                "SELECT 1 FROM inventory_items WHERE product_id=? AND content=? LIMIT 1",
                (product_id, c),
            ).fetchone():
                found.add(c)
        return found

    def page(self, product_id: int, *, status=None, page: int = 0, per_page: int = 8):
        conds, params = ["product_id=?"], [product_id]
        if status:
            conds.append("status=?"); params.append(status)
        return paged(
            self._c, columns="id, product_id, item_type, content, status, claimed_by, claimed_at",
            frm="inventory_items", where="WHERE " + " AND ".join(conds), params=params,
            order="id DESC", page=page, per_page=per_page,
            mapper=lambda r: InventoryItemRecord(*r))

    def delete_available_item(self, item_id: int) -> bool:
        cur = self._c.execute("DELETE FROM inventory_items WHERE id=? AND status='AVAILABLE'", (item_id,))
        return cur.rowcount > 0

    def reserve_placeholder(self, product_id: int, item_type: str, claimer_id: int) -> InventoryItemRecord:
        cur = self._c.execute(
            "INSERT INTO inventory_items (product_id, item_type, content, status, claimed_by, claimed_at) "
            "VALUES (?, ?, '', 'RESERVED', ?, datetime('now'))", (product_id, item_type, claimer_id))
        return InventoryItemRecord(cur.lastrowid, product_id, item_type, "", "RESERVED", claimer_id, None)

    def fulfil_placeholder(self, item_id: int, content: str) -> None:
        self._c.execute(
            "UPDATE inventory_items SET content=?, status='CLAIMED' WHERE id=? AND status='RESERVED'",
            (content, item_id))

    def void_item(self, item_id: int) -> None:
        self._c.execute("UPDATE inventory_items SET status='VOID', content='' WHERE id=?", (item_id,))

    def counts_by_product(self) -> dict:
        rows = self._c.execute(
            "SELECT product_id, COUNT(*) FROM inventory_items WHERE status='AVAILABLE' GROUP BY product_id"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
