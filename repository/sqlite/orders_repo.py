from __future__ import annotations
import sqlite3
from typing import Optional, Sequence
from repository.interface import OrderRecord, OrderItemRecord
from repository.sqlite._util import paged

_COLS = ("id, user_id, product_id, inventory_item_id, price_minor, currency, status, "
         "idempotency_key, created_at, refunded_at, discount_minor, coupon_code")


class SqliteOrdersRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, user_id: int, product_id: int, inventory_item_id: int,
               price_minor: int, currency: str, idempotency_key: Optional[str] = None,
               variant_id: Optional[int] = None, status: str = "COMPLETED") -> OrderRecord:
        cur = self._c.execute(
            "INSERT INTO orders (user_id, product_id, inventory_item_id, price_minor, "
            "currency, status, idempotency_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (user_id, product_id, inventory_item_id, price_minor, currency, status, idempotency_key),
        )
        order_id = cur.lastrowid
        # هر سفارش دقیقاً یک OrderItem متناظر می‌گیرد (پایهٔ خط‌آیتمی)
        self._c.execute(
            "INSERT INTO order_items (order_id, product_id, variant_id, "
            "inventory_item_id, quantity, price_minor, currency) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (order_id, product_id, variant_id, inventory_item_id, price_minor, currency),
        )
        return OrderRecord(
            id=order_id, user_id=user_id, product_id=product_id,
            inventory_item_id=inventory_item_id, price_minor=price_minor,
            currency=currency, status=status, idempotency_key=idempotency_key, created_at="",
        )

    def list_by_user(self, user_id: int) -> Sequence[OrderRecord]:
        rows = self._c.execute(
            f"SELECT {_COLS} FROM orders WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
        return [OrderRecord(*r) for r in rows]

    def get_by_id(self, order_id: int) -> Optional[OrderRecord]:
        row = self._c.execute(f"SELECT {_COLS} FROM orders WHERE id=?", (order_id,)).fetchone()
        return OrderRecord(*row) if row else None

    def get_by_idempotency_key(self, key: str) -> Optional[OrderRecord]:
        row = self._c.execute(f"SELECT {_COLS} FROM orders WHERE idempotency_key=?", (key,)).fetchone()
        return OrderRecord(*row) if row else None

    def list_items(self, order_id: int) -> Sequence[OrderItemRecord]:
        rows = self._c.execute(
            "SELECT id, order_id, product_id, variant_id, inventory_item_id, "
            "quantity, price_minor, currency FROM order_items WHERE order_id=? ORDER BY id",
            (order_id,),
        ).fetchall()
        return [OrderItemRecord(*r) for r in rows]

    def page(self, *, status: Optional[str] = None, user_id: Optional[int] = None,
             page: int = 0, per_page: int = 8):
        conds, params = [], []
        if status:
            conds.append("status=?"); params.append(status)
        if user_id is not None:
            conds.append("user_id=?"); params.append(user_id)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return paged(self._c, columns=_COLS, frm="orders", where=where, params=params,
                     order="id DESC", page=page, per_page=per_page, mapper=lambda r: OrderRecord(*r))

    def set_status(self, order_id: int, status: str) -> None:
        self._c.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))

    def mark_refunded(self, order_id: int) -> bool:
        """اتمیک: فقط اگر COMPLETED (یا PROVISIONING = پرداخت‌شدهٔ صادرنشده) باشد REFUNDED می‌شود (مانع بازپرداخت دوباره)."""
        cur = self._c.execute(
            "UPDATE orders SET status='REFUNDED', refunded_at=datetime('now') "
            "WHERE id=? AND status IN ('COMPLETED','PROVISIONING')", (order_id,))
        return cur.rowcount > 0

    def set_discount(self, order_id: int, discount_minor: int, coupon_code: Optional[str]) -> None:
        self._c.execute("UPDATE orders SET discount_minor=?, coupon_code=? WHERE id=?",
                        (discount_minor, coupon_code, order_id))
