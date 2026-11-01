"""
خزندهٔ کل پنل ادمین: از «acc:home» شروع می‌کند و هر دکمهٔ قابل‌دسترس را (BFS) روی مسیر واقعی
handle_callbacks می‌زند. هدف: هیچ دکمهٔ مرده/کرشی، callback_data بیش از ۶۴ بایت، یا نشت دسترسی.
(باگ «مخزن» که IndexError می‌داد با همین روش پیدا شد.)
"""
from __future__ import annotations

import asyncio

import pytest

from core.auth import rbac
from core.catalog import service as catalog_service
from core.coupons import service as coupons_service
from core.inventory import service as inventory_service
from core.orders import service as orders_service
from core.tickets import service as tickets_service
from tests.test_bot_admin_permissions import (  # noqa: F401
    app_ctx, _FakeContext, _FakeUpdate, _FakeCallbackQuery, _FakeBot, _FakeMessage,
    OWNER_ID, PLAIN_USER_ID,
)
from adapters.telegram_bot import bot as bot_module

LIMITED_ADMIN = 700123
MAX_BUTTONS = 700


async def _noop(self, *a, **k):
    return object()


class _Bot(_FakeBot):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    async def send_message(self, chat_id, text, **kw):
        self.sink.append(kw.get("reply_markup"))
        return await super().send_message(chat_id, text, **kw)

    send_document = _noop
    send_photo = _noop


class _Ctx(_FakeContext):
    def __init__(self, app_ctx, sink):
        super().__init__(app_ctx)
        self.bot = _Bot(sink)


class _Query(_FakeCallbackQuery):
    def __init__(self, data, uid, sink):
        super().__init__(data, uid)
        self.sink = sink
        self.message = _MsgWithReplies()

    async def edit_message_text(self, text, **kw):
        self.sink.append(kw.get("reply_markup"))
        await super().edit_message_text(text, **kw)

    async def edit_message_caption(self, **kw):
        self.sink.append(kw.get("reply_markup"))

    async def edit_message_reply_markup(self, **kw):
        self.sink.append(kw.get("reply_markup"))


class _MsgWithReplies(_FakeMessage):
    reply_html = _noop
    reply_text = _noop


def _fire(app_ctx, data, uid):
    sink: list = []
    asyncio.run(bot_module.handle_callbacks(_FakeUpdate(_Query(data, uid, sink)), _Ctx(app_ctx, sink)))
    return [b.callback_data for m in sink if m for row in m.inline_keyboard for b in row if b.callback_data]


def _seed(app_ctx):
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(PLAIN_USER_ID)
        p = catalog_service.create_product(uow, OWNER_ID, "پلن", 50_000)
        inventory_service.add_items(uow, p.id, "unlimited", ["a", "b", "c"], actor_id=OWNER_ID)
        inventory_service.add_items(uow, 0, "test", ["t1"], actor_id=OWNER_ID)
        uow.wallet.adjust(PLAIN_USER_ID, "TOMAN", 200_000)
        orders_service.purchase_with_wallet(uow, PLAIN_USER_ID, p.id)
        coupons_service.create(uow, OWNER_ID, "X1", "PERCENT", 10)
        tickets_service.open_ticket(uow, PLAIN_USER_ID, "s", "body")
        orders_service.create_pending_request(uow, "charge", PLAIN_USER_ID, amount_minor=1000, currency="TOMAN")
        uow.users.get_or_create(LIMITED_ADMIN)
        rbac.grant_admin(uow, LIMITED_ADMIN, actor_id=OWNER_ID, permissions=["dashboard.view", "tickets.view"])


def _crawl(app_ctx, uid):
    seen, queue, crashes, toolong = set(), ["acc:home"], [], []
    while queue and len(seen) < MAX_BUTTONS:
        cd = queue.pop(0)
        if cd in seen or cd.startswith(("acc:close", "acc:noop")):
            continue
        seen.add(cd)
        app_ctx.state.clear(uid)
        try:
            for nxt in _fire(app_ctx, cd, uid):
                if len(nxt.encode()) > 64:
                    toolong.append(nxt)
                if nxt not in seen:
                    queue.append(nxt)
        except Exception as exc:  # noqa: BLE001
            crashes.append((cd, type(exc).__name__, str(exc)[:80]))
    return seen, crashes, toolong


def test_owner_can_reach_every_admin_button_without_crash(app_ctx):
    _seed(app_ctx)
    seen, crashes, toolong = _crawl(app_ctx, OWNER_ID)
    assert len(seen) > 100          # واقعاً صفحه‌ها را پیمایش کرده، نه فقط home
    assert crashes == [], crashes
    assert toolong == []


def test_limited_admin_never_crashes_even_on_forbidden_buttons(app_ctx):
    _seed(app_ctx)
    seen, crashes, toolong = _crawl(app_ctx, LIMITED_ADMIN)
    assert crashes == [], crashes
    assert toolong == []


def test_limited_admin_cannot_change_state_through_forbidden_callbacks(app_ctx):
    """ادمینِ بدون Permission با callback دستی نباید چیزی تغییر دهد (RBAC سمت سرور، نه فقط مخفی‌سازی دکمه)."""
    _seed(app_ctx)
    for cd in ["acc:inv:add:0", "acc:cpn:home", "acc:wal:home", "acc:bak:home", "acc:set:home"]:
        try:
            _fire(app_ctx, cd, LIMITED_ADMIN)
        except Exception:
            pass
    st = app_ctx.state.get(LIMITED_ADMIN)
    assert not (isinstance(st, dict) and st.get("acc") == "inventory_add")


def test_limited_admin_crawl_never_enters_a_write_flow(app_ctx):
    """کل پنل را با ادمین محدود می‌گردد؛ در هیچ نقطه‌ای نباید وارد فلوی نوشتن شود."""
    _seed(app_ctx)
    entered = []
    queue, seen = ["acc:home"], set()
    while queue and len(seen) < MAX_BUTTONS:
        cd = queue.pop(0)
        if cd in seen or cd.startswith(("acc:close", "acc:noop")):
            continue
        seen.add(cd)
        app_ctx.state.clear(LIMITED_ADMIN)
        try:
            queue.extend(n for n in _fire(app_ctx, cd, LIMITED_ADMIN) if n not in seen)
        except Exception:
            pass
        st = app_ctx.state.get(LIMITED_ADMIN)
        if isinstance(st, dict) and st.get("acc"):
            entered.append((cd, st["acc"]))
    assert entered == [], entered


def test_plain_user_gets_nothing_from_admin_callbacks(app_ctx):
    _seed(app_ctx)
    for cd in ["acc:home", "acc:inv:home", "acc:usr:home", "acc:bak:dl", "acc:set:home"]:
        assert _fire(app_ctx, cd, PLAIN_USER_ID) == []
    assert app_ctx.state.get(PLAIN_USER_ID) is None
