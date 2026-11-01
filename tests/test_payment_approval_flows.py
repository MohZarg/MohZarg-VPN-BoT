"""
مسیر واقعی تأیید/رد رسید توسط ادمین (handle_callbacks) — نه فقط سرویس.
"""
from __future__ import annotations

import asyncio

import pytest
from telegram.error import BadRequest

from core.catalog import service as catalog_service
from core.inventory import service as inventory_service
from core.orders import service as orders_service
from core.errors import DomainError
from tests.test_bot_admin_permissions import (  # noqa: F401
    app_ctx, _FakeContext, _FakeUpdate, _FakeCallbackQuery, OWNER_ID, PLAIN_USER_ID,
)
from adapters.telegram_bot import bot as bot_module


class _FailingEditQuery(_FakeCallbackQuery):
    """ادمین پیام رسید را پاک کرده / پیام قدیمی است → ویرایش caption خطا می‌دهد."""
    async def edit_message_caption(self, **kwargs):
        raise BadRequest("Message can't be edited")


def _fire(app_ctx, data, user_id, query_cls=_FakeCallbackQuery):
    ctx = _FakeContext(app_ctx)
    q = query_cls(data, user_id)
    asyncio.run(bot_module.handle_callbacks(_FakeUpdate(q), ctx))
    return ctx, q


def _setup_product_with_stock(app_ctx, n=1):
    with app_ctx.unit_of_work() as uow:
        p = catalog_service.create_product(uow, OWNER_ID, "پلن", 50_000)
        if n:
            inventory_service.add_items(uow, p.id, "unlimited", [f"cfg-{i}" for i in range(n)], actor_id=OWNER_ID)
    return p


def _pending(app_ctx, req_type, **kw):
    with app_ctx.unit_of_work() as uow:
        return orders_service.create_pending_request(uow, req_type, PLAIN_USER_ID, **kw)


def _status(app_ctx, req_id):
    with app_ctx.unit_of_work() as uow:
        return uow.pending_requests.get(req_id).status


def test_user_is_notified_of_config_even_if_admin_message_edit_fails(app_ctx):
    """باگ: ویرایش پیام ادمین قبل از اطلاع‌رسانی بود؛ خطای آن کاربرِ پرداخت‌کرده را بی‌خبر می‌گذاشت."""
    p = _setup_product_with_stock(app_ctx)
    req = _pending(app_ctx, "buy", product_id=p.id)
    ctx, _ = _fire(app_ctx, f"ok_by_{req}", OWNER_ID, _FailingEditQuery)
    assert any(chat == PLAIN_USER_ID and "cfg-0" in text for chat, text in ctx.bot.sent_messages)


def test_user_is_notified_of_credit_even_if_admin_message_edit_fails(app_ctx):
    req = _pending(app_ctx, "charge", amount_minor=30_000, currency="TOMAN")
    ctx, _ = _fire(app_ctx, f"ok_dp_{req}", OWNER_ID, _FailingEditQuery)
    assert any(chat == PLAIN_USER_ID for chat, _ in ctx.bot.sent_messages)
    with app_ctx.unit_of_work() as uow:
        assert uow.wallet.get_balance(PLAIN_USER_ID, "TOMAN") == 30_000


def test_charge_approval_is_applied_once_on_double_tap(app_ctx):
    req = _pending(app_ctx, "charge", amount_minor=30_000, currency="TOMAN")
    _fire(app_ctx, f"ok_dp_{req}", OWNER_ID)
    _fire(app_ctx, f"ok_dp_{req}", OWNER_ID)
    with app_ctx.unit_of_work() as uow:
        assert uow.wallet.get_balance(PLAIN_USER_ID, "TOMAN") == 30_000


def test_out_of_stock_approval_keeps_request_pending_and_charges_nothing(app_ctx):
    p = _setup_product_with_stock(app_ctx, n=0)
    req = _pending(app_ctx, "buy", product_id=p.id)
    _fire(app_ctx, f"ok_by_{req}", OWNER_ID)
    assert _status(app_ctx, req) == "pending"
    with app_ctx.unit_of_work() as uow:
        assert uow.orders.page(user_id=PLAIN_USER_ID).total == 0


@pytest.mark.parametrize("req_type,approver", [
    ("buy", "approve_charge_request"),
    ("agency", "approve_charge_request"),
    ("charge", "approve_direct_purchase"),
    ("agency", "approve_direct_purchase"),
])
def test_approving_wrong_request_type_is_rejected_and_stays_pending(app_ctx, req_type, approver):
    """باگ: resolve نوع درخواست را نمی‌سنجید؛ تأیید با نوع اشتباه با خطای خام DB/TypeError می‌ترکید."""
    p = _setup_product_with_stock(app_ctx)
    kw = {"product_id": p.id} if req_type == "buy" else {}
    req = _pending(app_ctx, req_type, **kw)
    with pytest.raises(DomainError):
        with app_ctx.unit_of_work() as uow:
            getattr(orders_service, approver)(uow, req, OWNER_ID)
    assert _status(app_ctx, req) == "pending"


def test_plain_user_cannot_approve_receipts(app_ctx):
    req = _pending(app_ctx, "charge", amount_minor=30_000, currency="TOMAN")
    _fire(app_ctx, f"ok_dp_{req}", PLAIN_USER_ID)
    assert _status(app_ctx, req) == "pending"


# ---- سطح هندلر: پیام خطای دامنه به ادمین نشان داده می‌شود، نه Exception خام ----

class _AlertCapture(_FakeCallbackQuery):
    def __init__(self, data, user_id):
        super().__init__(data, user_id)
        self.alerts = []

    async def answer(self, text=None, **kwargs):
        if text:
            self.alerts.append(text)


@pytest.mark.parametrize("req_type,cb", [("buy", "ok_dp_"), ("agency", "ok_dp_"), ("charge", "ok_by_")])
def test_handler_wrong_type_shows_alert_and_does_not_raise(app_ctx, req_type, cb):
    p = _setup_product_with_stock(app_ctx)
    kw = {"product_id": p.id} if req_type == "buy" else {}
    req = _pending(app_ctx, req_type, **kw)
    _, q = _fire(app_ctx, f"{cb}{req}", OWNER_ID, _AlertCapture)
    assert q.alerts and "نمی‌خواند" in q.alerts[-1]
    assert _status(app_ctx, req) == "pending"


def test_agency_approval_sets_agent_and_notifies_even_if_edit_fails(app_ctx):
    req = _pending(app_ctx, "agency")
    ctx, _ = _fire(app_ctx, f"ok_ag_{req}", OWNER_ID, _FailingEditQuery_Text)
    with app_ctx.unit_of_work() as uow:
        assert uow.users.get_or_create(PLAIN_USER_ID).is_agent
    assert any(chat == PLAIN_USER_ID for chat, _ in ctx.bot.sent_messages)


class _FailingEditQuery_Text(_FakeCallbackQuery):
    async def edit_message_text(self, text, **kwargs):
        raise BadRequest("Message is not modified")
