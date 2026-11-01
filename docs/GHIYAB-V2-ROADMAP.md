# GhYiAb V2 — Roadmap فازبندی‌شده

نسخه: 0.1 — ترتیب فازها پیشنهادی است؛ Phase 1 فقط پس از تأیید صریح Owner و پاسخ به آیتم‌های `NEED-INFO` بحرانی شروع می‌شود.

| فاز | عنوان | خروجی اصلی | پیش‌نیاز |
|---|---|---|---|
| **0** | Audit + Architecture (این فاز) | 5 سند فعلی | — |
| **1** | Core Foundation | لایه‌بندی `core/repository/adapters`، Repository Interface (SQLite impl)، Secret loader از env، AuditLog schema | تأیید مسیر A/B (پاسخ NEED-INFO #1) |
| **2** | Wallet & Pricing Consolidation | پورت `adjust_balance`/`claim_config_locked` به `core/wallet`, `core/inventory`؛ یک‌جا کردن منطق قیمت‌گذاری/تخفیف؛ چندارزی (schema) | پاسخ NEED-INFO #3 (نرخ ارز)، #2 (سطوح کاربر) |
| **3** | RBAC-ready Auth | Role/Permission schema (فعلاً فقط OWNER فعال) | — |
| **4** | 3x-ui Provider Adapter | اتصال واقعی Inventory به 3x-ui (یا `NOT_CONFIGURED` صریح اگر کردنشیال نرسیده) | پاسخ NEED-INFO #4 (دسترسی/API 3x-ui) |
| **5** | Payments v2 | کارت‌به‌کارت ساختاریافته + Idempotency + آمادگی درگاه ارزی | پاسخ NEED-INFO #5 (درگاه ارزی هدف) |
| **6** | Referral & Reseller Policy | پیاده‌سازی سیاست ضدسوءاستفادهٔ رفرال + سطوح Reseller/عمده | پاسخ NEED-INFO #6, #7 |
| **7** | Coupons & Auto-Renewal | کوپن + تمدید خودکار | — |
| **8** | i18n (FA/EN) + RTL/LTR + Theme | استخراج متن‌ها از Business Logic؛ presentation layer دوزبانه | Phase 1 کامل شده باشد |
| **9** | n8n Automation | یادآوری تمدید/انقضا، اعلان‌ها — بدون منطق تصمیم مالی در n8n | Phase 2, 5 |
| **10** | AI Layer (Free APIs, Read-only) | Context Provider فقط-خواندنی برای AI؛ بدون دسترسی مستقیم DB/مالی | Phase 1, 3 |
| **11** | Mini App | کانال دوم روی همان `core` | Phase 1–5 |
| **12** | Website/PWA + SEO | کانال سوم + SEO پایه | Phase 1–5 |
| **13** | Analytics | گزارش‌گیری Read-model جدا از OLTP | Phase 2 |
| **14** | Security Hardening | Rate limiting پایدار (نه dict سراسری)، Input validation متمرکز | مستمر از Phase 1 |
| **15** | Load/Regression Testing + Backup Strategy | تست بار روی SQLite قبل از تصمیم مهاجرت Postgres | قبل از رشد ترافیک واقعی |

> توجه: شماره‌گذاری فازها فعلاً **پیشنهادی** است و پس از پاسخ Owner به `TODO.md` ممکن است بازچینی شود (مثلاً اگر مسیر B انتخاب شود، فازبندی با Phase 4 مونوریپوی قبلی هماهنگ می‌شود نه از صفر).
