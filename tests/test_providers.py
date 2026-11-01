from core.providers import service as providers_service

OWNER_ID = 999999


def test_xui_seeded_as_not_configured(uow_factory):
    """طبق No Fake Integration، seed اولیه باید دقیقاً NOT_CONFIGURED باشد."""
    with uow_factory() as uow:
        xui = providers_service.get_provider(uow, "xui_vpn")
        assert xui is not None
        assert xui.status == "NOT_CONFIGURED"
        assert xui.type == "VPN"
        # config_ref فقط نام متغیرهای محیطی است، هرگز مقدار واقعی
        assert "XUI_BASE_URL" in xui.config_ref and "XUI_API_TOKEN" in xui.config_ref
        assert "http" not in xui.config_ref.lower()


def test_report_status_records_real_value_and_audit(uow_factory):
    with uow_factory() as uow:
        providers_service.report_status(uow, OWNER_ID, "xui_vpn", "BLOCKED")

    with uow_factory() as uow:
        xui = providers_service.get_provider(uow, "xui_vpn")
        assert xui.status == "BLOCKED"
        logs = uow.audit.list_recent(limit=5)
        assert any(l.action == "provider.status_change" for l in logs)


def test_report_status_rejects_invalid_value(uow_factory):
    with uow_factory() as uow:
        try:
            providers_service.report_status(uow, OWNER_ID, "xui_vpn", "TOTALLY_FINE")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_register_new_provider(uow_factory):
    with uow_factory() as uow:
        providers_service.register_provider(
            uow, OWNER_ID, "example_gateway", "PAYMENT_GATEWAY", "NOT_CONFIGURED",
            config_ref="EXAMPLE_GATEWAY_API_KEY",
        )

    with uow_factory() as uow:
        all_providers = providers_service.list_providers(uow)
        names = {p.name for p in all_providers}
        assert {"xui_vpn", "example_gateway"} <= names
