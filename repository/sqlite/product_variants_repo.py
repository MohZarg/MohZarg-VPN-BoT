from __future__ import annotations
import sqlite3
from typing import Optional, Sequence
from repository.interface import ProductVariantRecord


class SqliteProductVariantsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, product_id: int, name: str, price_minor: int, currency: str,
               duration_days: Optional[int] = None,
               traffic_gb: Optional[float] = None) -> ProductVariantRecord:
        cur = self._c.execute(
            "INSERT INTO product_variants "
            "(product_id, name, duration_days, traffic_gb, price_minor, currency, "
            "is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'))",
            (product_id, name, duration_days, traffic_gb, price_minor, currency),
        )
        return self.get(cur.lastrowid)

    def get(self, variant_id: int) -> Optional[ProductVariantRecord]:
        row = self._c.execute(
            "SELECT id, product_id, name, duration_days, traffic_gb, price_minor, "
            "currency, is_active, created_at FROM product_variants WHERE id=?",
            (variant_id,),
        ).fetchone()
        if not row:
            return None
        return ProductVariantRecord(
            id=row[0], product_id=row[1], name=row[2], duration_days=row[3],
            traffic_gb=row[4], price_minor=row[5], currency=row[6],
            is_active=bool(row[7]), created_at=row[8],
        )

    def list_by_product(self, product_id: int) -> Sequence[ProductVariantRecord]:
        rows = self._c.execute(
            "SELECT id, product_id, name, duration_days, traffic_gb, price_minor, "
            "currency, is_active, created_at FROM product_variants "
            "WHERE product_id=? ORDER BY id",
            (product_id,),
        ).fetchall()
        return [
            ProductVariantRecord(
                id=r[0], product_id=r[1], name=r[2], duration_days=r[3],
                traffic_gb=r[4], price_minor=r[5], currency=r[6],
                is_active=bool(r[7]), created_at=r[8],
            )
            for r in rows
        ]

    def set_active(self, variant_id: int, is_active: bool) -> None:
        self._c.execute(
            "UPDATE product_variants SET is_active=? WHERE id=?",
            (1 if is_active else 0, variant_id),
        )
