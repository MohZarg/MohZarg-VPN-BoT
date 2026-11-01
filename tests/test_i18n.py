"""تست پایهٔ لایهٔ i18n (Phase 8، شروع تدریجی) — بدون تغییر رفتار V1/پنل."""

from shared.i18n import t, register_catalog, DEFAULT_LANG


def test_default_language_is_persian():
    assert DEFAULT_LANG == "fa"
    assert t("common.back") == "🔙 بازگشت"


def test_unknown_key_falls_back_to_key_itself_without_crashing():
    assert t("this.key.does.not.exist") == "this.key.does.not.exist"


def test_unregistered_language_falls_back_to_persian_catalog():
    assert t("module.dashboard", lang="zz") == t("module.dashboard", lang="fa")


def test_register_catalog_is_opt_in_and_does_not_affect_default_lookup():
    register_catalog("xx_test", {"common.back": "Back"})  # زبان آزمایشی؛ کاتالوگ واقعی en دست نمی‌خورد
    assert t("common.back", lang="xx_test") == "Back"
    assert t("common.back") == "🔙 بازگشت"  # پیش‌فرض فارسی دست‌نخورده می‌ماند


def test_format_kwargs_never_raises_on_missing_placeholder():
    register_catalog("test_lang", {"greet": "Hello {name}"})
    assert t("greet", lang="test_lang") == "Hello {name}"  # کلید placeholder غایب → بدون Exception
    assert t("greet", lang="test_lang", name="Ali") == "Hello Ali"
