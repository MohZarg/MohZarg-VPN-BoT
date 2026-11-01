from core.state.service import ConversationStateService
from repository.sqlite.state_repo import SqliteStateRepository


def test_state_survives_new_repository_instance_like_restart(db_path):
    """
    این دقیقاً تست رگرسیونِ رفع P0-5 است: در V1، ری‌استارت پردازه یعنی از دست
    رفتن user_states چون dict در RAM بود. اینجا یک StateRepository جدید
    می‌سازیم (شبیه‌سازی پردازهٔ تازه) و انتظار داریم state هنوز باشد.
    """
    repo1 = SqliteStateRepository(db_path)
    svc1 = ConversationStateService(repo1)
    svc1.set(111, {"action": "waiting_for_charge_amount"})

    # شبیه‌سازی ری‌استارت: repository/service جدید روی همان فایل دیتابیس
    repo2 = SqliteStateRepository(db_path)
    svc2 = ConversationStateService(repo2)
    state = svc2.get(111)

    assert state == {"action": "waiting_for_charge_amount"}


def test_state_clear_removes_value(db_path):
    repo = SqliteStateRepository(db_path)
    svc = ConversationStateService(repo)
    svc.set(222, "waiting_for_support_msg")
    assert svc.get(222) == "waiting_for_support_msg"
    svc.clear(222)
    assert svc.get(222) is None


def test_state_supports_plain_string_like_v1(db_path):
    """V1 گاهی رشتهٔ ساده در user_states می‌گذاشت (نه فقط dict) — این رفتار حفظ شده."""
    repo = SqliteStateRepository(db_path)
    svc = ConversationStateService(repo)
    svc.set(333, "p_cap_2")
    assert svc.get(333) == "p_cap_2"
