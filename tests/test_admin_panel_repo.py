"""
تست‌های Phase 3 برای متدهای Repository که پنل ادمین تلگرام (که تا این فاز
دکمه‌هایش بدون هندلر/بلااستفاده بودند) اکنون به آنها متکی است:
- شمارش درخواست‌های در انتظار (برای «آمار ربات»)
- فهرست کاربران بلاک‌نکرده (برای «ارسال پیام همگانی»)
"""

from core.orders import service as orders_service

OWNER_ID = 999999


def test_count_pending_reflects_only_pending_status(uow_factory):
    with uow_factory() as uow:
        req_id = orders_service.create_pending_request(uow, "charge", 111, amount_minor=1000, currency="TOMAN")
        orders_service.create_pending_request(uow, "charge", 222, amount_minor=2000, currency="TOMAN")

    with uow_factory() as uow:
        assert uow.pending_requests.count_pending() == 2

    with uow_factory() as uow:
        orders_service.reject_request(uow, req_id, actor_id=OWNER_ID)

    with uow_factory() as uow:
        assert uow.pending_requests.count_pending() == 1


def test_list_ids_not_blocked_excludes_blocked_users(uow_factory):
    with uow_factory() as uow:
        uow.users.get_or_create(111)
        uow.users.get_or_create(222)
        uow.users.get_or_create(333)
        uow.users.set_blocked_by_bot(222, True)

    with uow_factory() as uow:
        ids = set(uow.users.list_ids_not_blocked())
        assert 111 in ids
        assert 333 in ids
        assert 222 not in ids
