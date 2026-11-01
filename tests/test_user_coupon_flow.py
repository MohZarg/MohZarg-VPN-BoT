"""
مسیر کامل کوپن برای کاربر (قبلاً فقط ادمین می‌توانست کوپن بسازد و هیچ مسیری برای مصرف نبود):
دکمهٔ «کد تخفیف» → متن کد → پیش‌نمایش → پرداخت کیف پول / کارت‌به‌کارت → تأیید ادمین.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.catalog import service as catalog_service
from core.coupons import service as coupons_service
from core.inventory import service as inventory_service
from core.orders import service as orders_service
from core.reseller import service as reseller_service
from core.settings import service as settings_service
from core.errors import CouponError
from tests.test_bot_admin_permissions import (  # noqa: F401
    app_ctx, _FakeContext, _FakeUpdate, _FakeCallbackQuery, OWNER_ID, PLAIN_USER_ID,
)
from tests.test_referral_tier_receipt_wiring import _PhotoBot, _PhotoUpdate
from adapters.telegram_bot import bot as bot_module

OTHER = 888222


class _AlertQuery(_FakeCallbackQuery):
    def __init__(self, data, user_id):
        super().__init__(data, user_id)
        self.alerts = []
    async def answer(self, text=None, **kw):
        if text:
            self.alerts.append(text)


class _TextMessage:
    def __init__(self, text):
        self.text, self.replies, self.chat_id, self.message_id = text, [], 1, 1
    async def reply_text(self, text, **kw): self.replies.append(text)
    async def reply_html(self, text, **kw): self.replies.append(text); self.kw = kw


def _cb(app_ctx, data, uid, ctx=None):
    ctx = ctx or _FakeContext(app_ctx)
    q = _AlertQuery(data, uid)
    asyncio.run(bot_module.handle_callbacks(_FakeUpdate(q), ctx))
    return ctx, q


def _text(app_ctx, uid, text):
    ctx = _FakeContext(app_ctx)
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=uid, username=None), message=_TextMessage(text))
    asyncio.run(bot_module.handle_text_messages(upd, ctx))
    return upd.message


def _setup(app_ctx, *, price=100_000, stock=3, balance=500_000, kind="PERCENT", value=20, **ckw):
    with app_ctx.unit_of_work() as uow:
        p = catalog_service.create_product(uow, OWNER_ID, "پلن", price)
        inventory_service.add_items(uow, p.id, "unlimited", [f"cfg-{i}" for i in range(stock)], actor_id=OWNER_ID)
        uow.users.get_or_create(PLAIN_USER_ID)
        uow.users.get_or_create(OTHER)
        uow.wallet.adjust(PLAIN_USER_ID, "TOMAN", balance)
        uow.wallet.adjust(OTHER, "TOMAN", balance)
        coupons_service.create(uow, OWNER_ID, "SAVE", kind, value, **ckw)
    return p


def _bal(app_ctx, uid=PLAIN_USER_ID):
    with app_ctx.unit_of_work() as uow:
        return uow.wallet.get_balance(uid, "TOMAN")


def _uses(app_ctx):
    with app_ctx.unit_of_work() as uow:
        return uow.coupons.count_uses(uow.coupons.get_by_code("SAVE").id)


# ---------------- مسیر UI ----------------

def test_buy_screen_has_coupon_button_and_state_is_set(app_ctx):
    p = _setup(app_ctx)
    _, q = _cb(app_ctx, f"buy_prod_{p.id}", PLAIN_USER_ID)
    _, q2 = _cb(app_ctx, f"cpn_ask_{p.id}", PLAIN_USER_ID)
    assert app_ctx.state.get(PLAIN_USER_ID) == {"action": "waiting_coupon", "product_id": p.id}


def test_valid_code_shows_discounted_price_and_pay_buttons(app_ctx):
    p = _setup(app_ctx)
    _cb(app_ctx, f"cpn_ask_{p.id}", PLAIN_USER_ID)
    msg = _text(app_ctx, PLAIN_USER_ID, " save ")      # حروف کوچک و فاصله نرمال می‌شود
    assert "80,000" in msg.replies[-1]
    cbs = [b.callback_data for row in msg.kw["reply_markup"].inline_keyboard for b in row]
    assert f"wpc:{p.id}:SAVE" in cbs and f"dpc:{p.id}:SAVE" in cbs
    assert all(len(c.encode()) <= 64 for c in cbs)
    assert _uses(app_ctx) == 0      # پیش‌نمایش مصرف ثبت نمی‌کند


@pytest.mark.parametrize("code,needle", [("NOPE", ""), ("", "")])
def test_invalid_code_keeps_state_for_retry(app_ctx, code, needle):
    p = _setup(app_ctx)
    _cb(app_ctx, f"cpn_ask_{p.id}", PLAIN_USER_ID)
    msg = _text(app_ctx, PLAIN_USER_ID, code or "x")
    assert "⚠️" in msg.replies[-1]
    assert app_ctx.state.get(PLAIN_USER_ID) is not None


# ---------------- پرداخت با کیف پول ----------------

def test_wallet_purchase_with_coupon_charges_discounted_price_and_records_redemption(app_ctx):
    p = _setup(app_ctx)
    _, q = _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert _bal(app_ctx) == 420_000
    assert _uses(app_ctx) == 1
    assert "80,000" in q.edited_texts[-1] and "SAVE" in q.edited_texts[-1]
    with app_ctx.unit_of_work() as uow:
        o = uow.orders.page(user_id=PLAIN_USER_ID).items[0]
    assert (o.price_minor, o.discount_minor, o.coupon_code) == (80_000, 20_000, "SAVE")


def test_single_use_per_user_limit_blocks_second_purchase_atomically(app_ctx):
    p = _setup(app_ctx, per_user_limit=1)
    _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    _, q = _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert q.alerts and _bal(app_ctx) == 420_000 and _uses(app_ctx) == 1


def test_max_uses_global_limit(app_ctx):
    p = _setup(app_ctx, max_uses=1)
    _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    _, q = _cb(app_ctx, f"wpc:{p.id}:SAVE", OTHER)
    assert q.alerts and _bal(app_ctx, OTHER) == 500_000


def test_failed_purchase_does_not_consume_coupon(app_ctx):
    """مخزن خالی → rollback کامل: نه پول کسر می‌شود نه کوپن مصرف."""
    p = _setup(app_ctx, stock=0)
    _, q = _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert q.alerts and _bal(app_ctx) == 500_000 and _uses(app_ctx) == 0


def test_insufficient_balance_does_not_consume_coupon(app_ctx):
    p = _setup(app_ctx, balance=10_000)
    _, q = _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert q.alerts and _uses(app_ctx) == 0


def test_inactive_coupon_rejected(app_ctx):
    p = _setup(app_ctx)
    with app_ctx.unit_of_work() as uow:
        coupons_service.set_active(uow, OWNER_ID, uow.coupons.get_by_code("SAVE").id, False)
    _, q = _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert q.alerts and _bal(app_ctx) == 500_000


# ---------------- قاعدهٔ ترکیب (best / stack) ----------------

def test_best_mode_coupon_weaker_than_agent_discount_is_refused_and_not_consumed(app_ctx):
    p = _setup(app_ctx, value=5)                        # کوپن ۵٪ < نماینده ۱۰٪
    with app_ctx.unit_of_work() as uow:
        uow.users.set_agent(PLAIN_USER_ID, True)
    _, q = _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert q.alerts and "بهتر نیست" in q.alerts[-1]
    assert _bal(app_ctx) == 500_000 and _uses(app_ctx) == 0


def test_best_mode_stronger_coupon_replaces_agent_discount_not_adds(app_ctx):
    p = _setup(app_ctx, value=30)                       # کوپن ۳۰٪ > نماینده ۱۰٪
    with app_ctx.unit_of_work() as uow:
        uow.users.set_agent(PLAIN_USER_ID, True)
    _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert _bal(app_ctx) == 500_000 - 70_000            # نه 63,000


def test_stack_mode_applies_coupon_on_top_of_agent_discount(app_ctx):
    p = _setup(app_ctx, value=50)
    with app_ctx.unit_of_work() as uow:
        uow.users.set_agent(PLAIN_USER_ID, True)
        settings_service.set_value(uow, OWNER_ID, "coupon_stacking", "stack")
    _cb(app_ctx, f"wpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert _bal(app_ctx) == 500_000 - 45_000            # 90,000 → 50٪


# ---------------- کارت‌به‌کارت ----------------

def _send_buy_receipt(app_ctx, uid, mid, uniq, state):
    app_ctx.state.set(uid, state)
    ctx = _PhotoBot(app_ctx)
    asyncio.run(bot_module.handle_photos(_PhotoUpdate(uid, mid, uniq), ctx))
    return ctx


def test_direct_pay_with_coupon_shows_exact_amount_and_sets_state(app_ctx):
    p = _setup(app_ctx)
    ctx, _ = _cb(app_ctx, f"dpc:{p.id}:SAVE", PLAIN_USER_ID)
    assert "80,000" in ctx.bot.sent_messages[-1][1]
    assert app_ctx.state.get(PLAIN_USER_ID)["coupon"] == "SAVE"


def test_direct_receipt_with_coupon_stores_expected_price_and_approval_honours_it(app_ctx):
    p = _setup(app_ctx)
    _send_buy_receipt(app_ctx, PLAIN_USER_ID, 1, "R1",
                      {"action": "direct_buy_receipt", "product_id": p.id, "coupon": "SAVE"})
    with app_ctx.unit_of_work() as uow:
        req = uow.pending_requests.find_by_receipt_unique_id("R1")
        assert (req.coupon_code, req.expected_price_minor) == ("SAVE", 80_000)
        # قیمت محصول بعد از ارسال رسید گران می‌شود؛ کاربر همان ۸۰ هزار را پرداخته
        uow._conn.execute("UPDATE products SET price_minor=150000 WHERE id=?", (p.id,))
        _, _, order = orders_service.approve_direct_purchase(uow, req.id, OWNER_ID)
    assert order.price_minor == 80_000
    assert _uses(app_ctx) == 1


def test_pending_receipts_reserve_single_use_coupon(app_ctx):
    """باگ بالقوه: دو رسید هم‌زمان با کوپن یک‌بارمصرف → هر دو تأیید و دو بار تخفیف."""
    p = _setup(app_ctx, per_user_limit=1)
    _send_buy_receipt(app_ctx, PLAIN_USER_ID, 1, "R2",
                      {"action": "direct_buy_receipt", "product_id": p.id, "coupon": "SAVE"})
    ctx = _send_buy_receipt(app_ctx, PLAIN_USER_ID, 2, "R3",
                            {"action": "direct_buy_receipt", "product_id": p.id, "coupon": "SAVE"})
    with app_ctx.unit_of_work() as uow:
        assert uow.pending_requests.count_pending_with_coupon("SAVE") == 1
        assert uow.pending_requests.find_by_receipt_unique_id("R3") is None
    assert app_ctx.state.get(PLAIN_USER_ID) is None


def test_direct_receipt_without_coupon_unchanged(app_ctx):
    p = _setup(app_ctx)
    _send_buy_receipt(app_ctx, PLAIN_USER_ID, 1, "R4", {"action": "direct_buy_receipt", "product_id": p.id})
    with app_ctx.unit_of_work() as uow:
        req = uow.pending_requests.find_by_receipt_unique_id("R4")
        assert req.coupon_code is None and req.expected_price_minor is None
