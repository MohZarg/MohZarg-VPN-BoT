"""Backup باید واقعاً قابل بازیابی باشد (نه فقط فایلی با پسوند .db) و Retention درست کار کند."""
from __future__ import annotations

import os
import sqlite3
import time

from core.system import service as system_service
from core.settings import service as settings_service
from tests.test_bot_admin_permissions import app_ctx, OWNER_ID, PLAIN_USER_ID  # noqa: F401


def test_backup_is_a_consistent_restorable_copy(app_ctx, tmp_path):
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(PLAIN_USER_ID)
        uow.wallet.adjust(PLAIN_USER_ID, "TOMAN", 12_345)
    # Backup روی اتصال جدا snapshot می‌گیرد؛ فقط داده‌های commit‌شده را می‌بیند (رفتار درست در تولید)
    with app_ctx.unit_of_work() as uow:
        dest = system_service.create_backup(uow, OWNER_ID, app_ctx.db_path, str(tmp_path / "bk"))
    conn = sqlite3.connect(dest)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        bal = conn.execute(
            "SELECT amount_minor FROM wallets WHERE user_id=? AND currency='TOMAN'", (PLAIN_USER_ID,)).fetchone()[0]
    finally:
        conn.close()
    assert bal == 12_345
    assert os.path.getsize(dest) > 0


def test_backup_retention_keeps_only_newest(app_ctx, tmp_path):
    bdir = str(tmp_path / "bk")
    with app_ctx.unit_of_work() as uow:
        settings_service.set_value(uow, OWNER_ID, "backup_retention_count", "2")
    for _ in range(4):
        with app_ctx.unit_of_work() as uow:
            system_service.create_backup(uow, OWNER_ID, app_ctx.db_path, bdir)
        time.sleep(1.05)          # نام فایل بر پایهٔ ثانیه است
    assert len([f for f in os.listdir(bdir) if f.endswith(".db")]) == 2


def test_backup_requires_permission(app_ctx, tmp_path):
    import pytest
    from core.errors import NotAuthorizedError
    with app_ctx.unit_of_work() as uow:
        uow.users.get_or_create(PLAIN_USER_ID)
        with pytest.raises(NotAuthorizedError):
            system_service.create_backup(uow, PLAIN_USER_ID, app_ctx.db_path, str(tmp_path / "bk"))
