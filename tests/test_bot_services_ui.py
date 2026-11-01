"""لایهٔ Adapter: «سرویس‌های من»، تمدید با تأیید، اعتبارسنجی Callback، حلقهٔ نگهداری، بازیابی پس از ری‌استارت."""
import asyncio

import pytest

from adapters.telegram_bot import bot as bot_module
from adapters.telegram_bot import maintenance, services_ui
from core.provisioning import service as prov
from core.settings import service as settings_service
from core.vpn_services import service as svc
from core.wallet import service as wallet_service
from core.orders import service as orders_service
from providers.vpn.xui.provider import ThreeXUIProvider, XuiConfig
from tests.fake_xui import FakeXui
from tests.test_bot_admin_permissions import (
    app_ctx, _FakeCallbackQuery, _FakeUpdate, _FakeContext, OWNER_ID,  # noqa: F401
)

USER = 777
GB = 1024 ** 3


class Q(_FakeCallbackQuery):
    def __init__(self, data, user_id, message_id=10):
        super().__init__(data, user_id)
        self.message.message_id = message_id
        self.answers = []
        self.markups = []

    async def answer(self, text=None, **kw):
        if text:
            self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edited_texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))


class Ctx(_FakeContext):
    def __init__(self, app_ctx):
        super().__init__(app_ctx)
        self.photos = []

        async def send_photo(chat_id, photo, **kw):
            self.photos.append((chat_id, len(photo)))
        self.bot.send_photo = send_photo


@pytest.fixture
def xui():
    s = FakeXui(token="t").start()
    p = ThreeXUIProvider(XuiConfig(base_url=s.url, api_token="t", timeout=2, max_retries=0), sleep=lambda x: None)
    prov.set_provider_factory("3x-ui", lambda: p)
    yield s
    prov.set_provider_factory("3x-ui", None)
    s.stop()


def run(coro):
    return asyncio.run(coro)


def make_service(app_ctx, balance=100000):
    with app_ctx.unit_of_work() as uow:
        pid = uow.products.create("VPN 30d", 10000, "TOMAN").id
        prov.set_profile(uow, OWNER_ID, pid, "3x-ui", 1, 30, 10)
        wallet_service.adjust_balance(uow, USER, balance, "seed")
    with app_ctx.unit_of_work() as uow:
        order = orders_service.purchase_with_wallet(uow, USER, pid)
    prov.provision_order(app_ctx.unit_of_work, order.id)
    return order.id


def fire(app_ctx, data, user=USER, message_id=10):
    ctx = Ctx(app_ctx)
    q = Q(data, user, message_id)
    run(bot_module.handle_callbacks(_FakeUpdate(q), ctx))
    return ctx, q


def bal(app_ctx):
    with app_ctx.unit_of_work() as uow:
        return wallet_service.get_balance(uow, USER)


# ---- callback validation ----
@pytest.mark.parametrize("bad", ["svc:", "svc:v:", "svc:v:abc", "svc:zz:1", "svc:v:1;DROP", "svc:v:-1",
                                 "svc:rc:99999999999999", "svc:v:1:2"])
def test_invalid_service_callbacks_rejected_without_side_effects(app_ctx, bad):
    assert services_ui.parse_callback(bad) is None
    ctx, q = fire(app_ctx, bad)
    assert q.answers and not q.edited_texts


def test_valid_pattern_parses():
    assert services_ui.parse_callback("svc:rc:42") == ("rc", 42)


# ---- view / links / QR ----
def test_view_shows_status_traffic_expiry_and_buttons(app_ctx, xui):
    oid = make_service(app_ctx)
    xui.use(f"gy{oid}", down=2 * GB)
    ctx, q = fire(app_ctx, f"svc:v:{oid}")
    text = q.edited_texts[-1]
    assert "VPN 30d" in text and "2.00 GB" in text and "10.00 GB" in text and "🟢" in text
    cbs = [b.callback_data for row in q.markups[-1].inline_keyboard for b in row]
    assert f"svc:l:{oid}" in cbs and f"svc:r:{oid}" in cbs


def test_view_when_panel_down_is_honest_about_stale_data(app_ctx, xui):
    oid = make_service(app_ctx)
    fire(app_ctx, f"svc:v:{oid}")
    xui.down = True
    ctx, q = fire(app_ctx, f"svc:v:{oid}")
    assert "ℹ️" in q.edited_texts[-1]


def test_links_and_qr_delivery(app_ctx, xui):
    oid = make_service(app_ctx)
    ctx, q = fire(app_ctx, f"svc:l:{oid}")
    assert any("vless://" in m[1] for m in ctx.bot.sent_messages)
    assert ctx.photos and ctx.photos[0][1] > 100  # QR PNG


def test_other_user_cannot_open_service(app_ctx, xui):
    oid = make_service(app_ctx)
    ctx, q = fire(app_ctx, f"svc:v:{oid}", user=888)
    assert not q.edited_texts and q.answers


def test_english_language_rendering(app_ctx, xui):
    oid = make_service(app_ctx)
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(USER)
        uow.users.set_lang(USER, "en")
    ctx, q = fire(app_ctx, f"svc:v:{oid}")
    assert "Status:" in q.edited_texts[-1] and "Active" in q.edited_texts[-1]


# ---- renew ----
def test_renew_requires_confirmation_and_double_tap_charges_once(app_ctx, xui):
    oid = make_service(app_ctx)
    ctx, q = fire(app_ctx, f"svc:r:{oid}")
    assert "10,000" in q.edited_texts[-1] and bal(app_ctx) == 90000  # فقط خلاصه؛ هنوز کسر نشده
    for _ in range(2):  # دو تپ روی همان پیام تأیید
        ctx, q = fire(app_ctx, f"svc:rc:{oid}", message_id=55)
    assert bal(app_ctx) == 80000
    assert "✅" in q.edited_texts[-1]


def test_renew_insufficient_balance_alerts_and_keeps_balance(app_ctx, xui):
    oid = make_service(app_ctx, balance=10000)
    ctx, q = fire(app_ctx, f"svc:rc:{oid}", message_id=1)
    assert q.answers and "💸" in q.answers[-1] and bal(app_ctx) == 0


def test_provider_error_details_never_reach_user(app_ctx, xui):
    oid = make_service(app_ctx)
    xui.down = True
    ctx, q = fire(app_ctx, f"svc:l:{oid}")
    shown = " ".join(q.answers + q.edited_texts)
    assert "127.0.0.1" not in shown and "t" != shown and "Traceback" not in shown and "Bearer" not in shown
    assert q.answers


def test_auto_renew_toggle_requires_feature_flag(app_ctx, xui):
    oid = make_service(app_ctx)
    ctx, q = fire(app_ctx, f"svc:ar:{oid}")
    assert q.answers  # feature خاموش → پیام امن
    with app_ctx.unit_of_work() as uow:
        assert uow.provisioning.get_client_by_order(oid).auto_renew is False
        settings_service.toggle_bool(uow, OWNER_ID, "auto_renewal_enabled")
    fire(app_ctx, f"svc:ar:{oid}")
    with app_ctx.unit_of_work() as uow:
        assert uow.provisioning.get_client_by_order(oid).auto_renew is True


# ---- purchase → provision → deliver (adapter level) ----
def test_wallet_purchase_issues_real_service_and_delivers(app_ctx, xui):
    with app_ctx.unit_of_work() as uow:
        pid = uow.products.create("VPN", 10000, "TOMAN").id
        prov.set_profile(uow, OWNER_ID, pid, "3x-ui", 1, 30, 10)
        wallet_service.adjust_balance(uow, USER, 50000, "seed")
    ctx, q = fire(app_ctx, f"wallet_pay_{pid}")
    assert len(xui.clients) == 1
    assert any("🎉" in m[1] for m in ctx.bot.sent_messages)
    assert bal(app_ctx) == 40000


def test_wallet_purchase_when_not_configured_does_not_charge(app_ctx):
    unconf = ThreeXUIProvider(XuiConfig())
    prov.set_provider_factory("3x-ui", lambda: unconf)
    try:
        with app_ctx.unit_of_work() as uow:
            pid = uow.products.create("VPN", 10000, "TOMAN").id
            prov.set_profile(uow, OWNER_ID, pid, "3x-ui", 1, 30, 10)
            wallet_service.adjust_balance(uow, USER, 50000, "seed")
        ctx, q = fire(app_ctx, f"wallet_pay_{pid}")
        assert bal(app_ctx) == 50000 and q.answers and "NOT_CONFIGURED" in q.answers[-1]
    finally:
        prov.set_provider_factory("3x-ui", None)


def test_purchase_with_panel_down_defers_and_maintenance_delivers_later(app_ctx, xui):
    with app_ctx.unit_of_work() as uow:
        pid = uow.products.create("VPN", 10000, "TOMAN").id
        prov.set_profile(uow, OWNER_ID, pid, "3x-ui", 1, 30, 10)
        wallet_service.adjust_balance(uow, USER, 50000, "seed")
    xui.down = True
    ctx, q = fire(app_ctx, f"wallet_pay_{pid}")
    assert any("آماده‌سازی" in m[1] for m in ctx.bot.sent_messages)  # اعلام صادقانهٔ انتظار
    assert any(m[0] == OWNER_ID for m in ctx.bot.sent_messages)        # هشدار به Owner
    assert not xui.clients
    xui.down = False
    ctx2 = Ctx(app_ctx)
    report = run(maintenance.run_once(app_ctx, ctx2.bot))
    assert report["retry_provisioning"]["ok"] == 1
    assert len(xui.clients) == 1
    assert any(m[0] == USER and "🎉" in m[1] for m in ctx2.bot.sent_messages)


# ---- restart recovery ----
def test_pending_renewal_survives_restart_and_is_recovered(app_ctx, xui):
    oid = make_service(app_ctx)
    xui.down = True
    r = svc.renew_service(app_ctx.unit_of_work, USER, oid, idempotency_key="x")
    assert r.status == "PENDING"
    # «ری‌استارت»: هیچ شیء in-memory نمانده؛ فقط DB. حلقهٔ نگهداری از صفر اجرا می‌شود.
    xui.down = False
    from repository.sqlite.state_repo import SqliteStateRepository
    from core.state.service import ConversationStateService
    app_ctx.state = ConversationStateService(SqliteStateRepository(app_ctx.db_path))
    import os
    os.environ["GHIYAB_BACKUP_DIR"] = os.path.join(os.path.dirname(app_ctx.db_path), "bk")
    ctx = Ctx(app_ctx)
    # recover_stuck_renewals(older_than_minutes=5) → رکورد تازه است؛ مستقیم با آستانهٔ ۰ صدا می‌زنیم
    assert svc.recover_stuck_renewals(app_ctx.unit_of_work, older_than_minutes=0)["completed"] == 1
    assert bal(app_ctx) == 80000


def test_conversation_state_persists_across_restart(app_ctx):
    app_ctx.state.set(USER, {"action": "waiting_for_charge_amount", "amount": 5})
    from repository.sqlite.state_repo import SqliteStateRepository
    from core.state.service import ConversationStateService
    fresh = ConversationStateService(SqliteStateRepository(app_ctx.db_path))
    assert fresh.get(USER) == {"action": "waiting_for_charge_amount", "amount": 5}
    assert fresh.purge_stale(24) == 0 and fresh.get(USER) is not None


# ---- maintenance: daily backup + reminders + auto-renew notifications ----
def test_maintenance_daily_backup_created_once_and_verified(app_ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("GHIYAB_BACKUP_DIR", str(tmp_path / "bk"))
    ctx = Ctx(app_ctx)
    r1 = run(maintenance.run_once(app_ctx, ctx.bot))
    assert r1["backup"] and r1["backup"].endswith(".db")
    r2 = run(maintenance.run_once(app_ctx, ctx.bot))
    assert r2["backup"] is None  # امروز قبلاً گرفته شده


def test_maintenance_auto_renew_and_reminder_notify_user(app_ctx, xui, tmp_path, monkeypatch):
    monkeypatch.setenv("GHIYAB_BACKUP_DIR", str(tmp_path / "bk"))
    oid = make_service(app_ctx)
    with app_ctx.unit_of_work() as uow:
        settings_service.toggle_bool(uow, OWNER_ID, "auto_renewal_enabled")
        settings_service.set_value(uow, OWNER_ID, "auto_renewal_window_hours", "48")
        svc.set_auto_renew(uow, USER, oid, True)
    # انقضا را در بازهٔ پنجره بیاور
    with app_ctx.unit_of_work() as uow:
        uow.provisioning.set_expiry(oid, svc.now_ms() + 3600_000)
    ctx = Ctx(app_ctx)
    report = run(maintenance.run_once(app_ctx, ctx.bot))
    assert report["auto_renew"][0]["outcome"] == "renewed"
    assert any(m[0] == USER and "🔄" in m[1] for m in ctx.bot.sent_messages)


def test_maintenance_notifies_referrer_after_first_order(app_ctx, tmp_path, monkeypatch):
    from core.inventory import service as inv
    monkeypatch.setenv("GHIYAB_BACKUP_DIR", str(tmp_path / "bk"))
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(4242)
        uow.users.get_or_create(USER)
        uow.users.set_referred_by(USER, 4242)
        pid = uow.products.create("m", 1000, "TOMAN").id
        inv.add_items(uow, pid, "unlimited", ["a"], actor_id=OWNER_ID)
        wallet_service.adjust_balance(uow, USER, 5000, "seed")
        orders_service.purchase_with_wallet(uow, USER, pid)
    ctx = Ctx(app_ctx)
    run(maintenance.run_once(app_ctx, ctx.bot))
    assert any(m[0] == 4242 and "🎁" in m[1] for m in ctx.bot.sent_messages)
    ctx2 = Ctx(app_ctx)
    run(maintenance.run_once(app_ctx, ctx2.bot))
    assert not any(m[0] == 4242 for m in ctx2.bot.sent_messages)  # فقط یک‌بار
