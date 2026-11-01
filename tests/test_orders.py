import pytest

from core.orders import service as orders_service
from core.wallet import service as wallet_service
from core.inventory import service as inventory_service
from core.errors import (
    InsufficientBalanceError,
    OutOfStockError,
    AlreadyClaimedTestError,
    DailyTestLimitError,
    ConflictError,
)


def _seed_product(uow_factory, price=10000, stock=1):
    with uow_factory() as uow:
        product = uow.products.create("پلن یک‌ماهه", price, "TOMAN")
        if stock:
            inventory_service.add_items(
                uow, product.id, "unlimited", [f"cfg-{i}" for i in range(stock)],
                actor_id=999999,
            )
        return product.id


def test_purchase_with_wallet_success_deducts_and_issues_config(uow_factory):
    product_id = _seed_product(uow_factory, price=10000, stock=1)
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 111, 10000, "شارژ اولیه")

    with uow_factory() as uow:
        order = orders_service.purchase_with_wallet(uow, 111, product_id)

    assert order.price_minor == 10000
    with uow_factory() as uow:
        bal = wallet_service.get_balance(uow, 111)
    assert bal == 0


def test_purchase_with_wallet_applies_agent_discount(uow_factory):
    product_id = _seed_product(uow_factory, price=10000, stock=1)
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 222, 9000, "شارژ اولیه")
        uow.users.get_or_create(222)
        uow.users.set_agent(222, True)

    with uow_factory() as uow:
        order = orders_service.purchase_with_wallet(uow, 222, product_id)

    assert order.price_minor == 9000  # 10000 * 0.9 — دقیقاً تخفیف نماینده V1


def test_purchase_with_wallet_insufficient_balance_leaves_state_unchanged(uow_factory):
    product_id = _seed_product(uow_factory, price=10000, stock=1)
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 333, 1000, "شارژ ناکافی")

    with pytest.raises(InsufficientBalanceError):
        with uow_factory() as uow:
            orders_service.purchase_with_wallet(uow, 333, product_id)

    with uow_factory() as uow:
        bal = wallet_service.get_balance(uow, 333)
        available = inventory_service.count_available(uow, product_id)
    assert bal == 1000
    assert available == 1  # کانفیگ claim نشده


def test_purchase_with_wallet_out_of_stock_refunds_debited_amount(uow_factory):
    product_id = _seed_product(uow_factory, price=10000, stock=0)
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 444, 10000, "شارژ")

    with pytest.raises(OutOfStockError):
        with uow_factory() as uow:
            orders_service.purchase_with_wallet(uow, 444, product_id)

    with uow_factory() as uow:
        bal = wallet_service.get_balance(uow, 444)
    assert bal == 10000  # موجودی باید کامل برگردد


def test_purchase_with_wallet_twice_same_key_charges_once(uow_factory):
    """تپ دوباره روی «پرداخت از کیف پول» (همان پیام) نباید سفارش/کسر دوم بسازد."""
    product_id = _seed_product(uow_factory, price=10000, stock=2)
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 121, 20000, "شارژ")

    with uow_factory() as uow:
        first = orders_service.purchase_with_wallet(
            uow, 121, product_id, idempotency_key="buy:121:42")
    with uow_factory() as uow:
        second = orders_service.purchase_with_wallet(
            uow, 121, product_id, idempotency_key="buy:121:42")

    assert first.id == second.id
    with uow_factory() as uow:
        assert wallet_service.get_balance(uow, 121) == 10000
        assert inventory_service.count_available(uow, product_id) == 1


def test_purchase_idempotency_key_cannot_be_reused_by_another_user(uow_factory):
    product_id = _seed_product(uow_factory, price=10000, stock=2)
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 122, 10000, "شارژ")
        wallet_service.adjust_balance(uow, 123, 10000, "شارژ")

    with uow_factory() as uow:
        orders_service.purchase_with_wallet(uow, 122, product_id, idempotency_key="buy:shared:1")
    with pytest.raises(ConflictError):
        with uow_factory() as uow:
            orders_service.purchase_with_wallet(uow, 123, product_id, idempotency_key="buy:shared:1")


def test_claim_free_test_once_per_normal_user(uow_factory):
    with uow_factory() as uow:
        inventory_service.add_items(uow, 0, "test", ["free-cfg-1", "free-cfg-2"], actor_id=999999)

    with uow_factory() as uow:
        item = orders_service.claim_free_test(uow, 555, "2026-09-21")
    assert item.content == "free-cfg-1"

    with pytest.raises(AlreadyClaimedTestError):
        with uow_factory() as uow:
            orders_service.claim_free_test(uow, 555, "2026-09-21")


def test_claim_free_test_agent_daily_limit(uow_factory):
    with uow_factory() as uow:
        inventory_service.add_items(uow, 0, "test", ["free-cfg-a", "free-cfg-b"], actor_id=999999)
        uow.users.get_or_create(666)
        uow.users.set_agent(666, True)

    with uow_factory() as uow:
        orders_service.claim_free_test(uow, 666, "2026-09-21")

    with pytest.raises(DailyTestLimitError):
        with uow_factory() as uow:
            orders_service.claim_free_test(uow, 666, "2026-09-21")

    # روز بعد باید دوباره اجازه داشته باشد (رفتار نماینده در V1)
    with uow_factory() as uow:
        item = orders_service.claim_free_test(uow, 666, "2026-09-22")
    assert item.content == "free-cfg-b"


def test_pending_request_double_approve_is_rejected(uow_factory):
    with uow_factory() as uow:
        req_id = orders_service.create_pending_request(
            uow, "charge", 777, amount_minor=5000, currency="TOMAN"
        )

    with uow_factory() as uow:
        orders_service.approve_charge_request(uow, req_id, actor_id=999999)

    from core.errors import RequestAlreadyResolvedError
    with pytest.raises(RequestAlreadyResolvedError):
        with uow_factory() as uow:
            orders_service.approve_charge_request(uow, req_id, actor_id=999999)

    with uow_factory() as uow:
        bal = wallet_service.get_balance(uow, 777)
    assert bal == 5000  # فقط یک‌بار واریز شده، نه دوبار
