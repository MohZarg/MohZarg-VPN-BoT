"""
تست‌های افزودن دستی به مخزن (Inventory) — مسیر واقعی هندلرهای ادمین، نه فقط سرویس.
هر تست مربوط به یک باگ/قابلیتِ این تسک است.
"""
from __future__ import annotations

import asyncio

import pytest

from core.inventory import service as inventory_service
from core.orders import service as orders_service
from core.errors import ValidationError
from tests.test_admin_panel import (  # noqa: F401  (fixture app_ctx + fakes)
    app_ctx, _fire, _fire_text, _FakeContext, _FakeMessageUpdate, OWNER_ID, ADMIN_ID, PLAIN_USER_ID,
)
from adapters.telegram_bot import admin_panel


# ---------- سرویس ----------

def test_parse_config_text_handles_crlf_bom_blank_lines():
    assert inventory_service.parse_config_text("\ufeffa\r\n\r\n  b  \rc\n") == ["a", "b", "c"]
    assert inventory_service.parse_config_text("") == []


def test_default_item_type():
    assert inventory_service.default_item_type(0) == "test"
    assert inventory_service.default_item_type(5) == "unlimited"


def test_report_counts_duplicates_and_too_long(uow_factory):
    with uow_factory() as uow:
        p = uow.products.create("پلن", 1000, "TOMAN")
        inventory_service.add_items(uow, p.id, "unlimited", ["old"], actor_id=999999)
        long_line = "x" * (inventory_service.MAX_ITEM_LEN + 1)
        rep = inventory_service.add_items_report(
            uow, p.id, "unlimited", ["old", "n1", "n1", "n2", long_line], actor_id=999999)
    assert (rep.added, rep.duplicate_existing, rep.duplicate_in_input, rep.too_long) == (2, 1, 1, 1)
    assert rep.available_after == 3


def test_too_long_line_no_longer_rejects_whole_batch(uow_factory):
    with uow_factory() as uow:
        p = uow.products.create("پلن", 1000, "TOMAN")
        rep = inventory_service.add_items_report(
            uow, p.id, "unlimited", ["ok", "y" * (inventory_service.MAX_ITEM_LEN + 5)], actor_id=999999)
    assert rep.added == 1 and rep.too_long == 1


def test_batch_overflow_raises(uow_factory):
    with uow_factory() as uow:
        p = uow.products.create("پلن", 1000, "TOMAN")
        with pytest.raises(ValidationError):
            inventory_service.add_items_report(
                uow, p.id, "unlimited", [f"c{i}" for i in range(inventory_service.MAX_BATCH + 1)],
                actor_id=999999)


# ---------- مسیر واقعی ادمین ----------

def test_module_button_inventory_home_does_not_crash(app_ctx):
    """باگ: دکمهٔ «مخزن» در صفحهٔ اصلی (acc:inv:home) IndexError می‌داد."""
    _, q = asyncio.run(_fire(app_ctx, "acc:inv:home", OWNER_ID))
    assert q.edited_texts and "مخزن" in q.edited_texts[-1]


def test_test_pool_is_manageable_and_typed_test(app_ctx):
    """مخزن تست (product 0) از پنل جدید قابل پر کردن است و item_type='test' دارد و free-test از آن برمی‌دارد."""
    asyncio.run(_fire(app_ctx, "acc:inv:add:0", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    _, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "vless://t1\nvless://t2", state))
    assert "2 کانفیگ افزوده شد" in upd.message.replies[-1]
    with app_ctx.unit_of_work() as uow:
        types = {r[0] for r in uow._conn.execute(
            "SELECT item_type FROM inventory_items WHERE product_id=0").fetchall()}
        assert types == {"test"}
        item = orders_service.claim_free_test(uow, PLAIN_USER_ID, "2026-10-04")
    assert item.content.startswith("vless://t")


def test_add_report_shows_duplicates_and_stock(app_ctx):
    with app_ctx.unit_of_work() as uow:
        from core.catalog import service as catalog_service
        p = catalog_service.create_product(uow, OWNER_ID, "پلن", 10000)
    asyncio.run(_fire(app_ctx, f"acc:inv:add:{p.id}", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    _, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "a\nb\na\r\nc", state))
    msg = upd.message.replies[-1]
    assert "3 کانفیگ افزوده شد" in msg and "1 مورد تکراری" in msg and "موجودی فعلی این مخزن: 3" in msg
    assert app_ctx.state.get(OWNER_ID) is None


def test_validation_error_keeps_state_so_admin_can_resend(app_ctx):
    with app_ctx.unit_of_work() as uow:
        from core.catalog import service as catalog_service
        p = catalog_service.create_product(uow, OWNER_ID, "پلن", 10000)
    asyncio.run(_fire(app_ctx, f"acc:inv:add:{p.id}", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    big = "\n".join(f"c{i}" for i in range(inventory_service.MAX_BATCH + 1))
    _, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, big, state))
    assert "حداکثر" in upd.message.replies[-1]
    assert app_ctx.state.get(OWNER_ID) is not None  # قبلاً پاک می‌شد و ادمین باید از اول می‌رفت


def test_empty_input_keeps_state(app_ctx):
    asyncio.run(_fire(app_ctx, "acc:inv:add:0", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    _, upd = asyncio.run(_fire_text(app_ctx, OWNER_ID, "   \n  ", state))
    assert "هیچ کانفیگی" in upd.message.replies[-1]
    assert app_ctx.state.get(OWNER_ID) is not None


# ---------- فایل txt ----------

class _FakeTgFile:
    def __init__(self, data): self._d = data
    async def download_as_bytearray(self): return bytearray(self._d)


class _FakeDocument:
    def __init__(self, name, data, size=None):
        self.file_name, self._data = name, data
        self.file_size = len(data) if size is None else size
    async def get_file(self): return _FakeTgFile(self._data)


def _doc_update(user_id, doc):
    upd = _FakeMessageUpdate(user_id, None)
    upd.message.document = doc
    return upd


def _send_doc(app_ctx, user_id, doc, state):
    fctx = _FakeContext(app_ctx)
    upd = _doc_update(user_id, doc)
    asyncio.run(admin_panel.handle_document(upd, fctx, state))
    return upd


def test_txt_file_upload_adds_items(app_ctx):
    asyncio.run(_fire(app_ctx, "acc:inv:add:0", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    upd = _send_doc(app_ctx, OWNER_ID, _FakeDocument("c.txt", "\ufeffvless://f1\r\nvless://f2\r\n".encode("utf-8")), state)
    assert "2 کانفیگ افزوده شد" in upd.message.replies[-1]


@pytest.mark.parametrize("doc,needle", [
    (_FakeDocument("c.pdf", b"x"), "فقط فایل"),
    (_FakeDocument("c.txt", b"x", size=10_000_000), "حجم"),
    (_FakeDocument("c.txt", "سلام".encode("cp1256") + b"\xff\xfe"), "UTF-8"),
])
def test_bad_files_rejected_and_state_kept(app_ctx, doc, needle):
    asyncio.run(_fire(app_ctx, "acc:inv:add:0", OWNER_ID))
    state = app_ctx.state.get(OWNER_ID)
    upd = _send_doc(app_ctx, OWNER_ID, doc, state)
    assert needle in upd.message.replies[-1]
    assert app_ctx.state.get(OWNER_ID) is not None


def test_file_outside_inventory_flow_is_ignored(app_ctx):
    upd = _send_doc(app_ctx, OWNER_ID, _FakeDocument("c.txt", b"a"), {"acc": "broadcast_text"})
    assert "نیازی به ارسال فایل نیست" in upd.message.replies[-1]
    with app_ctx.unit_of_work() as uow:
        assert uow.inventory.count_available(0) == 0


def test_bot_level_document_handler_requires_inventory_permission(app_ctx):
    """کاربر عادی (حتی با state ساختگی) نمی‌تواند از مسیر فایل به مخزن چیزی اضافه کند."""
    from adapters.telegram_bot import bot as bot_module
    app_ctx.state.set(PLAIN_USER_ID, {"acc": "inventory_add", "product_id": 0})
    fctx = _FakeContext(app_ctx)
    upd = _doc_update(PLAIN_USER_ID, _FakeDocument("c.txt", b"evil"))
    asyncio.run(bot_module.handle_documents(upd, fctx))
    assert upd.message.replies == []
    with app_ctx.unit_of_work() as uow:
        assert uow.inventory.count_available(0) == 0


def test_bot_level_document_handler_owner_flow(app_ctx):
    from adapters.telegram_bot import bot as bot_module
    asyncio.run(_fire(app_ctx, "acc:inv:add:0", OWNER_ID))
    fctx = _FakeContext(app_ctx)
    upd = _doc_update(OWNER_ID, _FakeDocument("c.txt", b"one\ntwo"))
    asyncio.run(bot_module.handle_documents(upd, fctx))
    assert "2 کانفیگ افزوده شد" in upd.message.replies[-1]
    with app_ctx.unit_of_work() as uow:
        row = uow._conn.execute(
            "SELECT action FROM audit_logs WHERE action='inventory.add_items' ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
