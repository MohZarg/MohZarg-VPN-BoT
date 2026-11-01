"""
تست‌های Phase 5 (Payments v2 — بخش ساختاری): Idempotency روی PendingRequest.

سناریوی واقعی که این را لازم کرد: اگر همان Update تلگرام (مثلاً به‌خاطر
Retry شبکه یا دوبار تپ کاربر روی ارسال عکس) دوبار پردازش شود، نباید دو
درخواست شارژ/خرید جداگانه ساخته شود — چون تأیید هرکدام توسط ادمین یعنی
شارژ کیف پول یا صدور اکانت دوباره.
"""

from core.orders import service as orders_service

OWNER_ID = 999999


def test_duplicate_idempotency_key_returns_same_request_not_a_new_one(uow_factory):
    with uow_factory() as uow:
        first_id = orders_service.create_pending_request(
            uow, "charge", 111, amount_minor=50000, currency="TOMAN",
            idempotency_key="charge:111:4242",
        )

    with uow_factory() as uow:
        second_id = orders_service.create_pending_request(
            uow, "charge", 111, amount_minor=50000, currency="TOMAN",
            idempotency_key="charge:111:4242",
        )
        # هیچ رکورد دومی ساخته نشده؛ همان id قبلی برگردانده شده
        assert second_id == first_id
        assert uow.pending_requests.count_pending() == 1


def test_different_idempotency_keys_create_separate_requests(uow_factory):
    with uow_factory() as uow:
        id_a = orders_service.create_pending_request(
            uow, "charge", 111, amount_minor=50000, currency="TOMAN",
            idempotency_key="charge:111:1",
        )
        id_b = orders_service.create_pending_request(
            uow, "charge", 111, amount_minor=50000, currency="TOMAN",
            idempotency_key="charge:111:2",
        )
        assert id_a != id_b
        assert uow.pending_requests.count_pending() == 2


def test_no_idempotency_key_behaves_exactly_like_before(uow_factory):
    """رفتار قبلی (بدون کلید) نباید تغییر کند — سازگاری با فراخوان‌های موجود."""
    with uow_factory() as uow:
        id_a = orders_service.create_pending_request(uow, "agency", 222)
        id_b = orders_service.create_pending_request(uow, "agency", 222)
        assert id_a != id_b  # بدون کلید، هر فراخوانی یک رکورد جدید است (رفتار قبلی)


def test_approving_a_deduplicated_request_only_credits_wallet_once(uow_factory):
    """مهم‌ترین اثبات: حتی اگر Adapter به اشتباه دوبار create صدا بزند، تأیید
    فقط یک بار می‌تواند رخ دهد چون فقط یک ردیف pending واقعاً وجود دارد."""
    from core.errors import RequestAlreadyResolvedError
    from core.wallet import service as wallet_service

    idem_key = "charge:333:99"
    with uow_factory() as uow:
        req_id_1 = orders_service.create_pending_request(
            uow, "charge", 333, amount_minor=20000, currency="TOMAN",
            idempotency_key=idem_key,
        )
        req_id_2 = orders_service.create_pending_request(
            uow, "charge", 333, amount_minor=20000, currency="TOMAN",
            idempotency_key=idem_key,
        )
    assert req_id_1 == req_id_2

    with uow_factory() as uow:
        orders_service.approve_charge_request(uow, req_id_1, actor_id=OWNER_ID)

    with uow_factory() as uow:
        assert wallet_service.get_balance(uow, 333, "TOMAN") == 20000
        try:
            orders_service.approve_charge_request(uow, req_id_2, actor_id=OWNER_ID)
            assert False, "expected RequestAlreadyResolvedError"
        except RequestAlreadyResolvedError:
            pass

    with uow_factory() as uow:
        # هنوز فقط یک‌بار شارژ شده، نه دوبار
        assert wallet_service.get_balance(uow, 333, "TOMAN") == 20000
