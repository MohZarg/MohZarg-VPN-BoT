"""
GhYiAb V2 — Faoxima Features Migration
=======================================

Migration script to add database tables for Faoxima features:
- Multi-panel VPN support
- National Net Stock/Warehouse
- Crypto Payments
- Referral Tiers (N/N2/F)
- Scheduled Jobs/Cron
- Pro-rata Refund Calculation
- Emergency Panel Fallback
"""

from __future__ import annotations

from repository.sqlite.connection import get_conn


def run_migration(db_path: str) -> None:
    """Run the Faoxima features migration."""
    with get_conn(db_path) as conn:
        # ==================================================================
        # 1. Extend providers table for multi-panel support
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id INTEGER NOT NULL REFERENCES providers(id),
                config_key TEXT NOT NULL,
                config_value TEXT,
                is_secret INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(provider_id, config_key)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_configs_provider ON provider_configs(provider_id)")

        # Add panel_type and config_json to providers
        from repository.sqlite.connection import ensure_column
        ensure_column(conn, "providers", "panel_type", "TEXT DEFAULT 'xui'")
        ensure_column(conn, "providers", "config_json", "TEXT")  # JSON config
        ensure_column(conn, "providers", "is_primary", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "providers", "is_fallback", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "providers", "priority", "INTEGER NOT NULL DEFAULT 100")
        ensure_column(conn, "providers", "last_health_check", "TEXT")
        ensure_column(conn, "providers", "health_status", "TEXT DEFAULT 'UNKNOWN'")

        # ==================================================================
        # 2. National Net Stock/Warehouse System
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nm_config_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id INTEGER NOT NULL REFERENCES providers(id),
                inbound_id INTEGER,
                protocol TEXT,
                remark TEXT,
                config_str TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nm_stock_provider ON nm_config_stock(provider_id, used)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS nm_stock_shelves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shelf_name TEXT NOT NULL UNIQUE,
                shelf_type TEXT NOT NULL,
                configs TEXT,  -- JSON array of config IDs
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ==================================================================
        # 3. Crypto Payment System
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crypto_wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                currency TEXT NOT NULL UNIQUE,
                wallet_address TEXT NOT NULL,
                wallet_memo TEXT,  -- For TON/USDT_TON (memo/tag)
                network TEXT NOT NULL,  -- 'TON', 'TRON'
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS crypto_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                wallet_to TEXT NOT NULL,
                tx_hash TEXT,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'failed', 'expired')),
                memo TEXT,
                expected_amount REAL,
                tolerance_percent REAL DEFAULT 1.0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                verified_at TEXT,
                verified_by TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crypto_invoices_user ON crypto_invoices(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crypto_invoices_status ON crypto_invoices(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crypto_invoices_hash ON crypto_invoices(tx_hash)")

        # ==================================================================
        # 4. Referral Tier System (N/N2/F)
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_tiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tier_name TEXT NOT NULL UNIQUE CHECK (tier_name IN ('N', 'N2', 'F')),
                level INTEGER NOT NULL UNIQUE CHECK (level IN (1, 2, 3)),
                commission_rate INTEGER NOT NULL CHECK (commission_rate BETWEEN 0 AND 10000), -- basis points (0-100%)
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Seed default referral tiers
        conn.execute("""
            INSERT OR IGNORE INTO referral_tiers (tier_name, level, commission_rate, description)
            VALUES
                ('N', 1, 1000, 'Direct referral - 10%'),
                ('N2', 2, 500, 'Indirect referral (referral of referral) - 5%'),
                ('F', 3, 200, 'Further referral - 2%')
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                tier_id INTEGER NOT NULL REFERENCES referral_tiers(id),
                order_id INTEGER REFERENCES orders(id),
                commission_basis_minor INTEGER NOT NULL,  -- Amount commission calculated on
                commission_amount_minor INTEGER NOT NULL,  -- Actual commission earned
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'cancelled')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                paid_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_earnings_referrer ON referral_earnings(referrer_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_earnings_referred ON referral_earnings(referred_id)")

        # ==================================================================
        # 5. Scheduled Jobs/Cron
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                cron_expression TEXT,  -- 5-field cron
                fire_at TEXT,  -- ISO timestamp for one-time jobs
                handler TEXT NOT NULL,  -- Python function path
                payload TEXT,  -- JSON
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                next_run_at TEXT,
                last_status TEXT,
                last_detail TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_next_run ON scheduled_jobs(next_run_at, enabled)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES scheduled_jobs(id),
                status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                detail TEXT,
                error TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs(job_id, started_at)")

        # ==================================================================
        # 6. Pro-rata Refund Calculation
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_refunds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provisioned_client_id INTEGER NOT NULL REFERENCES provisioned_clients(id),
                user_id INTEGER NOT NULL,
                order_id INTEGER REFERENCES orders(id),
                original_amount_minor INTEGER NOT NULL,
                refund_amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                reason TEXT NOT NULL,
                calculation_method TEXT NOT NULL DEFAULT 'pro_rata',  -- 'pro_rata', 'full', 'partial'
                days_used INTEGER,
                days_remaining INTEGER,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'processed')),
                requested_by INTEGER,
                approved_by INTEGER,
                processed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_refunds_user ON service_refunds(user_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_refunds_client ON service_refunds(provisioned_client_id)")

        # ==================================================================
        # 7. Emergency Panel Fallback
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_failover_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                primary_provider_id INTEGER NOT NULL REFERENCES providers(id),
                fallback_provider_id INTEGER NOT NULL REFERENCES providers(id),
                trigger_condition TEXT NOT NULL DEFAULT 'health_check_failed',  -- 'health_check_failed', 'provisioning_failed', 'manual'
                max_retries INTEGER NOT NULL DEFAULT 3,
                cooldown_minutes INTEGER NOT NULL DEFAULT 5,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_failover_primary ON provider_failover_rules(primary_provider_id, is_active)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_failover_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL REFERENCES provider_failover_rules(id),
                primary_provider_id INTEGER NOT NULL,
                fallback_provider_id INTEGER NOT NULL,
                trigger_reason TEXT,
                status TEXT NOT NULL DEFAULT 'triggered' CHECK (status IN ('triggered', 'switched', 'recovered', 'failed')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                recovered_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_failover_events_rule ON provider_failover_events(rule_id, created_at)")

        # ==================================================================
        # 8. Excel Export Tracking
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requested_by INTEGER NOT NULL,
                export_type TEXT NOT NULL CHECK (export_type IN ('users', 'orders', 'payments', 'wallet_transactions', 'referral_earnings')),
                filters TEXT,  -- JSON
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
                file_path TEXT,
                row_count INTEGER,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exports_user ON export_jobs(requested_by, created_at)")

        # ==================================================================
        # 9. Phone Verification
        # ==================================================================
        ensure_column(conn, "users", "phone_verified_at", "TEXT")
        ensure_column(conn, "users", "phone_verification_method", "TEXT")  -- 'contact_sharing', 'manual', 'sms'

        # ==================================================================
        # 10. Gift Codes (separate from coupons)
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gift_codes_active ON gift_codes(is_active, expires_at)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_code_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gift_code_id INTEGER NOT NULL REFERENCES gift_codes(id),
                user_id INTEGER NOT NULL,
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gift_redemptions_code ON gift_code_redemptions(gift_code_id, user_id)")

        # ==================================================================
        # 11. Mini App Sessions (Telegram Web App)
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mini_app_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                init_data TEXT NOT NULL,  -- Telegram Web App init data
                session_data TEXT,  -- JSON
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_miniapp_user ON mini_app_sessions(user_id, expires_at)")

        # ==================================================================
        # 12. Panel Health Monitoring
        # ==================================================================
        conn.execute("""
            CREATE TABLE IF NOT EXISTS panel_health_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id INTEGER NOT NULL REFERENCES providers(id),
                status TEXT NOT NULL CHECK (status IN ('OK', 'DEGRADED', 'DOWN', 'NOT_CONFIGURED')),
                latency_ms INTEGER,
                error_message TEXT,
                checked_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_health_logs_provider ON panel_health_logs(provider_id, checked_at)")

        conn.commit()
        print("Faoxima features migration completed successfully!")


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "ghyiab.db"
    run_migration(db_path)