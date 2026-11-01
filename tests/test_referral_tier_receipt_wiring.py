"""
اتصال واقعی قابلیت‌هایی که در README «کامل» بودند ولی در مسیر کاربر وصل نبودند:
رفرال (UNIQUE/سقف/غیرفعال‌سازی)، تخفیف سطح Reseller، و تشخیص رسید تکراری.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.catalog import service as catalog_service
from core.inventory import service as inventory_service
from core.orders import service as orders_service
from core.reseller import service as reseller_service
from core.settings import service as settings_service
from tests.test_bot_admin_permissions import (  # noqa: F401
    app_ctx, _FakeContext, _FakeUpdate, _FakeCallbackQuery, OWNER_ID, PLAIN_USER_ID,
)
from adapters.telegram_bot import bot as bot_module

REFERRER = 777001


def _fire(app_ctx, data, user_id):
    ctx = _FakeContext(app_ctx)
    q = _FakeCallbackQuery(data, user_id)
    asyncio.run(bot_module.handle_callbacks(_FakeUpdate(q), ctx))
    return ctx, q


def _bal(app_ctx, uid):
    with app_ctx.unit_of_work() as uow:
        return uow.wallet.get_balance(uid, "TOMAN")


def _legacy_signup_trigger(app_ctx):
    """V2 Final: پیش‌فرض پاداش بعد از اولین سفارش موفق است؛ این تست‌ها حالت V1 (signup) را می‌سنجند."""
    with app_ctx.unit_of_work() as uow:
        settings_service.set_value(uow, OWNER_ID, "referral_trigger", "signup")


def _make_referred_user(app_ctx):
    _legacy_signup_trigger(app_ctx)
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(REFERRER)
        uow.users.get_or_create(PLAIN_USER_ID)
        uow.users.set_referred_by(PLAIN_USER_ID, REFERRER)


# ---------------- رفرال ----------------

def test_referral_reward_paid_once_even_if_accept_rules_pressed_repeatedly(app_ctx):
    """باگ: accept_rules هر بار پاداش می‌داد (کلیک روی پیام‌های قدیمیِ ضوابط = پاداش نامحدود)."""
    _make_referred_user(app_ctx)
    for _ in range(3):
        _fire(app_ctx, "accept_rules", PLAIN_USER_ID)
        bot_module._last_action_at.clear() if hasattr(bot_module, "_last_action_at") else None
    assert _bal(app_ctx, REFERRER) == 5000


def test_referral_respects_admin_disable_switch(app_ctx):
    """باگ: ادمین referral_enabled=0 می‌کرد ولی مسیر واقعی نادیده می‌گرفت."""
    _make_referred_user(app_ctx)
    with app_ctx.unit_of_work() as uow:
        settings_service.set_value(uow, OWNER_ID, "referral_enabled", "0")
    _fire(app_ctx, "accept_rules", PLAIN_USER_ID)
    assert _bal(app_ctx, REFERRER) == 0


def test_referral_uses_configured_bonus_amount(app_ctx):
    _make_referred_user(app_ctx)
    with app_ctx.unit_of_work() as uow:
        settings_service.set_value(uow, OWNER_ID, "referral_bonus_minor", "12000")
    _fire(app_ctx, "accept_rules", PLAIN_USER_ID)
    assert _bal(app_ctx, REFERRER) == 12000


# ---------------- تخفیف سطح Reseller ----------------

def _product_and_tier(app_ctx, discount):
    with app_ctx.unit_of_work() as uow:
        p = catalog_service.create_product(uow, OWNER_ID, "پلن", 100_000)
        inventory_service.add_items(uow, p.id, "unlimited", ["c1", "c2"], actor_id=OWNER_ID)
        uow.users.get_or_create(PLAIN_USER_ID)
        tier = reseller_service.create_tier(uow, OWNER_ID, "طلایی", discount)
        reseller_service.assign_tier(uow, OWNER_ID, PLAIN_USER_ID, tier.id)
        uow.wallet.adjust(PLAIN_USER_ID, "TOMAN", 200_000)
    return p


def test_wallet_purchase_applies_reseller_tier_discount(app_ctx):
    """باگ: price_with_tier هیچ‌جا صدا زده نمی‌شد؛ کاربر دارای سطح Reseller قیمت کامل می‌پرداخت."""
    p = _product_and_tier(app_ctx, 25)
    with app_ctx.unit_of_work() as uow:
        order = orders_service.purchase_with_wallet(uow, PLAIN_USER_ID, p.id)
    assert order.price_minor == 75_000
    assert _bal(app_ctx, PLAIN_USER_ID) == 125_000


def test_tier_and_agent_discount_use_best_not_sum(app_ctx):
    p = _product_and_tier(app_ctx, 5)      # tier 5% < agent 10%
    with app_ctx.unit_of_work() as uow:
        uow.users.set_agent(PLAIN_USER_ID, True)
        order = orders_service.purchase_with_wallet(uow, PLAIN_USER_ID, p.id)
    assert order.price_minor == 90_000


def test_direct_purchase_approval_applies_tier_discount(app_ctx):
    p = _product_and_tier(app_ctx, 20)
    with app_ctx.unit_of_work() as uow:
        req = orders_service.create_pending_request(uow, "buy", PLAIN_USER_ID, product_id=p.id)
        _, _, order = orders_service.approve_direct_purchase(uow, req, OWNER_ID)
    assert order.price_minor == 80_000


def test_buy_screen_shows_same_price_that_wallet_charges(app_ctx):
    p = _product_and_tier(app_ctx, 25)
    _, q = _fire(app_ctx, f"buy_prod_{p.id}", PLAIN_USER_ID)
    assert "75,000" in q.edited_texts[-1]


# ---------------- رسید تکراری ----------------

class _Photo:
    def __init__(self, uid): self.file_id, self.file_unique_id = f"fid-{uid}", uid


class _PhotoMessage:
    def __init__(self, mid, uid):
        self.message_id, self.photo, self.replies = mid, [_Photo(uid)], []
    async def reply_text(self, text, **kw): self.replies.append(text)


class _PhotoUpdate:
    def __init__(self, user_id, mid, uid):
        self.effective_user = SimpleNamespace(id=user_id)
        self.message = _PhotoMessage(mid, uid)


class _PhotoBot(_FakeContext):
    def __init__(self, app_ctx):
        super().__init__(app_ctx)
        self.bot.photos = []
        async def send_photo(chat_id, photo, **kw): self.bot.photos.append((chat_id, photo))
        self.bot.send_photo = send_photo


def _send_receipt(app_ctx, user_id, mid, uid, amount=30_000):
    app_ctx.state.set(user_id, {"action": "send_charge_receipt", "amount": amount})
    ctx = _PhotoBot(app_ctx)
    upd = _PhotoUpdate(user_id, mid, uid)
    asyncio.run(bot_module.handle_photos(upd, ctx))
    return ctx, upd


def _count_pending(app_ctx):
    with app_ctx.unit_of_work() as uow:
        return uow.pending_requests.count_pending()


def test_same_receipt_photo_resent_creates_no_second_request(app_ctx):
    """باگ: کلید idempotency بر پایهٔ message_id بود؛ همان عکس با پیام جدید = درخواست شارژ دوم."""
    _send_receipt(app_ctx, PLAIN_USER_ID, mid=1, uid="UNIQ-A")
    ctx, upd = _send_receipt(app_ctx, PLAIN_USER_ID, mid=2, uid="UNIQ-A")
    assert _count_pending(app_ctx) == 1
    assert "قبلاً" in upd.message.replies[-1]
    assert ctx.bot.photos == []          # دوباره برای ادمین ارسال نشد


def test_same_receipt_from_another_user_is_blocked_too(app_ctx):
    _send_receipt(app_ctx, PLAIN_USER_ID, mid=1, uid="UNIQ-B")
    _, upd = _send_receipt(app_ctx, 555123, mid=1, uid="UNIQ-B")
    assert _count_pending(app_ctx) == 1
    assert "قبلاً" in upd.message.replies[-1]


def test_different_receipts_both_accepted(app_ctx):
    _send_receipt(app_ctx, PLAIN_USER_ID, mid=1, uid="UNIQ-C")
    _send_receipt(app_ctx, PLAIN_USER_ID, mid=2, uid="UNIQ-D")
    assert _count_pending(app_ctx) == 2


def test_rejected_receipt_may_be_resent(app_ctx):
    _send_receipt(app_ctx, PLAIN_USER_ID, mid=1, uid="UNIQ-E")
    with app_ctx.unit_of_work() as uow:
        rid = uow.pending_requests.find_by_receipt_unique_id("UNIQ-E").id
        orders_service.reject_request(uow, rid, OWNER_ID)
    _send_receipt(app_ctx, PLAIN_USER_ID, mid=2, uid="UNIQ-E")
    assert _count_pending(app_ctx) == 1


def test_receipt_is_stored_with_file_ids(app_ctx):
    _send_receipt(app_ctx, PLAIN_USER_ID, mid=1, uid="UNIQ-F")
    with app_ctx.unit_of_work() as uow:
        r = uow.pending_requests.find_by_receipt_unique_id("UNIQ-F")
    assert r is not None and r.receipt_file_id == "fid-UNIQ-F"
