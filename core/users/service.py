"""Users admin service — جستجو، جزئیات، بن، نمایندگی (با Audit و ضد-Escalation)."""

from __future__ import annotations

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ConflictError, NotAuthorizedError, NotFoundError
from core.wallet.service import DEFAULT_CURRENCY


def list_users(uow: UnitOfWork, actor_id: int, *, flt: str = "all", query=None, page: int = 0):
    rbac.require(uow, actor_id, "users.view")
    return uow.users.page(flt=flt, query=query, page=page)


def detail(uow: UnitOfWork, actor_id: int, user_id: int) -> dict:
    rbac.require(uow, actor_id, "users.view")
    if not uow.users.exists(user_id):
        raise NotFoundError(f"کاربر {user_id} یافت نشد")
    u = uow.users.get_or_create(user_id)
    tier = uow.resellers.get_tier(u.reseller_tier_id) if u.reseller_tier_id else None
    return {
        "user": u,
        "balance": uow.wallet.get_balance(user_id, DEFAULT_CURRENCY),
        "orders": len(uow.orders.list_by_user(user_id)),
        "referrals": uow.users.count_referred_by(user_id),
        "tier": tier,
        "is_admin": uow.rbac.is_admin(user_id),
        "is_owner": uow.rbac.is_owner(user_id),
    }


def set_ban(uow: UnitOfWork, actor_id: int, target_id: int, banned: bool) -> None:
    rbac.require(uow, actor_id, "users.ban")
    if target_id == actor_id:
        raise ConflictError("امکان مسدودسازی خود وجود ندارد")
    if uow.rbac.is_owner(target_id):
        raise NotAuthorizedError("OWNER قابل مسدودسازی نیست")
    if uow.rbac.is_admin(target_id) and not uow.rbac.is_owner(actor_id):
        raise NotAuthorizedError("فقط OWNER می‌تواند ادمین را مسدود کند")
    if not uow.users.exists(target_id):
        raise NotFoundError(f"کاربر {target_id} یافت نشد")
    cur = uow.users.get_or_create(target_id)
    if cur.is_banned == banned:
        raise ConflictError("وضعیت کاربر از قبل همین است")
    uow.users.set_banned(target_id, banned)
    audit_service.record(
        uow, actor_id=actor_id, action="users.ban" if banned else "users.unban",
        entity_type="user", entity_id=target_id, before={"is_banned": cur.is_banned},
        after={"is_banned": banned},
    )


def set_agent(uow: UnitOfWork, actor_id: int, target_id: int, is_agent: bool) -> None:
    rbac.require(uow, actor_id, "users.agent")
    if not uow.users.exists(target_id):
        raise NotFoundError(f"کاربر {target_id} یافت نشد")
    cur = uow.users.get_or_create(target_id)
    if cur.is_agent == is_agent:
        raise ConflictError("وضعیت نمایندگی از قبل همین است")
    uow.users.set_agent(target_id, is_agent)
    audit_service.record(
        uow, actor_id=actor_id, action="users.agent_grant" if is_agent else "users.agent_revoke",
        entity_type="user", entity_id=target_id, before={"is_agent": cur.is_agent},
        after={"is_agent": is_agent},
    )
