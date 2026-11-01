from core.wallet import service as wallet_service
from core.inventory import service as inventory_service


def test_wallet_adjust_writes_audit_log(uow_factory):
    with uow_factory() as uow:
        wallet_service.adjust_balance(uow, 111, 5000, "شارژ", actor_id=999999)

    with uow_factory() as uow:
        logs = uow.audit.list_recent(limit=5)

    assert any(log.action == "wallet.adjust" and log.entity_id == "111" for log in logs)


def test_inventory_claim_writes_audit_log(uow_factory):
    with uow_factory() as uow:
        product = uow.products.create("پلن", 1000, "TOMAN")
        inventory_service.add_items(uow, product.id, "unlimited", ["c1"], actor_id=999999)

    with uow_factory() as uow:
        item = inventory_service.claim_item(uow, product.id, 222)

    with uow_factory() as uow:
        logs = uow.audit.list_recent(limit=10)

    assert any(
        log.action == "inventory.claim" and log.entity_id == str(item.id) for log in logs
    )
