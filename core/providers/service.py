"""
GhYiAb V2 — Providers Registry Service (Phase 2.1)
=====================================================

این سرویس هرگز خودش تصمیم نمی‌گیرد یک Provider متصل است یا نه — فقط
وضعیتی را که یک Adapter بیرونی (مثل `xui_provider.ThreeXUIProvider.
health_check()`) واقعاً گزارش داده ثبت/بازخوانی می‌کند. طبق اصل No Fake
Integration، این ماژول هیچ‌گاه status را به OK تغییر نمی‌دهد مگر آنکه
صدازننده صریحاً همان مقدار واقعی را از Adapter گرفته و پاس داده باشد.
"""

from __future__ import annotations

from typing import Optional, Sequence

from repository.interface import UnitOfWork, ProviderRecord
from core.audit import service as audit_service

VALID_STATUSES = {"NOT_CONFIGURED", "OK", "BLOCKED"}


def list_providers(uow: UnitOfWork) -> Sequence[ProviderRecord]:
    return uow.providers.list_all()


def get_provider(uow: UnitOfWork, name: str) -> Optional[ProviderRecord]:
    return uow.providers.get_by_name(name)


def register_provider(uow: UnitOfWork, actor_id: int, name: str, type_: str,
                       status: str, config_ref: Optional[str] = None) -> ProviderRecord:
    if status not in VALID_STATUSES:
        raise ValueError(f"وضعیت نامعتبر: {status}")
    record = uow.providers.upsert(name, type_, status, config_ref)
    audit_service.record(
        uow, actor_id=actor_id, action="provider.register",
        entity_type="provider", entity_id=name,
        after={"type": type_, "status": status, "config_ref": config_ref},
    )
    return record


def report_status(uow: UnitOfWork, actor_id: int, name: str, status: str) -> ProviderRecord:
    """
    فقط وضعیتی که یک health_check واقعی از Adapter برگردانده ثبت می‌شود
    (مثلاً خروجی `ThreeXUIProvider.health_check()`). هرگز از این تابع برای
    شبیه‌سازی موفقیت استفاده نشود.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"وضعیت نامعتبر: {status}")
    before = uow.providers.get_by_name(name)
    uow.providers.set_status(name, status)
    after = uow.providers.get_by_name(name)
    audit_service.record(
        uow, actor_id=actor_id, action="provider.status_change",
        entity_type="provider", entity_id=name,
        before={"status": before.status} if before else None,
        after={"status": status},
    )
    return after
