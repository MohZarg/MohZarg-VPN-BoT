"""
Confirmation tokens — تأیید دومرحله‌ای عملیات مخرب پنل ادمین.

هر عملیات مخرب/حساس ابتدا یک توکن یک‌بارمصرف می‌سازد (متصل به actor، با TTL).
اجرا فقط با consume() موفق انجام می‌شود؛ کلیک تکراری/دوبار/بعد از انقضا/توسط
کاربر دیگر رد می‌شود. consume داخل همان UoWِ عملیات اجرا می‌شود؛ اگر عملیات
شکست بخورد، rollback توکن را هم برمی‌گرداند (قابل تلاش مجدد).
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from repository.interface import UnitOfWork, ConfirmationRecord
from core.errors import ConfirmationInvalidError, NotAuthorizedError

DEFAULT_TTL_SECONDS = 300


def create(uow: UnitOfWork, actor_id: int, action: str, payload: dict,
           ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    token = secrets.token_hex(6)
    uow.confirmations.create(token, actor_id, action, json.dumps(payload, ensure_ascii=False), ttl_seconds)
    return token


def consume(uow: UnitOfWork, token: str, actor_id: int) -> tuple[ConfirmationRecord, dict]:
    rec = uow.confirmations.get(token)
    if rec is None:
        raise ConfirmationInvalidError("تأییدیه یافت نشد")
    if rec.actor_id != actor_id:
        raise NotAuthorizedError("این تأییدیه متعلق به شما نیست")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if rec.expires_at < now:
        raise ConfirmationInvalidError("تأییدیه منقضی شده است")
    if not uow.confirmations.consume(token):
        raise ConfirmationInvalidError("این تأییدیه قبلاً استفاده شده است")
    return rec, json.loads(rec.payload_json)
