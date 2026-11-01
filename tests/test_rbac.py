from core.auth import rbac


def test_owner_is_admin_and_owner(uow_factory):
    with uow_factory() as uow:
        assert rbac.is_owner(uow, 999999) is True  # همان OWNER_ID فیکسچر
        assert rbac.is_admin(uow, 999999) is True


def test_random_user_is_not_admin_by_default(uow_factory):
    with uow_factory() as uow:
        assert rbac.is_admin(uow, 12345) is False
        assert rbac.is_owner(uow, 12345) is False


def test_grant_and_revoke_admin(uow_factory):
    with uow_factory() as uow:
        rbac.grant_admin(uow, 555, actor_id=999999)
    with uow_factory() as uow:
        assert rbac.is_admin(uow, 555) is True
        assert rbac.is_owner(uow, 555) is False  # ادمین معمولی هرگز Owner نمی‌شود

    with uow_factory() as uow:
        rbac.revoke_admin(uow, 555, actor_id=999999)
    with uow_factory() as uow:
        assert rbac.is_admin(uow, 555) is False


def test_grant_admin_is_audited(uow_factory):
    with uow_factory() as uow:
        rbac.grant_admin(uow, 777, actor_id=999999)
    with uow_factory() as uow:
        logs = uow.audit.list_recent(limit=10)
    actions = [log.action for log in logs]
    assert "rbac.grant_admin" in actions
