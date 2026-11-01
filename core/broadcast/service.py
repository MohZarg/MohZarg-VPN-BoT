"""
Broadcast — طبق Audit (P1-2)، ارسال همگانی روی سرویس مرکزی با batching و
ثبت پیشرفت انجام می‌شود (نه یک حلقهٔ await ساده در Handler). ارسال واقعی
پیام توسط Adapter (bot.py) با فراخوانی مکرر `record_batch_progress` انجام
می‌شود؛ Core تصمیم می‌گیرد fan-out را چگونه دنبال کند، نه اینکه خودش با
Telegram API صحبت کند (که به core/* واردکردن آن ممنوع است).
"""

from __future__ import annotations

from repository.interface import UnitOfWork
from core.audit import service as audit_service
from core.auth import rbac
from core.errors import ValidationError

BATCH_SIZE = 25


def start(uow: UnitOfWork, actor_id: int, text: str, recipient_ids) -> tuple:
    rbac.require(uow, actor_id, "broadcast.send")
    text = (text or "").strip()
    if not text or len(text) > 4000:
        raise ValidationError("متن پیام همگانی باید بین ۱ تا ۴۰۰۰ کاراکتر باشد")
    recipient_ids = list(recipient_ids)
    b = uow.broadcasts.create(actor_id, text, len(recipient_ids))
    uow.broadcasts.set_status(b.id, "RUNNING")
    audit_service.record(uow, actor_id=actor_id, action="broadcast.start", entity_type="broadcast",
                         entity_id=b.id, after={"total": len(recipient_ids)})
    return b, recipient_ids


def record_batch_progress(uow: UnitOfWork, broadcast_id: int, sent_delta: int, failed_delta: int) -> None:
    b = uow.broadcasts.get(broadcast_id)
    if b is None:
        return
    uow.broadcasts.update_progress(broadcast_id, b.sent + sent_delta, b.failed + failed_delta)


def finish(uow: UnitOfWork, broadcast_id: int) -> None:
    uow.broadcasts.set_status(broadcast_id, "DONE")
    audit_service.record(uow, actor_id=0, action="broadcast.finish", entity_type="broadcast",
                         entity_id=broadcast_id)
