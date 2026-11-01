import pytest

from core.auth import rbac

OWNER_ID = 999999
ADMIN_ID = 555555
PLAIN_USER_ID = 111111


def test_owner_has_all_base_permissions(uow_factory):
    with uow_factory() as uow:
        uow.rbac.ensure_owner_role(OWNER_ID)

    with uow_factory() as uow:
        assert rbac.has_permission(uow, OWNER_ID, "wallet.adjust")
        assert rbac.has_permission(uow, OWNER_ID, "rbac.manage")
        assert rbac.has_permission(uow, OWNER_ID, "catalog.manage")
        assert rbac.has_permission(uow, OWNER_ID, "providers.manage")


def test_granted_admin_starts_with_zero_permissions(uow_factory):
    """
    تغییر عمدی رفتار (Granular RBAC / Admin Control Center): برخلاف V1 که هر
    ADMIN به‌صورت خودکار همان Permissionهای پایه را داشت، از این پس ADMIN با
    صفر Permission ساخته می‌شود و فقط OWNER می‌تواند صریحاً Permission بدهد
    (least privilege). این تست قبلاً نام
    ``test_granted_admin_gets_same_base_permissions`` را داشت و رفتار قدیمی
    را چک می‌کرد؛ رفتار جدید در تست بعدی (``test_owner_can_grant_specific_permissions``)
    پوشش داده شده است.
    """
    with uow_factory() as uow:
        uow.rbac.ensure_owner_role(OWNER_ID)
        rbac.grant_admin(uow, ADMIN_ID, actor_id=OWNER_ID)

    with uow_factory() as uow:
        assert rbac.is_admin(uow, ADMIN_ID)
        assert rbac.has_permission(uow, ADMIN_ID, "wallet.adjust") is False
        assert rbac.has_permission(uow, ADMIN_ID, "broadcast.send") is False
        assert list(rbac.grants_of(uow, ADMIN_ID)) == []


def test_owner_can_grant_specific_permissions(uow_factory):
    with uow_factory() as uow:
        uow.rbac.ensure_owner_role(OWNER_ID)
        rbac.grant_admin(uow, ADMIN_ID, actor_id=OWNER_ID)
        rbac.set_admin_permissions(uow, ADMIN_ID, ["wallet.adjust", "orders.view"], actor_id=OWNER_ID)

    with uow_factory() as uow:
        assert rbac.has_permission(uow, ADMIN_ID, "wallet.adjust")
        assert rbac.has_permission(uow, ADMIN_ID, "orders.view")
        assert rbac.has_permission(uow, ADMIN_ID, "broadcast.send") is False  # فقط همان دو Permission داده شد


def test_owner_only_permission_cannot_be_granted_to_admin(uow_factory):
    from core.errors import NotAuthorizedError
    with uow_factory() as uow:
        uow.rbac.ensure_owner_role(OWNER_ID)
        rbac.grant_admin(uow, ADMIN_ID, actor_id=OWNER_ID)
        with pytest.raises(NotAuthorizedError):
            rbac.set_admin_permissions(uow, ADMIN_ID, ["rbac.manage"], actor_id=OWNER_ID)


def test_non_owner_cannot_grant_admin_or_permissions(uow_factory):
    from core.errors import NotAuthorizedError
    with uow_factory() as uow:
        uow.rbac.ensure_owner_role(OWNER_ID)
        rbac.grant_admin(uow, ADMIN_ID, actor_id=OWNER_ID)
        with pytest.raises(NotAuthorizedError):
            rbac.grant_admin(uow, PLAIN_USER_ID, actor_id=ADMIN_ID)
        with pytest.raises(NotAuthorizedError):
            rbac.set_admin_permissions(uow, ADMIN_ID, ["wallet.adjust"], actor_id=ADMIN_ID)


def test_plain_user_has_no_permissions(uow_factory):
    with uow_factory() as uow:
        assert rbac.has_permission(uow, PLAIN_USER_ID, "wallet.adjust") is False
        assert rbac.list_my_permissions(uow, PLAIN_USER_ID) == []


def test_revoked_admin_loses_permissions(uow_factory):
    with uow_factory() as uow:
        uow.rbac.ensure_owner_role(OWNER_ID)
        rbac.grant_admin(uow, ADMIN_ID, actor_id=OWNER_ID)

    with uow_factory() as uow:
        rbac.revoke_admin(uow, ADMIN_ID, actor_id=OWNER_ID)

    with uow_factory() as uow:
        assert rbac.has_permission(uow, ADMIN_ID, "wallet.adjust") is False
        assert rbac.is_admin(uow, ADMIN_ID) is False


def test_unknown_permission_name_returns_false_not_error(uow_factory):
    with uow_factory() as uow:
        uow.rbac.ensure_owner_role(OWNER_ID)

    with uow_factory() as uow:
        assert rbac.has_permission(uow, OWNER_ID, "nonexistent.permission") is False
