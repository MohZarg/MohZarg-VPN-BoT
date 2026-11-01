# GhYiAb V2 — Phase 0: معماری پیشنهادی

نسخه: 0.1 — فقط طراحی، بدون کد. مبتنی بر Audit سورس فعلی (`GHIYAB-V2-AUDIT.md`).

---

## 0. اصل تصمیم باز (تعیین‌کننده)

این سند فرض می‌کند V2 مسیر خودش را دارد و به سورس Python/SQLite فعلی به‌عنوان **نقطهٔ شروع واقعی** (نه فرضی) نگاه می‌کند. اما دو مسیر ممکن وجود دارد که باید Owner انتخاب کند (به `TODO.md` مراجعه شود):

- **مسیر A — تکامل تدریجی:** همین کد Python + SQLite به‌صورت ماژولار بازسازی می‌شود، PostgreSQL-ready می‌ماند، و رشد می‌کند.
- **مسیر B — یکپارچه‌سازی با مونوریپوی Node/TS/Prisma قبلی:** ربات VPN به‌عنوان یک Channel Adapter (`apps/telegram-bot`) به همان `packages/core` که در Phase 3 (Auth) در حال ساخت بود متصل می‌شود.

تا تعیین‌تکلیف، معماری زیر **Stack-agnostic** نوشته شده (اصول و مرزها مستقل از زبان برنامه‌نویسی)، با یادداشت صریح کجا Python و کجا Node فرض متفاوت دارند.

---

## 1. اصول معماری (از سورس فعلی + الزامات V2)

1. **Interface-agnostic Core** — Bot / Mini App / Website / PWA هیچ Business Logic ندارند؛ فقط Adapter به `core` هستند. (نقض فعلی: همهٔ منطق داخل Bot handler است.)
2. **No Fake Integration** — اتصال 3x-ui واقعی نبود ⇒ `BLOCKED`/`NOT_CONFIGURED` علامت بخورد، نه Mock.
3. **Financial Integrity** — همهٔ مبالغ: `amount` (Decimal/Integer minor-unit) + `currency` (`TOMAN`/`USD`/`CRYPTO_*`) + Idempotency Key روی هر عملیات مالی.
4. **Everything Auditable** — هر تغییر حساس (موجودی، نقش، تنظیمات، تأیید/رد رسید) → رکورد `AuditLog`.
5. **RBAC-ready ولی Single-Owner فعلاً** — مدل Role/Permission از روز اول در schema باشد؛ فعلاً فقط نقش `OWNER` فعال.
6. **Secrets فقط Environment** — هیچ توکن/شمارهٔ کارت در کد.
7. **SQLite امروز، PostgreSQL فردا** — لایهٔ Repository طوری طراحی شود که تعویض دیتابیس معادل تعویض یک Adapter باشد (بدون تغییر Business Logic).
8. **i18n از روز اول** — هیچ متن Hardcoded فارسی در لایهٔ Business Logic؛ فقط در لایهٔ Presentation با کلید ترجمه.

---

## 2. مرزبندی ماژول‌ها (Modules)

```
core/                    → Business logic خالص (بدون وابستگی به Telegram/HTTP)
  ├─ wallet/             → adjust, transfer, balance query (Decimal + currency)
  ├─ orders/             → purchase flow, order lifecycle
  ├─ inventory/          → config pool claim (اتمیک — پورت از claim_config_locked)
  ├─ pricing/            → یک‌جا: تخفیف نماینده/سطح کاربر/کوپن (رفع Duplicate فعلی)
  ├─ referral/           → منطق پاداش + ضدسوءاستفاده (پس از تصمیم Owner)
  ├─ auth/                → نقش‌ها، سطوح کاربر (RBAC-ready)
  └─ audit/               → ثبت مرکزی AuditLog

providers/                → Provider Adapters پشت یک Interface یکسان
  ├─ vpn/3x-ui/            → Adapter واقعی 3x-ui (فعلاً NOT_CONFIGURED تا اتصال واقعی)
  └─ payment/               → کارت‌به‌کارت (دستی-تأییدی) + Gateway ارزی (بعداً)

repository/                → لایهٔ داده؛ Interface واحد، پیاده‌سازی فعلی: SQLite (WAL)
  → مسیر ارتقا: پیاده‌سازی دوم Postgres بدون تغییر Interface

adapters/ (Channels)        → بدون Business Logic، فقط ترجمهٔ ورودی/خروجی
  ├─ telegram-bot/           → پورت‌شدهٔ هندلرهای فعلی، صرفاً UI/State
  ├─ mini-app/                → Telegram WebApp (Phase بعد)
  ├─ website-pwa/              → Next.js یا معادل (Phase بعد)

automation/n8n/               → فقط Webhook/Scheduled/3rd-party glue؛ بدون تصمیم مالی
ai/                             → فقط Free API؛ بدون دسترسی مستقیم DB/مالی (Read-only context از core)
analytics/                      → گزارش‌گیری (Read model جدا از OLTP)
seo/                             → برای Website/PWA (Phase بعد؛ فعلاً N/A برای Bot)
security/                        → Rate limit (persisted، نه dict سراسری)، Input validation، Secret loader
```

**قانون سخت (پورت‌شده از اصول پروژهٔ قبلی):** هیچ Adapter کانالی مستقیم به `repository` وصل نمی‌شود — فقط از طریق `core`.

---

## 3. طرح دامنه/دیتابیس (V2 — تفاوت‌های کلیدی نسبت به فعلی)

### Bounded Contexts
Identity (User, Role, Permission) · Wallet (Wallet, WalletTransaction) · Catalog (Product, ProductVariant — شامل مدت/حجم VPN) · Inventory (ConfigPool ↔ 3x-ui) · Orders (Order, OrderItem) · Payments (PendingReceipt, PaymentMethod) · Referral (ReferralLink, ReferralReward) · Platform (AuditLog, Setting, FeatureFlag)

### تفاوت‌های حیاتی نسبت به Schema فعلی
| فعلی | V2 |
|---|---|
| `balance INTEGER` (فقط تومان) | `WalletBalance(amount_minor INTEGER, currency ENUM)` — یک کیف پول به‌ازای هر ارز |
| بدون AuditLog | `AuditLog(actor_id, action, entity, before, after, at)` برای همهٔ عملیات حساس |
| `admins(user_id)` تخت | `Role`, `Permission`, `UserRole` (فعلاً فقط OWNER پر می‌شود) |
| `configs` دستی | `InventoryItem` + `provider_ref` (اتصال به 3x-ui) — تا اتصال واقعی: `status=NOT_CONFIGURED` |
| بدون Idempotency Key | هر تراکنش مالی/سفارش دارای `idempotency_key` یکتا |
| بدون Coupon | `Coupon(code, type, value, constraints)` — طبق نیاز «Sales: عمده/Reseller» |

---

## 4. جریان مالی (Wallet/Payment) — الزام Transaction-safe + Idempotent

```
Request → Idempotency Check (کلید یکتا از کلاینت یا تولیدشده) 
        → core/wallet: BEGIN (اتمیک، معادل BEGIN IMMEDIATE فعلی)
        → اعتبارسنجی موجودی/کوپن/سطح کاربر (pricing واحد)
        → کسر/افزایش + ثبت WalletTransaction + AuditLog در همان تراکنش
        → COMMIT یا ROLLBACK کامل (بدون حالت میانی)
```

الگوی `BEGIN IMMEDIATE` فعلی از نظر تضمین Concurrency درست است و در Repository جدید **پورت می‌شود، نه دور ریخته**.

---

## 5. Automation (n8n) — قانون بدون‌تغییر

طبق سند معماری قبلی پروژه: n8n فقط Orchestration بیرونی/زمان‌بندی (یادآوری تمدید، اعلان انقضا، پیام‌های زمان‌بندی‌شده) است؛ هیچ تصمیم قیمت/تأیید مالی در n8n نمی‌نشیند — این تصمیمات همیشه در `core` هستند.

---

## 6. AI (Free APIs) — مرز دسترسی

مطابق الزام صریح Owner («AI: B/C اما بدون دسترسی مستقیم به DB یا عملیات مالی حساس»):
- AI فقط از طریق یک **Read-only Context Provider** در `core` به داده دسترسی دارد (مثلاً خلاصهٔ سبد کاربر، نه Query مستقیم DB).
- AI هرگز مستقیماً `adjust_balance`/`purchase` صدا نمی‌زند؛ حداکثر می‌تواند **پیشنهاد** بدهد که از Policy/Approval Layer رد می‌شود (مطابق اصل قبلی پروژه: Master Agent هم از Approval Layer رد می‌شود).

---

## 7. Deployment (Local-first / Zero-Low Cost)

```
Single VPS/Local
 └── (فعلاً) Python process (polling) + SQLite (WAL) + n8n local
 └── مسیر رشد: Docker Compose مشابه سند معماری قبلی، بدون Over-engineering زودهنگام
```

Backup روزانهٔ فایل SQLite + Retention از همین فاز باید تعریف شود (`NEED-INFO`: مقصد Backup — لوکال/ابری؟).

---

## 8. جدول تصمیم نهایی این فاز (خلاصه)

| ماژول | وضعیت فعلی | تصمیم Phase 0 |
|---|---|---|
| Wallet atomic ops | کارکردی و درست | **KEEP منطق، REFACTOR جایگاه** (انتقال به core) |
| Inventory claim | کارکردی و درست | **KEEP منطق، REFACTOR جایگاه** |
| 3x-ui Provider | وجود ندارد | **ADD (NEED-INFO: API/کردنشیال 3x-ui)** |
| AuditLog | وجود ندارد | **ADD** |
| RBAC | وجود ندارد (تخت) | **ADD schema، فعلاً یک نقش** |
| چندارزی | وجود ندارد | **ADD (NEED-INFO: نرخ تبدیل/منبع نرخ)** |
| i18n | وجود ندارد | **ADD در Phase مربوط به UI** |
| Secrets | هاردکد در فایل | **REFACTOR → env** |
| Referral anti-abuse | وجود ندارد | **NEED-INFO سیاست، سپس ADD** |
