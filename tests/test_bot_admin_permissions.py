"""
تست‌های Phase 3 Hardening — لایهٔ Adapter (تلگرام).

هدف: اثبات اینکه هر عملیات حساس در `handle_callbacks`/`handle_text_messages`
واقعاً روی مرز Adapter با `has_permission()` مسدود می‌شود — نه فقط در تئوری.
این‌ها اولین تست‌های سطح Adapter در این پروژه‌اند؛ به‌جای وابستگی به کتابخانهٔ
واقعی تلگرام، فقط همان چند متد/فیلدی که `bot.py` واقعاً از Update/Context
استفاده می‌کند شبیه‌سازی شده (بدون هیچ منطق کسب‌وکاری تقلبی).

هر تست یک الگوی جفتی دارد: کاربر عادی (بدون نقش) باید رد شود، همان مسیر
برای OWNER باید دقیقاً مثل قبل کار کند (بدون تغییر رفتار برای نقش‌های فعلی).
"""

import pytest

from repository.sqlite.connection import init_schema
from repository.sqlite.unit_of_work import SqliteUnitOfWork
from repository.sqlite.state_repo import SqliteStateRepository
from repository.sqlite.settings_repo import SqliteSettingsRepository
from core.state.service import ConversationStateService
from bootstrap import AppContext

from adapters.telegram_bot import bot as bot_module

OWNER_ID = 999999
PLAIN_USER_ID = 424242


class _FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.username = None


class _FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id

    async def delete(self):
        pass


class _FakeCallbackQuery:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage()
        self.edited_texts = []

    async def answer(self, *args, **kwargs):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.edited_texts.append(text)

    async def edit_message_reply_markup(self, **kwargs):
        pass

    async def edit_message_caption(self, **kwargs):
        pass


class _FakeUpdate:
    def __init__(self, callback_query):
        self.callback_query = callback_query


class _FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append((chat_id, text))
        return object()


class _FakeBotSecrets:
    channel_id = "@dummy"
    owner_id = OWNER_ID


class _FakeApplication:
    def __init__(self, app_ctx):
        self.bot_data = {"app_ctx": app_ctx, "bot_secrets": _FakeBotSecrets()}


class _FakeContext:
    def __init__(self, app_ctx):
        self.application = _FakeApplication(app_ctx)
        self.bot = _FakeBot()


@pytest.fixture()
def app_ctx(tmp_path):
    db_path = str(tmp_path / "test_bot_perms.db")
    init_schema(db_path, owner_user_id=OWNER_ID)
    return AppContext(
        db_path=db_path,
        owner_id=OWNER_ID,
        state=ConversationStateService(SqliteStateRepository(db_path)),
        settings=SqliteSettingsRepository(db_path),
    )


async def _fire_callback(app_ctx, data, user_id):
    ctx = _FakeContext(app_ctx)
    query = _FakeCallbackQuery(data, user_id)
    await bot_module.handle_callbacks(_FakeUpdate(query), ctx)
    return ctx, query


@pytest.mark.parametrize("callback_data,expected_state_action,permission", [
    ("adm_add_product", "waiting_new_product_name", "products.manage"),
    ("adm_add_admin", "waiting_for_new_admin_id", "rbac.manage"),
    ("adm_balance_adjust", "waiting_for_balance_adjust", "wallet.adjust"),
    ("adm_broadcast", "waiting_for_broadcast", "broadcast.send"),
])
def test_plain_user_cannot_trigger_permission_gated_callback(
    app_ctx, callback_data, expected_state_action, permission,
):
    import asyncio
    asyncio.run(_fire_callback(app_ctx, callback_data, PLAIN_USER_ID))
    # کاربر عادی نه نقشی دارد نه Permission‌ای؛ پس state هرگز نباید ست شود
    assert app_ctx.state.get(PLAIN_USER_ID) is None


@pytest.mark.parametrize("callback_data,expected_state", [
    ("adm_add_product", "waiting_new_product_name"),
    ("adm_add_admin", "waiting_for_new_admin_id"),
    ("adm_balance_adjust", "waiting_for_balance_adjust"),
    ("adm_broadcast", "waiting_for_broadcast"),
])
def test_owner_can_still_trigger_same_callbacks(app_ctx, callback_data, expected_state):
    import asyncio
    asyncio.run(_fire_callback(app_ctx, callback_data, OWNER_ID))
    # رفتار OWNER باید دقیقاً مثل قبل از Hardening بماند (بدون رگرسیون)
    assert app_ctx.state.get(OWNER_ID) == expected_state


def test_plain_user_cannot_open_inventory_admin_view(app_ctx):
    import asyncio
    ctx, query = asyncio.run(_fire_callback(app_ctx, "adm_makhzan", PLAIN_USER_ID))
    assert query.edited_texts == []


def test_owner_can_open_inventory_admin_view(app_ctx):
    import asyncio
    ctx, query = asyncio.run(_fire_callback(app_ctx, "adm_makhzan", OWNER_ID))
    assert len(query.edited_texts) == 1


def test_plain_user_cannot_approve_wallet_charge_request(app_ctx):
    """
    مهم‌ترین مسیر مالی: تأیید شارژ کیف پول از طریق دکمهٔ ادمین. کاربر عادی
    نباید بتواند این را تأیید کند — حتی اگر شمارهٔ درخواست را بداند.
    """
    import asyncio
    from core.orders import service as orders_service

    with SqliteUnitOfWork(app_ctx.db_path) as uow:
        req_id = orders_service.create_pending_request(
            uow, "charge", 555555, amount_minor=10000, currency="TOMAN",
        )

    asyncio.run(_fire_callback(app_ctx, f"ok_dp_{req_id}", PLAIN_USER_ID))

    with SqliteUnitOfWork(app_ctx.db_path) as uow:
        # درخواست هنوز باید pending باشد چون کاربر عادی مجاز به wallet.adjust نیست
        assert uow.pending_requests.count_pending() == 1
        balance = uow.wallet.get_balance(555555, "TOMAN")
        assert balance == 0


def test_owner_can_approve_wallet_charge_request(app_ctx):
    import asyncio
    from core.orders import service as orders_service

    with SqliteUnitOfWork(app_ctx.db_path) as uow:
        req_id = orders_service.create_pending_request(
            uow, "charge", 555555, amount_minor=10000, currency="TOMAN",
        )

    asyncio.run(_fire_callback(app_ctx, f"ok_dp_{req_id}", OWNER_ID))

    with SqliteUnitOfWork(app_ctx.db_path) as uow:
        assert uow.pending_requests.count_pending() == 0
        balance = uow.wallet.get_balance(555555, "TOMAN")
        assert balance == 10000
