"""Support Tickets — کاربر ایجاد/پاسخ می‌دهد، ادمین با tickets.reply پاسخ/می‌بندد."""

from __future__ import annotations

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ValidationError, NotFoundError, ConflictError


def open_ticket(uow: UnitOfWork, user_id: int, subject: str, body: str):
    from core.settings import service as settings_service
    subject = (subject or "").strip()[:120] or "بدون موضوع"
    body = (body or "").strip()
    if not body:
        raise ValidationError("متن پیام نمی‌تواند خالی باشد")
    max_open = settings_service.get_int(uow, "tickets_max_open")
    if uow.tickets.count_open_for_user(user_id) >= max_open:
        raise ConflictError(f"حداکثر {max_open} تیکت باز مجاز است؛ لطفاً منتظر پاسخ بمانید")
    return uow.tickets.create(user_id, subject, body)


def reply(uow: UnitOfWork, actor_id: int, ticket_id: int, body: str, *, close: bool = False):
    rbac.require(uow, actor_id, "tickets.reply")
    ticket = uow.tickets.get(ticket_id)
    if ticket is None:
        raise NotFoundError("تیکت یافت نشد")
    if ticket.status == "CLOSED":
        raise ConflictError("این تیکت بسته شده است")
    msg = uow.tickets.add_message(ticket_id, actor_id, True, (body or "").strip())
    uow.tickets.set_status(ticket_id, "CLOSED" if close else "ANSWERED")
    audit_service.record(uow, actor_id=actor_id, action="ticket.reply", entity_type="ticket",
                         entity_id=ticket_id, after={"closed": close})
    return msg


def user_reply(uow: UnitOfWork, user_id: int, ticket_id: int, body: str):
    ticket = uow.tickets.get(ticket_id)
    if ticket is None or ticket.user_id != user_id:
        raise NotFoundError("تیکت یافت نشد")
    if ticket.status == "CLOSED":
        raise ConflictError("این تیکت بسته شده است")
    msg = uow.tickets.add_message(ticket_id, user_id, False, (body or "").strip())
    uow.tickets.set_status(ticket_id, "OPEN")
    return msg


def close(uow: UnitOfWork, actor_id: int, ticket_id: int) -> None:
    rbac.require(uow, actor_id, "tickets.reply")
    ticket = uow.tickets.get(ticket_id)
    if ticket is None:
        raise NotFoundError("تیکت یافت نشد")
    uow.tickets.set_status(ticket_id, "CLOSED")
    audit_service.record(uow, actor_id=actor_id, action="ticket.close", entity_type="ticket",
                         entity_id=ticket_id)


def list_page(uow: UnitOfWork, actor_id: int, *, status=None, page: int = 0):
    rbac.require(uow, actor_id, "tickets.view")
    return uow.tickets.page(status=status, page=page)
