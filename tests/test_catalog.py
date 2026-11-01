from core.catalog import service as catalog_service
from core.errors import ProductNotFoundError

OWNER_ID = 999999


def test_create_and_list_category(uow_factory):
    with uow_factory() as uow:
        cat = catalog_service.create_category(uow, OWNER_ID, "VPN Plans")
        assert cat.name == "VPN Plans"
        assert cat.parent_id is None

    with uow_factory() as uow:
        cats = catalog_service.list_categories(uow)
        assert any(c.name == "VPN Plans" for c in cats)


def test_category_hierarchy_and_delete_detaches_products(uow_factory):
    with uow_factory() as uow:
        parent = catalog_service.create_category(uow, OWNER_ID, "VPN")
        child = catalog_service.create_category(uow, OWNER_ID, "Unlimited", parent.id)
        product = uow.products.create("Test Plan", 10000, "TOMAN")
        catalog_service.assign_product_category(uow, OWNER_ID, product.id, child.id)

    with uow_factory() as uow:
        catalog_service.delete_category(uow, OWNER_ID, child.id)

    with uow_factory() as uow:
        refreshed = uow.products.get(product.id)
        assert refreshed is not None
        # حذف دسته باید محصول را از دسته جدا کند، نه اینکه محصول را حذف کند
        row = uow._conn.execute(
            "SELECT category_id FROM products WHERE id=?", (product.id,)
        ).fetchone()
        assert row[0] is None


def test_assign_category_to_missing_product_raises(uow_factory):
    with uow_factory() as uow:
        try:
            catalog_service.assign_product_category(uow, OWNER_ID, 999999, None)
            assert False, "expected ProductNotFoundError"
        except ProductNotFoundError:
            pass


def test_create_variant_and_list(uow_factory):
    with uow_factory() as uow:
        product = uow.products.create("VPN Sub", 50000, "TOMAN")
        variant = catalog_service.create_variant(
            uow, OWNER_ID, product.id, "1 Month",
            price_minor=50000, currency="TOMAN", duration_days=30,
        )
        assert variant.duration_days == 30
        assert variant.is_active is True

    with uow_factory() as uow:
        variants = catalog_service.list_variants(uow, product.id)
        assert len(variants) == 1
        assert variants[0].name == "1 Month"


def test_deactivate_variant(uow_factory):
    with uow_factory() as uow:
        product = uow.products.create("VPN Sub", 50000, "TOMAN")
        variant = catalog_service.create_variant(
            uow, OWNER_ID, product.id, "1 Month", 50000, "TOMAN",
        )

    with uow_factory() as uow:
        catalog_service.deactivate_variant(uow, OWNER_ID, variant.id)

    with uow_factory() as uow:
        refreshed = uow.product_variants.get(variant.id)
        assert refreshed.is_active is False


def test_create_variant_for_missing_product_raises(uow_factory):
    with uow_factory() as uow:
        try:
            catalog_service.create_variant(uow, OWNER_ID, 999999, "X", 1000, "TOMAN")
            assert False, "expected ProductNotFoundError"
        except ProductNotFoundError:
            pass
