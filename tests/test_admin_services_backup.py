"""Admin «سرویس‌های VPN» (RBAC + Confirm + Audit) و Backup/Restore واقعی."""
import asyncio
import os
import sqlite3

import pytest

from core.auth import rbac
from core.confirm import service as confirm_service
from core.system import service as system_service
from core.settings import service as settings_service
from core.wallet import service as wallet_service
from tests.test_bot_services_ui import (  # noqa: F401
    app_ctx, xui, make_service, fire, bal, USER, OWNER_ID, GB,
)

SUPPORT = 4001


def _texts(q):
    return " ".join(q.edited_texts + q.answers)


def test_support_can_view_but_not_act(app_ctx, xui):
    oid = make_service(app_ctx)
    with app_ctx.unit_of_work() as uow:
        rbac.apply_role_preset(uow, SUPPORT, "SUPPORT", actor_id=OWNER_ID)
    ctx, q = fire(app_ctx, "acc:svcs:home", user=SUPPORT)
    assert f"#{oid}" in str(q.markups[-1].inline_keyboard)
    ctx, q = fire(app_ctx, f"acc:svcs:d:{oid}", user=SUPPORT)
    cbs = str(q.markups[-1].inline_keyboard)
    assert "svc_suspend" not in cbs and "svc_cancel" not in cbs  # دکمهٔ عملیات اصلاً نمایش داده نمی‌شود
    ctx, q = fire(app_ctx, f"acc:svcs:act:svc_suspend:{oid}", user=SUPPORT)
    assert not q.edited_texts or "تأیید" not in q.edited_texts[-1]
    assert xui.clients[f"gy{oid}"]["enable"] is True


def test_plain_user_sees_nothing_in_admin_services(app_ctx, xui):
    oid = make_service(app_ctx)
    ctx, q = fire(app_ctx, "acc:svcs:home", user=USER)
    assert not q.markups


def test_owner_suspend_via_confirm_flow_and_audit(app_ctx, xui):
    oid = make_service(app_ctx)
    ctx, q = fire(app_ctx, f"acc:svcs:act:svc_suspend:{oid}", user=OWNER_ID)
    assert "تأیید" in str(q.markups[-1].inline_keyboard) or "confirm" in str(q.markups[-1].inline_keyboard)
    with app_ctx.unit_of_work() as uow:
        token = confirm_service.create(uow, OWNER_ID, "svc_suspend", {"order_id": oid})
    ctx, q = fire(app_ctx, f"acc:confirm:{token}", user=OWNER_ID)
    assert xui.clients[f"gy{oid}"]["enable"] is False
    with app_ctx.unit_of_work() as uow:
        assert "service.suspend" in {l.action for l in uow.audit.list_recent(limit=30)}
    # توکن تأیید یک‌بارمصرف است
    fire(app_ctx, f"acc:confirm:{token}", user=OWNER_ID)
    assert xui.clients[f"gy{oid}"]["enable"] is False


def test_admin_cancel_when_panel_down_reports_failure_not_success(app_ctx, xui):
    oid = make_service(app_ctx)
    with app_ctx.unit_of_work() as uow:
        token = confirm_service.create(uow, OWNER_ID, "svc_cancel_refund", {"order_id": oid})
    xui.down = True
    ctx, q = fire(app_ctx, f"acc:confirm:{token}", user=OWNER_ID)
    assert bal(app_ctx) == 90000 and f"gy{oid}" in xui.clients
    with app_ctx.unit_of_work() as uow:
        assert uow.provisioning.get_client_by_order(oid).status == "ACTIVE"


def test_system_health_reports_provider_modes(app_ctx, xui):
    h = system_service.health(app_ctx.unit_of_work, OWNER_ID)
    assert h["xui"]["status"] == "OK"
    xui.down = True
    assert system_service.health(app_ctx.unit_of_work, OWNER_ID)["xui"]["status"] == "BLOCKED"


# ---------------- Backup / Restore ----------------
def test_backup_verify_detects_corruption(app_ctx, tmp_path):
    with app_ctx.unit_of_work() as uow:
        dest = system_service.create_backup(uow, OWNER_ID, app_ctx.db_path, str(tmp_path / "bk"))
    assert system_service.verify_backup(dest)["ok"] is True
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database" * 100)
    assert system_service.verify_backup(str(bad))["ok"] is False
    assert system_service.verify_backup(str(tmp_path / "missing.db"))["reason"] == "missing_or_empty"
    empty_db = tmp_path / "empty.db"
    sqlite3.connect(empty_db).execute("CREATE TABLE x(a)").connection.close()
    assert system_service.verify_backup(str(empty_db))["reason"] == "missing_tables"


def test_full_restore_roundtrip_recovers_wallet_and_services(app_ctx, xui, tmp_path):
    oid = make_service(app_ctx)
    with app_ctx.unit_of_work() as uow:
        dest = system_service.create_backup(uow, OWNER_ID, app_ctx.db_path, str(tmp_path / "bk"))
    # فاجعه: تراکنش‌های بعد از Backup + خرابی
    with app_ctx.unit_of_work() as uow:
        wallet_service.adjust_balance(uow, USER, -50000, "oops")
    assert bal(app_ctx) == 40000
    aside = system_service.restore_backup(dest, app_ctx.db_path)
    assert os.path.exists(aside)
    assert bal(app_ctx) == 90000  # وضعیت لحظهٔ Backup
    with app_ctx.unit_of_work() as uow:
        rec = uow.provisioning.get_client_by_order(oid)
        assert rec is not None and rec.status == "ACTIVE"


def test_restore_refuses_invalid_backup_and_keeps_db(app_ctx, tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"garbage")
    before = os.path.getsize(app_ctx.db_path)
    with pytest.raises(ValueError):
        system_service.restore_backup(str(bad), app_ctx.db_path)
    assert os.path.getsize(app_ctx.db_path) >= before - 1  # دست‌نخورده


def test_backup_cli_create_verify_restore(app_ctx, tmp_path, monkeypatch, capsys):
    from tools import backup_cli
    monkeypatch.setenv("GHIYAB_DB_PATH", app_ctx.db_path)
    assert backup_cli.main(["create", "--dir", str(tmp_path / "b")]) == 0
    f = next((tmp_path / "b").iterdir())
    assert backup_cli.main(["verify", str(f)]) == 0
    assert backup_cli.main(["restore", str(f)]) == 0


def test_daily_backup_respects_setting(app_ctx, tmp_path):
    with app_ctx.unit_of_work() as uow:
        settings_service.toggle_bool(uow, OWNER_ID, "backup_daily_enabled")  # روشن→خاموش
    assert system_service.daily_backup_if_due(app_ctx.unit_of_work, OWNER_ID, app_ctx.db_path, str(tmp_path / "bk")) is None
