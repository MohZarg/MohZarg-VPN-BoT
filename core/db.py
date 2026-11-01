"""
GhYiAb V2 — SQLAlchemy Database Models
=======================================

این ماژول مدل‌های SQLAlchemy را برای پشتیبانی از PostgreSQL و MySQL
(علاوه بر SQLite) فراهم می‌کند. مدل‌ها با اسکیمای موجود در
repository/sqlite/connection.py هم‌خوانی دارند.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, create_engine, event
)
from sqlalchemy.orm import DeclarativeBase, declared_attr, relationship, sessionmaker
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    """Base class for all models."""

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class User(Base):
    """Users table."""
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=True)
    language_code = Column(String(10), default="fa", nullable=False)
    is_agent = Column(Boolean, default=False, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    ban_reason = Column(Text, nullable=True)
    referred_by = Column(BigInteger, nullable=True)
    phone_number = Column(String(32), nullable=True)
    phone_verified = Column(Boolean, default=False, nullable=False)
    phone_verified_at = Column(DateTime, nullable=True)
    wallet_balance_irt_minor = Column(BigInteger, default=0, nullable=False)
    wallet_balance_usdt_minor = Column(BigInteger, default=0, nullable=False)
    referral_code = Column(String(32), unique=True, nullable=True)
    referral_earnings_minor = Column(BigInteger, default=0, nullable=False)
    has_accepted_rules = Column(Boolean, default=False, nullable=False)
    last_test_date = Column(String(10), nullable=True)
    last_dice_at = Column(DateTime, nullable=True)
    blocked_by_bot = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    orders = relationship("Order", back_populates="user")
    wallet_transactions = relationship("WalletTransaction", back_populates="user")
    pending_requests = relationship("PendingRequest", back_populates="user")
    provisioned_clients = relationship("ProvisionedClient", back_populates="user")
    referral_earnings = relationship("ReferralEarning", back_populates="referrer")
    tickets = relationship("Ticket", back_populates="user")
    dice_rolls = relationship("DiceRoll", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="actor")
    user_roles = relationship("UserRole", back_populates="user")
    user_permissions = relationship("UserPermission", back_populates="user")
    crypto_invoices = relationship("CryptoInvoice", back_populates="user")
    export_jobs = relationship("ExportJob", back_populates="requested_by_user")
    mini_app_sessions = relationship("MiniAppSession", back_populates="user")
    referrals = relationship("User", back_populates="referrer", remote_side=[user_id])
    referrer = relationship("User", back_populates="referrals", remote_side=[referred_by])

    __table_args__ = (
        Index("idx_users_referred_by", "referred_by"),
        Index("idx_users_referral_code", "referral_code"),
        Index("idx_users_phone", "phone_number"),
        Index("idx_users_is_agent", "is_agent"),
        Index("idx_users_is_banned", "is_banned"),
    )


class Product(Base):
    """Products/Services table."""
    __tablename__ = "products"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), default="IRT", nullable=False)
    duration_days = Column(Integer, nullable=False, default=30)
    traffic_gb = Column(Float, default=0, nullable=False)
    inbound_id = Column(Integer, nullable=False)
    provider_name = Column(String(64), default="xui", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    features = Column(Text, nullable=True)  # JSON
    sort_order = Column(Integer, default=0, nullable=False)
    category_id = Column(BigInteger, ForeignKey("categories.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    category = relationship("Category", back_populates="products")
    variants = relationship("ProductVariant", back_populates="product")
    provisioning_profiles = relationship("ProvisioningProfile", back_populates="product")
    orders = relationship("Order", back_populates="product")
    inventory_items = relationship("InventoryItem", back_populates="product")

    __table_args__ = (
        Index("idx_products_is_active", "is_active"),
        Index("idx_products_provider_inbound", "provider_name", "inbound_id"),
    )


class Category(Base):
    """Categories table."""
    __tablename__ = "categories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(BigInteger, ForeignKey("categories.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    parent = relationship("Category", remote_side=[id], back_populates="children")
    children = relationship("Category", back_populates="parent")
    products = relationship("Product", back_populates="category")

    __table_args__ = (
        UniqueConstraint("name", "parent_id", name="uk_category_name_parent"),
    )


class ProductVariant(Base):
    """Product variants table."""
    __tablename__ = "product_variants"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    name = Column(String(255), nullable=False)
    duration_days = Column(Integer, nullable=True)
    traffic_gb = Column(Float, nullable=True)
    price_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("Product", back_populates="variants")
    order_items = relationship("OrderItem", back_populates="variant")

    __table_args__ = (
        Index("idx_variants_product", "product_id"),
    )


class InventoryItem(Base):
    """Inventory items table."""
    __tablename__ = "inventory_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    item_type = Column(String(64), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(32), default="AVAILABLE", nullable=False)
    claimed_by = Column(BigInteger, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("Product", back_populates="inventory_items")
    order_items = relationship("OrderItem", back_populates="inventory_item")
    order = relationship("Order", back_populates="inventory_item")

    __table_args__ = (
        Index("idx_inventory_product_status", "product_id", "status"),
    )


class Order(Base):
    """Orders table."""
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    inventory_item_id = Column(BigInteger, ForeignKey("inventory_items.id"), nullable=True)
    price_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), default="IRT", nullable=False)
    status = Column(
        Enum("pending", "paid", "provisioning", "active", "expired", "cancelled", "refunded", name="order_status"),
        default="pending", nullable=False
    )
    discount_minor = Column(BigInteger, default=0, nullable=False)
    coupon_code = Column(String(64), nullable=True)
    payment_gateway = Column(String(64), nullable=True)
    payment_authority = Column(String(255), nullable=True)
    payment_ref_id = Column(String(255), nullable=True)
    client_uuid = Column(String(255), nullable=True)
    subscription_url = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    provisioned_at = Column(DateTime, nullable=True)
    refunded_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String(255), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="orders")
    product = relationship("Product", back_populates="orders")
    inventory_item = relationship("InventoryItem", back_populates="order")
    order_items = relationship("OrderItem", back_populates="order")
    provisioned_client = relationship("ProvisionedClient", back_populates="order", uselist=False)
    service_renewals = relationship("ServiceRenewal", back_populates="order")
    refunds = relationship("ServiceRefund", back_populates="order")

    __table_args__ = (
        Index("idx_orders_user", "user_id"),
        Index("idx_orders_status", "status"),
        Index("idx_orders_payment_authority", "payment_authority"),
        Index("idx_orders_created_at", "created_at"),
    )


class OrderItem(Base):
    """Order items table."""
    __tablename__ = "order_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    variant_id = Column(BigInteger, ForeignKey("product_variants.id"), nullable=True)
    inventory_item_id = Column(BigInteger, ForeignKey("inventory_items.id"), nullable=True)
    quantity = Column(Integer, default=1, nullable=False)
    price_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), nullable=False)

    # Relationships
    order = relationship("Order", back_populates="order_items")
    product = relationship("Product")
    variant = relationship("ProductVariant", back_populates="order_items")
    inventory_item = relationship("InventoryItem", back_populates="order_items")

    __table_args__ = (
        Index("idx_order_items_order", "order_id"),
    )


class PendingRequest(Base):
    """Pending requests (payments) table."""
    __tablename__ = "pending_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    type = Column(Enum("charge", "buy", "agency", name="pending_type"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), default="IRT", nullable=False)
    status = Column(
        Enum("pending", "approved", "rejected", "cancelled", name="pending_status"),
        default="pending", nullable=False
    )
    receipt_unique_id = Column(String(255), nullable=True)
    receipt_media = Column(Text, nullable=True)  # JSON
    coupon_code = Column(String(64), nullable=True)
    expected_price_minor = Column(BigInteger, nullable=True)
    resolved_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    reject_reason = Column(Text, nullable=True)
    resolution_note = Column(Text, nullable=True)
    idempotency_key = Column(String(255), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="pending_requests", foreign_keys=[user_id])
    resolver = relationship("User", foreign_keys=[resolved_by])
    product = relationship("Product")

    __table_args__ = (
        Index("idx_pending_user_status", "user_id", "status"),
        Index("idx_pending_receipt", "receipt_unique_id"),
        Index("idx_pending_idempotency", "idempotency_key"),
        Index("idx_pending_type_status", "type", "status"),
    )


class WalletTransaction(Base):
    """Wallet transactions table."""
    __tablename__ = "wallet_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    currency = Column(String(10), default="IRT", nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    balance_after_minor = Column(BigInteger, nullable=False)
    reason = Column(String(255), nullable=False)
    idempotency_key = Column(String(255), unique=True, nullable=False)
    metadata = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="wallet_transactions")

    __table_args__ = (
        Index("idx_wtx_user_currency", "user_id", "currency"),
        Index("idx_wtx_idempotency", "idempotency_key"),
        Index("idx_wtx_created_at", "created_at"),
    )


class Provider(Base):
    """Providers table."""
    __tablename__ = "providers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    display_name = Column(String(128), nullable=False)
    type = Column(String(64), nullable=False)
    config = Column(Text, nullable=False)  # JSON
    status = Column(
        Enum("OK", "FAILED", "STANDBY", "FAILOVER_ACTIVE", "NOT_CONFIGURED", name="provider_status"),
        default="NOT_CONFIGURED", nullable=False
    )
    priority = Column(Integer, default=100, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    provisioning_profiles = relationship("ProvisioningProfile", back_populates="provider")
    panel_health_logs = relationship("PanelHealthLog", back_populates="provider")
    crypto_wallets = relationship("CryptoWallet", back_populates="provider")
    stock_configs = relationship("NMConfigStock", back_populates="provider")
    stock_shelves = relationship("NMStockShelf", back_populates="provider")

    __table_args__ = (
        Index("idx_providers_status", "status"),
        Index("idx_providers_priority", "priority"),
    )


class ProvisioningProfile(Base):
    """Provisioning profiles table."""
    __tablename__ = "provisioning_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=False)
    provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    inbound_id = Column(Integer, nullable=False)
    protocol = Column(String(32), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("Product", back_populates="provisioning_profiles")
    provider = relationship("Provider", back_populates="provisioning_profiles")

    __table_args__ = (
        UniqueConstraint("product_id", "provider_id", name="uk_product_provider"),
        Index("idx_provisioning_provider_inbound", "provider_id", "inbound_id"),
    )


class ProvisionedClient(Base):
    """Provisioned clients table."""
    __tablename__ = "provisioned_clients"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False, unique=True)
    provider_name = Column(String(64), nullable=False)
    inbound_id = Column(Integer, nullable=False)
    client_uuid = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    sub_id = Column(String(255), nullable=True)
    expires_at_ms = Column(BigInteger, nullable=True)
    status = Column(
        Enum("ACTIVE", "EXPIRED", "DISABLED", "FAILED", "REFUNDED", name="provisioned_status"),
        default="ACTIVE", nullable=False
    )
    last_synced_at = Column(DateTime, nullable=True)
    sync_data = Column(Text, nullable=True)  # JSON
    attempts = Column(Integer, default=0, nullable=False)
    notified_expiry_ms = Column(BigInteger, default=0, nullable=False)
    cached_used_bytes = Column(BigInteger, default=0, nullable=False)
    cached_total_bytes = Column(BigInteger, default=0, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    order = relationship("Order", back_populates="provisioned_client")
    user = relationship("User", back_populates="provisioned_clients")
    refunds = relationship("ServiceRefund", back_populates="provisioned_client")

    __table_args__ = (
        UniqueConstraint("provider_name", "email", name="uk_provider_email"),
        Index("idx_provisioned_order", "order_id"),
        Index("idx_provisioned_email", "email"),
        Index("idx_provisioned_status", "status"),
        Index("idx_provisioned_expiry", "status", "expires_at_ms"),
    )


class Coupon(Base):
    """Coupons table."""
    __tablename__ = "coupons"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False)
    type = Column(Enum("percent", "fixed", name="coupon_type"), nullable=False)
    value = Column(BigInteger, nullable=False)
    currency = Column(String(10), default="IRT", nullable=False)
    max_uses = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0, nullable=False)
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    min_order_minor = Column(BigInteger, nullable=True)
    max_discount_minor = Column(BigInteger, nullable=True)
    applicable_products = Column(Text, nullable=True)  # JSON
    applicable_categories = Column(Text, nullable=True)  # JSON
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    creator = relationship("User")
    uses = relationship("CouponUse", back_populates="coupon")

    __table_args__ = (
        Index("idx_coupons_code", "code"),
        Index("idx_coupons_active_dates", "is_active", "valid_from", "valid_until"),
    )


class CouponUse(Base):
    """Coupon uses table."""
    __tablename__ = "coupon_uses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    coupon_id = Column(BigInteger, ForeignKey("coupons.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    discount_minor = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    coupon = relationship("Coupon", back_populates="uses")
    user = relationship("User")
    order = relationship("Order")

    __table_args__ = (
        UniqueConstraint("coupon_id", "user_id", "order_id", name="uk_coupon_user_order"),
        Index("idx_coupon_uses_user", "user_id"),
    )


class ReferralTier(Base):
    """Referral tiers table."""
    __tablename__ = "referral_tiers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tier_name = Column(Enum("N", "N2", "F", name="referral_tier_name"), nullable=False)
    level = Column(Integer, nullable=False)
    commission_percent = Column(Float, nullable=False)
    max_depth = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    earnings = relationship("ReferralEarning", back_populates="tier")

    __table_args__ = (
        UniqueConstraint("tier_name", name="uk_tier_name"),
        UniqueConstraint("level", name="uk_tier_level"),
    )


class ReferralEarning(Base):
    """Referral earnings table."""
    __tablename__ = "referral_earnings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    referred_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    tier_id = Column(BigInteger, ForeignKey("referral_tiers.id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    commission_basis_minor = Column(BigInteger, nullable=False)
    commission_amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), default="IRT", nullable=False)
    status = Column(
        Enum("pending", "approved", "paid", "cancelled", name="referral_status"),
        default="pending", nullable=False
    )
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    referrer = relationship("User", foreign_keys=[referrer_id], back_populates="referral_earnings")
    referred = relationship("User", foreign_keys=[referred_id])
    tier = relationship("ReferralTier", back_populates="earnings")
    order = relationship("Order")

    __table_args__ = (
        Index("idx_referral_referrer_status", "referrer_id", "status"),
        Index("idx_referral_referred", "referred_id"),
        Index("idx_referral_order", "order_id"),
        Index("idx_referral_status", "status"),
    )


class GiftCode(Base):
    """Gift codes table."""
    __tablename__ = "gift_codes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=True)
    amount_minor = Column(BigInteger, nullable=True)
    currency = Column(String(10), default="IRT", nullable=False)
    duration_days = Column(Integer, nullable=True)
    traffic_gb = Column(Float, nullable=True)
    max_uses = Column(Integer, default=1, nullable=False)
    used_count = Column(Integer, default=0, nullable=False)
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("Product")
    creator = relationship("User")
    uses = relationship("GiftCodeUse", back_populates="gift_code")

    __table_args__ = (
        Index("idx_gift_codes_code", "code"),
        Index("idx_gift_codes_active", "is_active", "valid_from", "valid_until"),
    )


class GiftCodeUse(Base):
    """Gift code uses table."""
    __tablename__ = "gift_code_uses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    gift_code_id = Column(BigInteger, ForeignKey("gift_codes.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    gift_code = relationship("GiftCode", back_populates="uses")
    user = relationship("User")
    order = relationship("Order")

    __table_args__ = (
        UniqueConstraint("gift_code_id", "user_id", name="uk_gift_code_user"),
    )


class CryptoWallet(Base):
    """Crypto wallets table."""
    __tablename__ = "crypto_wallets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    currency = Column(String(20), nullable=False)
    network = Column(String(32), nullable=True)
    address = Column(String(255), nullable=False)
    tag = Column(String(255), nullable=True)
    label = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    min_deposit_minor = Column(BigInteger, nullable=True)
    max_deposit_minor = Column(BigInteger, nullable=True)
    confirmations_required = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    invoices = relationship("CryptoInvoice", back_populates="wallet")

    __table_args__ = (
        UniqueConstraint("currency", "network", "address", name="uk_crypto_wallet"),
        Index("idx_crypto_wallet_currency", "currency", "is_active"),
    )


class CryptoInvoice(Base):
    """Crypto invoices table."""
    __tablename__ = "crypto_invoices"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    wallet_id = Column(BigInteger, ForeignKey("crypto_wallets.id"), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(20), nullable=False)
    wallet_to = Column(String(255), nullable=False)
    tx_hash = Column(String(255), unique=True, nullable=True)
    status = Column(
        Enum("pending", "verifying", "verified", "failed", "expired", name="crypto_invoice_status"),
        default="pending", nullable=False
    )
    memo = Column(String(255), nullable=True)
    expected_amount = Column(BigInteger, nullable=True)
    confirmed_amount = Column(BigInteger, nullable=True)
    confirmations = Column(Integer, default=0, nullable=False)
    required_confirmations = Column(Integer, default=1, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="crypto_invoices")
    wallet = relationship("CryptoWallet", back_populates="invoices")

    __table_args__ = (
        Index("idx_crypto_invoice_user_status", "user_id", "status"),
        Index("idx_crypto_invoice_tx_hash", "tx_hash"),
        Index("idx_crypto_invoice_status_expires", "status", "expires_at"),
    )


class NMConfigStock(Base):
    """National Net config stock table."""
    __tablename__ = "nm_config_stock"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    inbound_id = Column(Integer, nullable=False)
    protocol = Column(String(32), nullable=False)
    remark = Column(String(255), nullable=True)
    config_string = Column(Text, nullable=False)
    qr_code = Column(Text, nullable=True)
    used = Column(Boolean, default=False, nullable=False)
    used_by_order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    provider = relationship("Provider", back_populates="stock_configs")
    used_by_order = relationship("Order")

    __table_args__ = (
        Index("idx_nm_stock_provider_inbound", "provider_id", "inbound_id"),
        Index("idx_nm_stock_protocol_used", "protocol", "used"),
        Index("idx_nm_stock_used_order", "used_by_order_id"),
    )


class NMStockShelf(Base):
    """National Net stock shelves table."""
    __tablename__ = "nm_stock_shelves"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    inbound_id = Column(Integer, nullable=False)
    protocol = Column(String(32), nullable=False)
    auto_refill = Column(Boolean, default=False, nullable=False)
    min_stock = Column(Integer, default=5, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    provider = relationship("Provider", back_populates="stock_shelves")

    __table_args__ = (
        UniqueConstraint("name", "provider_id", name="uk_shelf_name_provider"),
        Index("idx_nm_shelf_provider_inbound", "provider_id", "inbound_id"),
    )


class PanelHealthLog(Base):
    """Panel health logs table."""
    __tablename__ = "panel_health_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    status = Column(
        Enum("OK", "BLOCKED", "ERROR", "NOT_CONFIGURED", "FAILED", name="panel_health_status"),
        nullable=False
    )
    latency_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    provider = relationship("Provider", back_populates="panel_health_logs")

    __table_args__ = (
        Index("idx_panel_health_provider_checked", "provider_id", "checked_at"),
        Index("idx_panel_health_status", "status"),
    )


class ScheduledJob(Base):
    """Scheduled jobs table."""
    __tablename__ = "scheduled_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False)
    cron_expression = Column(String(128), nullable=True)
    fire_at = Column(DateTime, nullable=True)
    handler = Column(String(255), nullable=False)
    payload = Column(Text, nullable=True)  # JSON
    enabled = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_status = Column(Enum("succeeded", "failed", "running", name="job_status"), nullable=True)
    last_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    runs = relationship("JobRun", back_populates="job")

    __table_args__ = (
        Index("idx_scheduled_jobs_enabled_cron", "enabled", "cron_expression"),
        Index("idx_scheduled_jobs_fire_at", "fire_at"),
    )


class JobRun(Base):
    """Job runs table."""
    __tablename__ = "job_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(BigInteger, ForeignKey("scheduled_jobs.id"), nullable=False)
    status = Column(Enum("running", "succeeded", "failed", name="job_run_status"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    detail = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    # Relationships
    job = relationship("ScheduledJob", back_populates="runs")

    __table_args__ = (
        Index("idx_job_runs_job_started", "job_id", "started_at"),
        Index("idx_job_runs_status", "status"),
    )


class ProviderFailoverRule(Base):
    """Provider failover rules table."""
    __tablename__ = "provider_failover_rules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    primary_provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    fallback_provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    trigger_condition = Column(
        Enum("health_check_failed", "provisioning_failed", name="failover_trigger"),
        default="health_check_failed", nullable=False
    )
    max_retries = Column(Integer, default=3, nullable=False)
    cooldown_minutes = Column(Integer, default=5, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    primary_provider = relationship("Provider", foreign_keys=[primary_provider_id])
    fallback_provider = relationship("Provider", foreign_keys=[fallback_provider_id])
    events = relationship("ProviderFailoverEvent", back_populates="rule")

    __table_args__ = (
        UniqueConstraint("primary_provider_id", "fallback_provider_id", name="uk_primary_fallback"),
        Index("idx_failover_active", "is_active"),
    )


class ProviderFailoverEvent(Base):
    """Provider failover events table."""
    __tablename__ = "provider_failover_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    rule_id = Column(BigInteger, ForeignKey("provider_failover_rules.id"), nullable=False)
    primary_provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    fallback_provider_id = Column(BigInteger, ForeignKey("providers.id"), nullable=False)
    trigger_reason = Column(Text, nullable=True)
    status = Column(
        Enum("triggered", "switched", "recovered", name="failover_event_status"),
        default="triggered", nullable=False
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    recovered_at = Column(DateTime, nullable=True)

    # Relationships
    rule = relationship("ProviderFailoverRule", back_populates="events")
    primary_provider = relationship("Provider", foreign_keys=[primary_provider_id])
    fallback_provider = relationship("Provider", foreign_keys=[fallback_provider_id])

    __table_args__ = (
        Index("idx_failover_event_rule_created", "rule_id", "created_at"),
        Index("idx_failover_event_status", "status"),
    )


class ServiceRefund(Base):
    """Service refunds table."""
    __tablename__ = "service_refunds"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provisioned_client_id = Column(BigInteger, ForeignKey("provisioned_clients.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=True)
    original_amount_minor = Column(BigInteger, nullable=False)
    refund_amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), default="IRT", nullable=False)
    reason = Column(Text, nullable=False)
    calculation_method = Column(
        Enum("pro_rata_time", "pro_rata_traffic", "pro_rata_min", "full", "partial", name="refund_method"),
        nullable=False
    )
    days_used = Column(Integer, nullable=True)
    days_remaining = Column(Integer, nullable=True)
    status = Column(
        Enum("pending", "approved", "rejected", "processed", name="refund_status"),
        default="pending", nullable=False
    )
    requested_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    approved_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    provisioned_client = relationship("ProvisionedClient", back_populates="refunds")
    user = relationship("User", foreign_keys=[user_id])
    order = relationship("Order", back_populates="refunds")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        Index("idx_refunds_user_status", "user_id", "status"),
        Index("idx_refunds_client", "provisioned_client_id"),
        Index("idx_refunds_status", "status"),
    )


class ExportJob(Base):
    """Export jobs table."""
    __tablename__ = "export_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    requested_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    export_type = Column(String(64), nullable=False)
    filters = Column(Text, nullable=True)  # JSON
    status = Column(
        Enum("pending", "processing", "completed", "failed", name="export_status"),
        default="pending", nullable=False
    )
    file_path = Column(String(512), nullable=True)
    row_count = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    requested_by_user = relationship("User", back_populates="export_jobs")

    __table_args__ = (
        Index("idx_export_jobs_user_created", "requested_by", "created_at"),
        Index("idx_export_jobs_status", "status"),
    )


class MiniAppSession(Base):
    """Mini App sessions table."""
    __tablename__ = "mini_app_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    session_data = Column(Text, nullable=True)  # JSON
    init_data_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="mini_app_sessions")

    __table_args__ = (
        UniqueConstraint("init_data_hash", name="uk_miniapp_init_hash"),
        Index("idx_miniapp_user_expires", "user_id", "expires_at"),
    )


class AuditLog(Base):
    """Audit logs table."""
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    action = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(64), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    actor = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_actor_created", "actor_id", "created_at"),
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_created_at", "created_at"),
    )


class RateLimit(Base):
    """Rate limits table (token bucket)."""
    __tablename__ = "rate_limits"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    key = Column(String(255), nullable=False)
    bucket = Column(String(64), nullable=False)
    tokens = Column(Float, nullable=False)
    last_refill = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("key", "bucket", name="uk_rate_limit_key_bucket"),
        Index("idx_rate_limit_last_refill", "last_refill"),
    )


class Setting(Base):
    """Settings table."""
    __tablename__ = "settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=False)  # JSON
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Role(Base):
    """Roles table."""
    __tablename__ = "roles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)

    # Relationships
    permissions = relationship("RolePermission", back_populates="role")
    user_roles = relationship("UserRole", back_populates="role")


class Permission(Base):
    """Permissions table."""
    __tablename__ = "permissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False)

    # Relationships
    role_permissions = relationship("RolePermission", back_populates="permission")
    user_permissions = relationship("UserPermission", back_populates="permission")


class RolePermission(Base):
    """Role permissions table."""
    __tablename__ = "role_permissions"

    role_id = Column(BigInteger, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(BigInteger, ForeignKey("permissions.id"), primary_key=True)

    # Relationships
    role = relationship("Role", back_populates="permissions")
    permission = relationship("Permission", back_populates="role_permissions")


class UserRole(Base):
    """User roles table."""
    __tablename__ = "user_roles"

    user_id = Column(BigInteger, ForeignKey("users.user_id"), primary_key=True)
    role_id = Column(BigInteger, ForeignKey("roles.id"), primary_key=True)

    # Relationships
    user = relationship("User", back_populates="user_roles")
    role = relationship("Role", back_populates="user_roles")


class UserPermission(Base):
    """User permissions table."""
    __tablename__ = "user_permissions"

    user_id = Column(BigInteger, ForeignKey("users.user_id"), primary_key=True)
    permission_id = Column(BigInteger, ForeignKey("permissions.id"), primary_key=True)
    granted_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    granted_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="user_permissions", foreign_keys=[user_id])
    permission = relationship("Permission", back_populates="user_permissions")
    granted_by_user = relationship("User", foreign_keys=[granted_by])


class SchemaMigration(Base):
    """Schema migrations table."""
    __tablename__ = "schema_migrations"

    name = Column(String(255), primary_key=True)
    applied_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Confirmation(Base):
    """Confirmations table."""
    __tablename__ = "confirmations"

    token = Column(String(64), primary_key=True)
    actor_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    action = Column(String(128), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)


class ResellerTier(Base):
    """Reseller tiers table."""
    __tablename__ = "reseller_tiers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    discount_percent = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReferralReward(Base):
    """Referral rewards table."""
    __tablename__ = "referral_rewards"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    referred_id = Column(BigInteger, ForeignKey("users.user_id"), unique=True, nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), nullable=False)
    status = Column(String(32), default="PAID", nullable=False)
    notified = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_referral_reward_referrer", "referrer_id"),
    )


class Ticket(Base):
    """Tickets table."""
    __tablename__ = "tickets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    subject = Column(String(255), nullable=False)
    status = Column(String(32), default="OPEN", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="tickets")
    messages = relationship("TicketMessage", back_populates="ticket")

    __table_args__ = (
        Index("idx_tickets_status", "status", "user_id"),
    )


class TicketMessage(Base):
    """Ticket messages table."""
    __tablename__ = "ticket_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id = Column(BigInteger, ForeignKey("tickets.id"), nullable=False)
    sender_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    is_staff = Column(Integer, default=0, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    ticket = relationship("Ticket", back_populates="messages")
    sender = relationship("User")


class Broadcast(Base):
    """Broadcasts table."""
    __tablename__ = "broadcasts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String(32), default="QUEUED", nullable=False)
    total = Column(Integer, default=0, nullable=False)
    sent = Column(Integer, default=0, nullable=False)
    failed = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)


class DiceRoll(Base):
    """Dice rolls table."""
    __tablename__ = "dice_rolls"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    value = Column(Integer, nullable=False)
    reward_minor = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="dice_rolls")


class ServiceRenewal(Base):
    """Service renewals table."""
    __tablename__ = "service_renewals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(10), nullable=False)
    idempotency_key = Column(String(255), unique=True, nullable=False)
    new_expiry_ms = Column(BigInteger, nullable=False)
    total_bytes = Column(BigInteger, nullable=False)
    status = Column(
        Enum("CHARGED", "COMPLETED", "REFUNDED", name="renewal_status"),
        default="CHARGED", nullable=False
    )
    source = Column(String(32), default="manual", nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    # Relationships
    order = relationship("Order", back_populates="service_renewals")
    user = relationship("User")

    __table_args__ = (
        Index("idx_renewals_order", "order_id"),
        Index("idx_renewals_status", "status", "created_at"),
    )


# Database engine and session management
def create_engine_from_url(database_url: str):
    """Create SQLAlchemy engine from database URL."""
    # Handle different dialects
    if database_url.startswith("postgresql"):
        engine = create_engine(
            database_url,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10}
        )
    elif database_url.startswith("mysql"):
        engine = create_engine(
            database_url,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10}
        )
    else:
        # SQLite
        engine = create_engine(
            database_url,
            poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 30}
        )

    # Enable foreign keys for SQLite
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def create_session_factory(engine):
    """Create session factory."""
    return sessionmaker(bind=engine, expire_on_commit=False)


# Export all models
__all__ = [
    "Base",
    "User",
    "Product",
    "Category",
    "ProductVariant",
    "InventoryItem",
    "Order",
    "OrderItem",
    "PendingRequest",
    "WalletTransaction",
    "Provider",
    "ProvisioningProfile",
    "ProvisionedClient",
    "Coupon",
    "CouponUse",
    "ReferralTier",
    "ReferralEarning",
    "GiftCode",
    "GiftCodeUse",
    "CryptoWallet",
    "CryptoInvoice",
    "NMConfigStock",
    "NMStockShelf",
    "PanelHealthLog",
    "ScheduledJob",
    "JobRun",
    "ProviderFailoverRule",
    "ProviderFailoverEvent",
    "ServiceRefund",
    "ExportJob",
    "MiniAppSession",
    "AuditLog",
    "RateLimit",
    "Setting",
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "UserPermission",
    "SchemaMigration",
    "Confirmation",
    "ResellerTier",
    "ReferralReward",
    "Ticket",
    "TicketMessage",
    "Broadcast",
    "DiceRoll",
    "ServiceRenewal",
    "create_engine_from_url",
    "create_session_factory",
]