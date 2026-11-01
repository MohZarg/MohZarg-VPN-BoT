"""تست‌های رگرسیون برای توابع ورودی‌سازی پورت‌شده (بدون تغییر رفتاری)."""

from adapters.telegram_bot.util import (
    to_en_digits, parse_positive_int, parse_signed_int, normalize_ir_phone,
)


def test_to_en_digits_converts_persian_and_arabic():
    assert to_en_digits("۱۲۳") == "123"
    assert to_en_digits("١٢٣") == "123"
    assert to_en_digits("abc۵") == "abc5"


def test_parse_positive_int():
    assert parse_positive_int("۵۰۰۰") == 5000
    assert parse_positive_int("-5") is None
    assert parse_positive_int("0") is None
    assert parse_positive_int("abc") is None


def test_parse_signed_int_accepts_negative_for_manual_deduction():
    """طبق Phase 3: تنظیم دستی موجودی توسط ادمین باید مقدار منفی (کسر) هم بپذیرد."""
    assert parse_signed_int("5000") == 5000
    assert parse_signed_int("-5000") == -5000
    assert parse_signed_int("۵۰۰۰-".replace("-", "")) == 5000  # فقط برای اطمینان از to_en_digits
    assert parse_signed_int("-۵۰۰۰") == -5000
    assert parse_signed_int("0") is None
    assert parse_signed_int("-0") is None
    assert parse_signed_int("abc") is None
    assert parse_signed_int("") is None


def test_normalize_ir_phone_accepts_valid_formats():
    assert normalize_ir_phone("09123456789") == "989123456789"
    assert normalize_ir_phone("+989123456789") == "989123456789"
    assert normalize_ir_phone("00989123456789") == "989123456789"
    assert normalize_ir_phone("۰۹۱۲۳۴۵۶۷۸۹") == "989123456789"


def test_normalize_ir_phone_rejects_invalid():
    assert normalize_ir_phone("123") is None
    assert normalize_ir_phone("+14155551234") is None
    assert normalize_ir_phone("") is None
    assert normalize_ir_phone(None) is None
