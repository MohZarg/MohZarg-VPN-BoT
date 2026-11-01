"""پشتیبانی کاربر باید واقعاً تیکت بسازد (قبلاً فقط فوروارد به OWNER بود)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.settings import service as settings_service
from core.tickets import service as tickets_service
from tests.test_bot_admin_permissions import app_ctx, _FakeContext, OWNER_ID, PLAIN_USER_ID  # noqa: F401
from tests.test_user_coupon_flow import _TextMessage
from adapters.telegram_bot import bot as bot_module


def _support(app_ctx, text, uid=PLAIN_USER_ID):
    app_ctx.state.set(uid, "waiting_for_support_msg")
    ctx = _FakeContext(app_ctx)
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=uid, username="u1"), message=_TextMessage(text))
    asyncio.run(bot_module.handle_text_messages(upd, ctx))
    return ctx, upd.message


def test_support_message_creates_ticket_visible_to_admin_and_notifies_owner(app_ctx):
    ctx, msg = _support(app_ctx, "اکانتم وصل نمیشه")
    assert "#1" in msg.replies[-1]
    with app_ctx.unit_of_work() as uow:
        page = tickets_service.list_page(uow, OWNER_ID, status="OPEN")
    assert page.total == 1 and page.items[0].user_id == PLAIN_USER_ID
    assert any(chat == OWNER_ID and "#1" in text and "اکانتم" in text for chat, text in ctx.bot.sent_messages)
    assert app_ctx.state.get(PLAIN_USER_ID) is None


def test_open_ticket_limit_is_enforced_for_users(app_ctx):
    with app_ctx.unit_of_work() as uow:
        settings_service.set_value(uow, OWNER_ID, "tickets_max_open", "1")
    _support(app_ctx, "اولی")
    ctx, msg = _support(app_ctx, "دومی")
    assert "حداکثر" in msg.replies[-1]
    with app_ctx.unit_of_work() as uow:
        assert tickets_service.list_page(uow, OWNER_ID).total == 1
    assert ctx.bot.sent_messages == []


def test_empty_support_text_rejected_and_state_kept(app_ctx):
    _, msg = _support(app_ctx, "   ")
    assert "⚠️" in msg.replies[-1]
    assert app_ctx.state.get(PLAIN_USER_ID) == "waiting_for_support_msg"
