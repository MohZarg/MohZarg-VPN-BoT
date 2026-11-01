import time
import pytest

from core.dice import service as dice_service
from core.errors import DiceCooldownError, DiceDisabledError, DiceBudgetExceededError
from core.settings import service as settings_service

OWNER_ID = 999999  # همان مقدار seed در conftest.init_schema


def test_first_claim_succeeds(uow_factory):
    with uow_factory() as uow:
        dice_service.claim_dice_turn(uow, 111, cooldown_hours=24)  # نباید خطا بدهد


def test_second_claim_within_cooldown_fails(uow_factory):
    with uow_factory() as uow:
        dice_service.claim_dice_turn(uow, 222, cooldown_hours=24)

    with pytest.raises(DiceCooldownError) as exc_info:
        with uow_factory() as uow:
            dice_service.claim_dice_turn(uow, 222, cooldown_hours=24)
    assert exc_info.value.remaining_seconds > 0


def test_claim_after_cooldown_expired_succeeds(uow_factory):
    from repository.sqlite.unit_of_work import SqliteUnitOfWork
    with uow_factory() as uow:
        uow.users.get_or_create(333)
        # شبیه‌سازی اینکه آخرین نوبت خیلی وقت پیش بوده (کول‌داون ۰ ساعت)
    with uow_factory() as uow:
        dice_service.claim_dice_turn(uow, 333, cooldown_hours=0)
    time.sleep(0.01)
    with uow_factory() as uow:
        dice_service.claim_dice_turn(uow, 333, cooldown_hours=0)  # باید دوباره موفق شود


def test_play_records_roll_and_pays_only_for_six(uow_factory):
    with uow_factory() as uow:
        assert dice_service.play(uow, 444, 3) is None
        assert uow.dice.payout_today() == 0

    with uow_factory() as uow:
        reward = dice_service.play(uow, 555, 6)
        assert reward == settings_service.get_int(uow, "dice_reward")
        assert uow.wallet.get_balance(555, "TOMAN") == reward


def test_play_respects_disabled_setting(uow_factory):
    with uow_factory() as uow:
        settings_service.set_value(uow, OWNER_ID, "dice_enabled", "0")
    with pytest.raises(DiceDisabledError):
        with uow_factory() as uow:
            dice_service.play(uow, 666, 6)


def test_daily_budget_blocks_reward_atomically(uow_factory):
    with uow_factory() as uow:
        settings_service.set_value(uow, OWNER_ID, "dice_daily_budget_minor", "100")
    with pytest.raises(DiceBudgetExceededError):
        with uow_factory() as uow:
            dice_service.play(uow, 777, 6)
    with uow_factory() as uow:
        # خطا کل تراکنش را rollback می‌کند: نه پاداشی پرداخت شده و نه نوبت مصرف شده
        assert uow.wallet.get_balance(777, "TOMAN") == 0
        assert uow.dice.stats()["rolls"] == 0


def test_claim_turn_false_does_not_reapply_cooldown(uow_factory):
    with uow_factory() as uow:
        dice_service.play(uow, 888, 6)  # نوبت مصرف می‌شود
    with uow_factory() as uow:
        # هندلر نوبت را پیش از پرتاب تاس مصرف می‌کند؛ ثبت نتیجه نباید کول‌داون بدهد
        dice_service.play(uow, 888, 2, claim_turn=False)
