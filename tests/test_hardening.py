"""تست‌های سخت‌سازی نهایی: Escape متن HTML و محاسبهٔ صحیح قیمت."""

from types import SimpleNamespace

from adapters.telegram_bot.util import esc
from core.pricing import service as pricing


def test_esc_escapes_telegram_html_metacharacters():
    assert esc('a & b <c>') == "a &amp; b &lt;c&gt;"
    assert esc(None) == ""
    assert esc(123) == "123"
    # نقل‌قول‌ها عمداً Escape نمی‌شوند؛ Telegram فقط & < > را لازم دارد.
    assert esc('"x"') == '"x"'


def test_agent_discount_uses_exact_integer_arithmetic():
    base = 999_999_999_999_999_999
    assert pricing.final_price_minor(base, True) == base * 90 // 100
    assert pricing.final_price_minor(base, False) == base


def test_best_of_agent_and_tier_discount_wins():
    assert pricing.price_with_tier(10_000, False, 0) == 10_000
    assert pricing.price_with_tier(10_000, True, 0) == 9_000
    assert pricing.price_with_tier(10_000, False, 25) == 7_500
    assert pricing.price_with_tier(10_000, True, 5) == 9_000  # ۱۰٪ نمایندگی بهتر از ۵٪ است
    assert pricing.price_with_tier(10_000, True, 150) == 0  # clamp


def test_percent_coupon_is_integer_and_never_negative():
    coupon = SimpleNamespace(kind="PERCENT", value=10, is_active=True)
    final, discount = pricing.apply_coupon(333, coupon)
    assert (final, discount) == (300, 33)

    coupon.value = 150
    final, discount = pricing.apply_coupon(333, coupon)
    assert final == 0 and discount == 333
