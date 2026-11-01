import threading

from core.inventory import service as inventory_service


def _seed_product_with_items(uow_factory, count=1):
    with uow_factory() as uow:
        product = uow.products.create("پلن تست", 10000, "TOMAN")
        inventory_service.add_items(
            uow, product.id, "unlimited", [f"config-{i}" for i in range(count)],
            actor_id=999999,
        )
        return product.id


def test_claim_one_returns_item_and_marks_claimed(uow_factory):
    product_id = _seed_product_with_items(uow_factory, count=1)
    with uow_factory() as uow:
        item = inventory_service.claim_item(uow, product_id, 111)
    assert item is not None
    assert item.claimed_by == 111

    with uow_factory() as uow:
        remaining = inventory_service.count_available(uow, product_id)
    assert remaining == 0


def test_claim_one_returns_none_when_out_of_stock(uow_factory):
    product_id = _seed_product_with_items(uow_factory, count=0)
    with uow_factory() as uow:
        item = inventory_service.claim_item(uow, product_id, 111)
    assert item is None


def test_two_users_never_get_the_same_config(db_path):
    """
    تست رگرسیون مستقیم برای باگ «دو کاربر، یک کانفیگ» که در V1 حل شده بود.
    اینجا تأیید می‌کنیم پورت جدید همان تضمین را دارد.
    """
    from repository.sqlite.unit_of_work import SqliteUnitOfWork

    with SqliteUnitOfWork(db_path) as uow:
        product = uow.products.create("پلن تک‌نسخه", 5000, "TOMAN")
        inventory_service.add_items(uow, product.id, "unlimited", ["only-config"], actor_id=999999)
        product_id = product.id

    claimed_by = []
    errors = []

    def try_claim(user_id):
        try:
            with SqliteUnitOfWork(db_path) as uow:
                item = inventory_service.claim_item(uow, product_id, user_id)
            if item is not None:
                claimed_by.append((user_id, item.content))
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=try_claim, args=(uid,)) for uid in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed_by) == 1, f"دقیقاً یک کاربر باید کانفیگ را بگیرد؛ گرفته‌شده‌ها: {claimed_by}"
