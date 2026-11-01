"""
توابع کمکی ورودی‌سازی — عیناً پورت‌شده از V1 (این‌ها در Audit به‌عنوان KEEP
مشخص شدند: نرمال‌سازی شمارهٔ ایران و تبدیل ارقام فارسی/عربی). هیچ رفتاری
تغییر نکرده، فقط جایگاهش به یک ماژول مستقل قابل‌تست منتقل شده.
"""

from __future__ import annotations

import html as _html

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {}
for _i, _c in enumerate(PERSIAN_DIGITS):
    _DIGIT_MAP[_c] = str(_i)
for _i, _c in enumerate(ARABIC_DIGITS):
    _DIGIT_MAP[_c] = str(_i)


def to_en_digits(s: str) -> str:
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in s.strip())


def parse_positive_int(s: str):
    s = to_en_digits(s)
    if not s.isdigit():
        return None
    v = int(s)
    return v if v > 0 else None


def parse_signed_int(s: str):
    """مثل parse_positive_int اما علامت منفی را هم می‌پذیرد (برای تنظیم دستی
    موجودی توسط ادمین — مثبت=افزایش، منفی=کسر)."""
    s = to_en_digits(s).strip()
    neg = s.startswith("-")
    body = s[1:] if neg else s
    if not body.isdigit():
        return None
    v = int(body)
    if v == 0:
        return None
    return -v if neg else v


def parse_user_id(s: str):
    s = to_en_digits(s).strip()
    if not s.isdigit():
        return None
    return int(s)


def esc(value) -> str:
    """Escape a dynamic value for a Telegram `parse_mode="HTML"` message.

    Telegram requires `&`, `<` and `>` to be escaped; links and admin-supplied
    names routinely contain `&` (query strings), so interpolating them raw can
    break the whole message or inject markup.
    """
    return _html.escape(str(value if value is not None else ""), quote=False)


def normalize_ir_phone(raw: str):
    if not raw:
        return None
    digits = to_en_digits(raw).strip().replace(" ", "").replace("-", "")
    digits = digits.lstrip("+")
    if digits.startswith("0098"):
        digits = "98" + digits[4:]
    elif digits.startswith("098"):
        digits = "98" + digits[3:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = "98" + digits[1:]
    if not digits.startswith("98"):
        return None
    if not digits.isdigit():
        return None
    if len(digits) != 12:
        return None
    return digits
