"""
GhYiAb V2 — National Net Stock Service
=======================================

سیستم مدیریت استوک کانفیگ‌های نِت ملی (National Net)
- nm_config_stock: استوک کانفیگ‌های خام از پنل‌ها
- nm_stock_shelves: قفسه‌بندی و دسته‌بندی استوک
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from bootstrap import AppContext
from core.errors import ValidationError, NotFoundError, DomainError
from core.audit import service as audit_service

logger = logging.getLogger("ghyiab.core.national_net_stock")


class NationalNetStockError(DomainError):
    pass


class StockNotAvailableError(NationalNetStockError):
    pass


class ShelfNotFoundError(NationalNetStockError):
    pass


@dataclass(frozen=True)
class StockConfig:
    id: int
    provider_id: int
    inbound_id: Optional[int]
    protocol: Optional[str]
    remark: Optional[str]
    config_str: str
    used: bool
    created_at: str


@dataclass(frozen=True)
class StockShelf:
    id: int
    shelf_name: str
    shelf_type: str
    configs: list[int]  # List of config IDs
    active: bool
    created_at: str


# =============================================================================
# Stock Config Management
# =============================================================================

def add_stock_config(
    app_ctx: AppContext,
    actor_id: int,
    provider_id: int,
    config_str: str,
    inbound_id: Optional[int] = None,
    protocol: Optional[str] = None,
    remark: Optional[str] = None
) -> StockConfig:
    """Add a single config to national net stock."""
    with app_ctx.unit_of_work() as uow:
        # Verify provider exists
        provider_row = uow.conn.execute(
            "SELECT id, name FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if not provider_row:
            raise NotFoundError("Provider not found")

        cursor = uow.conn.execute("""
            INSERT INTO nm_config_stock (provider_id, inbound_id, protocol, remark, config_str, used, created_at)
            VALUES (?, ?, ?, ?, ?, 0, datetime('now'))
        """, (provider_id, inbound_id, protocol, remark, config_str))
        config_id = cursor.lastrowid
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="stock_config_added",
            entity_type="nm_config_stock", entity_id=str(config_id),
            after_json={"provider_id": provider_id, "inbound_id": inbound_id, "protocol": protocol}
        )

        return _row_to_config(uow.conn.execute("SELECT * FROM nm_config_stock WHERE id = ?", (config_id,)).fetchone())


def add_stock_configs_bulk(
    app_ctx: AppContext,
    actor_id: int,
    provider_id: int,
    configs: list[dict],  # Each: {config_str, inbound_id?, protocol?, remark?}
    shelf_id: Optional[int] = None
) -> list[StockConfig]:
    """Bulk add configs to stock, optionally assign to shelf."""
    with app_ctx.unit_of_work() as uow:
        provider_row = uow.conn.execute("SELECT id FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if not provider_row:
            raise NotFoundError("Provider not found")

        if shelf_id:
            shelf_row = uow.conn.execute("SELECT id, configs FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone()
            if not shelf_row:
                raise ShelfNotFoundError("Shelf not found")
            existing_configs = json.loads(shelf_row[1]) if shelf_row[1] else []
        else:
            existing_configs = []

        new_config_ids = []
        for cfg in configs:
            cursor = uow.conn.execute("""
                INSERT INTO nm_config_stock (provider_id, inbound_id, protocol, remark, config_str, used, created_at)
                VALUES (?, ?, ?, ?, ?, 0, datetime('now'))
            """, (provider_id, cfg.get("inbound_id"), cfg.get("protocol"), cfg.get("remark"), cfg["config_str"]))
            new_config_ids.append(cursor.lastrowid)

        if shelf_id:
            updated_configs = existing_configs + new_config_ids
            uow.conn.execute(
                "UPDATE nm_stock_shelves SET configs = ? WHERE id = ?",
                (json.dumps(updated_configs), shelf_id)
            )

        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="stock_configs_bulk_added",
            entity_type="nm_config_stock", entity_id=f"bulk_{len(configs)}",
            after_json={"provider_id": provider_id, "count": len(configs), "shelf_id": shelf_id}
        )

        results = []
        for cid in new_config_ids:
            row = uow.conn.execute("SELECT * FROM nm_config_stock WHERE id = ?", (cid,)).fetchone()
            results.append(_row_to_config(row))
        return results


def get_available_stock(app_ctx: AppContext, provider_id: Optional[int] = None, limit: int = 100) -> list[StockConfig]:
    """Get available (unused) stock configs."""
    with app_ctx.unit_of_work() as uow:
        if provider_id:
            rows = uow.conn.execute("""
                SELECT * FROM nm_config_stock
                WHERE used = 0 AND provider_id = ?
                ORDER BY created_at ASC LIMIT ?
            """, (provider_id, limit)).fetchall()
        else:
            rows = uow.conn.execute("""
                SELECT * FROM nm_config_stock
                WHERE used = 0
                ORDER BY created_at ASC LIMIT ?
            """, (limit,)).fetchall()
        return [_row_to_config(r) for r in rows]


def claim_stock_config(app_ctx: AppContext, actor_id: int, config_id: int) -> StockConfig:
    """Claim (mark as used) a stock config."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM nm_config_stock WHERE id = ?", (config_id,)).fetchone()
        if not row:
            raise NotFoundError("Stock config not found")
        if row[6]:  # used column
            raise StockNotAvailableError("Config already claimed")

        uow.conn.execute(
            "UPDATE nm_config_stock SET used = 1 WHERE id = ?", (config_id,)
        )
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="stock_config_claimed",
            entity_type="nm_config_stock", entity_id=str(config_id),
            before_json={"used": 0}, after_json={"used": 1}
        )

        return _row_to_config(uow.conn.execute("SELECT * FROM nm_config_stock WHERE id = ?", (config_id,)).fetchone())


def get_stock_stats(app_ctx: AppContext) -> dict:
    """Get stock statistics."""
    with app_ctx.unit_of_work() as uow:
        total = uow.conn.execute("SELECT COUNT(*) FROM nm_config_stock").fetchone()[0]
        used = uow.conn.execute("SELECT COUNT(*) FROM nm_config_stock WHERE used = 1").fetchone()[0]
        available = total - used

        by_provider = uow.conn.execute("""
            SELECT p.name, p.id, COUNT(*) as total, SUM(CASE WHEN used=1 THEN 1 ELSE 0 END) as used
            FROM nm_config_stock s
            JOIN providers p ON p.id = s.provider_id
            GROUP BY p.id, p.name
        """).fetchall()

        by_protocol = uow.conn.execute("""
            SELECT protocol, COUNT(*) as total, SUM(CASE WHEN used=1 THEN 1 ELSE 0 END) as used
            FROM nm_config_stock
            GROUP BY protocol
        """).fetchall()

        return {
            "total": total,
            "used": used,
            "available": available,
            "by_provider": [
                {"provider": r[0], "provider_id": r[1], "total": r[2], "used": r[3], "available": r[2] - r[3]}
                for r in by_provider
            ],
            "by_protocol": [
                {"protocol": r[0] or "unknown", "total": r[1], "used": r[2], "available": r[1] - r[2]}
                for r in by_protocol
            ]
        }


# =============================================================================
# Shelf Management
# =============================================================================

def create_shelf(app_ctx: AppContext, actor_id: int, shelf_name: str, shelf_type: str, config_ids: list[int] = None) -> StockShelf:
    """Create a new stock shelf."""
    with app_ctx.unit_of_work() as uow:
        # Verify configs exist and are available
        if config_ids:
            for cid in config_ids:
                row = uow.conn.execute("SELECT id, used FROM nm_config_stock WHERE id = ?", (cid,)).fetchone()
                if not row:
                    raise NotFoundError(f"Config {cid} not found")
                if row[1]:
                    raise StockNotAvailableError(f"Config {cid} already used")

        configs_json = json.dumps(config_ids or [])
        cursor = uow.conn.execute("""
            INSERT INTO nm_stock_shelves (shelf_name, shelf_type, configs, active, created_at)
            VALUES (?, ?, ?, 1, datetime('now'))
        """, (shelf_name, shelf_type, configs_json))
        shelf_id = cursor.lastrowid
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="stock_shelf_created",
            entity_type="nm_stock_shelves", entity_id=str(shelf_id),
            after_json={"shelf_name": shelf_name, "shelf_type": shelf_type, "config_count": len(config_ids or [])}
        )

        return _row_to_shelf(uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone())


def get_shelf(app_ctx: AppContext, shelf_id: int) -> StockShelf:
    """Get shelf by ID."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone()
        if not row:
            raise ShelfNotFoundError("Shelf not found")
        return _row_to_shelf(row)


def list_shelves(app_ctx: AppContext, active_only: bool = True) -> list[StockShelf]:
    """List all shelves."""
    with app_ctx.unit_of_work() as uow:
        if active_only:
            rows = uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE active = 1 ORDER BY created_at DESC").fetchall()
        else:
            rows = uow.conn.execute("SELECT * FROM nm_stock_shelves ORDER BY created_at DESC").fetchall()
        return [_row_to_shelf(r) for r in rows]


def add_configs_to_shelf(app_ctx: AppContext, actor_id: int, shelf_id: int, config_ids: list[int]) -> StockShelf:
    """Add configs to an existing shelf."""
    with app_ctx.unit_of_work() as uow:
        shelf_row = uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone()
        if not shelf_row:
            raise ShelfNotFoundError("Shelf not found")

        existing = json.loads(shelf_row[3]) if shelf_row[3] else []

        # Verify all configs exist and are available
        for cid in config_ids:
            row = uow.conn.execute("SELECT id, used FROM nm_config_stock WHERE id = ?", (cid,)).fetchone()
            if not row:
                raise NotFoundError(f"Config {cid} not found")
            if row[1]:
                raise StockNotAvailableError(f"Config {cid} already used")
            if cid in existing:
                raise ValidationError(f"Config {cid} already in shelf")

        updated = existing + config_ids
        uow.conn.execute("UPDATE nm_stock_shelves SET configs = ? WHERE id = ?", (json.dumps(updated), shelf_id))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="stock_shelf_configs_added",
            entity_type="nm_stock_shelves", entity_id=str(shelf_id),
            after_json={"added_count": len(config_ids)}
        )

        return _row_to_shelf(uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone())


def remove_configs_from_shelf(app_ctx: AppContext, actor_id: int, shelf_id: int, config_ids: list[int]) -> StockShelf:
    """Remove configs from shelf (makes them available again)."""
    with app_ctx.unit_of_work() as uow:
        shelf_row = uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone()
        if not shelf_row:
            raise ShelfNotFoundError("Shelf not found")

        existing = json.loads(shelf_row[3]) if shelf_row[3] else []
        updated = [cid for cid in existing if cid not in config_ids]

        uow.conn.execute("UPDATE nm_stock_shelves SET configs = ? WHERE id = ?", (json.dumps(updated), shelf_id))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="stock_shelf_configs_removed",
            entity_type="nm_stock_shelves", entity_id=str(shelf_id),
            after_json={"removed_count": len(config_ids)}
        )

        return _row_to_shelf(uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone())


def delete_shelf(app_ctx: AppContext, actor_id: int, shelf_id: int) -> None:
    """Delete a shelf (configs remain in stock)."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM nm_stock_shelves WHERE id = ?", (shelf_id,)).fetchone()
        if not row:
            raise ShelfNotFoundError("Shelf not found")

        uow.conn.execute("DELETE FROM nm_stock_shelves WHERE id = ?", (shelf_id,))
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=actor_id, action="stock_shelf_deleted",
            entity_type="nm_stock_shelves", entity_id=str(shelf_id),
            before_json={"shelf_name": row[1], "config_count": len(json.loads(row[3]) if row[3] else [])}
        )


# =============================================================================
# QR Code Generation
# =============================================================================

def generate_qr_code(config_str: str) -> bytes:
    """Generate QR code image for config string."""
    try:
        import qrcode
        from io import BytesIO

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(config_str)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        raise NationalNetStockError("qrcode library not installed. Run: pip install qrcode[pil]")


def generate_qr_for_config(app_ctx: AppContext, config_id: int) -> bytes:
    """Generate QR code for a stock config."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT config_str FROM nm_config_stock WHERE id = ?", (config_id,)).fetchone()
        if not row:
            raise NotFoundError("Config not found")
        return generate_qr_code(row[0])


# =============================================================================
# Invoice to Panel Conversion
# =============================================================================

def convert_invoice_to_panel(
    app_ctx: AppContext,
    actor_id: int,
    invoice_id: int,
    provider_id: int,
    inbound_id: int
) -> StockConfig:
    """
    Convert a paid invoice to a panel config by claiming from national net stock.
    This implements the 'invoice-to-panel' flow from Faoxima.
    """
    with app_ctx.unit_of_work() as uow:
        # Get invoice details
        inv_row = uow.conn.execute("""
            SELECT pr.*, p.name as product_name
            FROM pending_requests pr
            LEFT JOIN products p ON p.id = pr.product_id
            WHERE pr.id = ?
        """, (invoice_id,)).fetchone()

        if not inv_row:
            raise NotFoundError("Invoice not found")

        if inv_row[6] != 'approved':  # status column
            raise ValidationError("Invoice not approved")

        # Get available stock for this provider
        stock = get_available_stock(app_ctx, provider_id, limit=1)
        if not stock:
            raise StockNotAvailableError("No available stock for this provider")

        config = stock[0]

        # Claim the config
        claimed = claim_stock_config(app_ctx, actor_id, config.id)

        # Update inventory with the config
        # (This would integrate with inventory_service to assign to user)

        audit_service.log(
            uow, actor_id=actor_id, action="invoice_converted_to_panel",
            entity_type="pending_requests", entity_id=str(invoice_id),
            after_json={"stock_config_id": claimed.id, "provider_id": provider_id, "inbound_id": inbound_id}
        )

        return claimed


# =============================================================================
# Stock Delivery with QR
# =============================================================================

def deliver_stock_with_qr(app_ctx: AppContext, user_id: int, config_id: int) -> dict:
    """Deliver a stock config to user with QR code."""
    with app_ctx.unit_of_work() as uow:
        config = claim_stock_config(app_ctx, user_id, config_id)
        qr_bytes = generate_qr_code(config.config_str)

        audit_service.log(
            uow, actor_id=user_id, action="stock_delivered_with_qr",
            entity_type="nm_config_stock", entity_id=str(config_id),
            after_json={"delivered": True}
        )

        return {
            "config": config,
            "qr_code": qr_bytes,
            "config_str": config.config_str
        }


# =============================================================================
# Helper Functions
# =============================================================================

def _row_to_config(row: tuple) -> StockConfig:
    return StockConfig(
        id=row[0], provider_id=row[1], inbound_id=row[2], protocol=row[3],
        remark=row[4], config_str=row[5], used=bool(row[6]), created_at=row[7]
    )


def _row_to_shelf(row: tuple) -> StockShelf:
    configs = json.loads(row[3]) if row[3] else []
    return StockShelf(
        id=row[0], shelf_name=row[1], shelf_type=row[2],
        configs=configs, active=bool(row[4]), created_at=row[5]
    )