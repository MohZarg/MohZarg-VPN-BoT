"""Provisioning + service lifecycle + renewal + auto-renew against the fake 3x-ui (real HTTP)."""
import concurrent.futures as cf

import pytest

from core.auth import rbac
from core.errors import (
    InsufficientBalanceError, ProviderNotReadyError, ProvisioningFailedError, ValidationError,
    NotFoundError, NotAuthorizedError, ConflictError,
)
from core.orders import service as orders_service
from core.provisioning import service as prov
from core.settings import service as settings_service
from core.vpn_services import service as svc
from core.wallet import service as wallet_service
from providers.vpn.xui.provider import ThreeXUIProvider, XuiConfig
from tests.fake_xui import FakeXui

OWNER = 999999
GB = 1024 ** 3
USER = 111


@pytest.fixture
def xui():
    s = FakeXui(token="t").start()
    p = ThreeXUIProvider(XuiConfig(base_url=s.url, api_token="t", timeout=2, max_retries=1), sleep=lambda x: None)
    prov.set_provider_factory("3x-ui", lambda: p)
    yield s
    prov.set_provider_factory("3x-ui", None)
    s.stop()


@pytest.fixture
def unconfigured():
    p = ThreeXUIProvider(XuiConfig())
    prov.set_provider_factory("3x-ui", lambda: p)
    yield p
    prov.set_provider_factory("3x-ui", None)


def seed(uow_factory, price=10000, balance=100000, days=30, gb=10):
    with uow_factory() as uow:
        pid = uow.products.create("VPN 30d", price, "TOMAN").id
        prov.set_profile(uow, OWNER, pid, "3x-ui", 1, days, gb)
        if balance:
            wallet_service.adjust_balance(uow, USER, balance, "seed")
    return pid


def buy(uow_factory, pid):
    with uow_factory() as uow:
        order = orders_service.purchase_with_wallet(uow, USER, pid)
    return order


def bal(uow_factory):
    with uow_factory() as uow:
        return wallet_service.get_balance(uow, USER)


# ---------- provisioning ----------
def test_purchase_then_provision_creates_real_client(uow_factory, xui):
    pid = seed(uow_factory)
    order = buy(uow_factory, pid)
    assert order.status == "PROVISIONING" and order.inventory_item_id == 0
    res = prov.provision_order(uow_factory, order.id)
    assert res["email"] == f"gy{order.id}"
    c = xui.clients[f"gy{order.id}"]
    assert c["totalGB"] == 10 * GB and c["tgId"] == USER and c["subId"]
    with uow_factory() as uow:
        assert uow.orders.get_by_id(order.id).status == "COMPLETED"
        assert uow.provisioning.get_client_by_order(order.id).status == "ACTIVE"
    assert bal(uow_factory) == 90000
    assert prov.provision_order(uow_factory, order.id) is None  # idempotent


def test_not_configured_blocks_purchase_without_charging(uow_factory, unconfigured):
    pid = seed(uow_factory)
    with pytest.raises(ProviderNotReadyError):
        with uow_factory() as uow:
            orders_service.purchase_with_wallet(uow, USER, pid)
    assert bal(uow_factory) == 100000  # no money taken, nothing faked
    with uow_factory() as uow:
        assert uow.orders.list_by_user(USER) == []


def test_provider_down_keeps_order_provisioning_then_retry_succeeds(uow_factory, xui):
    pid = seed(uow_factory)
    order = buy(uow_factory, pid)
    xui.down = True
    with pytest.raises(ProvisioningFailedError):
        prov.provision_order(uow_factory, order.id)
    with uow_factory() as uow:
        assert uow.orders.get_by_id(order.id).status == "PROVISIONING"  # never silently success
        rec = uow.provisioning.get_client_by_order(order.id)
        assert rec.status == "FAILED" and rec.attempts == 1
    xui.down = False
    out = prov.retry_pending(uow_factory)
    assert out["ok"] == 1
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).status == "ACTIVE"


def test_retry_adopts_client_created_before_crash(uow_factory, xui):
    pid = seed(uow_factory)
    order = buy(uow_factory, pid)
    with uow_factory() as uow:
        plan = prov.begin(uow, order.id)
    prov.execute(plan)  # panel has it, our DB never finished (crash)
    assert len(xui.clients) == 1
    prov.provision_order(uow_factory, order.id)
    assert len(xui.clients) == 1  # adopted, no duplicate
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).status == "ACTIVE"


def test_retry_pending_skips_unconfigured_without_burning_attempts(uow_factory, xui):
    pid = seed(uow_factory)
    order = buy(uow_factory, pid)
    xui.down = True
    with pytest.raises(ProvisioningFailedError):
        prov.provision_order(uow_factory, order.id)
    p = ThreeXUIProvider(XuiConfig())
    prov.set_provider_factory("3x-ui", lambda: p)
    assert prov.retry_pending(uow_factory)["skipped_not_configured"] == 1
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).attempts == 1


def test_direct_purchase_approval_blocked_when_unconfigured_keeps_request_pending(uow_factory, unconfigured):
    pid = seed(uow_factory)
    with uow_factory() as uow:
        req = orders_service.create_pending_request(uow, "buy", USER, product_id=pid)
    with pytest.raises(ProviderNotReadyError):
        with uow_factory() as uow:
            orders_service.approve_direct_purchase(uow, req, OWNER)
    with uow_factory() as uow:
        assert uow.pending_requests.get(req).status == "pending"


# ---------- status / traffic / links ----------
def activate(uow_factory, xui, **kw):
    pid = seed(uow_factory, **kw)
    order = buy(uow_factory, pid)
    prov.provision_order(uow_factory, order.id)
    return order


def test_view_live_traffic_and_cache_fallback(uow_factory, xui):
    order = activate(uow_factory, xui)
    xui.use(f"gy{order.id}", up=GB, down=GB)
    v = svc.get_service_view(uow_factory, USER, order.id)
    assert v.live and v.state == "ACTIVE" and v.used_bytes == 2 * GB and v.remaining_bytes == 8 * GB
    xui.down = True
    v2 = svc.get_service_view(uow_factory, USER, order.id)
    assert v2.live is False and v2.used_bytes == 2 * GB and v2.error  # cached, honestly labelled


def test_view_derives_suspended_when_traffic_exhausted_and_expired(uow_factory, xui):
    order = activate(uow_factory, xui)
    xui.use(f"gy{order.id}", down=10 * GB)
    assert svc.get_service_view(uow_factory, USER, order.id).state == "SUSPENDED"
    xui.traffic[f"gy{order.id}"].update(down=0, expiryTime=1)
    assert svc.get_service_view(uow_factory, USER, order.id).state == "EXPIRED"


def test_other_users_cannot_see_service(uow_factory, xui):
    order = activate(uow_factory, xui)
    with pytest.raises(NotFoundError):
        svc.get_service_view(uow_factory, 222, order.id)
    with pytest.raises(NotFoundError):
        svc.get_connection_info(uow_factory, 222, order.id)


def test_connection_links(uow_factory, xui):
    order = activate(uow_factory, xui)
    info = svc.get_connection_info(uow_factory, USER, order.id)
    assert info["links"][0].startswith("vless://") and info["subscription_url"] is None
    xui.down = True
    with pytest.raises(ProvisioningFailedError):
        svc.get_connection_info(uow_factory, USER, order.id)


# ---------- renewal ----------
def test_renew_success_charges_once_and_extends(uow_factory, xui):
    order = activate(uow_factory, xui)
    email = f"gy{order.id}"
    xui.use(email, down=5 * GB)
    old = xui.clients[email]["expiryTime"]
    r = svc.renew_service(uow_factory, USER, order.id, idempotency_key="k1")
    assert r.status == "COMPLETED"
    assert xui.clients[email]["expiryTime"] == r.new_expiry_ms and r.new_expiry_ms > old
    assert xui.traffic[email]["down"] == 0  # traffic reset
    assert bal(uow_factory) == 80000
    r2 = svc.renew_service(uow_factory, USER, order.id, idempotency_key="k1")  # replay
    assert r2.status == "COMPLETED" and r2.renewal_id == r.renewal_id and bal(uow_factory) == 80000


def test_renew_insufficient_balance_changes_nothing(uow_factory, xui):
    order = activate(uow_factory, xui, balance=10000)
    before = dict(xui.clients[f"gy{order.id}"])
    with pytest.raises(InsufficientBalanceError):
        svc.renew_service(uow_factory, USER, order.id, idempotency_key="k")
    assert xui.clients[f"gy{order.id}"] == before and bal(uow_factory) == 0


def test_renew_provider_rejects_refunds_and_not_marked_renewed(uow_factory, xui):
    order = activate(uow_factory, xui)
    exp_before = xui.clients[f"gy{order.id}"]["expiryTime"]
    xui.reject_writes = True
    r = svc.renew_service(uow_factory, USER, order.id, idempotency_key="k")
    assert r.status == "REFUNDED" and bal(uow_factory) == 90000
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).expires_at_ms != r.new_expiry_ms
    assert xui.clients[f"gy{order.id}"]["expiryTime"] == exp_before
    r2 = svc.renew_service(uow_factory, USER, order.id, idempotency_key="k")
    assert r2.status == "REFUNDED" and bal(uow_factory) == 90000  # no double refund


def test_renew_ambiguous_failure_stays_charged_then_recovers_after_restart(uow_factory, xui):
    order = activate(uow_factory, xui)
    xui.down = True
    r = svc.renew_service(uow_factory, USER, order.id, idempotency_key="k")
    assert r.status == "PENDING" and bal(uow_factory) == 80000  # not refunded (panel may have applied it)
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).expires_at_ms != r.new_expiry_ms
    xui.down = False
    out = svc.recover_stuck_renewals(uow_factory, older_than_minutes=0)
    assert out["completed"] == 1
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).expires_at_ms == r.new_expiry_ms
    assert bal(uow_factory) == 80000


def test_concurrent_renew_same_key_charges_once(uow_factory, xui):
    order = activate(uow_factory, xui)
    def go(_):
        try:
            return svc.renew_service(uow_factory, USER, order.id, idempotency_key="same").status
        except Exception as e:
            return type(e).__name__
    with cf.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(go, range(6)))
    assert bal(uow_factory) == 80000, res
    assert "COMPLETED" in res


def test_concurrent_renew_distinct_keys_never_overdraws(uow_factory, xui):
    order = activate(uow_factory, xui, balance=25000)  # 15000 left → only one renewal affordable
    def go(i):
        try:
            return svc.renew_service(uow_factory, USER, order.id, idempotency_key=f"k{i}").status
        except InsufficientBalanceError:
            return "INSUFFICIENT"
    with cf.ThreadPoolExecutor(5) as ex:
        res = list(ex.map(go, range(5)))
    assert res.count("COMPLETED") == 1 and bal(uow_factory) == 5000


# ---------- auto renew ----------
def test_auto_renew_requires_flag_and_is_opt_in(uow_factory, xui):
    order = activate(uow_factory, xui)
    with uow_factory() as uow:
        with pytest.raises(ValidationError):
            svc.set_auto_renew(uow, USER, order.id, True)  # feature off by default
        settings_service.toggle_bool(uow, OWNER, "auto_renewal_enabled")
    # not opted in → scan does nothing
    assert svc.run_auto_renewals(uow_factory, at_ms=2 ** 62) == []
    with uow_factory() as uow:
        svc.set_auto_renew(uow, USER, order.id, True)
        assert uow.provisioning.get_client_by_order(order.id).auto_renew_consent_at
    ev = svc.run_auto_renewals(uow_factory)  # within 24h window? no → not due yet
    assert ev == []
    with uow_factory() as uow:
        exp = uow.provisioning.get_client_by_order(order.id).expires_at_ms
    ev = svc.run_auto_renewals(uow_factory, at_ms=exp - 3600_000)
    assert ev[0]["outcome"] == "renewed" and bal(uow_factory) == 80000
    # second scan for the new period must not charge again
    assert svc.run_auto_renewals(uow_factory, at_ms=exp - 3600_000) == []


def test_auto_renew_insufficient_balance_and_provider_failure(uow_factory, xui):
    order = activate(uow_factory, xui, balance=10000)
    with uow_factory() as uow:
        settings_service.toggle_bool(uow, OWNER, "auto_renewal_enabled")
        svc.set_auto_renew(uow, USER, order.id, True)
        exp = uow.provisioning.get_client_by_order(order.id).expires_at_ms
    ev = svc.run_auto_renewals(uow_factory, at_ms=exp - 1000)
    assert ev[0]["outcome"] == "insufficient_balance"
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, USER, 20000, "topup")
    xui.reject_writes = True
    ev = svc.run_auto_renewals(uow_factory, at_ms=exp - 1000)
    assert ev[0]["outcome"] == "failed_refunded" and bal(uow_factory) == 20000
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).expires_at_ms == exp  # NOT renewed


def test_reminders_once_and_mark_expired(uow_factory, xui):
    order = activate(uow_factory, xui)
    with uow_factory() as uow:
        exp = uow.provisioning.get_client_by_order(order.id).expires_at_ms
    assert svc.expiry_reminders(uow_factory) == []
    ev = svc.expiry_reminders(uow_factory, at_ms=exp - 3600_000)
    assert len(ev) == 1 and ev[0]["user_id"] == USER
    assert svc.expiry_reminders(uow_factory, at_ms=exp - 3600_000) == []  # not repeated
    assert svc.mark_expired(uow_factory, at_ms=exp + 1) == 1
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).status == "EXPIRED"
    r = svc.renew_service(uow_factory, USER, order.id, idempotency_key="after-expiry")
    assert r.status == "COMPLETED"
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).status == "ACTIVE"


# ---------- admin ops / RBAC / audit ----------
def test_admin_ops_permissions_and_audit(uow_factory, xui):
    order = activate(uow_factory, xui)
    email = f"gy{order.id}"
    with pytest.raises(NotAuthorizedError):
        svc.admin_set_enabled(uow_factory, 555, order.id, False)
    with uow_factory() as uow:
        rbac.apply_role_preset(uow, 555, "SUPPORT", actor_id=OWNER)
    with pytest.raises(NotAuthorizedError):  # SUPPORT can view but not manage
        svc.admin_set_enabled(uow_factory, 555, order.id, False)
    with uow_factory() as uow:
        assert len(svc.admin_list(uow, 555)) == 1
        rbac.apply_role_preset(uow, 556, "ADMIN", actor_id=OWNER)
    svc.admin_set_enabled(uow_factory, 556, order.id, False)
    assert xui.clients[email]["enable"] is False
    xui.use(email, down=GB)
    svc.admin_reset_traffic(uow_factory, 556, order.id)
    assert xui.traffic[email]["down"] == 0
    svc.admin_set_enabled(uow_factory, 556, order.id, True)
    with uow_factory() as uow:
        actions = {l.action for l in uow.audit.list_recent(limit=50)}
    assert {"service.suspend", "service.enable", "service.reset_traffic", "rbac.apply_preset"} <= actions


def test_admin_cancel_with_refund_requires_provider_success(uow_factory, xui):
    order = activate(uow_factory, xui)
    xui.down = True
    with pytest.raises(ProvisioningFailedError):
        svc.admin_cancel(uow_factory, OWNER, order.id, refund=True)
    assert bal(uow_factory) == 90000  # no refund while service still alive on panel
    xui.down = False
    svc.admin_cancel(uow_factory, OWNER, order.id, refund=True)
    assert f"gy{order.id}" not in xui.clients and bal(uow_factory) == 100000
    with uow_factory() as uow:
        assert uow.provisioning.get_client_by_order(order.id).status == "CANCELLED"


def test_plain_refund_blocked_for_active_provider_service(uow_factory, xui):
    order = activate(uow_factory, xui)
    with pytest.raises(ConflictError):
        with uow_factory() as uow:
            orders_service.refund_order(uow, OWNER, order.id)


def test_role_presets_never_grant_owner_only():
    from security.permissions_catalog import ROLE_PRESETS, OWNER_ONLY
    for name, perms in ROLE_PRESETS.items():
        assert not (set(perms) & OWNER_ONLY), name
    assert "services.manage" not in ROLE_PRESETS["SUPPORT"]
