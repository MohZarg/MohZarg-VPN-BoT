"""
GhYiAb V2 — Repository Interfaces
==================================

این ماژول قراردادهای (Protocol) لایهٔ داده را تعریف می‌کند تا:
  - core/* هرگز مستقیماً به sqlite3 وابسته نباشد.
  - مهاجرت SQLite → PostgreSQL معادل نوشتن یک پیاده‌سازی جدید همین Protocolها
    باشد، بدون تغییر یک خط در core/*.

طبق تصمیم Owner (Path A)، پیاده‌سازی فعلی SQLite است (`repository/sqlite/*`)،
اما همه‌چیز پشت این Interfaceها قرار می‌گیرد.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence


# --------------------------------------------------------------------------
# Value Objects مشترک
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class UserRecord:
    user_id: int
    is_agent: bool
    is_banned: bool
    has_accepted_rules: bool
    referred_by: int
    last_test_date: Optional[str]
    phone_number: Optional[str]
    phone_verified: bool
    last_dice_at: Optional[str]
    blocked_by_bot: bool
    reseller_tier_id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass(frozen=True)
class WalletBalance:
    user_id: int
    currency: str
    amount_minor: int  # مبلغ به کوچک‌ترین واحد ارز (برای تومان معادل خودش، بدون اعشار)


@dataclass(frozen=True)
class WalletTransactionRecord:
    id: int
    user_id: int
    currency: str
    amount_minor: int
    balance_after_minor: int
    reason: str
    idempotency_key: Optional[str]
    created_at: str


@dataclass(frozen=True)
class ProductRecord:
    id: int
    name: str
    price_minor: int
    currency: str
    description: Optional[str]
    qr_file_id: Optional[str]
    is_active: bool = True


@dataclass(frozen=True)
class InventoryItemRecord:
    id: int
    product_id: int
    item_type: str
    content: str
    status: str  # AVAILABLE | CLAIMED
    claimed_by: Optional[int]
    claimed_at: Optional[str]


@dataclass(frozen=True)
class PendingRequestRecord:
    id: int
    type: str
    user_id: int
    product_id: Optional[int]
    amount_minor: Optional[int]
    currency: Optional[str]
    status: str
    created_at: str
    idempotency_key: Optional[str] = None
    resolution_note: Optional[str] = None
    resolved_by: Optional[int] = None
    receipt_file_id: Optional[str] = None
    receipt_unique_id: Optional[str] = None
    coupon_code: Optional[str] = None
    expected_price_minor: Optional[int] = None


@dataclass(frozen=True)
class OrderRecord:
    id: int
    user_id: int
    product_id: int
    inventory_item_id: int
    price_minor: int
    currency: str
    status: str
    idempotency_key: Optional[str]
    created_at: str
    refunded_at: Optional[str] = None
    discount_minor: int = 0
    coupon_code: Optional[str] = None


@dataclass(frozen=True)
class OrderItemRecord:
    id: int
    order_id: int
    product_id: int
    variant_id: Optional[int]
    inventory_item_id: Optional[int]
    quantity: int
    price_minor: int
    currency: str


@dataclass(frozen=True)
class CategoryRecord:
    id: int
    name: str
    parent_id: Optional[int]
    created_at: str


@dataclass(frozen=True)
class ProductVariantRecord:
    id: int
    product_id: int
    name: str
    duration_days: Optional[int]
    traffic_gb: Optional[float]
    price_minor: int
    currency: str
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class ProviderRecord:
    id: int
    name: str
    type: str
    status: str  # NOT_CONFIGURED | OK | BLOCKED
    config_ref: Optional[str]
    updated_at: str


@dataclass(frozen=True)
class AuditLogRecord:
    id: int
    actor_id: int
    action: str
    entity_type: str
    entity_id: str
    before_json: Optional[str]
    after_json: Optional[str]
    created_at: str


@dataclass(frozen=True)
class UserStateRecord:
    user_id: int
    state_json: str
    updated_at: str


# --------------------------------------------------------------------------
# Admin Control Center / Phase 4-7 — Records جدید
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CouponRecord:
    id: int
    code: str
    kind: str  # PERCENT | FIXED
    value: int
    currency: Optional[str]
    max_uses: Optional[int]
    per_user_limit: Optional[int]
    expires_at: Optional[str]
    is_active: bool
    created_at: str
    min_order_minor: Optional[int] = None
    product_ids: Optional[str] = None  # CSV؛ None = بدون محدودیت محصول


@dataclass(frozen=True)
class ResellerTierRecord:
    id: int
    name: str
    discount_percent: int
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class ReferralRewardRecord:
    id: int
    referrer_id: int
    referred_id: int
    amount_minor: int
    currency: str
    status: str
    created_at: str


@dataclass(frozen=True)
class TicketRecord:
    id: int
    user_id: int
    subject: str
    status: str  # OPEN | ANSWERED | CLOSED
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TicketMessageRecord:
    id: int
    ticket_id: int
    sender_id: int
    is_staff: bool
    body: str
    created_at: str


@dataclass(frozen=True)
class BroadcastRecord:
    id: int
    actor_id: int
    text: str
    status: str  # QUEUED | RUNNING | DONE | CANCELLED
    total: int
    sent: int
    failed: int
    created_at: str
    finished_at: Optional[str]


@dataclass(frozen=True)
class ConfirmationRecord:
    token: str
    actor_id: int
    action: str
    payload_json: str
    created_at: str
    expires_at: str
    consumed_at: Optional[str]


@dataclass(frozen=True)
class JobRecord:
    name: str
    enabled: bool
    interval_minutes: int
    last_run_at: Optional[str]
    last_status: Optional[str]
    last_detail: Optional[str]


@dataclass(frozen=True)
class RenewalRecord:
    id: int
    order_id: int
    user_id: int
    amount_minor: int
    currency: str
    idempotency_key: str
    new_expiry_ms: int
    total_bytes: int
    status: str  # CHARGED | COMPLETED | REFUNDED
    source: str  # manual | auto
    error: Optional[str]
    created_at: str
    resolved_at: Optional[str]


@dataclass(frozen=True)
class ProvisioningProfileRecord:
    id: int
    product_id: int
    provider_name: str
    inbound_id: int
    duration_days: int
    traffic_gb: float
    limit_ip: int
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class ProvisionedClientRecord:
    id: int
    order_id: int
    provider_name: str
    inbound_id: int
    client_uuid: str
    email: str
    sub_id: str
    expires_at_ms: int
    status: str  # PENDING | ACTIVE | FAILED
    last_error: Optional[str]
    auto_renew: bool
    auto_renew_consent_at: Optional[str]
    created_at: str
    attempts: int = 0
    notified_expiry_ms: int = 0
    cached_used_bytes: int = 0
    cached_total_bytes: int = 0
    synced_at: Optional[str] = None


@dataclass(frozen=True)
class DiceRollRecord:
    id: int
    user_id: int
    value: int
    reward_minor: int
    created_at: str


@dataclass(frozen=True)
class Page:
    """نتیجهٔ صفحه‌بندی‌شده — مشترک بین همهٔ Listهای پنل ادمین."""
    items: Sequence
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per_page))


# --------------------------------------------------------------------------
# Unit of Work — تراکنش اتمیک چند-Repository
# --------------------------------------------------------------------------

class UnitOfWork(Protocol):
    """
    نمایانگر یک تراکنش دیتابیسی. صدازننده باید داخل `with` از آن استفاده کند؛
    اگر بلوک بدون خطا تمام شود commit، در غیر این صورت rollback خودکار انجام
    می‌شود. این انتزاع دقیقاً معادل الگوی BEGIN IMMEDIATE فعلی است، اما بدون
    وابستگی core به sqlite3.
    """

    def __enter__(self) -> "UnitOfWork": ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    @property
    def users(self) -> "UsersRepository": ...

    @property
    def wallet(self) -> "WalletRepository": ...

    @property
    def inventory(self) -> "InventoryRepository": ...

    @property
    def orders(self) -> "OrdersRepository": ...

    @property
    def products(self) -> "ProductsRepository": ...

    @property
    def pending_requests(self) -> "PendingRequestsRepository": ...

    @property
    def audit(self) -> "AuditRepository": ...

    @property
    def rbac(self) -> "RbacRepository": ...

    @property
    def categories(self) -> "CategoriesRepository": ...

    @property
    def product_variants(self) -> "ProductVariantsRepository": ...

    @property
    def providers(self) -> "ProvidersRepository": ...

    @property
    def settings(self) -> "SettingsTxRepository": ...

    @property
    def coupons(self) -> "CouponsRepository": ...

    @property
    def resellers(self) -> "ResellersRepository": ...

    @property
    def referrals(self) -> "ReferralsRepository": ...

    @property
    def tickets(self) -> "TicketsRepository": ...

    @property
    def broadcasts(self) -> "BroadcastsRepository": ...

    @property
    def confirmations(self) -> "ConfirmationsRepository": ...

    @property
    def jobs(self) -> "JobsRepository": ...

    @property
    def provisioning(self) -> "ProvisioningRepository": ...
    @property
    def renewals(self) -> "RenewalsRepository": ...

    @property
    def dice(self) -> "DiceRepository": ...

    @property
    def reports(self) -> "ReportsRepository": ...


# --------------------------------------------------------------------------
# Repository Protocolها
# --------------------------------------------------------------------------

class UsersRepository(Protocol):
    def get_or_create(self, user_id: int) -> UserRecord: ...
    def get_lang(self, user_id: int) -> str: ...
    def set_lang(self, user_id: int, lang: str) -> None: ...
    def set_banned(self, user_id: int, banned: bool) -> None: ...
    def set_agent(self, user_id: int, is_agent: bool) -> None: ...
    def set_accepted_rules(self, user_id: int) -> None: ...
    def set_referred_by(self, user_id: int, referrer_id: int) -> None: ...
    def set_last_test_date(self, user_id: int, date_str: str) -> None: ...
    def set_last_dice_at(self, user_id: int, iso_ts: str) -> None: ...
    def set_phone(self, user_id: int, phone: str) -> None: ...
    def set_blocked_by_bot(self, user_id: int, blocked: bool) -> None: ...
    def count_all(self) -> int: ...
    def list_ids_not_blocked(self) -> Sequence[int]: ...
    def exists(self, user_id: int) -> bool: ...
    def set_reseller_tier(self, user_id: int, tier_id: Optional[int]) -> None: ...
    def page(self, *, flt: str = "all", query: Optional[str] = None,
             page: int = 0, per_page: int = 8) -> "Page": ...
    def count_referred_by(self, referrer_id: int) -> int: ...
    def list_all_ids(self) -> Sequence[int]: ...


class WalletRepository(Protocol):
    def get_balance(self, user_id: int, currency: str) -> int: ...
    def adjust(self, user_id: int, currency: str, delta_minor: int) -> int:
        """موجودی را تغییر می‌دهد و موجودی جدید را برمی‌گرداند. باید اتمیک باشد."""
        ...
    def debit_if_sufficient(self, user_id: int, currency: str, amount_minor: int) -> bool:
        """فقط اگر موجودی کافی باشد کسر می‌کند؛ True/False برمی‌گرداند."""
        ...
    def record_transaction(self, user_id: int, currency: str, amount_minor: int,
                            balance_after_minor: int, reason: str,
                            idempotency_key: Optional[str] = None) -> int: ...
    def find_transaction_by_idempotency_key(self, key: str) -> Optional[WalletTransactionRecord]: ...
    def list_recent_transactions(self, user_id: int, limit: int = 10) -> Sequence[WalletTransactionRecord]: ...


class InventoryRepository(Protocol):
    def claim_one(self, product_id: int, claimer_id: int) -> Optional[InventoryItemRecord]:
        """اتمیک: یک آیتم AVAILABLE را claim می‌کند یا None اگر موجود نبود."""
        ...
    def get_by_id(self, item_id: int) -> Optional[InventoryItemRecord]: ...
    def count_available(self, product_id: int) -> int: ...
    def add_items(self, product_id: int, item_type: str, contents: Sequence[str]) -> int: ...
    def existing_contents(self, product_id: int, contents: Sequence[str]) -> set: ...
    def page(self, product_id: int, *, status: Optional[str] = None,
             page: int = 0, per_page: int = 8) -> "Page": ...
    def delete_available_item(self, item_id: int) -> bool: ...
    def reserve_placeholder(self, product_id: int, item_type: str, claimer_id: int) -> InventoryItemRecord: ...
    def fulfil_placeholder(self, item_id: int, content: str) -> None: ...
    def void_item(self, item_id: int) -> None: ...
    def counts_by_product(self) -> dict: ...
    def delete_unclaimed(self, product_id: int, limit: int) -> int: ...


class ProductsRepository(Protocol):
    def get(self, product_id: int) -> Optional[ProductRecord]: ...
    def list_all(self) -> Sequence[ProductRecord]: ...
    def create(self, name: str, price_minor: int, currency: str,
               description: Optional[str] = None) -> ProductRecord: ...
    def set_qr_file_id(self, product_id: int, file_id: str) -> None: ...
    def delete(self, product_id: int) -> None: ...
    def list_active(self) -> Sequence[ProductRecord]: ...
    def list_by_category(self, category_id: int) -> Sequence[ProductRecord]: ...
    def set_category(self, product_id: int, category_id: Optional[int]) -> None: ...
    def set_active(self, product_id: int, is_active: bool) -> None: ...
    def update(self, product_id: int, *, name: Optional[str] = None,
               price_minor: Optional[int] = None) -> None: ...
    def page(self, *, page: int = 0, per_page: int = 8) -> "Page": ...
    def count_orders(self, product_id: int) -> int: ...


class OrdersRepository(Protocol):
    def create(self, user_id: int, product_id: int, inventory_item_id: int,
               price_minor: int, currency: str, idempotency_key: Optional[str] = None,
               variant_id: Optional[int] = None) -> OrderRecord: ...
    def get_by_idempotency_key(self, key: str) -> Optional[OrderRecord]: ...
    def list_by_user(self, user_id: int) -> Sequence[OrderRecord]: ...
    def get_by_id(self, order_id: int) -> Optional[OrderRecord]: ...
    def list_items(self, order_id: int) -> Sequence[OrderItemRecord]: ...
    def page(self, *, status: Optional[str] = None, user_id: Optional[int] = None,
             page: int = 0, per_page: int = 8) -> "Page": ...
    def set_status(self, order_id: int, status: str) -> None: ...
    def mark_refunded(self, order_id: int) -> bool: ...
    def set_discount(self, order_id: int, discount_minor: int, coupon_code: Optional[str]) -> None: ...


class CategoriesRepository(Protocol):
    def create(self, name: str, parent_id: Optional[int] = None) -> CategoryRecord: ...
    def get(self, category_id: int) -> Optional[CategoryRecord]: ...
    def list_all(self) -> Sequence[CategoryRecord]: ...
    def delete(self, category_id: int) -> None: ...
    def rename(self, category_id: int, name: str) -> None: ...


class ProductVariantsRepository(Protocol):
    def create(self, product_id: int, name: str, price_minor: int, currency: str,
               duration_days: Optional[int] = None,
               traffic_gb: Optional[float] = None) -> ProductVariantRecord: ...
    def get(self, variant_id: int) -> Optional[ProductVariantRecord]: ...
    def list_by_product(self, product_id: int) -> Sequence[ProductVariantRecord]: ...
    def set_active(self, variant_id: int, is_active: bool) -> None: ...


class ProvidersRepository(Protocol):
    def get_by_name(self, name: str) -> Optional[ProviderRecord]: ...
    def list_all(self) -> Sequence[ProviderRecord]: ...
    def set_status(self, name: str, status: str) -> None: ...
    def upsert(self, name: str, type_: str, status: str,
               config_ref: Optional[str] = None) -> ProviderRecord: ...


class PendingRequestsRepository(Protocol):
    def create(self, req_type: str, user_id: int, product_id: Optional[int] = None,
               amount_minor: Optional[int] = None, currency: Optional[str] = None,
               idempotency_key: Optional[str] = None) -> int: ...
    def resolve(self, req_id: int, new_status: str) -> Optional[PendingRequestRecord]: ...
    def find_pending_by_type_and_user(self, req_type: str, user_id: int) -> Optional[PendingRequestRecord]: ...
    def find_by_idempotency_key(self, key: str) -> Optional[PendingRequestRecord]: ...
    def count_pending(self) -> int: ...
    def get(self, req_id: int) -> Optional[PendingRequestRecord]: ...
    def page(self, *, status: Optional[str] = None, req_type: Optional[str] = None,
             page: int = 0, per_page: int = 8) -> "Page": ...
    def set_receipt(self, req_id: int, file_id: str, unique_id: Optional[str]) -> None: ...
    def set_coupon(self, req_id: int, coupon_code: Optional[str], expected_price_minor: Optional[int]) -> None: ...
    def set_resolution(self, req_id: int, actor_id: int, note: Optional[str]) -> None: ...
    def find_by_receipt_unique_id(self, unique_id: str) -> Optional[PendingRequestRecord]: ...
    def count_pending_with_coupon(self, coupon_code: str, user_id: Optional[int] = None) -> int:
        """تعداد درخواست‌های pending که این کوپن را «رزرو» کرده‌اند (هنوز مصرف ثبت نشده)."""
        ...
    def find_active_by_receipt_unique_id(self, unique_id: str) -> Optional[PendingRequestRecord]:
        """درخواست pending/approved با همین رسید؛ ردشده‌ها حساب نمی‌شوند."""
        ...
    def expire_older_than(self, hours: int) -> int: ...


class AuditRepository(Protocol):
    def append(self, actor_id: int, action: str, entity_type: str, entity_id: str,
               before: Optional[dict], after: Optional[dict]) -> int: ...
    def list_recent(self, limit: int = 50) -> Sequence[AuditLogRecord]: ...
    def page(self, *, action_prefix: Optional[str] = None, actor_id: Optional[int] = None,
             entity_type: Optional[str] = None, page: int = 0, per_page: int = 8) -> "Page": ...
    def get(self, log_id: int) -> Optional[AuditLogRecord]: ...


class RbacRepository(Protocol):
    def ensure_owner_role(self, owner_user_id: int) -> None: ...
    def is_owner(self, user_id: int) -> bool: ...
    def list_admins(self) -> Sequence[int]: ...
    def grant_admin(self, user_id: int) -> None: ...
    def revoke_admin(self, user_id: int) -> None: ...
    def is_admin(self, user_id: int) -> bool: ...
    def has_permission(self, user_id: int, permission_name: str) -> bool: ...
    def list_permissions_for_role(self, role_name: str) -> Sequence[str]: ...
    def list_permissions_for_user(self, user_id: int) -> Sequence[str]: ...
    def list_user_grants(self, user_id: int) -> Sequence[str]: ...
    def set_user_grants(self, user_id: int, permissions: Sequence[str], granted_by: int) -> None: ...
    def catalog_names(self) -> Sequence[str]: ...


class StateRepository(Protocol):
    def get(self, user_id: int) -> Optional[dict]: ...
    def set(self, user_id: int, state: Optional[dict]) -> None: ...
    def clear(self, user_id: int) -> None: ...


class SettingsRepository(Protocol):
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]: ...
    def set(self, key: str, value: str) -> None: ...


class SettingsTxRepository(Protocol):
    """نسخهٔ داخل-تراکنش تنظیمات (برای اتمیک بودن با AuditLog)."""
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]: ...
    def set(self, key: str, value: str) -> None: ...
    def all(self) -> dict: ...


class CouponsRepository(Protocol):
    def create(self, code: str, kind: str, value: int, currency: Optional[str],
               max_uses: Optional[int], per_user_limit: Optional[int],
               expires_at: Optional[str], created_by: int) -> CouponRecord: ...
    def get_by_code(self, code: str) -> Optional[CouponRecord]: ...
    def get(self, coupon_id: int) -> Optional[CouponRecord]: ...
    def set_active(self, coupon_id: int, active: bool) -> None: ...
    def page(self, *, page: int = 0, per_page: int = 8) -> Page: ...
    def count_uses(self, coupon_id: int) -> int: ...
    def count_uses_by_user(self, coupon_id: int, user_id: int) -> int: ...
    def record_redemption(self, coupon_id: int, user_id: int, order_id: Optional[int],
                          discount_minor: int) -> int: ...


class ResellersRepository(Protocol):
    def create_tier(self, name: str, discount_percent: int) -> ResellerTierRecord: ...
    def get_tier(self, tier_id: int) -> Optional[ResellerTierRecord]: ...
    def list_tiers(self) -> Sequence[ResellerTierRecord]: ...
    def set_tier_active(self, tier_id: int, active: bool) -> None: ...
    def count_users_in_tier(self, tier_id: int) -> int: ...


class ReferralsRepository(Protocol):
    def get_reward_for_referred(self, referred_id: int) -> Optional[ReferralRewardRecord]: ...
    def record_reward(self, referrer_id: int, referred_id: int, amount_minor: int,
                      currency: str, notified: bool = True) -> Optional[ReferralRewardRecord]: ...
    def mark_reversed(self, reward_id: int) -> bool: ...
    def list_unnotified(self, limit: int = 50) -> Sequence[tuple]: ...
    def mark_notified(self, reward_id: int) -> None: ...
    def get(self, reward_id: int) -> Optional[ReferralRewardRecord]: ...
    def count_rewards_today(self, referrer_id: int) -> int: ...
    def top_referrers(self, limit: int = 5) -> Sequence[tuple]: ...
    def totals(self) -> dict: ...
    def page_for_referrer(self, referrer_id: int, *, page: int = 0, per_page: int = 8) -> Page: ...


class TicketsRepository(Protocol):
    def create(self, user_id: int, subject: str, body: str) -> TicketRecord: ...
    def get(self, ticket_id: int) -> Optional[TicketRecord]: ...
    def add_message(self, ticket_id: int, sender_id: int, is_staff: bool, body: str) -> TicketMessageRecord: ...
    def set_status(self, ticket_id: int, status: str) -> None: ...
    def messages(self, ticket_id: int, limit: int = 20) -> Sequence[TicketMessageRecord]: ...
    def page(self, *, status: Optional[str] = None, user_id: Optional[int] = None,
             page: int = 0, per_page: int = 8) -> Page: ...
    def count_open_for_user(self, user_id: int) -> int: ...
    def count_by_status(self, status: str) -> int: ...


class BroadcastsRepository(Protocol):
    def create(self, actor_id: int, text: str, total: int) -> BroadcastRecord: ...
    def get(self, broadcast_id: int) -> Optional[BroadcastRecord]: ...
    def update_progress(self, broadcast_id: int, sent: int, failed: int) -> None: ...
    def set_status(self, broadcast_id: int, status: str) -> None: ...
    def page(self, *, page: int = 0, per_page: int = 8) -> Page: ...


class ConfirmationsRepository(Protocol):
    def create(self, token: str, actor_id: int, action: str, payload_json: str, ttl_seconds: int) -> None: ...
    def get(self, token: str) -> Optional[ConfirmationRecord]: ...
    def consume(self, token: str) -> bool: ...
    def purge_expired(self) -> int: ...


class JobsRepository(Protocol):
    def ensure(self, name: str, interval_minutes: int) -> None: ...
    def get(self, name: str) -> Optional[JobRecord]: ...
    def list_all(self) -> Sequence[JobRecord]: ...
    def set_enabled(self, name: str, enabled: bool) -> None: ...
    def record_run(self, name: str, status: str, detail: str) -> None: ...


class ProvisioningRepository(Protocol):
    def upsert_profile(self, product_id: int, provider_name: str, inbound_id: int,
                       duration_days: int, traffic_gb: float, limit_ip: int) -> ProvisioningProfileRecord: ...
    def get_profile(self, product_id: int) -> Optional[ProvisioningProfileRecord]: ...
    def list_profiles(self) -> Sequence[ProvisioningProfileRecord]: ...
    def set_profile_active(self, product_id: int, active: bool) -> None: ...
    def create_client(self, order_id: int, provider_name: str, inbound_id: int, client_uuid: str,
                      email: str, sub_id: str, expires_at_ms: int) -> ProvisionedClientRecord: ...
    def get_client_by_order(self, order_id: int) -> Optional[ProvisionedClientRecord]: ...
    def set_client_status(self, order_id: int, status: str, error: Optional[str] = None) -> None: ...
    def list_clients(self, status: str) -> Sequence[ProvisionedClientRecord]: ...
    def set_auto_renew(self, order_id: int, enabled: bool, consent_at: Optional[str]) -> None: ...
    def set_expiry(self, order_id: int, expires_at_ms: int) -> None: ...
    def list_expiring(self, before_ms: int) -> Sequence[ProvisionedClientRecord]: ...
    def list_by_user(self, user_id: int) -> Sequence[ProvisionedClientRecord]: ...
    def list_active_expired(self, before_ms: int) -> Sequence[ProvisionedClientRecord]: ...
    def list_active_expiring_soon(self, before_ms: int, not_notified_for_ms: int) -> Sequence[ProvisionedClientRecord]: ...
    def bump_attempts(self, order_id: int) -> int: ...
    def set_notified(self, order_id: int, expiry_ms: int) -> None: ...
    def set_cache(self, order_id: int, used: int, total: int, expires_at_ms: int) -> None: ...
    def count_by_status(self) -> dict: ...


class RenewalsRepository(Protocol):
    def create(self, order_id: int, user_id: int, amount_minor: int, currency: str, key: str,
               new_expiry_ms: int, total_bytes: int, source: str) -> RenewalRecord: ...
    def get_by_key(self, key: str) -> Optional[RenewalRecord]: ...
    def set_status(self, renewal_id: int, status: str, error: Optional[str] = None) -> None: ...
    def list_stuck(self, older_than_minutes: int) -> Sequence[RenewalRecord]: ...
    def list_for_order(self, order_id: int) -> Sequence[RenewalRecord]: ...


class DiceRepository(Protocol):
    def record(self, user_id: int, value: int, reward_minor: int) -> DiceRollRecord: ...
    def set_reward(self, roll_id: int, reward_minor: int) -> None: ...
    def payout_today(self) -> int: ...
    def stats(self) -> dict: ...


class ReportsRepository(Protocol):
    """کوئری‌های فقط‌خواندنی تجمیعی (Read-model) برای داشبورد/گزارش."""
    def dashboard(self) -> dict: ...
    def liabilities(self) -> dict: ...
    def revenue(self) -> dict: ...
    def low_stock(self, threshold: int) -> Sequence[tuple]: ...
