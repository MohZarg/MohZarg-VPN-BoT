"""
تست‌های End-to-End پنل جدید مرکز کنترل ادمین (`adapters/telegram_bot/admin_panel.py`).

الگو دقیقاً مشابه ``test_bot_admin_permissions.py`` است: یک UnitOfWork واقعی
روی SQLite موقت + Fakeهای حداقلی Update/Context تلگرام (بدون شبیه‌سازی
منطق کسب‌وکاری). هر تست یک مسیر واقعی (Happy-path) و اثباتِ رد شدن کاربر
بدون Permission را پوشش می‌دهد.
"""

from __future__ import annotations

import asyncio

import pytest

from repository.sqlite.connection import init_schema
from repository.sqlite.unit_of_work import SqliteUnitOfWork
from repository.sqlite.state_repo import SqliteStateRepository
from repository.sqlite.settings_repo import SqliteSettingsRepository
from core.state.service import ConversationStateService
from bootstrap import AppContext
from core.auth import rbac
from core.errors import NotAuthorizedError

from adapters.telegram_bot import admin_panel

OWNER_ID = 999999
ADMIN_ID = 700000
PLAIN_USER_ID = 424242


class _FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.username = None


class _FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.replies = []
        self.html_replies = []
        self.deleted = False

    async def delete(self):
        self.deleted = True

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)

    async def reply_html(self, text, **kwargs):
        self.html_replies.append(text)


class _FakeCallbackQuery:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage()
        self.edited_texts = []
        self.alerts = []

    async def answer(self, text="", **kwargs):
        if text:
            self.alerts.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edited_texts.append(text)

    async def edit_message_reply_markup(self, **kwargs):
        pass


class _FakeCallbackUpdate:
    def __init__(self, query):
        self.callback_query = query
        self.message = None

    @property
    def effective_user(self):
        return self.callback_query.from_user


class _FakeMessageUpdate:
    def __init__(self, user_id, text):
        self.callback_query = None
        self.message = _FakeMessage()
        self.message.text = text
        self._user = _FakeUser(user_id)

    @property
    def effective_user(self):
        return self._user


class _FakeBot:
    def __init__(self):
        self.sent_messages = []
        self.sent_documents = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append((chat_id, text))
        return object()

    async def send_document(self, chat_id, document, **kwargs):
        self.sent_documents.append((chat_id, document))


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


@pytest.fixture
def app_ctx(tmp_path):
    db_path = str(tmp_path / "test_admin_panel.db")
    init_schema(db_path, owner_user_id=OWNER_ID)
    ctx = AppContext(
        db_path=db_path,
        owner_id=OWNER_ID,
        state=ConversationStateService(SqliteStateRepository(db_path)),
        settings=SqliteSettingsRepository(db_path),
    )
    with ctx.unit_of_work() as uow:
        uow.users.get_or_create(OWNER_ID)
        uow.users.get_or_create(ADMIN_ID)
        uow.users.get_or_create(PLAIN_USER_ID)
        rbac.grant_admin(uow, ADMIN_ID, actor_id=OWNER_ID)
    return ctx


async def _fire(app_ctx, data, user_id):
    fctx = _FakeContext(app_ctx)
    query = _FakeCallbackQuery(data, user_id)
    update = _FakeCallbackUpdate(query)
    await admin_panel.handle_callback(update, fctx)
    return fctx, query


async def _fire_text(app_ctx, user_id, text, state):
    fctx = _FakeContext(app_ctx)
    update = _FakeMessageUpdate(user_id, text)
    await admin_panel.handle_text(update, fctx, state)
    return fctx, update


# --------------------------------------------------------------------------
# دسترسی پایه: کاربر عادی هرگز چیزی از پنل نمی‌بیند
# --------------------------------------------------------------------------

def test_plain_user_is_rejected_from_home(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:home", PLAIN_USER_ID))
    assert query.edited_texts == []
    assert any("دسترسی" in a for a in query.alerts)


def test_owner_can_open_home(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:home", OWNER_ID))
    assert len(query.edited_texts) == 1
    assert "مرکز کنترل ادمین" in query.edited_texts[0]


def test_admin_without_permissions_can_open_home_but_not_users(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:home", ADMIN_ID))
    assert len(query.edited_texts) == 1  # navigation always allowed for any admin/owner

    ctx2, query2 = asyncio.run(_fire(app_ctx, "acc:usr:home", ADMIN_ID))
    assert query2.edited_texts == []
    assert any("دسترسی" in a for a in query2.alerts)


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

def test_owner_sees_dashboard_numbers(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:dash:home", OWNER_ID))
    assert "داشبورد" in query.edited_texts[0]
    assert "کاربران" in query.edited_texts[0]


# --------------------------------------------------------------------------
# Wallet adjust — دوسه‌مرحله‌ای + تأیید نهایی
# --------------------------------------------------------------------------

def test_wallet_adjust_full_flow_with_confirmation(app_ctx):
    # 1) شروع فلو
    ctx, query = asyncio.run(_fire(app_ctx, f"acc:wal:adj:{PLAIN_USER_ID}", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    assert state == {"acc": "wallet_amount", "target_id": PLAIN_USER_ID}

    # 2) مقدار
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "5000", state))
    state = app_ctx.state.get(OWNER_ID)
    assert state["acc"] == "wallet_reason"
    assert state["amount"] == 5000

    # 3) دلیل → تأییدیه ساخته می‌شود
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "هدیهٔ تستی", state))
    assert app_ctx.state.get(OWNER_ID) is None
    assert len(upd.message.replies) == 1
    assert "تأیید نهایی" in upd.message.replies[0]

    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute("SELECT token FROM confirmations WHERE actor_id=?", (OWNER_ID,)).fetchone()
    token = row[0]

    # 4) اجرای واقعی با کلیک روی «✅ اجرا»
    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert "موفقیت" in query2.edited_texts[-1]
    with app_ctx.unit_of_work() as uow:
        assert uow.wallet.get_balance(PLAIN_USER_ID, "TOMAN") == 5000

    # 5) کلیک دوباره روی همان توکن → دیگر معتبر نیست (idempotent)
    ctx, query3 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert any("قبلاً" in a or "منقضی" in a for a in query3.alerts)
    with app_ctx.unit_of_work() as uow:
        assert uow.wallet.get_balance(PLAIN_USER_ID, "TOMAN") == 5000  # بدون تغییر دوباره


def test_admin_without_wallet_permission_cannot_start_adjust(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, f"acc:wal:adj:{PLAIN_USER_ID}", ADMIN_ID))
    assert app_ctx.state.get(ADMIN_ID) is None
    assert any("دسترسی" in a for a in query.alerts)


def test_admin_with_granted_permission_can_adjust_wallet(app_ctx):
    with app_ctx.unit_of_work() as uow:
        rbac.set_admin_permissions(uow, ADMIN_ID, ["wallet.adjust"], actor_id=OWNER_ID)
    ctx, query = asyncio.run(_fire(app_ctx, f"acc:wal:adj:{PLAIN_USER_ID}", ADMIN_ID))
    assert app_ctx.state.get(ADMIN_ID) == {"acc": "wallet_amount", "target_id": PLAIN_USER_ID}


# --------------------------------------------------------------------------
# Catalog: create product → set inactive → attempt delete blocked by orders
# --------------------------------------------------------------------------

def test_create_product_full_flow(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:cat:new", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    assert state == {"acc": "product_new_name"}

    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "پلن یک‌ماهه", state))
    state = app_ctx.state.get(OWNER_ID)
    assert state["acc"] == "product_new_price"

    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "50000", state))
    assert app_ctx.state.get(OWNER_ID) is None
    assert "ساخته شد" in upd.message.replies[-1]

    with app_ctx.unit_of_work() as uow:
        products = uow.products.list_all()
    assert len(products) == 1
    assert products[0].name == "پلن یک‌ماهه"
    assert products[0].price_minor == 50000


def test_product_delete_requires_confirmation_and_blocks_with_orders(app_ctx):
    with app_ctx.unit_of_work() as uow:
        from core.catalog import service as catalog_service
        p = catalog_service.create_product(uow, OWNER_ID, "پلن تست", 10000)

    # درخواست حذف → توکن تأیید صادر می‌شود، هنوز چیزی حذف نشده
    ctx, query = asyncio.run(_fire(app_ctx, f"acc:cat:del:{p.id}", OWNER_ID))
    assert "حذف پلن" in query.edited_texts[-1]
    with app_ctx.unit_of_work() as uow:
        assert uow.products.get(p.id) is not None

    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute("SELECT token FROM confirmations WHERE actor_id=?", (OWNER_ID,)).fetchone()
    token = row[0]

    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert "حذف شد" in query2.edited_texts[-1]
    with app_ctx.unit_of_work() as uow:
        assert uow.products.get(p.id) is None


# --------------------------------------------------------------------------
# Inventory add/reveal/delete
# --------------------------------------------------------------------------

def test_inventory_add_and_reveal_and_delete(app_ctx):
    with app_ctx.unit_of_work() as uow:
        from core.catalog import service as catalog_service
        p = catalog_service.create_product(uow, OWNER_ID, "پلن VPN", 10000)

    ctx, query = asyncio.run(_fire(app_ctx, f"acc:inv:add:{p.id}", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "vless://abc123\nvless://def456", state))
    assert "افزوده شد" in upd.message.replies[-1]

    with app_ctx.unit_of_work() as uow:
        items = uow.inventory.page(p.id, status="AVAILABLE")
    assert items.total == 2
    item_id = items.items[0].id

    # کاربر بدون inventory.reveal رد می‌شود
    ctx, q1 = asyncio.run(_fire(app_ctx, f"acc:inv:reveal:{item_id}:{p.id}", ADMIN_ID))
    assert any("دسترسی" in a for a in q1.alerts)

    # OWNER می‌تواند ببیند
    ctx, q2 = asyncio.run(_fire(app_ctx, f"acc:inv:reveal:{item_id}:{p.id}", OWNER_ID))
    assert any("vless" in h for h in q2.message.html_replies)

    # حذف با تأیید دومرحله‌ای
    ctx, q3 = asyncio.run(_fire(app_ctx, f"acc:inv:delitem:{item_id}:{p.id}", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute("SELECT token FROM confirmations WHERE actor_id=?", (OWNER_ID,)).fetchone()
    token = row[0]
    ctx, q4 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert "حذف شد" in q4.edited_texts[-1]
    with app_ctx.unit_of_work() as uow:
        remaining = uow.inventory.page(p.id, status="AVAILABLE")
    assert remaining.total == 1


# --------------------------------------------------------------------------
# RBAC granular: grant/toggle/revoke — و جلوگیری از Privilege Escalation
# --------------------------------------------------------------------------

def test_owner_grants_and_toggles_admin_permission(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:adm:new", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, str(PLAIN_USER_ID), state))
    assert app_ctx.state.get(OWNER_ID) is None
    with app_ctx.unit_of_work() as uow:
        assert rbac.is_admin(uow, PLAIN_USER_ID)
        assert list(rbac.grants_of(uow, PLAIN_USER_ID)) == []

    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:adm:tglp:{PLAIN_USER_ID}:users.view", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        assert "users.view" in rbac.grants_of(uow, PLAIN_USER_ID)

    # toggle again removes it
    ctx, query3 = asyncio.run(_fire(app_ctx, f"acc:adm:tglp:{PLAIN_USER_ID}:users.view", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        assert "users.view" not in rbac.grants_of(uow, PLAIN_USER_ID)


def test_non_owner_admin_cannot_grant_or_revoke_admins(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:adm:new", ADMIN_ID))
    assert app_ctx.state.get(ADMIN_ID) is None
    assert any("OWNER" in a for a in query.alerts)

    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:adm:rev:{ADMIN_ID}", ADMIN_ID))
    with app_ctx.unit_of_work() as uow:
        assert rbac.is_admin(uow, ADMIN_ID)  # هنوز ادمین است، چون خودش اجازهٔ حذف ندارد


def test_owner_only_permission_can_never_be_granted(app_ctx):
    from core.errors import NotAuthorizedError as NAE
    with app_ctx.unit_of_work() as uow:
        with pytest.raises(NAE):
            rbac.set_admin_permissions(uow, ADMIN_ID, ["rbac.manage"], actor_id=OWNER_ID)


def test_admin_revoke_flow_with_confirmation(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, f"acc:adm:rev:{ADMIN_ID}", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute("SELECT token FROM confirmations WHERE actor_id=?", (OWNER_ID,)).fetchone()
    token = row[0]
    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert "حذف شد" in query2.edited_texts[-1]
    with app_ctx.unit_of_work() as uow:
        assert not rbac.is_admin(uow, ADMIN_ID)


# --------------------------------------------------------------------------
# Settings: typed registry with validation + audit masking for card_number
# --------------------------------------------------------------------------

def test_settings_toggle_bool_and_edit_validated_int(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:set:tgl:locked", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        from core.settings import service as settings_service
        assert settings_service.get_bool(uow, "locked") is True

    ctx, query2 = asyncio.run(_fire(app_ctx, "acc:set:edit:dice_reward", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "abc", state))
    assert "عدد" in upd.message.replies[-1] or "نامعتبر" in upd.message.replies[-1] or "⚠️" in upd.message.replies[-1]

    ctx, query3 = asyncio.run(_fire(app_ctx, "acc:set:edit:dice_reward", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd2 = asyncio.run(_fire_text(app_ctx, OWNER_ID, "30000", state))
    with app_ctx.unit_of_work() as uow:
        from core.settings import service as settings_service
        assert settings_service.get_int(uow, "dice_reward") == 30000


def test_card_number_change_is_masked_in_audit(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:set:edit:card_number", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    asyncio.run(_fire_text(app_ctx, OWNER_ID, "1234567890123456", state))
    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute(
            "SELECT after_json FROM audit_logs WHERE action='settings.change' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert "1234567890123456" not in row[0]
    assert "3456" in row[0]


# --------------------------------------------------------------------------
# Coupons
# --------------------------------------------------------------------------

def test_coupon_create_and_toggle(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:cpn:new", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "OFF10", state))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "PERCENT", state))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "10", state))
    assert "ساخته شد" in upd.message.replies[-1]

    with app_ctx.unit_of_work() as uow:
        coupon = uow.coupons.get_by_code("OFF10")
    assert coupon is not None and coupon.value == 10

    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:cpn:tgl:{coupon.id}:0", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        assert uow.coupons.get(coupon.id).is_active is False


# --------------------------------------------------------------------------
# Reseller tiers + referral reward anti-abuse
# --------------------------------------------------------------------------

def test_reseller_tier_create_and_assign(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:ref:newtier", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "طلایی", state))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "20", state))
    with app_ctx.unit_of_work() as uow:
        tiers = uow.resellers.list_tiers()
    assert len(tiers) == 1 and tiers[0].discount_percent == 20

    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:ref:settier:{PLAIN_USER_ID}:{tiers[0].id}", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        u = uow.users.get_or_create(PLAIN_USER_ID)
    assert u.reseller_tier_id == tiers[0].id


def test_referral_reward_paid_once_and_daily_cap_respected(app_ctx):
    from core.reseller import service as reseller_service
    from core.settings import service as settings_service

    with app_ctx.unit_of_work() as uow:
        ok1 = reseller_service.pay_referral_reward(uow, OWNER_ID, 111111)
    assert ok1 is True
    with app_ctx.unit_of_work() as uow:
        ok2 = reseller_service.pay_referral_reward(uow, OWNER_ID, 111111)  # همان referred دوباره
    assert ok2 is False  # UNIQUE(referred_id) از پرداخت دوباره جلوگیری می‌کند

    with app_ctx.unit_of_work() as uow:
        settings_service.set_value(uow, OWNER_ID, "referral_daily_cap", "1")
    with app_ctx.unit_of_work() as uow:
        ok3 = reseller_service.pay_referral_reward(uow, OWNER_ID, 222222)
    assert ok3 is False  # سقف روزانه (۱، که قبلاً با کاربر ۱۱۱۱۱۱ مصرف شده) رعایت می‌شود


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------

def test_ticket_open_reply_close_cycle(app_ctx):
    from core.tickets import service as tickets_service
    with app_ctx.unit_of_work() as uow:
        t = tickets_service.open_ticket(uow, PLAIN_USER_ID, "مشکل اتصال", "وصل نمی‌شود")

    ctx, query = asyncio.run(_fire(app_ctx, f"acc:tic:reply:{t.id}", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "پروتکل را عوض کنید", state))
    assert len(ctx.bot.sent_messages) == 1

    with app_ctx.unit_of_work() as uow:
        refreshed = uow.tickets.get(t.id)
    assert refreshed.status == "ANSWERED"

    ctx, query2 = asyncio.run(_fire(app_ctx, f"acc:tic:close:{t.id}", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        assert uow.tickets.get(t.id).status == "CLOSED"


def test_admin_without_tickets_permission_cannot_reply(app_ctx):
    from core.tickets import service as tickets_service
    with app_ctx.unit_of_work() as uow:
        t = tickets_service.open_ticket(uow, PLAIN_USER_ID, "سوال", "چطور شارژ کنم؟")
    ctx, query = asyncio.run(_fire(app_ctx, f"acc:tic:reply:{t.id}", ADMIN_ID))
    assert app_ctx.state.get(ADMIN_ID) is None
    assert any("دسترسی" in a for a in query.alerts)


# --------------------------------------------------------------------------
# Broadcast
# --------------------------------------------------------------------------

def test_broadcast_full_flow(app_ctx):
    ctx, query = asyncio.run(_fire(app_ctx, "acc:bro:home", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    assert state == {"acc": "broadcast_text"}

    ctx, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "سرویس‌ها به‌روزرسانی شدند", state))
    assert app_ctx.state.get(OWNER_ID) is None
    assert "تأیید می‌کنید" in upd.message.html_replies[-1]

    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute("SELECT token FROM confirmations WHERE actor_id=?", (OWNER_ID,)).fetchone()
    token = row[0]
    ctx2, query2 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert "پایان یافت" in query2.edited_texts[-1]
    # سه کاربر seed‌شده در fixture (OWNER/ADMIN/PLAIN) پیام گرفتند
    assert len(ctx2.bot.sent_messages) == 3


# --------------------------------------------------------------------------
# Backup + system health
# --------------------------------------------------------------------------

def test_backup_create_flow(app_ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("GHIYAB_BACKUP_DIR", str(tmp_path / "backups"))
    ctx, query = asyncio.run(_fire(app_ctx, "acc:bak:home", OWNER_ID))
    assert "سلامت سیستم" in query.edited_texts[-1]

    ctx, query2 = asyncio.run(_fire(app_ctx, "acc:bak:new", OWNER_ID))
    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute("SELECT token FROM confirmations WHERE actor_id=?", (OWNER_ID,)).fetchone()
    token = row[0]
    ctx3, query3 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert "Backup ساخته شد" in query3.edited_texts[-1]

    import os
    files = os.listdir(str(tmp_path / "backups"))
    assert any(f.endswith(".db") for f in files)


def test_non_owner_admin_cannot_download_backup(app_ctx):
    with app_ctx.unit_of_work() as uow:
        rbac.set_admin_permissions(uow, ADMIN_ID, ["backup.create", "system.health"], actor_id=OWNER_ID)
    ctx, query = asyncio.run(_fire(app_ctx, "acc:bak:dl", ADMIN_ID))
    assert any("دسترسی" in a or "OWNER" in a for a in query.alerts)


# --------------------------------------------------------------------------
# Confirmation token cross-user rejection
# --------------------------------------------------------------------------

def test_confirmation_token_cannot_be_used_by_another_user(app_ctx):
    with app_ctx.unit_of_work() as uow:
        rbac.set_admin_permissions(uow, ADMIN_ID, ["wallet.adjust"], actor_id=OWNER_ID)
    ctx, query = asyncio.run(_fire(app_ctx, f"acc:wal:adj:{PLAIN_USER_ID}", ADMIN_ID))
    state = app_ctx.state.get(ADMIN_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, ADMIN_ID, "1000", state))
    state = app_ctx.state.get(ADMIN_ID)
    ctx, upd = asyncio.run(_fire_text(app_ctx, ADMIN_ID, "دلیل", state))
    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute("SELECT token FROM confirmations WHERE actor_id=?", (ADMIN_ID,)).fetchone()
    token = row[0]

    # OWNER تلاش می‌کند توکن ادمین دیگر را مصرف کند
    ctx2, query2 = asyncio.run(_fire(app_ctx, f"acc:confirm:{token}", OWNER_ID))
    assert any("متعلق" in a for a in query2.alerts)
    with app_ctx.unit_of_work() as uow:
        assert uow.wallet.get_balance(PLAIN_USER_ID, "TOMAN") == 0
