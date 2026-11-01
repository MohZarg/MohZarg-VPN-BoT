"""
GhYiAb V2 — Bootstrap
========================

توسعه‌دهنده: MohZarg — https://github.com/MohZarg
حمایت مالی: https://github.com/MohZarg

نقطهٔ ترکیب (Composition Root) لایه‌های مختلف: Secret loader → Schema init →
UnitOfWork factory → State/Settings repositories. هیچ Adapter (بات/تست) نباید
مستقیم `repository.sqlite.*` یا `sqlite3` را import کند؛ همه از اینجا
اشیاء آماده می‌گیرند — دقیقاً طبق قانون سخت معماری («Adapter مستقیم به
repository وصل نمی‌شود، فقط از طریق core / composition root»).
"""

from __future__ import annotations

from dataclasses import dataclass

from security.secret_loader import BotSecrets, secrets
from repository.sqlite.connection import init_schema
from repository.sqlite.unit_of_work import SqliteUnitOfWork
from repository.sqlite.state_repo import SqliteStateRepository
from repository.sqlite.settings_repo import SqliteSettingsRepository
from core.state.service import ConversationStateService


@dataclass
class AppContext:
    db_path: str
    owner_id: int
    state: ConversationStateService
    settings: SqliteSettingsRepository

    def unit_of_work(self) -> SqliteUnitOfWork:
        return SqliteUnitOfWork(self.db_path)


def build_app_context(bot_secrets: BotSecrets | None = None) -> AppContext:
    bs = bot_secrets or BotSecrets(secrets)
    db_path = bs.db_path
    init_schema(db_path, owner_user_id=bs.owner_id)
    ctx = AppContext(
        db_path=db_path,
        owner_id=bs.owner_id,
        state=ConversationStateService(SqliteStateRepository(db_path)),
        settings=SqliteSettingsRepository(db_path),
    )
    # Jobهای شناخته‌شدهٔ Admin Control Center را idempotent seed می‌کند
    # (اجرا خودکار نیست؛ فقط قابل مشاهده/فعال‌سازی از پنل می‌شوند).
    with ctx.unit_of_work() as uow:
        from core.jobs import service as jobs_service
        jobs_service.ensure_defaults(uow)
    return ctx
