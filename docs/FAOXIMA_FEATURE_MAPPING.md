# Faoxima → GhYiAb V2 Feature Mapping

Comprehensive feature-by-feature comparison and implementation roadmap.

---

## 1. Multi-Panel VPN Support

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| 3x-ui / X-UI | ✅ | ✅ | Done | — |
| Marzban | ✅ | ❌ | Missing | **HIGH** |
| WGDashboard | ✅ | ❌ | Missing | **HIGH** |
| Guard | ✅ | ❌ | Missing | **MEDIUM** |
| Mikrotik | ✅ | ❌ | Missing | **MEDIUM** |
| IBSng | ✅ | ❌ | Missing | **LOW** |
| Hiddify | ✅ | ❌ | Missing | **HIGH** |
| Marzneshin | ✅ | ❌ | Missing | **MEDIUM** |
| Alireza Single | ✅ | ❌ | Missing | **LOW** |
| S-UI | ✅ | ❌ | Missing | **MEDIUM** |
| Manualsale | ✅ | ❌ | Missing | **LOW** |

**Faoxima Panel Methods (per panel):**
- `createUser` - Create VPN user
- `DataUser` - Get user info
- `Revoke_sub` - Revoke subscription
- `RemoveUser` - Delete user
- `Modifyuser` - Update user
- `Change_status` - Enable/disable
- `ResetUserDataUsage` - Reset traffic
- `extend` - Extend expiry/volume
- `extra_volume` - Add volume
- `extra_time` - Add time

**GhYiAb V2 VPNProvider Interface** (already defined in `providers/vpn/base.py`) covers all these operations. Need to implement adapters for each panel type.

---

## 2. National Net Stock/Warehouse System

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| `nm_config_stock` table | ✅ | ❌ | Missing | **HIGH** |
| `nm_stock_shelves` table | ✅ | ❌ | Missing | **HIGH** |
| Stock management UI | ✅ | ❌ | Missing | **HIGH** |
| QR code generation for configs | ✅ | ❌ | Missing | **MEDIUM** |
| Stock extend products | ✅ | ❌ | Missing | **MEDIUM** |
| Invoice-to-panel conversion | ✅ | ❌ | Missing | **MEDIUM** |
| National Net fallback | ✅ | ❌ | Missing | **HIGH** |
| Stock delivery with QR | ✅ | ❌ | Missing | **HIGH** |

**Faoxima Tables:**
```sql
nm_config_stock: id, panel_id, inbound_id, protocol, remark, config_str, used, created_at
nm_stock_shelves: id, shelf_name, shelf_type, configs (JSON), active
```

---

## 3. Crypto Payment Gateway

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| TON verification | ✅ | ❌ | Missing | **HIGH** |
| TRX verification | ✅ | ❌ | Missing | **HIGH** |
| USDT_TRC20 verification | ✅ | ❌ | Missing | **HIGH** |
| USDT_TON (Jetton) verification | ✅ | ❌ | Missing | **HIGH** |
| Memo/Tag support | ✅ | ❌ | Missing | **HIGH** |
| Amount tolerance (Iranian mode) | ✅ | ❌ | Missing | **MEDIUM** |
| tonapi.io integration | ✅ | ❌ | Missing | **HIGH** |
| tronscan.org integration | ✅ | ❌ | Missing | **HIGH** |
| Explorer URLs | ✅ | ❌ | Missing | **LOW** |

**Faoxima Crypto Helpers** (`crypto_helpers.php`): 302 lines of verification logic

---

## 4. Phone Verification Flow

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Contact sharing UI | ✅ | ✅ (partial) | Partial | **MEDIUM** |
| Phone verification handler | ✅ | ❌ | Missing | **HIGH** |
| Auto-verification on contact | ✅ | ❌ | Missing | **HIGH** |

---

## 5. Mini App Frontend (Telegram Web App v0.0.2)

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| crypto-offline.js (payment flow) | ✅ | ❌ | Missing | **HIGH** |
| home.js (main UI) | ✅ | ❌ | Missing | **HIGH** |
| services.js (service listing) | ✅ | ❌ | Missing | **HIGH** |
| buy.js (5-step purchase wizard) | ✅ | ❌ | Missing | **HIGH** |
| recharge.js (wallet recharge) | ✅ | ❌ | Missing | **HIGH** |
| gateway-watch.js (payment polling) | ✅ | ❌ | Missing | **HIGH** |
| account.js (user account) | ✅ | ❌ | Missing | **MEDIUM** |
| settings.js (user settings) | ✅ | ❌ | Missing | **MEDIUM** |
| service.js (service detail) | ✅ | ❌ | Missing | **MEDIUM** |

---

## 6. Advanced Admin User Management

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| User block/unblock | ✅ | ✅ | Done | — |
| User verify (phone) | ✅ | ❌ | Missing | **HIGH** |
| Agent tiers (multi-level) | ✅ | ✅ (basic) | Partial | **MEDIUM** |
| Detailed admin permissions | ✅ | ✅ (RBAC) | Done | — |
| User search/filter | ✅ | ✅ | Done | — |
| User detail with services | ✅ | ✅ | Done | — |
| Admin instant reply | ✅ | ❌ | Missing | **LOW** |

---

## 7. Gift/Discount Code Management

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Discount codes (percent) | ✅ | ✅ | Done | — |
| Gift codes (fixed amount) | ✅ | ❌ | Missing | **MEDIUM** |
| Usage limits (total/per user) | ✅ | ✅ | Done | — |
| Expiry dates | ✅ | ✅ | Done | — |
| Minimum order amount | ✅ | ✅ | Done | — |
| Product restrictions | ✅ | ✅ | Done | — |
| Web management UI | ✅ | ❌ | Missing | **LOW** |

---

## 8. Referral Tier System

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Tier N (direct) | ✅ | ✅ | Done | — |
| Tier N2 (indirect) | ✅ | ❌ | Missing | **HIGH** |
| Tier F (further) | ✅ | ❌ | Missing | **HIGH** |
| Commission rates per tier | ✅ | ❌ | Missing | **HIGH** |
| Referral earnings tracking | ✅ | ✅ (basic) | Partial | **MEDIUM** |

---

## 9. Panel Health Monitoring & Cron Jobs

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Panel health checks | ✅ | ✅ (basic) | Partial | **MEDIUM** |
| Cron job management UI | ✅ | ❌ | Missing | **HIGH** |
| Scheduled tasks (cron) | ✅ | ❌ | Missing | **HIGH** |
| Auto panel switching | ✅ | ❌ | Missing | **HIGH** |

---

## 10. Excel Export

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Users export | ✅ | ❌ | Missing | **MEDIUM** |
| Orders export | ✅ | ❌ | Missing | **MEDIUM** |
| Payments export | ✅ | ❌ | Missing | **MEDIUM** |
| Excel format (.xlsx) | ✅ | ❌ | Missing | **MEDIUM** |

---

## 11. Service Removal with Pro-Rata Refund

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Remove service | ✅ | ✅ | Done | — |
| Pro-rata refund calc | ✅ | ❌ | Missing | **HIGH** |
| Refund to wallet | ✅ | ✅ (wallet exists) | Partial | **MEDIUM** |

---

## 12. Emergency Panel Fallback

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Primary/backup panels | ✅ | ❌ | Missing | **HIGH** |
| Auto-failover | ✅ | ❌ | Missing | **HIGH** |
| Health-based switching | ✅ | ❌ | Missing | **HIGH** |

---

## 13. Payment Gateways

| Gateway | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| Zarinpal | ✅ | ❌ | Missing | **HIGH** |
| Zarinpey | ✅ | ❌ | Missing | **MEDIUM** |
| AqayePardakht | ✅ | ❌ | Missing | **MEDIUM** |
| Plisio (crypto) | ✅ | ❌ | Missing | **MEDIUM** |
| NowPayments (crypto) | ✅ | ❌ | Missing | **MEDIUM** |
| Star Telegram | ✅ | ❌ | Missing | **MEDIUM** |
| Card-to-card (manual) | ✅ | ✅ | Done | — |

---

## 14. Railway Deployment Model

| Feature | Faoxima | GhYiAb V2 | Status | Implementation Priority |
|---------|---------|-----------|--------|------------------------|
| MySQL database | ✅ | ❌ (SQLite) | Different | **MEDIUM** |
| Docker support | ✅ | ❌ | Missing | **HIGH** |
| Adminer for migration | ✅ | ❌ | Missing | **LOW** |
| Webhook setup | ✅ | ❌ | Missing | **HIGH** |
| Environment variables | ✅ | ✅ (.env.example) | Partial | **MEDIUM** |

---

## Implementation Roadmap

### Phase A: Core Infrastructure (Week 1-2)
1. ✅ VPN Provider Interface (already exists)
2. 🔄 Implement Marzban Provider Adapter
3. 🔄 Implement Hiddify Provider Adapter
4. 🔄 Implement WGDashboard Provider Adapter
5. 🔄 Add Panel Health Monitoring

### Phase B: Stock/Warehouse System (Week 2-3)
1. 🔄 Add `nm_config_stock` and `nm_stock_shelves` tables
2. 🔄 Implement Stock Management Service
3. 🔄 Add QR Code Generation
3. 🔄 Add Invoice-to-Panel Conversion

### Phase C: Crypto Payments (Week 3-4)
1. 🔄 Implement TON/TRX/USDT verification
2. 🔄 Add Crypto Payment Gateway Service
3. 🔄 Integrate with tonapi.io and tronscan.org

### Phase D: Mini App Frontend (Week 4-5)
1. 🔄 Port crypto-offline.js to TypeScript/React
2. 🔄 Build Mini App UI components
3. 🔄 Integrate with GhYiAb V2 API

### Phase E: Advanced Features (Week 5-6)
1. 🔄 Referral Tier System (N/N2/F)
2. 🔄 Pro-Rata Refund Calculation
3. 🔄 Emergency Panel Fallback
4. 🔄 Cron Job Management
5. 🔄 Excel Export

### Phase F: Payment Gateways (Week 6-7)
1. 🔄 Zarinpal Integration
2. 🔄 Plisio/NowPayments (Crypto)
3. 🔄 Star Telegram

### Phase G: Railway Deployment (Week 7-8)
1. 🔄 Docker Configuration
2. 🔄 MySQL Migration Support
3. 🔄 Railway Deployment Guide

---

## Database Schema Extensions Needed

### For Multi-Panel VPN
```sql
-- Extend providers table to support panel types
ALTER TABLE providers ADD COLUMN panel_type TEXT DEFAULT 'xui';
ALTER TABLE providers ADD COLUMN panel_config JSON;  -- Panel-specific config
```

### For National Net Stock
```sql
CREATE TABLE nm_config_stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER REFERENCES providers(id),
    inbound_id INTEGER,
    protocol TEXT,
    remark TEXT,
    config_str TEXT,
    used INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT (strftime('%s','now')*1000)
);

CREATE TABLE nm_stock_shelves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shelf_name TEXT,
    shelf_type TEXT,
    configs TEXT,  -- JSON
    active INTEGER DEFAULT 1
);
```

### For Referral Tiers
```sql
-- Extend referral_codes or create new table
CREATE TABLE referral_tiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tier_name TEXT,  -- 'N', 'N2', 'F'
    commission_rate INTEGER,  -- minor units
    level INTEGER  -- 1, 2, 3
);
```

### For Crypto Payments
```sql
CREATE TABLE crypto_wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    currency TEXT,  -- 'TON', 'TRX', 'USDT_TRC20', 'USDT_TON'
    wallet_address TEXT,
    wallet_memo TEXT,  -- For TON/USDT_TON
    network TEXT,     -- 'TON', 'TRON'
    is_active INTEGER DEFAULT 1,
    created_at INTEGER DEFAULT (strftime('%s','now')*1000)
);

CREATE TABLE crypto_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount_minor INTEGER,
    currency TEXT,
    wallet_to TEXT,
    tx_hash TEXT,
    status TEXT DEFAULT 'pending',  -- pending, verified, failed, expired
    memo TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now')*1000),
    verified_at INTEGER
);
```

### For Scheduled Jobs/Cron
```sql
CREATE TABLE scheduled_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    cron_expression TEXT,
    handler TEXT,  -- Python function path
    payload TEXT,  -- JSON
    enabled INTEGER DEFAULT 1,
    last_run_at INTEGER,
    next_run_at INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now')*1000)
);
```

---

## Priority Summary

### 🔴 CRITICAL (Must have for parity)
1. Multi-panel VPN adapters (Marzban, Hiddify, WGDashboard)
2. National Net Stock System
3. Crypto Payment Gateway (TON/TRX/USDT)
4. Referral Tier System (N/N2/F)
5. Pro-Rata Refund Calculation
6. Emergency Panel Fallback
6. Cron Job Management

### 🟠 HIGH (Important for production)
7. Mini App Frontend
8. Zarinpal Payment Gateway
9. Docker/Railway Deployment
10. Excel Export

### 🟡 MEDIUM (Nice to have)
11. Other VPN panels (Guard, Mikrotik, etc.)
12. Plisio/NowPayments/Star Telegram
13. Advanced Admin Features
14. Gift Codes

### 🟢 LOW (Future enhancements)
15. Admin Instant Reply
16. IBSng, Alireza Single, S-UI, Manualsale panels
17. Design Tokens from Logo