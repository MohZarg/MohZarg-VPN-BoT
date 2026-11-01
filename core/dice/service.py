"""
GhYiAb V2 — Dice (گردونه شانس) Core Service
==============================================

پورت مستقیمِ رفتاری `claim_dice_turn` قدیمی: اتمیک، کول‌داون بر اساس
last_dice_at، بدون تغییر منطق. طبق TODO #7 (NEED-INFO)، سقف بودجهٔ روزانه/کلی
هنوز تعیین نشده — اینجا حدس زده نشده و همان رفتار بدون‌سقف V1 حفظ شده است.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from repository.interface import UnitOfWork
from core.errors import DiceCooldownError, DiceDisabledError, DiceBudgetExceededError


def claim_dice_turn(uow: UnitOfWork, user_id: int, cooldown_hours: int) -> None:
    user = uow.users.get_or_create(user_id)
    now = datetime.now()

    if user.last_dice_at:
        try:
            last_dt = datetime.fromisoformat(user.last_dice_at)
        except ValueError:
            last_dt = None
        if last_dt is not None:
            elapsed = now - last_dt
            cooldown = timedelta(hours=cooldown_hours)
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                raise DiceCooldownError(int(remaining.total_seconds()))

    uow.users.set_last_dice_at(user_id, now.isoformat())


def play(uow: UnitOfWork, user_id: int, roll_value: int, *, claim_turn: bool = True):
    """
    ثبت نتیجهٔ تاسِ سرور تلگرام (roll_value را خودِ Telegram تعیین می‌کند، نه
    این تابع — دقیقاً مثل V1، هرگز اینجا تصادفی تولید نمی‌شود). جایزه فقط برای
    عدد ۶ پرداخت می‌شود؛ سقف بودجهٔ روزانه (اگر Owner تنظیم کرده باشد) رعایت
    می‌شود.

    ``claim_turn=False`` یعنی نوبت/کول‌داون قبلاً (پیش از پرتاب تاس) مصرف شده
    است؛ در این حالت فقط سقف بودجه/فعال‌بودن و ثبت نتیجه اعمال می‌شود.
    """
    from core.settings import service as settings_service
    from core.wallet.service import adjust_balance

    if not settings_service.get_bool(uow, "dice_enabled"):
        raise DiceDisabledError("گردونهٔ شانس موقتاً غیرفعال است")
    if claim_turn:
        cooldown = settings_service.get_int(uow, "dice_cooldown_hours")
        claim_dice_turn(uow, user_id, cooldown)

    if roll_value != 6:
        uow.dice.record(user_id, roll_value, 0)
        return None

    reward = settings_service.get_int(uow, "dice_reward")
    budget = settings_service.get_int(uow, "dice_daily_budget_minor")
    if budget > 0 and uow.dice.payout_today() + reward > budget:
        uow.dice.record(user_id, roll_value, 0)
        raise DiceBudgetExceededError("سقف بودجهٔ روزانهٔ جایزه تکمیل شده؛ فردا دوباره تلاش کنید")

    uow.dice.record(user_id, roll_value, reward)
    adjust_balance(uow, user_id, reward, "جایزه گردونه شانس (تاس ۶)", actor_id=0)
    return reward
