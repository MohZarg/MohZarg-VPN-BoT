"""
GhYiAb V2 — Inventory Core Service
=====================================

پورت مستقیمِ رفتاری `claim_config_locked` قدیمی — بدون تغییر در تضمین
Concurrency (چون همچنان داخل `BEGIN IMMEDIATE` یک UnitOfWork اجرا می‌شود).
تنها افزوده: AuditLog روی claim موفق، تا مشخص باشد کدام کانفیگ به کدام کاربر
و در چه لحظه‌ای تعلق گرفته (P0-2 در Audit).

نکتهٔ صریح طبق دستور Owner: اتصال واقعی به 3x-ui اینجا نیست. این سرویس فقط
روی «مخزن دستی» (inventory_items که توسط ادمین پر می‌شود) کار می‌کند — دقیقاً
مثل V1. Provider واقعی (`providers/vpn/xui/provider.py`) تا رسیدن Credential
واقعی NOT_CONFIGURED می‌ماند و به این سرویس وصل نشده.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from repository.interface import UnitOfWork, InventoryItemRecord
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ValidationError, NotFoundError, ConflictError


def claim_item(uow: UnitOfWork, product_id: int, claimer_id: int,
                *, audit_reason: str = "inventory.claim") -> Optional[InventoryItemRecord]:
    item = uow.inventory.claim_one(product_id, claimer_id)
    if item is None:
        return None
    audit_service.record(
        uow, actor_id=claimer_id, action=audit_reason, entity_type="inventory_item",
        entity_id=item.id,
        after={"product_id": product_id, "claimed_by": claimer_id},
    )
    return item


def count_available(uow: UnitOfWork, product_id: int) -> int:
    return uow.inventory.count_available(product_id)


MAX_BATCH = 500
MAX_ITEM_LEN = 4000


def mask(content: str) -> str:
    """پیش‌نمایش امن: هرگز محتوای کامل کانفیگ در لیست‌ها نمایش داده نمی‌شود."""
    if len(content) <= 10:
        return "•" * len(content)
    return content[:6] + "…" + content[-3:]


@dataclass(frozen=True)
class AddReport:
    """نتیجهٔ افزودن دستی به مخزن — برای نمایش دقیق به ادمین."""
    added: int
    duplicate_in_input: int      # تکراری داخل همان پیام/فایل
    duplicate_existing: int      # قبلاً در همین مخزن موجود بود
    too_long: int                # بیش از MAX_ITEM_LEN و ردشده
    available_after: int         # موجودی AVAILABLE پس از افزودن


def default_item_type(product_id: int) -> str:
    """مخزن تست (product_id=0) نوع 'test' دارد؛ بقیه 'unlimited' (مطابق V1)."""
    return "test" if product_id == 0 else "unlimited"


def parse_config_text(text: str) -> list:
    """متن چندخطی → فهرست کانفیگ‌ها. هر خط یک مورد؛ خطوط خالی و فاصله‌های اضافی حذف می‌شوند."""
    if not text:
        return []
    text = text.lstrip("\ufeff")
    return [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]


def add_items_report(uow: UnitOfWork, product_id: int, item_type: str, contents, *, actor_id: int) -> AddReport:
    """
    افزودن گروهی با گزارش کامل. خطوط بیش‌ازحد طولانی کل دسته را رد نمی‌کنند؛
    جداگانه شمارش و رد می‌شوند. سقف MAX_BATCH روی تعداد آیتم‌های یکتای معتبر اعمال می‌شود.
    """
    rbac.require(uow, actor_id, "inventory.manage")
    clean, seen = [], set()
    dup_in, too_long = 0, 0
    for c in contents:
        c = (c or "").strip()
        if not c:
            continue
        if len(c) > MAX_ITEM_LEN:
            too_long += 1
            continue
        if c in seen:
            dup_in += 1
            continue
        seen.add(c)
        clean.append(c)
    if len(clean) > MAX_BATCH:
        raise ValidationError(f"حداکثر {MAX_BATCH} کانفیگ در هر دسته؛ این دسته {len(clean)} مورد یکتا دارد")
    dup = uow.inventory.existing_contents(product_id, clean)
    fresh = [c for c in clean if c not in dup]
    added = uow.inventory.add_items(product_id, item_type, fresh)
    audit_service.record(
        uow, actor_id=actor_id, action="inventory.add_items", entity_type="product",
        entity_id=product_id, after={"item_type": item_type, "count": added,
                                     "skipped_duplicates": dup_in + len(dup),
                                     "skipped_too_long": too_long},
    )
    return AddReport(added=added, duplicate_in_input=dup_in, duplicate_existing=len(dup),
                     too_long=too_long, available_after=uow.inventory.count_available(product_id))


def add_items(uow: UnitOfWork, product_id: int, item_type: str, contents, *, actor_id: int) -> int:
    """سازگار با امضای قبلی: فقط تعداد افزوده‌شده را برمی‌گرداند."""
    return add_items_report(uow, product_id, item_type, contents, actor_id=actor_id).added


def delete_unclaimed(uow: UnitOfWork, product_id: int, limit: int, *, actor_id: int) -> int:
    rbac.require(uow, actor_id, "inventory.manage")
    deleted = uow.inventory.delete_unclaimed(product_id, limit)
    audit_service.record(
        uow, actor_id=actor_id, action="inventory.delete_unclaimed", entity_type="product",
        entity_id=product_id, after={"deleted": deleted},
    )
    return deleted


def delete_item(uow: UnitOfWork, actor_id: int, item_id: int) -> None:
    rbac.require(uow, actor_id, "inventory.manage")
    item = uow.inventory.get_by_id(item_id)
    if item is None:
        raise NotFoundError("آیتم یافت نشد")
    if item.status != "AVAILABLE":
        raise ConflictError("فقط آیتم‌های موجود (AVAILABLE) قابل حذف‌اند")
    if not uow.inventory.delete_available_item(item_id):
        raise ConflictError("آیتم دیگر قابل حذف نیست")
    audit_service.record(uow, actor_id=actor_id, action="inventory.delete_item", entity_type="inventory_item",
                         entity_id=item_id, before={"product_id": item.product_id, "preview": mask(item.content)})


def list_items(uow: UnitOfWork, actor_id: int, product_id: int, *, status=None, page: int = 0):
    rbac.require(uow, actor_id, "inventory.view")
    return uow.inventory.page(product_id, status=status, page=page)


def reveal_item(uow: UnitOfWork, actor_id: int, item_id: int) -> str:
    """نمایش کامل محتوا فقط با inventory.reveal و همراه Audit."""
    rbac.require(uow, actor_id, "inventory.reveal")
    item = uow.inventory.get_by_id(item_id)
    if item is None:
        raise NotFoundError("آیتم یافت نشد")
    audit_service.record(uow, actor_id=actor_id, action="inventory.reveal", entity_type="inventory_item",
                         entity_id=item_id, after={"product_id": item.product_id})
    return item.content


def stock_overview(uow: UnitOfWork, actor_id: int):
    rbac.require(uow, actor_id, "inventory.view")
    counts = uow.inventory.counts_by_product()
    rows = [(0, "🔑 مخزن تست", counts.get(0, 0))]
    rows += [(p.id, p.name, counts.get(p.id, 0)) for p in uow.products.list_all()]
    return rows
