"""
GhYiAb V2 — Audit Service
============================
نقطهٔ واحد ثبت AuditLog. رکوردها append-only‌اند (Trigger دیتابیس UPDATE/DELETE را
رد می‌کند). مقادیر حساس به‌صورت خودکار Mask می‌شوند تا Secret/کارت در Audit نشت نکند.
"""

from __future__ import annotations

from typing import Optional

from repository.interface import UnitOfWork
from core.auth import rbac

SENSITIVE_KEYS = {"password", "token", "api_token", "secret", "card_number", "content", "api_key"}

# دسته‌بندی فیلتر پنل Audit → پیشوند action
CATEGORIES = {
    "wallet": "wallet.", "payment": "pending_request.", "order": "order.", "product": "catalog.",
    "inventory": "inventory.", "provider": "provider.", "users": "users.", "rbac": "rbac.",
    "settings": "settings.", "broadcast": "broadcast.", "backup": "backup.", "security": "security.",
    "coupon": "coupon.", "referral": "referral.", "ticket": "ticket.", "job": "job.",
}


def _mask_value(v):
    s = str(v)
    return "*" * max(0, len(s) - 4) + s[-4:]


def sanitize(data: Optional[dict]) -> Optional[dict]:
    if data is None:
        return None
    out = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[k] = sanitize(v)
        elif k.lower() in SENSITIVE_KEYS and v is not None:
            out[k] = _mask_value(v)
        else:
            out[k] = v
    return out


def record(uow: UnitOfWork, *, actor_id: int, action: str, entity_type: str,
           entity_id, before: Optional[dict] = None, after: Optional[dict] = None) -> int:
    return uow.audit.append(
        actor_id=actor_id, action=action, entity_type=entity_type,
        entity_id=str(entity_id), before=sanitize(before), after=sanitize(after),
    )


def query(uow: UnitOfWork, actor_id: int, *, category: Optional[str] = None,
          actor_filter: Optional[int] = None, page: int = 0, per_page: int = 8):
    rbac.require(uow, actor_id, "audit.view")
    prefix = CATEGORIES.get(category) if category else None
    return uow.audit.page(action_prefix=prefix, actor_id=actor_filter, page=page, per_page=per_page)


def get(uow: UnitOfWork, actor_id: int, log_id: int):
    rbac.require(uow, actor_id, "audit.view")
    return uow.audit.get(log_id)
