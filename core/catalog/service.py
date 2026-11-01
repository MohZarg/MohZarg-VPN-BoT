"""
GhYiAb V2 — Catalog Core Service (Phase 2.1)
===============================================

مدیریت Category و ProductVariant — ساخته‌شده روی مبنای `core/pricing` و
`core/orders` (Phase 1) بدون تغییر رفتاری در آنها. مقادیر واقعی کاتالوگ
(کدام مدت‌ها/حجم‌ها واقعاً فروخته می‌شوند) طبق TODO حدس زده نمی‌شود — این
سرویس فقط عملیات CRUD روی اسکیمای رزروشده را فراهم می‌کند؛ تصمیم چه
Variant‌هایی ساخته شود با Owner/ادمین است.

هر ساخت/حذف یک اقدام ادمین حساس است ⇒ AuditLog اجباری (طبق تصمیم ثبت‌شده:
«AuditLog for all admin actions is a P0 fix, not optional»).
"""

from __future__ import annotations

from typing import Optional, Sequence

from repository.interface import UnitOfWork, CategoryRecord, ProductVariantRecord, ProductRecord
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ProductNotFoundError, ValidationError, ConflictError, NotFoundError


def create_category(uow: UnitOfWork, actor_id: int, name: str,
                     parent_id: Optional[int] = None) -> CategoryRecord:
    rbac.require(uow, actor_id, "catalog.manage")
    category = uow.categories.create(_check_name(name), parent_id)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.category.create",
        entity_type="category", entity_id=category.id,
        after={"name": name, "parent_id": parent_id},
    )
    return category


def list_categories(uow: UnitOfWork) -> Sequence[CategoryRecord]:
    return uow.categories.list_all()


def delete_category(uow: UnitOfWork, actor_id: int, category_id: int) -> None:
    rbac.require(uow, actor_id, "catalog.manage")
    uow.categories.delete(category_id)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.category.delete",
        entity_type="category", entity_id=category_id,
    )


def assign_product_category(uow: UnitOfWork, actor_id: int, product_id: int,
                             category_id: Optional[int]) -> None:
    rbac.require(uow, actor_id, "catalog.manage")
    if uow.products.get(product_id) is None:
        raise ProductNotFoundError(f"محصول {product_id} یافت نشد")
    uow.products.set_category(product_id, category_id)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.product.set_category",
        entity_type="product", entity_id=product_id,
        after={"category_id": category_id},
    )


def create_variant(uow: UnitOfWork, actor_id: int, product_id: int, name: str,
                    price_minor: int, currency: str,
                    duration_days: Optional[int] = None,
                    traffic_gb: Optional[float] = None) -> ProductVariantRecord:
    rbac.require(uow, actor_id, "catalog.manage")
    if uow.products.get(product_id) is None:
        raise ProductNotFoundError(f"محصول {product_id} یافت نشد")
    variant = uow.product_variants.create(
        product_id, name, price_minor, currency,
        duration_days=duration_days, traffic_gb=traffic_gb,
    )
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.variant.create",
        entity_type="product_variant", entity_id=variant.id,
        after={"product_id": product_id, "name": name, "price_minor": price_minor,
               "currency": currency, "duration_days": duration_days,
               "traffic_gb": traffic_gb},
    )
    return variant


def list_variants(uow: UnitOfWork, product_id: int) -> Sequence[ProductVariantRecord]:
    return uow.product_variants.list_by_product(product_id)


def deactivate_variant(uow: UnitOfWork, actor_id: int, variant_id: int) -> None:
    rbac.require(uow, actor_id, "catalog.manage")
    uow.product_variants.set_active(variant_id, False)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.variant.deactivate",
        entity_type="product_variant", entity_id=variant_id,
    )


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValidationError("نام باید بین ۱ تا ۶۴ کاراکتر باشد")
    return name


def create_product(uow: UnitOfWork, actor_id: int, name: str, price_minor: int,
                    currency: str = "TOMAN") -> ProductRecord:
    """ساخت پلن — Business Logic و Audit در Core (نه Adapter)."""
    rbac.require(uow, actor_id, "products.manage")
    name = _check_name(name)
    if price_minor <= 0:
        raise ValidationError("قیمت باید بزرگ‌تر از صفر باشد")
    product = uow.products.create(name, price_minor, currency)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.product.create",
        entity_type="product", entity_id=product.id,
        after={"name": name, "price_minor": price_minor, "currency": currency},
    )
    return product


def _get_product(uow, product_id):
    p = uow.products.get(product_id)
    if p is None:
        raise ProductNotFoundError(f"محصول {product_id} یافت نشد")
    return p


def update_product(uow: UnitOfWork, actor_id: int, product_id: int, *, name=None, price_minor=None):
    rbac.require(uow, actor_id, "products.manage")
    p = _get_product(uow, product_id)
    if name is not None:
        name = _check_name(name)
    if price_minor is not None and price_minor <= 0:
        raise ValidationError("قیمت باید بزرگ‌تر از صفر باشد")
    uow.products.update(product_id, name=name, price_minor=price_minor)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.product.update", entity_type="product",
        entity_id=product_id, before={"name": p.name, "price_minor": p.price_minor},
        after={"name": name or p.name, "price_minor": price_minor or p.price_minor},
    )


def set_product_active(uow: UnitOfWork, actor_id: int, product_id: int, active: bool) -> None:
    rbac.require(uow, actor_id, "products.manage")
    p = _get_product(uow, product_id)
    if p.is_active == active:
        raise ConflictError("وضعیت پلن از قبل همین است")
    uow.products.set_active(product_id, active)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.product.set_active", entity_type="product",
        entity_id=product_id, before={"is_active": p.is_active}, after={"is_active": active},
    )


def delete_product(uow: UnitOfWork, actor_id: int, product_id: int) -> None:
    """حذف فقط برای پلنی که هیچ سفارشی ندارد؛ در غیر این صورت غیرفعال‌سازی."""
    rbac.require(uow, actor_id, "products.manage")
    p = _get_product(uow, product_id)
    if uow.products.count_orders(product_id) > 0:
        raise ConflictError("این پلن سفارش دارد؛ به‌جای حذف، غیرفعالش کنید")
    stock = uow.inventory.count_available(product_id)
    uow.products.delete(product_id)
    audit_service.record(
        uow, actor_id=actor_id, action="catalog.product.delete", entity_type="product",
        entity_id=product_id, before={"name": p.name, "price_minor": p.price_minor,
                                       "deleted_stock": stock},
    )


def rename_category(uow: UnitOfWork, actor_id: int, category_id: int, name: str) -> None:
    rbac.require(uow, actor_id, "catalog.manage")
    c = uow.categories.get(category_id)
    if c is None:
        raise NotFoundError("دسته یافت نشد")
    name = _check_name(name)
    uow.categories.rename(category_id, name)
    audit_service.record(uow, actor_id=actor_id, action="catalog.category.rename",
                         entity_type="category", entity_id=category_id,
                         before={"name": c.name}, after={"name": name})


def list_products_page(uow: UnitOfWork, actor_id: int, page: int = 0):
    rbac.require(uow, actor_id, "products.manage")
    return uow.products.page(page=page)
