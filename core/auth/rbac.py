"""
GhYiAb V2 — RBAC Core Service (Granular)
===========================================

- OWNER: همهٔ Permissionهای کاتالوگ (sync در init_schema) — غیرقابل‌تغییر از راه bot.
- ADMIN: هیچ Permission پیش‌فرضی ندارد؛ فقط grantهای per-user که OWNER بدهد.
- **جلوگیری از Privilege Escalation** (اعمال‌شده در خود Core، نه فقط UI):
  * فقط OWNER می‌تواند ادمین بسازد/حذف کند یا Permission بدهد/بگیرد.
  * `OWNER_ONLY` (rbac.manage، backup.download) هرگز قابل واگذاری نیست.
  * هدف بودن OWNER در grant/revoke/permission ممنوع است.
  * نام Permission ناشناس رد می‌شود.
  * SYSTEM_ACTOR (jobs داخلی) فقط توسط کد سرور استفاده می‌شود، نه ورودی کاربر.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from repository.interface import UnitOfWork
from core.errors import NotAuthorizedError, ConflictError, ValidationError, NotFoundError
from security.permissions_catalog import CATALOG, GRANTABLE, OWNER_ONLY

SYSTEM_ACTOR = 0  # Jobs/Automation داخلی؛ هرگز از ورودی تلگرام نمی‌آید (IDها مثبت‌اند)


def is_admin(uow: UnitOfWork, user_id: int) -> bool:
    return uow.rbac.is_admin(user_id)


def is_owner(uow: UnitOfWork, user_id: int) -> bool:
    return uow.rbac.is_owner(user_id)


def has_permission(uow: UnitOfWork, user_id: int, permission_name: str) -> bool:
    return uow.rbac.has_permission(user_id, permission_name)


def require(uow: UnitOfWork, actor_id: int, permission: str) -> None:
    """Defense-in-depth: سرویس‌های Core خودشان هم Permission را چک می‌کنند."""
    if actor_id == SYSTEM_ACTOR:
        return
    if not uow.rbac.has_permission(actor_id, permission):
        raise NotAuthorizedError(f"دسترسی «{permission}» برای کاربر {actor_id} وجود ندارد")


def require_owner(uow: UnitOfWork, actor_id: int) -> None:
    if actor_id == SYSTEM_ACTOR:
        return
    if not uow.rbac.is_owner(actor_id):
        raise NotAuthorizedError("این عملیات فقط برای OWNER مجاز است")


def list_my_permissions(uow: UnitOfWork, user_id: int) -> Sequence[str]:
    return uow.rbac.list_permissions_for_user(user_id)


def _validate_grantable(permissions: Iterable[str]) -> list[str]:
    out: list[str] = []
    for name in permissions:
        if name not in CATALOG:
            raise ValidationError(f"Permission ناشناس: {name}")
        if name in OWNER_ONLY:
            raise NotAuthorizedError(f"Permission «{name}» فقط مخصوص OWNER است و قابل واگذاری نیست")
        if name not in out:
            out.append(name)
    return out


def grant_admin(uow: UnitOfWork, user_id: int, *, actor_id: int,
                permissions: Iterable[str] = ()) -> None:
    from core.audit import service as audit_service
    require_owner(uow, actor_id)
    if uow.rbac.is_owner(user_id):
        raise ConflictError("کاربر هدف OWNER است")
    perms = _validate_grantable(permissions)
    was_admin = uow.rbac.is_admin(user_id)
    uow.rbac.grant_admin(user_id)
    if perms:
        uow.rbac.set_user_grants(user_id, perms, actor_id)
    audit_service.record(
        uow, actor_id=actor_id, action="rbac.grant_admin", entity_type="user",
        entity_id=user_id, before={"was_admin": was_admin},
        after={"role": "ADMIN", "permissions": perms or list(uow.rbac.list_user_grants(user_id))},
    )


def revoke_admin(uow: UnitOfWork, user_id: int, *, actor_id: int) -> None:
    from core.audit import service as audit_service
    require_owner(uow, actor_id)
    if uow.rbac.is_owner(user_id):
        raise ConflictError("OWNER قابل حذف نیست")
    before = list(uow.rbac.list_user_grants(user_id))
    uow.rbac.revoke_admin(user_id)
    audit_service.record(
        uow, actor_id=actor_id, action="rbac.revoke_admin", entity_type="user",
        entity_id=user_id, before={"permissions": before}, after={"role": "ADMIN", "revoked": True},
    )


def set_admin_permissions(uow: UnitOfWork, user_id: int, permissions: Iterable[str],
                          *, actor_id: int) -> list[str]:
    from core.audit import service as audit_service
    require_owner(uow, actor_id)
    if uow.rbac.is_owner(user_id):
        raise ConflictError("Permissionهای OWNER قابل تغییر نیست")
    if not uow.rbac.is_admin(user_id):
        raise NotFoundError("کاربر ادمین نیست")
    perms = _validate_grantable(permissions)
    before = list(uow.rbac.list_user_grants(user_id))
    uow.rbac.set_user_grants(user_id, perms, actor_id)
    audit_service.record(
        uow, actor_id=actor_id, action="rbac.set_permissions", entity_type="user",
        entity_id=user_id, before={"permissions": before}, after={"permissions": perms},
    )
    return perms


def toggle_admin_permission(uow: UnitOfWork, user_id: int, permission: str, *, actor_id: int) -> bool:
    """Permission را برعکس می‌کند؛ True=اکنون فعال."""
    current = list(uow.rbac.list_user_grants(user_id))
    if permission in current:
        new = [p for p in current if p != permission]
        state = False
    else:
        new = current + [permission]
        state = True
    set_admin_permissions(uow, user_id, new, actor_id=actor_id)
    return state


def list_admins(uow: UnitOfWork):
    return uow.rbac.list_admins()


def grants_of(uow: UnitOfWork, user_id: int) -> Sequence[str]:
    return uow.rbac.list_user_grants(user_id)


def grantable_permissions() -> list[str]:
    return sorted(GRANTABLE)


def role_presets() -> dict[str, tuple[str, ...]]:
    from security.permissions_catalog import ROLE_PRESETS
    return dict(ROLE_PRESETS)


def apply_role_preset(uow: UnitOfWork, user_id: int, preset: str, *, actor_id: int) -> list[str]:
    """
    میان‌بر Owner: کاربر را ادمین می‌کند و مجموعهٔ Permission آن نقش (SUPPORT/FINANCE/ADMIN)
    را اعطا می‌کند. مدل اصلی همچنان per-user است؛ preset فقط قالب است و Permissionهای
    OWNER_ONLY هرگز واگذار نمی‌شوند (خود `_validate_grantable` تضمین می‌کند).
    """
    from security.permissions_catalog import ROLE_PRESETS
    require_owner(uow, actor_id)
    key = (preset or "").upper()
    if key not in ROLE_PRESETS:
        raise ValidationError(f"نقش ناشناس: {preset}")
    perms = list(ROLE_PRESETS[key])
    grant_admin(uow, user_id, actor_id=actor_id, permissions=perms)
    from core.audit import service as audit_service
    audit_service.record(uow, actor_id=actor_id, action="rbac.apply_preset", entity_type="user",
                         entity_id=user_id, after={"preset": key, "count": len(perms)})
    return perms
