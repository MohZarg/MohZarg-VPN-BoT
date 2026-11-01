from __future__ import annotations
import sqlite3
from typing import Optional, Sequence
from repository.interface import ProductRecord
from repository.sqlite._util import paged

_COLS = "id, name, price_minor, currency, description, qr_file_id, is_active"


def _map(r) -> ProductRecord:
    return ProductRecord(r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6]))


class SqliteProductsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def get(self, product_id: int) -> Optional[ProductRecord]:
        row = self._c.execute(f"SELECT {_COLS} FROM products WHERE id=?", (product_id,)).fetchone()
        return _map(row) if row else None

    def list_all(self) -> Sequence[ProductRecord]:
        return [_map(r) for r in self._c.execute(f"SELECT {_COLS} FROM products ORDER BY id").fetchall()]

    def list_active(self) -> Sequence[ProductRecord]:
        return [_map(r) for r in self._c.execute(
            f"SELECT {_COLS} FROM products WHERE is_active=1 ORDER BY id").fetchall()]

    def list_by_category(self, category_id: int) -> Sequence[ProductRecord]:
        rows = self._c.execute(
            f"SELECT {_COLS} FROM products WHERE category_id=? ORDER BY id", (category_id,)
        ).fetchall()
        return [_map(r) for r in rows]

    def page(self, *, page: int = 0, per_page: int = 8):
        return paged(self._c, columns=_COLS, frm="products", where="", params=[],
                     order="id DESC", page=page, per_page=per_page, mapper=_map)

    def create(self, name: str, price_minor: int, currency: str,
               description: Optional[str] = None,
               category_id: Optional[int] = None) -> ProductRecord:
        cur = self._c.execute(
            "INSERT INTO products (name, price_minor, currency, description, category_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, price_minor, currency, description, category_id),
        )
        return ProductRecord(
            id=cur.lastrowid, name=name, price_minor=price_minor,
            currency=currency, description=description, qr_file_id=None, is_active=True,
        )

    def set_category(self, product_id: int, category_id: Optional[int]) -> None:
        self._c.execute("UPDATE products SET category_id=? WHERE id=?", (category_id, product_id))

    def set_active(self, product_id: int, is_active: bool) -> None:
        self._c.execute("UPDATE products SET is_active=? WHERE id=?", (int(is_active), product_id))

    def update(self, product_id: int, *, name: Optional[str] = None,
               price_minor: Optional[int] = None) -> None:
        if name is not None:
            self._c.execute("UPDATE products SET name=? WHERE id=?", (name, product_id))
        if price_minor is not None:
            self._c.execute("UPDATE products SET price_minor=? WHERE id=?", (price_minor, product_id))

    def count_orders(self, product_id: int) -> int:
        return self._c.execute("SELECT COUNT(*) FROM orders WHERE product_id=?", (product_id,)).fetchone()[0]

    def set_qr_file_id(self, product_id: int, file_id: str) -> None:
        self._c.execute("UPDATE products SET qr_file_id=? WHERE id=?", (file_id, product_id))

    def delete(self, product_id: int) -> None:
        self._c.execute("DELETE FROM product_variants WHERE product_id=?", (product_id,))
        self._c.execute("DELETE FROM provisioning_profiles WHERE product_id=?", (product_id,))
        self._c.execute("DELETE FROM products WHERE id=?", (product_id,))
        self._c.execute(
            "DELETE FROM inventory_items WHERE product_id=? AND status='AVAILABLE'", (product_id,)
        )
