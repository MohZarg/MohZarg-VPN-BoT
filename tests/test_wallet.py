import threading

import pytest

from core.wallet import service as wallet_service
from core.errors import InsufficientBalanceError, NotFoundError, NotAuthorizedError, ValidationError

OWNER_ID = 999999  # همان مقدار seed در conftest.init_schema


def test_adjust_balance_increases_and_records_transaction(uow_factory):
    with uow_factory() as uow:
        new_bal = wallet_service.adjust_balance(uow, 111, 5000, "شارژ تست")
    assert new_bal == 5000

    with uow_factory() as uow:
        bal = wallet_service.get_balance(uow, 111)
        txs = wallet_service.list_recent_transactions(uow, 111)
    assert bal == 5000
    assert len(txs) == 1
    assert txs[0].amount_minor == 5000
    assert txs[0].reason == "شارژ تست"


def test_adjust_balance_can_go_negative_like_v1_admin_deduction(uow_factory):
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 111, 1000, "شارژ")
    with uow_factory() as uow:
        new_bal = wallet_service.adjust_balance(uow, 111, -1500, "کسر ادمین")
    assert new_bal == -500  # دقیقاً رفتار adjust_balance قدیمی؛ بررسی کفایت موجودی نداشت


def test_debit_for_purchase_fails_when_insufficient(uow_factory):
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 222, 1000, "شارژ")
    try:
        with uow_factory() as uow:
            wallet_service.debit_for_purchase(uow, 222, 5000, "خرید")
        assert False, "باید InsufficientBalanceError پرتاب می‌شد"
    except InsufficientBalanceError:
        pass

    with uow_factory() as uow:
        bal = wallet_service.get_balance(uow, 222)
    assert bal == 1000  # موجودی دست‌نخورده باقی مانده (rollback خودکار UoW)


def test_debit_for_purchase_succeeds_and_updates_balance(uow_factory):
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 333, 10000, "شارژ")
    with uow_factory() as uow:
        new_bal = wallet_service.debit_for_purchase(uow, 333, 4000, "خرید محصول")
    assert new_bal == 6000


def test_idempotency_key_prevents_double_credit(uow_factory):
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 444, 1000, "شارژ اول", idempotency_key="k-1")
    with uow_factory() as uow:
        # فراخوانی دوم با همان کلید نباید دوباره واریز کند
        wallet_service.adjust_balance(uow, 444, 1000, "شارژ اول", idempotency_key="k-1")
    with uow_factory() as uow:
        bal = wallet_service.get_balance(uow, 444)
    assert bal == 1000


def test_concurrent_debit_never_double_spends(db_path):
    """
    تست هم‌زمانی: شبیه‌سازی دو خرید هم‌زمان با موجودی فقط کافی برای یکی.
    این دقیقاً همان ریسکی است که BEGIN IMMEDIATE در V1 حل می‌کرد؛ اینجا تضمین
    می‌کنیم که در معماری جدید هم دست‌نخورده باقی مانده است.
    """
    from repository.sqlite.unit_of_work import SqliteUnitOfWork

    with SqliteUnitOfWork(db_path) as uow:
        wallet_service.adjust_balance(uow, 555, 1000, "شارژ اولیه")

    results = []
    errors = []

    def try_debit():
        try:
            with SqliteUnitOfWork(db_path) as uow:
                wallet_service.debit_for_purchase(uow, 555, 1000, "خرید همزمان")
            results.append("ok")
        except InsufficientBalanceError:
            errors.append("insufficient")
        except Exception as exc:  # قفل موقت SQLite ممکن است یکی را با خطای busy رد کند
            errors.append(f"other:{exc}")

    threads = [threading.Thread(target=try_debit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1, f"فقط یک کسر باید موفق شود، نتایج: {results + errors}"

    with SqliteUnitOfWork(db_path) as uow:
        final_balance = wallet_service.get_balance(uow, 555)
    assert final_balance == 0


def test_admin_adjust_requires_permission_and_existing_user(uow_factory):
    with uow_factory() as uow:
        uow.users.get_or_create(901)
        with pytest.raises(NotAuthorizedError):
            wallet_service.admin_adjust(uow, 901, 901, 1000, "دلیل")

    with pytest.raises(NotFoundError):
        with uow_factory() as uow:
            wallet_service.admin_adjust(uow, OWNER_ID, 999_000_111, 1000, "دلیل")


def test_admin_adjust_rejects_zero_negative_balance_and_missing_reason(uow_factory):
    with uow_factory() as uow:
        uow.users.get_or_create(902)
        with pytest.raises(ValidationError):
            wallet_service.admin_adjust(uow, OWNER_ID, 902, 0, "دلیل")
        with pytest.raises(ValidationError):
            wallet_service.admin_adjust(uow, OWNER_ID, 902, 1000, "   ")
        with pytest.raises(InsufficientBalanceError):
            wallet_service.admin_adjust(uow, OWNER_ID, 902, -1, "کسر")

    with uow_factory() as uow:
        assert wallet_service.admin_adjust(uow, OWNER_ID, 902, 5000, "شارژ دستی") == 5000
        assert wallet_service.admin_adjust(uow, OWNER_ID, 902, -2000, "اصلاح") == 3000
