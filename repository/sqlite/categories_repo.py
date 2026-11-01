from __future__ import annotations
import sqlite3
from typing import Optional, Sequence
from repository.interface import CategoryRecord


class SqliteCategoriesRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, name: str, parent_id: Optional[int] = None) -> CategoryRecord:
        cur = self._c.execute(
            "INSERT INTO categories (name, parent_id, created_at) "
            "VALUES (?, ?, datetime('now'))",
            (name, parent_id),
        )
        row = self._c.execute(
            "SELECT id, name, parent_id, created_at FROM categories WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
        return CategoryRecord(*row)

    def get(self, category_id: int) -> Optional[CategoryRecord]:
        row = self._c.execute(
            "SELECT id, name, parent_id, created_at FROM categories WHERE id=?",
            (category_id,),
        ).fetchone()
        return CategoryRecord(*row) if row else None

    def list_all(self) -> Sequence[CategoryRecord]:
        rows = self._c.execute(
            "SELECT id, name, parent_id, created_at FROM categories ORDER BY id"
        ).fetchall()
        return [CategoryRecord(*r) for r in rows]

    def delete(self, category_id: int) -> None:
        self._c.execute("UPDATE products SET category_id=NULL WHERE category_id=?", (category_id,))
        self._c.execute("DELETE FROM categories WHERE id=?", (category_id,))

    def rename(self, category_id: int, name: str) -> None:
        self._c.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))
