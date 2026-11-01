"""
GhYiAb V2 — VPN Provider Factory & Registry
=============================================

Factory pattern برای مدیریت Providerهای مختلف VPN.
Core فقط با این فایل صحبت می‌کند و از Providerهای خاص بی‌خبر است.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from providers.vpn.base import VPNProvider, VPNProviderError, NotConfiguredError

logger = logging.getLogger("ghyiab.providers.vpn")

# Lazy imports to avoid circular dependencies
_PROVIDER_CLASSES: dict[str, type] = {}
_PROVIDER_INSTANCES: dict[str, VPNProvider] = {}


def _import_provider(name: str) -> type:
    """Lazy import provider class."""
    if name in _PROVIDER_CLASSES:
        return _PROVIDER_CLASSES[name]

    try:
        if name == "xui" or name == "3x-ui":
            from providers.vpn.xui.provider import ThreeXUIProvider as ProviderClass
        elif name == "marzban":
            from providers.vpn.marzban.provider import MarzbanProvider as ProviderClass
        elif name == "marzneshin":
            from providers.vpn.marzneshin.provider import MarzneshinProvider as ProviderClass
        elif name == "hiddify":
            from providers.vpn.hiddify.provider import HiddifyProvider as ProviderClass
        elif name == "wgdashboard":
            from providers.vpn.wgdashboard.provider import WGDashboardProvider as ProviderClass
        elif name == "guard":
            from providers.vpn.guard.provider import GuardProvider as ProviderClass
        elif name == "mikrotik":
            from providers.vpn.mikrotik.provider import MikrotikProvider as ProviderClass
        elif name == "sui":
            from providers.vpn.sui.provider import SUIProvider as ProviderClass
        elif name == "alireza":
            from providers.vpn.alireza.provider import AlirezaProvider as ProviderClass
        elif name == "manualsale":
            from providers.vpn.manualsale.provider import ManualsaleProvider as ProviderClass
        elif name == "ibsng":
            from providers.vpn.ibsng.provider import IBSngProvider as ProviderClass
        else:
            raise ValueError(f"Unknown provider type: {name}")

        _PROVIDER_CLASSES[name] = ProviderClass
        return ProviderClass
    except ImportError as e:
        logger.warning("Provider %s not available: %s", name, e)
        raise VPNProviderError(f"Provider {name} not available: {e}")


def create_provider(name: str, config: Any = None) -> VPNProvider:
    """Create a provider instance by name."""
    ProviderClass = _import_provider(name)
    if config is not None:
        return ProviderClass(config)
    return ProviderClass()


def get_provider(name: str) -> VPNProvider:
    """Get or create singleton provider instance."""
    if name not in _PROVIDER_INSTANCES:
        _PROVIDER_INSTANCES[name] = create_provider(name)
    return _PROVIDER_INSTANCES[name]


def get_default_provider() -> VPNProvider:
    """Get the default provider from environment."""
    provider_type = os.getenv("VPN_PROVIDER", "xui").lower()
    return get_provider(provider_type)


def list_available_providers() -> list[str]:
    """List all available provider types."""
    return ["xui", "marzban", "marzneshin", "hiddify", "wgdashboard", "guard", "mikrotik", "sui", "alireza", "manualsale", "ibsng"]


def health_check_all() -> dict[str, dict]:
    """Health check all configured providers."""
    results = {}
    for name in list_available_providers():
        try:
            provider = get_provider(name)
            if provider.is_configured():
                results[name] = provider.health_check()
            else:
                results[name] = {"status": "NOT_CONFIGURED"}
        except Exception as e:
            results[name] = {"status": "ERROR", "detail": str(e)}
    return results


# For backward compatibility
def build_default_provider() -> VPNProvider:
    """Build default provider (3x-ui)."""
    from providers.vpn.xui.provider import build_default_provider as build_xui
    return build_xui()


__all__ = [
    "VPNProvider",
    "VPNProviderError",
    "NotConfiguredError",
    "create_provider",
    "get_provider",
    "get_default_provider",
    "list_available_providers",
    "health_check_all",
    "build_default_provider",
]