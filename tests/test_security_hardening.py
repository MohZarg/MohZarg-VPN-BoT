import logging
import os

import pytest

from core.coupons import service as coupons_service
from core.errors import CouponError
from core.orders import service as orders_service
from core.wallet import service as wallet_service
from security.env_file import load_env_file
from security.logging_setup import RedactingFilter, redact
from security.rate_limit import RateLimiter
from tests.test_bot_services_ui import app_ctx, Q, Ctx, OWNER_ID  # noqa: F401
from tests.test_bot_admin_permissions import _FakeUpdate
from adapters.telegram_bot import bot as bot_module
import asyncio


# ---- rate limiting ----
def test_token_bucket_blocks_burst_then_refills():
    t = [0.0]
    rl = RateLimiter(capacity=3, refill_per_sec=1.0, clock=lambda: t[0])
    assert [rl.allow(1) for _ in range(4)] == [True, True, True, False]
    assert rl.allow(2)  # کاربر دیگر مستقل است
    t[0] += 2.0
    assert rl.allow(1)


def test_rate_limiter_memory_is_bounded():
    t = [0.0]
    rl = RateLimiter(max_keys=100, ttl=10, clock=lambda: t[0])
    for i in range(5000):
        rl.allow(i)
    assert len(rl) <= 100


def test_bot_throttles_flood_but_not_owner(app_ctx, monkeypatch):
    monkeypatch.delenv("GHIYAB_RL_DISABLED", raising=False)
    monkeypatch.setattr(bot_module, "RATE_LIMITER", RateLimiter(capacity=3, refill_per_sec=0.01))
    answered = []

    async def flood(uid, n):
        for _ in range(n):
            q = Q("svc:v:1", uid)
            orig = q.answer

            async def ans(text=None, _o=orig, **kw):
                answered.append(text)
                await _o(text, **kw)
            q.answer = ans
            await bot_module.handle_callbacks(_FakeUpdate(q), Ctx(app_ctx))

    asyncio.run(flood(31337, 10))
    assert answered.count("⏳") >= 6  # بیشتر درخواست‌ها محدود شدند
    answered.clear()
    asyncio.run(flood(OWNER_ID, 10))
    assert "⏳" not in answered  # Owner معاف


# ---- secrets / logging ----
def test_redaction_masks_bot_token_and_bearer():
    s = "POST https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/getUpdates Bearer abcdef123456789 token=xyz"
    out = redact(s)
    assert "AAHdqTcv" not in out and "abcdef123456789" not in out and "xyz" not in out


def test_log_filter_applies_to_records(caplog):
    f = RedactingFilter()
    rec = logging.LogRecord("x", logging.INFO, "", 0, "url %s", ("https://x/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/y",), None)
    f.filter(rec)
    assert "AAHdqTcv" not in rec.getMessage()


def test_env_file_loader_does_not_override_and_parses(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# c\nA_KEY=1\nB_KEY="two words"\nEXISTING=new\nBADLINE\n')
    monkeypatch.setenv("EXISTING", "keep")
    monkeypatch.delenv("A_KEY", raising=False)
    monkeypatch.delenv("B_KEY", raising=False)
    assert load_env_file(str(f)) == 2
    assert os.environ["A_KEY"] == "1" and os.environ["B_KEY"] == "two words" and os.environ["EXISTING"] == "keep"
    monkeypatch.delenv("A_KEY"); monkeypatch.delenv("B_KEY")


def test_no_secrets_or_tokens_in_source_tree():
    import re
    root = os.path.dirname(os.path.dirname(__file__))
    pat = re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in (".git", "__pycache__", ".pytest_cache", "backups", "node_modules")]
        for f in fn:
            if f.endswith((".py", ".md", ".example", ".txt")):
                text = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()
                assert not pat.search(text), f"possible bot token in {f}"


# ---- coupon rules (server-side) ----
def _prod(uow_factory, price=10000):
    with uow_factory() as uow:
        a = uow.products.create("A", price, "TOMAN").id
        b = uow.products.create("B", price, "TOMAN").id
        from core.inventory import service as inv
        inv.add_items(uow, a, "unlimited", ["x1", "x2"], actor_id=OWNER_ID)
        inv.add_items(uow, b, "unlimited", ["y1", "y2"], actor_id=OWNER_ID)
        wallet_service.adjust_balance(uow, 9, 100000, "seed")
    return a, b


def test_coupon_min_order_and_product_restriction(uow_factory):
    a, b = _prod(uow_factory)
    with uow_factory() as uow:
        coupons_service.create(uow, OWNER_ID, "ONLYA", "PERCENT", 20, product_ids=[a])
        coupons_service.create(uow, OWNER_ID, "BIG", "FIXED", 1000, min_order_minor=50000)
    with uow_factory() as uow:
        o = orders_service.purchase_with_wallet(uow, 9, a, "ONLYA")
        assert o.price_minor == 8000
    with pytest.raises(CouponError) as ei:
        with uow_factory() as uow:
            orders_service.purchase_with_wallet(uow, 9, b, "ONLYA")
    with pytest.raises(CouponError):
        with uow_factory() as uow:
            orders_service.purchase_with_wallet(uow, 9, a, "BIG")  # زیر حداقل سفارش
    with uow_factory() as uow:
        assert wallet_service.get_balance(uow, 9) == 92000  # شکست‌ها چیزی کسر نکردند
