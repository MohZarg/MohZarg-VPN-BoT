"""
GhYiAb V2 — Secret Loader
=========================

قانون سخت: هیچ Secret در کد هاردکد نمی‌شود. همه‌چیز از Environment Variables
خوانده می‌شود. این ماژول یک لایهٔ نازک روی os.environ است تا:
  1) یک نقطهٔ واحد برای خواندن Secretها داشته باشیم (نه پخش‌شده در کل کدبیس).
  2) بتوانیم بعداً (بدون تغییر کد بالادستی) این Adapter را با یک Vault/Secret
     Manager واقعی جایگزین کنیم — دقیقاً طبق اصل «Secret Management پشت یک
     Interface یکسان» در سند معماری.
  3) اگر یک Secret الزامی غیرقابل‌دسترس بود، خطای صریح بدهیم، نه مقدار خالی
     که بی‌صدا باعث رفتار نادرست شود.
"""

from __future__ import annotations

import os
from typing import Optional


class MissingSecretError(RuntimeError):
    """یک Secret الزامی در Environment تنظیم نشده است."""


class SecretProvider:
    """
    Interface نازک روی منبع Secretها. پیاده‌سازی فعلی: Environment Variables.
    اگر بعداً به Vault/AWS Secrets Manager/... مهاجرت شود، فقط این کلاس
    عوض می‌شود؛ صدازننده‌ها (core/*) هیچ تغییری نمی‌خواهند.
    """

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = os.getenv(key)
        if value is None or value == "":
            return default
        return value

    def require(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise MissingSecretError(
                f"Secret الزامی '{key}' در Environment تنظیم نشده است. "
                f"طبق اصل No plaintext secrets، این مقدار هرگز در کد هاردکد نمی‌شود؛ "
                f"باید در .env یا محیط اجرا تنظیم شود."
            )
        return value

    def get_int(self, key: str, default: int) -> int:
        raw = self.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return raw.strip().lower() not in ("0", "false", "no", "")


# نمونهٔ Singleton سبک — صدازننده‌ها همین را import می‌کنند
secrets = SecretProvider()


class BotSecrets:
    """
    گروه‌بندی Secretهای خاص ربات تلگرام — فقط خواندن، بدون هیچ مقدار پیش‌فرض
    واقعی (Placeholder امن نیست چون ممکن است به اشتباه استفاده شود).
    """

    def __init__(self, provider: SecretProvider = secrets):
        self._p = provider

    @property
    def bot_token(self) -> str:
        return self._p.require("TELEGRAM_BOT_TOKEN")

    @property
    def owner_id(self) -> int:
        return int(self._p.require("TELEGRAM_OWNER_ID"))

    @property
    def channel_id(self) -> str:
        return self._p.require("TELEGRAM_CHANNEL_ID")

    @property
    def db_path(self) -> str:
        return self._p.get("GHIYAB_DB_PATH", "ghyiab_v2.db")
