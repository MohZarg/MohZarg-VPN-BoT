"""
GhYiAb V2 — VPN Provider Interface (مستقل از 3x-ui)
=====================================================

Core فقط با این قرارداد صحبت می‌کند؛ هیچ Adapter ای (۳x-ui یا هر پنل آینده)
نباید جزئیات خودش را به لایهٔ بالاتر نشت بدهد. مرز معماری:

    V2 Core → VPNProvider (این فایل) → Adapter (مثلاً 3x-ui) → REST API → Xray

خطاها صریح‌اند: ``NotConfiguredError`` (BLOCKED/NOT_CONFIGURED)،
``ProviderUnavailableError`` (شبکه/۵xx؛ قابل Retry)، ``ProviderRejectedError``
(پنل صراحتاً رد کرد؛ Retry بی‌فایده). هیچ‌کدام هرگز به «موفقیت» تبدیل نمی‌شوند.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence


class VPNProviderError(Exception):
    """پایهٔ همهٔ خطاهای Provider."""


class NotConfiguredError(VPNProviderError):
    """Provider پیکربندی نشده (NOT_CONFIGURED/BLOCKED) — هرگز شبیه‌سازی نمی‌شود."""


class ProviderUnavailableError(VPNProviderError):
    """پنل در دسترس نیست (timeout/اتصال/۵xx). عملیات انجام‌شده فرض نمی‌شود."""


class ProviderAuthError(VPNProviderError):
    """توکن نامعتبر/منقضی یا دسترسی ناکافی."""


class ProviderRejectedError(VPNProviderError):
    """پنل درخواست را صراحتاً رد کرد (success=false / 4xx)."""

    def __init__(self, message: str, *, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ClientSpec:
    """مشخصات کلاینت جدید. total_bytes=0 یعنی نامحدود؛ expiry_ms=0 یعنی بدون انقضا."""
    email: str
    sub_id: str
    client_uuid: str = ""
    total_bytes: int = 0
    expiry_ms: int = 0
    limit_ip: int = 0
    enable: bool = True
    telegram_id: int = 0
    comment: str = ""


@dataclass(frozen=True)
class ClientState:
    email: str
    enable: bool
    expiry_ms: int
    total_bytes: int
    up_bytes: int = 0
    down_bytes: int = 0
    sub_id: str = ""
    uuid: str = ""
    inbound_ids: tuple = ()

    @property
    def used_bytes(self) -> int:
        return self.up_bytes + self.down_bytes

    @property
    def remaining_bytes(self) -> Optional[int]:
        """None = نامحدود."""
        if self.total_bytes <= 0:
            return None
        return max(0, self.total_bytes - self.used_bytes)


class VPNProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...
    def health_check(self) -> dict: ...
    def list_inbounds(self) -> list[dict]: ...
    def get_client(self, email: str) -> Optional[ClientState]: ...
    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState: ...
    def update_client(self, email: str, **changes) -> ClientState: ...
    def delete_client(self, email: str) -> None: ...
    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState: ...
    def get_traffic(self, email: str) -> Optional[ClientState]: ...
    def get_links(self, email: str) -> list[str]: ...
    def get_subscription_url(self, sub_id: str) -> Optional[str]: ...
    def reset_traffic(self, email: str) -> None: ...
    def set_enabled(self, email: str, enabled: bool) -> ClientState: ...
