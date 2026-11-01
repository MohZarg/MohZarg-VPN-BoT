"""
GhYiAb V2 — SQLite Connection & Schema
========================================

پورت مستقیم الگوی درست فعلی (`get_conn` با WAL + busy_timeout، `ensure_column`
برای مهاجرت بدون از دست رفتن داده). تفاوت این نسخه با فایل تک‌بخشی قبلی:
این ماژول فقط دیتابیس/اسکیما را مدیریت می‌کند؛ هیچ Business Logic اینجا نیست.

طراحی جدول‌ها Postgres-ready است: انواع داده و روابط طوری انتخاب شده‌اند که
پیاده‌سازی دوم (`repository/postgres/*` در آینده) بدون تغییر Interface در
`repository/interface.py` قابل افزودن باشد.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from security.permissions_catalog import CATALOG, OWNER_ONLY


DEFAULT_CURRENCY = "TOMAN"


@contextmanager
def get_conn(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def ensure_column(conn: sqlite3.Connection, table: str, col: str, coltype: str) -> None:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


def init_schema(db_path: str, owner_user_id: int) -> None:
    with get_conn(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            is_agent INTEGER NOT NULL DEFAULT 0,
            is_banned INTEGER NOT NULL DEFAULT 0,
            has_accepted_rules INTEGER NOT NULL DEFAULT 0,
            referred_by INTEGER NOT NULL DEFAULT 0,
            last_test_date TEXT,
            phone_number TEXT,
            phone_verified INTEGER NOT NULL DEFAULT 0,
            last_dice_at TEXT,
            blocked_by_bot INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )""")

        ensure_column(conn, "users", "lang", "TEXT NOT NULL DEFAULT 'fa'")

        # --- Wallet: یک ردیف به‌ازای هر (user_id, currency) — چندارزی از روز اول
        conn.execute("""CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER NOT NULL,
            currency TEXT NOT NULL,
            amount_minor INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, currency)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            currency TEXT NOT NULL,
            amount_minor INTEGER NOT NULL,
            balance_after_minor INTEGER NOT NULL,
            reason TEXT NOT NULL,
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wtx_user ON wallet_transactions(user_id)")

        conn.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'TOMAN',
            description TEXT,
            qr_file_id TEXT
        )""")

        # --- Catalog: Category (Phase 2.1 — safe structural addition, no
        # business values guessed; hierarchy optional via parent_id)
        conn.execute("""CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER REFERENCES categories(id),
            created_at TEXT NOT NULL,
            UNIQUE(name, parent_id)
        )""")

        # --- Catalog: ProductVariant (duration/traffic per architecture doc
        # §3 "ProductVariant — شامل مدت/حجم VPN"). Actual catalog values
        # (which durations/volumes exist) are NEED-INFO — this only reserves
        # the schema; no rows are guessed/seeded.
        conn.execute("""CREATE TABLE IF NOT EXISTS product_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id),
            name TEXT NOT NULL,
            duration_days INTEGER,
            traffic_gb REAL,
            price_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)"
        )

        # --- Providers registry (Bounded Context per Phase 0 architecture
        # §2). Reflects real connection status only — never a fake success.
        # config_ref stores ENV VAR NAMES only, never secret values.
        conn.execute("""CREATE TABLE IF NOT EXISTS providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'NOT_CONFIGURED',
            config_ref TEXT,
            updated_at TEXT NOT NULL
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'AVAILABLE',
            claimed_by INTEGER,
            claimed_at TEXT
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_inv_product_status "
            "ON inventory_items(product_id, status)"
        )

        conn.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            inventory_item_id INTEGER NOT NULL,
            price_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'COMPLETED',
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")

        # --- OrderItem (line-item breakdown of an order). Additive only —
        # `orders` keeps its existing columns for backward compatibility
        # with Phase 1 code/tests; each order created from now on also gets
        # a matching order_items row so future multi-item/coupon logic has
        # a real line-item model to build on, without a data migration of
        # historical orders.
        conn.execute("""CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            product_id INTEGER NOT NULL,
            variant_id INTEGER REFERENCES product_variants(id),
            inventory_item_id INTEGER,
            quantity INTEGER NOT NULL DEFAULT 1,
            price_minor INTEGER NOT NULL,
            currency TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)"
        )

        conn.execute("""CREATE TABLE IF NOT EXISTS pending_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            product_id INTEGER,
            amount_minor INTEGER,
            currency TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)")

        # --- RBAC: فعلاً فقط نقش OWNER پر می‌شود؛ اسکیما برای نقش‌های آینده آماده است
        conn.execute("""CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            PRIMARY KEY (role_id, permission_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS user_roles (
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, role_id)
        )""")

        # --- Phase 3: RBAC-ready — permission catalog واقعاً استفاده می‌شود
        # (نه فقط schema خالی). نام‌ها ساختاری/فنی‌اند و معادل قابلیت‌های
        # پنل ادمین موجود در V1 هستند — تصمیم تجاری‌ای دربارهٔ اینکه چه نقشی
        # به کدام Permission محدود شود گرفته نشده (طبق دستور «فعلاً فقط
        # OWNER فعال»)؛ فعلاً هم OWNER و هم ADMIN همان مجموعهٔ کامل را دارند
        # تا رفتار فعلی (V1) بدون تغییر عملیاتی حفظ شود.
        # --- Phase 3.x (Granular RBAC): کاتالوگ کامل module.action seed می‌شود.
        # OWNER همیشه کل کاتالوگ را دارد (sync در هر init). ADMIN هیچ
        # Permission سطح-نقش ندارد؛ فقط grantهای per-user (user_permissions).
        for _perm in CATALOG:
            conn.execute("INSERT OR IGNORE INTO permissions (name) VALUES (?)", (_perm,))
        for _role_name in ("OWNER", "ADMIN"):
            conn.execute("INSERT OR IGNORE INTO roles (name) VALUES (?)", (_role_name,))
        _owner_rid = conn.execute("SELECT id FROM roles WHERE name='OWNER'").fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) "
            "SELECT ?, id FROM permissions", (_owner_rid,),
        )

        conn.execute("""CREATE TABLE IF NOT EXISTS user_permissions (
            user_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            granted_by INTEGER,
            granted_at TEXT,
            PRIMARY KEY (user_id, permission_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )""")
        # مهاجرت یک‌باره: نصب‌های قبلی که ADMIN‌شان Permissionهای سطح-نقش داشت →
        # همان مجموعه (منهای OWNER_ONLY) به grant per-user هر ادمین موجود کپی
        # می‌شود تا هیچ ادمینی ناگهان قدرت از دست ندهد، سپس Permissionهای
        # سطح-نقش ADMIN پاک می‌شوند (رفع Privilege Escalation: قبلاً هر ADMIN
        # rbac.manage داشت).
        if conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name='rbac_granular_v1'"
        ).fetchone() is None:
            _admin_rid = conn.execute("SELECT id FROM roles WHERE name='ADMIN'").fetchone()[0]
            _owner_only_sql = ",".join("?" for _ in OWNER_ONLY)
            conn.execute(
                "INSERT OR IGNORE INTO user_permissions (user_id, permission_id, granted_by, granted_at) "
                "SELECT ur.user_id, rp.permission_id, NULL, datetime('now') FROM user_roles ur "
                "JOIN role_permissions rp ON rp.role_id = ur.role_id "
                "JOIN permissions p ON p.id = rp.permission_id "
                f"WHERE ur.role_id=? AND p.name NOT IN ({_owner_only_sql})",
                (_admin_rid, *sorted(OWNER_ONLY)),
            )
            conn.execute("DELETE FROM role_permissions WHERE role_id=?", (_admin_rid,))
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES ('rbac_granular_v1', datetime('now'))"
            )

        conn.execute("""CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER PRIMARY KEY,
            state_json TEXT,
            updated_at TEXT NOT NULL
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        # --- مهاجرت‌های احتمالی روی نصب‌های قبلی (idempotent)
        ensure_column(conn, "pending_requests", "resolved_at", "TEXT")
        ensure_column(conn, "products", "category_id", "INTEGER REFERENCES categories(id)")

        # --- Phase 5 (Payments v2, structural part): idempotency_key روی
        # pending_requests برای نصب‌های قبلی که این ستون را نداشتند. طبق همان
        # الگوی wallet_transactions/orders — ALTER TABLE نمی‌تواند مستقیم
        # UNIQUE اضافه کند، پس ستون معمولی + ایندکس یکتای جدا.
        ensure_column(conn, "pending_requests", "idempotency_key", "TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_requests_idem "
            "ON pending_requests(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )

        # ==================================================================
        # Admin Control Center + Phase 4-7 (همه Additive/Idempotent)
        # ==================================================================
        ensure_column(conn, "products", "is_active", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "users", "reseller_tier_id", "INTEGER")
        ensure_column(conn, "orders", "refunded_at", "TEXT")
        ensure_column(conn, "orders", "discount_minor", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "orders", "coupon_code", "TEXT")
        ensure_column(conn, "pending_requests", "resolution_note", "TEXT")
        ensure_column(conn, "pending_requests", "resolved_by", "INTEGER")
        ensure_column(conn, "pending_requests", "receipt_file_id", "TEXT")
        ensure_column(conn, "pending_requests", "receipt_unique_id", "TEXT")
        ensure_column(conn, "pending_requests", "coupon_code", "TEXT")
        ensure_column(conn, "pending_requests", "expected_price_minor", "INTEGER")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_receipt ON pending_requests(receipt_unique_id)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_requests(status, type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")

        conn.execute("""CREATE TABLE IF NOT EXISTS confirmations (
            token TEXT PRIMARY KEY,
            actor_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('PERCENT','FIXED')),
            value INTEGER NOT NULL CHECK (value > 0),
            currency TEXT,
            max_uses INTEGER,
            per_user_limit INTEGER,
            expires_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_at TEXT NOT NULL
        )""")
        ensure_column(conn, "coupons", "min_order_minor", "INTEGER")
        ensure_column(conn, "coupons", "product_ids", "TEXT")  # CSV از شناسهٔ محصول؛ NULL = همهٔ محصولات
        conn.execute("""CREATE TABLE IF NOT EXISTS coupon_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coupon_id INTEGER NOT NULL REFERENCES coupons(id),
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            discount_minor INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_redemp_coupon ON coupon_redemptions(coupon_id, user_id)")

        conn.execute("""CREATE TABLE IF NOT EXISTS reseller_tiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            discount_percent INTEGER NOT NULL CHECK (discount_percent BETWEEN 0 AND 100),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS referral_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            amount_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PAID',
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_refrew_referrer ON referral_rewards(referrer_id)")
        # پاداش‌های قدیمی «اعلام‌شده» فرض می‌شوند (DEFAULT 1)؛ فقط پاداش‌های جدیدِ مسیر سفارش با 0 ثبت می‌شوند.
        ensure_column(conn, "referral_rewards", "notified", "INTEGER NOT NULL DEFAULT 1")

        conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id),
            sender_id INTEGER NOT NULL,
            is_staff INTEGER NOT NULL DEFAULT 0,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, user_id)")

        conn.execute("""CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'QUEUED',
            total INTEGER NOT NULL DEFAULT 0,
            sent INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            finished_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS dice_rolls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            value INTEGER NOT NULL,
            reward_minor INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            interval_minutes INTEGER NOT NULL DEFAULT 60,
            last_run_at TEXT,
            last_status TEXT,
            last_detail TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS provisioning_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL UNIQUE REFERENCES products(id),
            provider_name TEXT NOT NULL,
            inbound_id INTEGER NOT NULL,
            duration_days INTEGER NOT NULL,
            traffic_gb REAL NOT NULL,
            limit_ip INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS provisioned_clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
            provider_name TEXT NOT NULL,
            inbound_id INTEGER NOT NULL,
            client_uuid TEXT NOT NULL,
            email TEXT NOT NULL,
            sub_id TEXT NOT NULL,
            expires_at_ms INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'PENDING',
            last_error TEXT,
            auto_renew INTEGER NOT NULL DEFAULT 0,
            auto_renew_consent_at TEXT,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_provclients_status ON provisioned_clients(status)")
        # --- V2 Final: ستون‌های چرخهٔ عمر سرویس (additive؛ بدون مهاجرت داده)
        ensure_column(conn, "provisioned_clients", "attempts", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "provisioned_clients", "notified_expiry_ms", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "provisioned_clients", "cached_used_bytes", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "provisioned_clients", "cached_total_bytes", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "provisioned_clients", "synced_at", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_provclients_expiry ON provisioned_clients(status, expires_at_ms)")
        # تمدید دو-فازی: CHARGED (پول کسر شد) → COMPLETED | REFUNDED. مقدار مطلق انقضا
        # ذخیره می‌شود تا Retry/Recovery بعد از ری‌استارت امن (Idempotent) باشد.
        conn.execute("""CREATE TABLE IF NOT EXISTS service_renewals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            user_id INTEGER NOT NULL,
            amount_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            new_expiry_ms INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'CHARGED',
            source TEXT NOT NULL DEFAULT 'manual',
            error TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_renewals_order ON service_renewals(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_renewals_status ON service_renewals(status, created_at)")

        # --- AuditLog append-only: هیچ UPDATE/DELETE ای روی audit_logs مجاز نیست
        conn.execute("""CREATE TRIGGER IF NOT EXISTS audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_id)")

        # --- Seed: providers registry reflects the real, already-audited
        # state — xui_vpn is NOT_CONFIGURED until real credentials arrive
        # (TODO #2). config_ref lists ENV VAR NAMES only, never values.
        conn.execute(
            "INSERT OR IGNORE INTO providers (name, type, status, config_ref, updated_at) "
            "VALUES ('xui_vpn', 'VPN', 'NOT_CONFIGURED', "
            "'XUI_BASE_URL,XUI_API_TOKEN,XUI_TIMEOUT,XUI_VERIFY_TLS', datetime('now'))"
        )
        # مهاجرت: نام قدیمی متغیرهای env در ردیف seed قبلی
        conn.execute(
            "UPDATE providers SET config_ref='XUI_BASE_URL,XUI_API_TOKEN,XUI_TIMEOUT,XUI_VERIFY_TLS' "
            "WHERE name='xui_vpn' AND config_ref LIKE '%XUI_PANEL_URL%'"
        )

        # --- Seed: نقش OWNER + تخصیص آن به owner_user_id (طبق دستور Owner:
        # فعلاً فقط OWNER فعال است، بقیهٔ نقش‌ها فقط در schema رزرو شده‌اند)
        conn.execute("INSERT OR IGNORE INTO roles (name) VALUES ('OWNER')")
        owner_role_id = conn.execute(
            "SELECT id FROM roles WHERE name = 'OWNER'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO users (user_id, created_at) VALUES (?, datetime('now')) "
            "ON CONFLICT(user_id) DO NOTHING",
            (owner_user_id,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (owner_user_id, owner_role_id),
        )

        conn.commit()
