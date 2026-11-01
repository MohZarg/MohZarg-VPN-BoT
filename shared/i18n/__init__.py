"""
GhYiAb V2 — i18n Foundation (Phase 8, شروع تدریجی)
======================================================

طبق Roadmap (Phase 8) و تصمیم `decisions.md` («بدون متن فارسی Hardcoded در
Business Logic؛ فقط در Presentation با کلید ترجمه»)، این ماژول نخستین لایهٔ
واقعی ترجمه را فراهم می‌کند — **بدون** تغییر هیچ رفتار/متن فعلی:

  * زبان پیش‌فرض و تنها زبان فعال همچنان فارسی است (`fa`)؛ هیچ انتخاب‌گر
    زبان به کاربر نشان داده نمی‌شود تا Owner صراحتاً EN را سفارش بدهد.
  * `t(key, **kwargs)` کلید را از کاتالوگ فعال می‌خواند؛ اگر کلید در کاتالوگ
    فعال نبود، به فارسی (کاتالوگ مرجع) سقوط می‌کند؛ اگر در فارسی هم نبود،
    خودِ کلید را برمی‌گرداند (هرگز Exception کاربر را قطع نمی‌کند).
  * این لایه عمداً هنوز هیچ `adapters/telegram_bot/bot.py` (منطق V1) یا
    `adapters/telegram_bot/texts.py` را لمس نمی‌کند — ریسک رگرسیون روی مسیر
    پرترافیک V1 پذیرفته نشد. اولین مصرف‌کننده، جداول متنی ایستای
    `admin_panel.py` (خروجی همین تسک، تازه‌ساخت و کم‌ریسک) است.
"""

from __future__ import annotations

from shared.i18n.fa import CATALOG as FA_CATALOG
from shared.i18n.en import CATALOG as EN_CATALOG

DEFAULT_LANG = "fa"

_CATALOGS: dict[str, dict[str, str]] = {"fa": FA_CATALOG, "en": EN_CATALOG}
SUPPORTED_LANGS = ("fa", "en")
RTL_LANGS = ("fa",)


def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    catalog = _CATALOGS.get(lang, FA_CATALOG)
    template = catalog.get(key, FA_CATALOG.get(key, key))
    try:
        return template.format(**kwargs) if kwargs else template
    except (KeyError, IndexError):
        return template


def register_catalog(lang: str, catalog: dict[str, str]) -> None:
    """برای Phase 8 واقعی (افزودن EN): بدون تغییر این فایل، فقط یک کاتالوگ
    جدید ثبت می‌شود. تا امروز هیچ‌کس این را صدا نمی‌زند."""
    _CATALOGS[lang] = catalog
