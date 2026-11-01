import pytest
from core.reseller import service as reseller_service
from core.orders import service as orders_service
from core.provisioning import service as prov
from core.settings import service as settings_service
from core.wallet import service as wallet_service
from core.inventory import service as inventory_service
from tests.test_vpn_lifecycle import xui, seed, buy, OWNER, bal  # noqa: F401

REF, NEW = 5001, 5002


def setup_referral(uow_factory):
    with uow_factory() as uow:
        uow.users.get_or_create(REF)
        uow.users.get_or_create(NEW)
        uow.users.set_referred_by(NEW, REF)


def ref_balance(uow_factory):
    with uow_factory() as uow:
        return wallet_service.get_balance(uow, REF)


def manual_product(uow_factory, price=1000):
    with uow_factory() as uow:
        pid = uow.products.create("manual", price, "TOMAN").id
        inventory_service.add_items(uow, pid, "unlimited", ["c1", "c2"], actor_id=OWNER)
        wallet_service.adjust_balance(uow, NEW, 5000, "seed")
    return pid


def test_no_reward_before_paid_order(uow_factory):
    setup_referral(uow_factory)
    assert ref_balance(uow_factory) == 0


def test_reward_after_first_paid_order_only_once(uow_factory):
    setup_referral(uow_factory)
    pid = manual_product(uow_factory)
    for _ in range(2):
        with uow_factory() as uow:
            orders_service.purchase_with_wallet(uow, NEW, pid)
    assert ref_balance(uow_factory) == 5000  # یک‌بار، نه دوبار


def test_self_referral_never_pays(uow_factory):
    with uow_factory() as uow:
        uow.users.get_or_create(REF)
        assert reseller_service.pay_referral_reward(uow, REF, REF) is False


def test_reward_disabled_and_phone_requirement_and_signup_mode(uow_factory):
    setup_referral(uow_factory)
    pid = manual_product(uow_factory)
    with uow_factory() as uow:
        settings_service.set_value(uow, OWNER, "referral_require_phone", "1")
    with uow_factory() as uow:
        orders_service.purchase_with_wallet(uow, NEW, pid)
    assert ref_balance(uow_factory) == 0
    with uow_factory() as uow:
        settings_service.set_value(uow, OWNER, "referral_trigger", "signup")
        settings_service.set_value(uow, OWNER, "referral_require_phone", "0")
    with uow_factory() as uow:
        orders_service.purchase_with_wallet(uow, NEW, pid)
    assert ref_balance(uow_factory) == 0  # trigger=signup → سفارش پاداش نمی‌دهد


def test_provisioned_order_rewards_only_after_successful_issue(uow_factory, xui):
    setup_referral(uow_factory)
    with uow_factory() as uow:
        pid = uow.products.create("vpn", 10000, "TOMAN").id
        prov.set_profile(uow, OWNER, pid, "3x-ui", 1, 30, 10)
        wallet_service.adjust_balance(uow, NEW, 50000, "seed")
    with uow_factory() as uow:
        order = orders_service.purchase_with_wallet(uow, NEW, pid)
    assert ref_balance(uow_factory) == 0  # پرداخت شد ولی هنوز صادر نشده
    xui.down = True
    with pytest.raises(Exception):
        prov.provision_order(uow_factory, order.id)
    assert ref_balance(uow_factory) == 0
    xui.down = False
    prov.provision_order(uow_factory, order.id)
    assert ref_balance(uow_factory) == 5000


def test_order_trigger_reward_is_notified_once_by_maintenance(uow_factory):
    from adapters.telegram_bot import maintenance
    setup_referral(uow_factory)
    pid = manual_product(uow_factory)
    with uow_factory() as uow:
        orders_service.purchase_with_wallet(uow, NEW, pid)
        assert len(uow.referrals.list_unnotified()) == 1
    with uow_factory() as uow:
        rid, ref, amt = uow.referrals.list_unnotified()[0]
        assert ref == REF and amt == 5000
        uow.referrals.mark_notified(rid)
        assert uow.referrals.list_unnotified() == []
