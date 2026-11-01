-- GhYiAb V2 — MySQL Initialization Script for Railway
-- This script creates the database schema compatible with MySQL 8.0

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS `ghyiab` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `ghyiab`;

-- Users table
CREATE TABLE IF NOT EXISTS `users` (
    `user_id` BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    `username` VARCHAR(255) DEFAULT NULL,
    `first_name` VARCHAR(255) NOT NULL,
    `last_name` VARCHAR(255) DEFAULT NULL,
    `language_code` VARCHAR(10) DEFAULT 'fa',
    `is_agent` BOOLEAN NOT NULL DEFAULT FALSE,
    `is_banned` BOOLEAN NOT NULL DEFAULT FALSE,
    `ban_reason` TEXT DEFAULT NULL,
    `referred_by` BIGINT UNSIGNED DEFAULT NULL,
    `phone_number` VARCHAR(32) DEFAULT NULL,
    `phone_verified` BOOLEAN NOT NULL DEFAULT FALSE,
    `phone_verified_at` DATETIME DEFAULT NULL,
    `wallet_balance_irt_minor` BIGINT NOT NULL DEFAULT 0,
    `wallet_balance_usdt_minor` BIGINT NOT NULL DEFAULT 0,
    `referral_code` VARCHAR(32) NOT NULL UNIQUE,
    `referral_earnings_minor` BIGINT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_referred_by` (`referred_by`),
    INDEX `idx_referral_code` (`referral_code`),
    INDEX `idx_phone_number` (`phone_number`),
    INDEX `idx_is_agent` (`is_agent`),
    INDEX `idx_is_banned` (`is_banned`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Products/Services table
CREATE TABLE IF NOT EXISTS `products` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(255) NOT NULL,
    `description` TEXT DEFAULT NULL,
    `price_minor` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(10) NOT NULL DEFAULT 'IRT',
    `duration_days` INT UNSIGNED NOT NULL,
    `traffic_gb` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `inbound_id` INT UNSIGNED NOT NULL,
    `provider_name` VARCHAR(64) NOT NULL DEFAULT 'xui',
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `features` JSON DEFAULT NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_is_active` (`is_active`),
    INDEX `idx_provider_inbound` (`provider_name`, `inbound_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Orders table
CREATE TABLE IF NOT EXISTS `orders` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `product_id` BIGINT UNSIGNED NOT NULL,
    `price_minor` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(10) NOT NULL DEFAULT 'IRT',
    `status` ENUM('pending', 'paid', 'provisioning', 'active', 'expired', 'cancelled', 'refunded') NOT NULL DEFAULT 'pending',
    `discount_minor` BIGINT NOT NULL DEFAULT 0,
    `coupon_code` VARCHAR(64) DEFAULT NULL,
    `payment_gateway` VARCHAR(64) DEFAULT NULL,
    `payment_authority` VARCHAR(255) DEFAULT NULL,
    `payment_ref_id` VARCHAR(255) DEFAULT NULL,
    `client_uuid` VARCHAR(255) DEFAULT NULL,
    `subscription_url` TEXT DEFAULT NULL,
    `expires_at` DATETIME DEFAULT NULL,
    `provisioned_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON DELETE RESTRICT,
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_status` (`status`),
    INDEX `idx_payment_authority` (`payment_authority`),
    INDEX `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Pending Requests (Payments)
CREATE TABLE IF NOT EXISTS `pending_requests` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `type` ENUM('charge', 'buy', 'agency') NOT NULL,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `product_id` BIGINT UNSIGNED DEFAULT NULL,
    `amount_minor` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(10) NOT NULL DEFAULT 'IRT',
    `status` ENUM('pending', 'approved', 'rejected', 'cancelled') NOT NULL DEFAULT 'pending',
    `receipt_unique_id` VARCHAR(255) DEFAULT NULL,
    `receipt_media` JSON DEFAULT NULL,
    `coupon_code` VARCHAR(64) DEFAULT NULL,
    `resolved_by` BIGINT UNSIGNED DEFAULT NULL,
    `resolved_at` DATETIME DEFAULT NULL,
    `reject_reason` TEXT DEFAULT NULL,
    `idempotency_key` VARCHAR(255) DEFAULT NULL UNIQUE,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON DELETE SET NULL,
    FOREIGN KEY (`resolved_by`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,
    INDEX `idx_user_status` (`user_id`, `status`),
    INDEX `idx_receipt_unique` (`receipt_unique_id`),
    INDEX `idx_idempotency` (`idempotency_key`),
    INDEX `idx_type_status` (`type`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Wallet Transactions
CREATE TABLE IF NOT EXISTS `wallet_transactions` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(10) NOT NULL DEFAULT 'IRT',
    `amount_minor` BIGINT NOT NULL,
    `balance_after_minor` BIGINT NOT NULL,
    `reason` VARCHAR(255) NOT NULL,
    `idempotency_key` VARCHAR(255) NOT NULL UNIQUE,
    `metadata` JSON DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    INDEX `idx_user_currency` (`user_id`, `currency`),
    INDEX `idx_idempotency` (`idempotency_key`),
    INDEX `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Provisioned Clients
CREATE TABLE IF NOT EXISTS `provisioned_clients` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `order_id` BIGINT UNSIGNED NOT NULL,
    `provider_name` VARCHAR(64) NOT NULL,
    `inbound_id` INT UNSIGNED NOT NULL,
    `client_uuid` VARCHAR(255) NOT NULL,
    `email` VARCHAR(255) NOT NULL,
    `sub_id` VARCHAR(255) DEFAULT NULL,
    `expires_at_ms` BIGINT UNSIGNED DEFAULT NULL,
    `status` ENUM('ACTIVE', 'EXPIRED', 'DISABLED', 'FAILED', 'REFUNDED') NOT NULL DEFAULT 'ACTIVE',
    `last_synced_at` DATETIME DEFAULT NULL,
    `sync_data` JSON DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `uk_provider_email` (`provider_name`, `email`),
    INDEX `idx_order_id` (`order_id`),
    INDEX `idx_email` (`email`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Providers table
CREATE TABLE IF NOT EXISTS `providers` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(64) NOT NULL UNIQUE,
    `display_name` VARCHAR(128) NOT NULL,
    `type` VARCHAR(64) NOT NULL,
    `config` JSON NOT NULL,
    `status` ENUM('OK', 'FAILED', 'STANDBY', 'FAILOVER_ACTIVE', 'NOT_CONFIGURED') NOT NULL DEFAULT 'NOT_CONFIGURED',
    `priority` INT NOT NULL DEFAULT 100,
    `is_default` BOOLEAN NOT NULL DEFAULT FALSE,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_status` (`status`),
    INDEX `idx_priority` (`priority`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Provisioning Profiles
CREATE TABLE IF NOT EXISTS `provisioning_profiles` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `product_id` BIGINT UNSIGNED NOT NULL,
    `provider_id` BIGINT UNSIGNED NOT NULL,
    `inbound_id` INT UNSIGNED NOT NULL,
    `protocol` VARCHAR(32) DEFAULT NULL,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `uk_product_provider` (`product_id`, `provider_id`),
    INDEX `idx_provider_inbound` (`provider_id`, `inbound_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Coupons
CREATE TABLE IF NOT EXISTS `coupons` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `code` VARCHAR(64) NOT NULL UNIQUE,
    `type` ENUM('percent', 'fixed') NOT NULL,
    `value` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(10) NOT NULL DEFAULT 'IRT',
    `max_uses` INT UNSIGNED DEFAULT NULL,
    `used_count` INT UNSIGNED NOT NULL DEFAULT 0,
    `valid_from` DATETIME DEFAULT NULL,
    `valid_until` DATETIME DEFAULT NULL,
    `min_order_minor` BIGINT UNSIGNED DEFAULT NULL,
    `max_discount_minor` BIGINT UNSIGNED DEFAULT NULL,
    `applicable_products` JSON DEFAULT NULL,
    `applicable_categories` JSON DEFAULT NULL,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `created_by` BIGINT UNSIGNED DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`created_by`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,
    INDEX `idx_code` (`code`),
    INDEX `idx_active_dates` (`is_active`, `valid_from`, `valid_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Coupon Uses
CREATE TABLE IF NOT EXISTS `coupon_uses` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `coupon_id` BIGINT UNSIGNED NOT NULL,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `order_id` BIGINT UNSIGNED NOT NULL,
    `discount_minor` BIGINT UNSIGNED NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`coupon_id`) REFERENCES `coupons`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `uk_coupon_user_order` (`coupon_id`, `user_id`, `order_id`),
    INDEX `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Referral Tiers
CREATE TABLE IF NOT EXISTS `referral_tiers` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tier_name` ENUM('N', 'N2', 'F') NOT NULL,
    `level` TINYINT UNSIGNED NOT NULL,
    `commission_percent` DECIMAL(5,2) NOT NULL,
    `max_depth` TINYINT UNSIGNED DEFAULT NULL,
    `description` TEXT DEFAULT NULL,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_tier_name` (`tier_name`),
    UNIQUE KEY `uk_level` (`level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Referral Earnings
CREATE TABLE IF NOT EXISTS `referral_earnings` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `referrer_id` BIGINT UNSIGNED NOT NULL,
    `referred_id` BIGINT UNSIGNED NOT NULL,
    `tier_id` BIGINT UNSIGNED NOT NULL,
    `order_id` BIGINT UNSIGNED NOT NULL,
    `commission_basis_minor` BIGINT UNSIGNED NOT NULL,
    `commission_amount_minor` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(10) NOT NULL DEFAULT 'IRT',
    `status` ENUM('pending', 'approved', 'paid', 'cancelled') NOT NULL DEFAULT 'pending',
    `paid_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`referrer_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`referred_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`tier_id`) REFERENCES `referral_tiers`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON DELETE CASCADE,
    INDEX `idx_referrer_status` (`referrer_id`, `status`),
    INDEX `idx_referred_id` (`referred_id`),
    INDEX `idx_order_id` (`order_id`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Gift Codes
CREATE TABLE IF NOT EXISTS `gift_codes` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `code` VARCHAR(64) NOT NULL UNIQUE,
    `product_id` BIGINT UNSIGNED DEFAULT NULL,
    `amount_minor` BIGINT UNSIGNED DEFAULT NULL,
    `currency` VARCHAR(10) DEFAULT 'IRT',
    `duration_days` INT UNSIGNED DEFAULT NULL,
    `traffic_gb` DECIMAL(10,2) DEFAULT NULL,
    `max_uses` INT UNSIGNED NOT NULL DEFAULT 1,
    `used_count` INT UNSIGNED NOT NULL DEFAULT 0,
    `valid_from` DATETIME DEFAULT NULL,
    `valid_until` DATETIME DEFAULT NULL,
    `created_by` BIGINT UNSIGNED DEFAULT NULL,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON DELETE SET NULL,
    FOREIGN KEY (`created_by`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,
    INDEX `idx_code` (`code`),
    INDEX `idx_active` (`is_active`, `valid_from`, `valid_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Gift Code Uses
CREATE TABLE IF NOT EXISTS `gift_code_uses` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `gift_code_id` BIGINT UNSIGNED NOT NULL,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `order_id` BIGINT UNSIGNED DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`gift_code_id`) REFERENCES `gift_codes`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON DELETE SET NULL,
    UNIQUE KEY `uk_gift_code_user` (`gift_code_id`, `user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Crypto Wallets
CREATE TABLE IF NOT EXISTS `crypto_wallets` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `currency` VARCHAR(20) NOT NULL,
    `network` VARCHAR(32) DEFAULT NULL,
    `address` VARCHAR(255) NOT NULL,
    `tag` VARCHAR(255) DEFAULT NULL,
    `label` VARCHAR(128) DEFAULT NULL,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `is_default` BOOLEAN NOT NULL DEFAULT FALSE,
    `min_deposit_minor` BIGINT UNSIGNED DEFAULT NULL,
    `max_deposit_minor` BIGINT UNSIGNED DEFAULT NULL,
    `confirmations_required` INT UNSIGNED NOT NULL DEFAULT 1,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_currency_network_address` (`currency`, `network`, `address`),
    INDEX `idx_currency_active` (`currency`, `is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Crypto Invoices
CREATE TABLE IF NOT EXISTS `crypto_invoices` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `wallet_id` BIGINT UNSIGNED NOT NULL,
    `amount_minor` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(20) NOT NULL,
    `wallet_to` VARCHAR(255) NOT NULL,
    `tx_hash` VARCHAR(255) DEFAULT NULL UNIQUE,
    `status` ENUM('pending', 'verifying', 'verified', 'failed', 'expired') NOT NULL DEFAULT 'pending',
    `memo` VARCHAR(255) DEFAULT NULL,
    `expected_amount` BIGINT UNSIGNED DEFAULT NULL,
    `confirmed_amount` BIGINT UNSIGNED DEFAULT NULL,
    `confirmations` INT UNSIGNED NOT NULL DEFAULT 0,
    `required_confirmations` INT UNSIGNED NOT NULL DEFAULT 1,
    `verified_at` DATETIME DEFAULT NULL,
    `expires_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`wallet_id`) REFERENCES `crypto_wallets`(`id`) ON DELETE RESTRICT,
    INDEX `idx_user_status` (`user_id`, `status`),
    INDEX `idx_tx_hash` (`tx_hash`),
    INDEX `idx_status_expires` (`status`, `expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- National Net Stock Configs
CREATE TABLE IF NOT EXISTS `nm_config_stock` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `provider_id` BIGINT UNSIGNED NOT NULL,
    `inbound_id` INT UNSIGNED NOT NULL,
    `protocol` VARCHAR(32) NOT NULL,
    `remark` VARCHAR(255) DEFAULT NULL,
    `config_string` TEXT NOT NULL,
    `qr_code` TEXT DEFAULT NULL,
    `used` BOOLEAN NOT NULL DEFAULT FALSE,
    `used_by_order_id` BIGINT UNSIGNED DEFAULT NULL,
    `used_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`used_by_order_id`) REFERENCES `orders`(`id`) ON DELETE SET NULL,
    INDEX `idx_provider_inbound` (`provider_id`, `inbound_id`),
    INDEX `idx_protocol_used` (`protocol`, `used`),
    INDEX `idx_used_order` (`used_by_order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- National Net Stock Shelves
CREATE TABLE IF NOT EXISTS `nm_stock_shelves` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(128) NOT NULL,
    `provider_id` BIGINT UNSIGNED NOT NULL,
    `inbound_id` INT UNSIGNED NOT NULL,
    `protocol` VARCHAR(32) NOT NULL,
    `auto_refill` BOOLEAN NOT NULL DEFAULT FALSE,
    `min_stock` INT UNSIGNED NOT NULL DEFAULT 5,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `uk_name_provider` (`name`, `provider_id`),
    INDEX `idx_provider_inbound` (`provider_id`, `inbound_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Panel Health Logs
CREATE TABLE IF NOT EXISTS `panel_health_logs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `provider_id` BIGINT UNSIGNED NOT NULL,
    `status` ENUM('OK', 'BLOCKED', 'ERROR', 'NOT_CONFIGURED', 'FAILED') NOT NULL,
    `latency_ms` INT UNSIGNED DEFAULT NULL,
    `error_message` TEXT DEFAULT NULL,
    `checked_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    INDEX `idx_provider_checked` (`provider_id`, `checked_at`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Scheduled Jobs
CREATE TABLE IF NOT EXISTS `scheduled_jobs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(128) NOT NULL UNIQUE,
    `cron_expression` VARCHAR(128) DEFAULT NULL,
    `fire_at` DATETIME DEFAULT NULL,
    `handler` VARCHAR(255) NOT NULL,
    `payload` JSON DEFAULT NULL,
    `enabled` BOOLEAN NOT NULL DEFAULT TRUE,
    `last_run_at` DATETIME DEFAULT NULL,
    `next_run_at` DATETIME DEFAULT NULL,
    `last_status` ENUM('succeeded', 'failed', 'running') DEFAULT NULL,
    `last_detail` TEXT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_enabled_cron` (`enabled`, `cron_expression`),
    INDEX `idx_fire_at` (`fire_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Job Runs
CREATE TABLE IF NOT EXISTS `job_runs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `job_id` BIGINT UNSIGNED NOT NULL,
    `status` ENUM('running', 'succeeded', 'failed') NOT NULL,
    `started_at` DATETIME NOT NULL,
    `finished_at` DATETIME DEFAULT NULL,
    `detail` TEXT DEFAULT NULL,
    `error` TEXT DEFAULT NULL,
    FOREIGN KEY (`job_id`) REFERENCES `scheduled_jobs`(`id`) ON DELETE CASCADE,
    INDEX `idx_job_started` (`job_id`, `started_at`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Provider Failover Rules
CREATE TABLE IF NOT EXISTS `provider_failover_rules` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `primary_provider_id` BIGINT UNSIGNED NOT NULL,
    `fallback_provider_id` BIGINT UNSIGNED NOT NULL,
    `trigger_condition` ENUM('health_check_failed', 'provisioning_failed') NOT NULL DEFAULT 'health_check_failed',
    `max_retries` INT UNSIGNED NOT NULL DEFAULT 3,
    `cooldown_minutes` INT UNSIGNED NOT NULL DEFAULT 5,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`primary_provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`fallback_provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `uk_primary_fallback` (`primary_provider_id`, `fallback_provider_id`),
    INDEX `idx_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Provider Failover Events
CREATE TABLE IF NOT EXISTS `provider_failover_events` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `rule_id` BIGINT UNSIGNED NOT NULL,
    `primary_provider_id` BIGINT UNSIGNED NOT NULL,
    `fallback_provider_id` BIGINT UNSIGNED NOT NULL,
    `trigger_reason` TEXT DEFAULT NULL,
    `status` ENUM('triggered', 'switched', 'recovered') NOT NULL DEFAULT 'triggered',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `recovered_at` DATETIME DEFAULT NULL,
    FOREIGN KEY (`rule_id`) REFERENCES `provider_failover_rules`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`primary_provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`fallback_provider_id`) REFERENCES `providers`(`id`) ON DELETE CASCADE,
    INDEX `idx_rule_created` (`rule_id`, `created_at`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Service Refunds
CREATE TABLE IF NOT EXISTS `service_refunds` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `provisioned_client_id` BIGINT UNSIGNED NOT NULL,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `order_id` BIGINT UNSIGNED DEFAULT NULL,
    `original_amount_minor` BIGINT UNSIGNED NOT NULL,
    `refund_amount_minor` BIGINT UNSIGNED NOT NULL,
    `currency` VARCHAR(10) NOT NULL DEFAULT 'IRT',
    `reason` TEXT NOT NULL,
    `calculation_method` ENUM('pro_rata_time', 'pro_rata_traffic', 'pro_rata_min', 'full', 'partial') NOT NULL,
    `days_used` INT UNSIGNED DEFAULT NULL,
    `days_remaining` INT UNSIGNED DEFAULT NULL,
    `status` ENUM('pending', 'approved', 'rejected', 'processed') NOT NULL DEFAULT 'pending',
    `requested_by` BIGINT UNSIGNED DEFAULT NULL,
    `approved_by` BIGINT UNSIGNED DEFAULT NULL,
    `processed_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`provisioned_client_id`) REFERENCES `provisioned_clients`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON DELETE SET NULL,
    FOREIGN KEY (`requested_by`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,
    FOREIGN KEY (`approved_by`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,
    INDEX `idx_user_status` (`user_id`, `status`),
    INDEX `idx_client_id` (`provisioned_client_id`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Export Jobs
CREATE TABLE IF NOT EXISTS `export_jobs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `requested_by` BIGINT UNSIGNED NOT NULL,
    `export_type` VARCHAR(64) NOT NULL,
    `filters` JSON DEFAULT NULL,
    `status` ENUM('pending', 'processing', 'completed', 'failed') NOT NULL DEFAULT 'pending',
    `file_path` VARCHAR(512) DEFAULT NULL,
    `row_count` INT UNSIGNED DEFAULT NULL,
    `error` TEXT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `completed_at` DATETIME DEFAULT NULL,
    FOREIGN KEY (`requested_by`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    INDEX `idx_user_created` (`requested_by`, `created_at`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mini App Sessions
CREATE TABLE IF NOT EXISTS `mini_app_sessions` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `session_data` JSON DEFAULT NULL,
    `init_data_hash` VARCHAR(64) NOT NULL,
    `expires_at` DATETIME NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    UNIQUE KEY `uk_init_data_hash` (`init_data_hash`),
    INDEX `idx_user_expires` (`user_id`, `expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Audit Logs
CREATE TABLE IF NOT EXISTS `audit_logs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `actor_id` BIGINT UNSIGNED DEFAULT NULL,
    `action` VARCHAR(128) NOT NULL,
    `entity_type` VARCHAR(64) NOT NULL,
    `entity_id` VARCHAR(64) NOT NULL,
    `before_json` JSON DEFAULT NULL,
    `after_json` JSON DEFAULT NULL,
    `ip_address` VARCHAR(45) DEFAULT NULL,
    `user_agent` TEXT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`actor_id`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,
    INDEX `idx_actor_created` (`actor_id`, `created_at`),
    INDEX `idx_entity` (`entity_type`, `entity_id`),
    INDEX `idx_action` (`action`),
    INDEX `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rate Limits
CREATE TABLE IF NOT EXISTS `rate_limits` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `key` VARCHAR(255) NOT NULL,
    `bucket` VARCHAR(64) NOT NULL,
    `tokens` DECIMAL(10,2) NOT NULL,
    `last_refill` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_key_bucket` (`key`, `bucket`),
    INDEX `idx_last_refill` (`last_refill`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Settings
CREATE TABLE IF NOT EXISTS `settings` (
    `key` VARCHAR(128) NOT NULL PRIMARY KEY,
    `value` JSON NOT NULL,
    `description` TEXT DEFAULT NULL,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default referral tiers
INSERT IGNORE INTO `referral_tiers` (`tier_name`, `level`, `commission_percent`, `max_depth`, `description`) VALUES
('N', 1, 10.00, 1, 'مستوی ۱ - رفرال مستقیم (۱۰٪)'),
('N2', 2, 5.00, 2, 'مستوی ۲ - رفرال زیرمجموعه (۵٪)'),
('F', 3, 2.00, 3, 'مستوی ۳ - رفرال عمیق (۲٪)');

-- Insert default scheduled jobs
INSERT IGNORE INTO `scheduled_jobs` (`name`, `cron_expression`, `handler`, `payload`, `enabled`) VALUES
('panel_health_check', '*/5 * * * *', 'panel_health_check', '{}', TRUE),
('auto_renew_services', '0 2 * * *', 'auto_renew_services', '{}', TRUE),
('process_pending_payments', '*/10 * * * *', 'process_pending_payments', '{}', TRUE),
('sync_provisioned_clients', '*/15 * * * *', 'sync_provisioned_clients', '{}', TRUE),
('check_crypto_invoices', '*/5 * * * *', 'check_crypto_invoices', '{}', TRUE),
('send_expiry_notifications', '0 10 * * *', 'send_expiry_notifications', '{}', TRUE),
('backup_database', '0 3 * * *', 'backup_database', '{"backup_dir": "/app/backups", "retention_days": 30}', FALSE),
('cleanup_old_logs', '0 4 * * 0', 'cleanup_old_logs', '{"days_to_keep": 30}', TRUE);

SET FOREIGN_KEY_CHECKS = 1;