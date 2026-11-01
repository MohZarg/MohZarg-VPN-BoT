# GhYiAb (غیاب) — PHASE 0: Architecture & Specification

نسخه: 0.1 — طراحی اولیه، قبل از هرگونه پیاده‌سازی کد

---

## 0. دامنه این سند

این سند فقط **Phase 0** است: معماری، مرزبندی ماژول‌ها، طرح دیتابیس/دامنه، طرح API، معماری Agentها، معماری امنیت، معماری SEO، معماری اتوماسیون، معماری Deployment و نقشه فازبندی‌شده. **هیچ کدی در این فاز نوشته نمی‌شود.** پیاده‌سازی از Phase 1 به بعد و پس از تأیید شما شروع می‌شود.

---

## 1. اصول معماری کلان (Guiding Principles)

1. **Interface-agnostic Core** — Telegram Bot، Website، PWA، Mini App و Instagram integration هیچ Business Logic ای در خودشان ندارند؛ فقط Adapter هستند که به `packages/core` وصل می‌شوند.
2. **Modular Monolith اول، Microservice بعداً** — بدون over-engineering زودهنگام. مرزهای ماژول از روز اول شفاف است تا استخراج آینده ارزان باشد.
3. **Provider Abstraction در همه‌جا** — Payment، Fulfillment، AI، Notification: همه پشت یک Interface یکسان قرار می‌گیرند تا Provider قابل تعویض باشد بدون تغییر Business Logic.
4. **Least Privilege برای Agentها** — هیچ Agent ای دسترسی کامل ندارد؛ یک Policy/Approval Layer بین Master Agent و عملیات حساس می‌نشیند.
5. **Everything Auditable & Reversible** — هر تغییر مهم (کد، قیمت، محتوا، تنظیمات) Versioned و قابل Rollback است.
6. **No Fake Integration** — اگر Providerای واقعاً متصل نیست، به‌صورت `BLOCKED` علامت‌گذاری می‌شود، نه شبیه‌سازی می‌شود.

---

## 2. مرزبندی ماژول‌ها (Module Boundaries)

```
apps/
├── web/            → Next.js storefront + customer dashboard (channel adapter)
├── admin/           → Next.js admin/ops dashboard (internal, RBAC-gated)
├── api/             → Core HTTP API (REST/tRPC) — single source of truth
├── telegram-bot/    → Telegram channel adapter → calls api/ only
├── mini-app/        → Telegram Mini App (webapp) → calls api/ only
└── worker/          → BullMQ workers (fulfillment, notifications, content, SEO jobs)

packages/
├── core/            → Domain services, use-cases, orchestration (no HTTP/UI code)
├── database/         → Prisma schema, migrations, repositories
├── auth/             → JWT/session, RBAC, MFA-ready
├── agents/           → Master Agent + specialized agents, tool registry, policy layer
├── providers/        → Provider adapters (gaming, gift cards, AI, VPN, etc.) + selection engine
├── payments/         → Payment gateway abstraction, wallet, refunds, webhooks
├── orders/           → Order lifecycle, fulfillment orchestration
├── products/         → Catalog, categories, pricing engine
├── content/           → Content generation pipeline, scheduling, publishing
├── seo/               → Technical SEO utilities, sitemap/schema generation, SEO agent tools
├── security/          → Rate limiting, input validation, audit log, secret access
└── shared/            → Types, constants, i18n (fa/en), utils
```

**قانون سخت:** هیچ‌کدام از `apps/*` مستقیماً به `database` یا `providers` وصل نمی‌شوند — همه از طریق `api/` که خودش از `core/` استفاده می‌کند.

---

## 3. طرح دامنه/دیتابیس (Domain & Database Plan)

### 3.1 Bounded Contexts
- **Identity** — Users, Roles, Permissions, Sessions
- **Catalog** — Categories, Products, ProductVariants, ProviderProducts
- **Providers** — Providers, ProviderCredentials(encrypted ref), ProviderMetrics
- **Commerce** — Orders, OrderItems, Payments, Wallet, Coupons, Refunds
- **Support** — Tickets, TicketMessages
- **Content** — ContentItems, ContentSchedule, ContentApprovals
- **SEO** — SeoMeta, Redirects, SitemapEntries
- **Agents** — AgentDefinitions, AgentTasks, AgentLogs, PolicyApprovals
- **Platform** — AuditLogs, Notifications, Settings, FeatureFlags

### 3.2 هسته جداول اولیه (نام‌گذاری اولیه — نهایی در Phase 2)
```
User, Role, Permission, Session
Category, Product, ProductVariant
Provider, ProviderProduct, ProviderMetric
Order, OrderItem, Payment, Wallet, WalletTransaction, Coupon, Refund
Ticket, TicketMessage
ContentItem, ContentSchedule
SeoMeta, Redirect
Agent, AgentTask, AgentLog, PolicyApproval
AuditLog, Notification, Setting, FeatureFlag
```

### 3.3 اصول
- PostgreSQL + Prisma؛ همه Migrationها Versioned و در حد امکان Reversible.
- بدون ذخیره داده حساس کارت بانکی (PCI scope خارج از سیستم — فقط توکن/رفرنس Gateway).
- Soft-delete برای Product/Order/User جهت Audit؛ Hard-delete فقط برای داده‌های غیرحیاتی طبق Retention Policy.
- ایندکس‌گذاری از ابتدا برای مسیرهای پرترافیک: `Order.status`, `Order.userId`, `ProviderProduct.productId`.

---

## 4. طرح API

- **الگو:** REST یا tRPC (تصمیم نهایی در Phase 4 — پیشنهاد: tRPC داخلی بین `web/admin` و `api/`، REST عمومی برای `telegram-bot`/`mini-app`/Webhookها).
- **لایه‌بندی:** `Controller → Use-case (core) → Repository (database)`. Controller هیچ منطق کسب‌وکاری ندارد.
- **Versioning:** `/api/v1/...` از روز اول.
- **Auth:** JWT (access + refresh rotation) + API Key برای Server-to-Server (Telegram bot, n8n).
- **Webhookها:** مسیر مجزا با Signature Verification اجباری (`payments`, `providers`, `n8n`).
- **Rate Limiting:** در سطح Nginx/Reverse Proxy + سطح Application (Redis token bucket).

---

## 5. معماری Agentها

```
Owner (شما)
   ↓
Master Agent  ──────────────► Policy / Approval Layer ──────► Sensitive Ops
   ↓ (delegates via tool calls, scoped)
┌────────────┬────────────┬────────────┬─────────────┬────────────┐
Sales Agent  Provider Agent  Pricing Agent  Order Agent  Support Agent
Marketing    Content Agent   SEO Agent      Analytics    Finance Agent
Developer Agent  QA Agent   Security Agent  Research     Monitoring Agent
```

- هر Agent یک **Tool Registry** محدود دارد (فقط ابزارهای لازم خودش).
- **Policy/Approval Layer** برای: Payment، Destructive DB ops، Production deploy، Security/Credential changes، Provider changes — Master Agent هم از این لایه رد می‌شود.
- **AgentTask/AgentLog** در دیتابیس ذخیره می‌شود تا هر تصمیم/اقدام Agent قابل Audit باشد.
- توسعه: `Idea → Code → Branch → Tests → Security Scan → Staging → Health Check → Deploy → Monitoring → Rollback` — Developer/QA/Security Agent در این مسیر با Human Approval روی مراحل حساس کار می‌کنند، نه به‌صورت خودکار روی Production.

---

## 6. معماری امنیت

```
Internet → WAF/Reverse Proxy (Nginx) → Rate Limiting → API Auth (JWT)
   → RBAC → Input Validation (Zod) → Business Logic
   → Output Sanitization → DB (parameterized queries via Prisma)
```

- Secret Management: `.env` + Vault-ready abstraction از Phase 3 (بدون هاردکد).
- Webhook signature verification اجباری برای Payment/Provider.
- Audit Log برای همه عملیات حساس (Login, Payment, Refund, Role change, Agent action, Production deploy).
- Fraud/Abuse: Rate limiting + Anomaly flags روی سفارش‌ها از Phase 6 به بعد (نه در MVP اولیه، ولی جای آن در schema رزرو می‌شود).

---

## 7. معماری SEO

- Technical SEO از Phase 1 در `packages/seo` (sitemap generator, schema.org helpers, canonical/redirect management) — مستقل از محتوا.
- عملکرد (Core Web Vitals) به‌عنوان constraint معماری فرانت‌اند (Next.js SSR/ISR، تصویر بهینه، code splitting) از Phase 13.
- چندزبانگی (fa/en) با hreflang از ابتدا در `shared/i18n` رزرو می‌شود، حتی اگر Launch اول فقط فارسی باشد.
- SEO Agent در Phase 10 روی زیرساخت آماده‌شده در Phase 1 کار می‌کند؛ هر تغییر SEO مهم → AuditLog + Rollback path.

---

## 8. معماری اتوماسیون (n8n)

```
Agent Core / Business Logic (packages/core, agents)
        ↓ triggers via internal API
      n8n  (فقط: webhooks, scheduled jobs, 3rd-party glue, notifications)
        ↓
External Integrations (Telegram API, Instagram, Payment Gateways, Providers)
```

قانون: **n8n هرگز منطق تصمیم‌گیری کسب‌وکاری را نگه نمی‌دارد** — فقط Orchestration بیرونی/زمان‌بندی. تصمیم (کدام Provider، چه قیمتی، تأیید سفارش) همیشه در `core/` است.

---

## 9. معماری Deployment

**MVP (Phase 1 اولیه):**
```
Single VPS
 └── Docker Compose: nginx | api | web | worker | postgres | redis | n8n | (telegram-bot)
```
- Backup خودکار PostgreSQL (روزانه، retention مشخص) از Phase 1.
- Health check endpoint (`/health`) در `api` از ابتدا.
- CI: lint → typecheck → test → build → (manual) deploy، از Phase 1 با GitHub Actions.
- مسیر رشد آینده: جدا کردن `worker` و `postgres` به سرورهای مجزا در صورت نیاز واقعی load — بدون Kubernetes زودهنگام.

---

## 10. نقشه فازبندی‌شده (خلاصه — جزئیات کامل در Spec اصلی بخش 20)

| فاز | خروجی اصلی |
|---|---|
| 0 | این سند (Architecture) |
| 1 | Monorepo + Docker + Env + CI اسکلت |
| 2 | Database schema + Core domain models |
| 3 | Auth + RBAC + Security foundation |
| 4 | Core API skeleton |
| 5 | Products/Categories/Providers |
| 6 | Orders/Payments/Fulfillment |
| 7 | Agent Core + Master Agent |
| 8 | Agentهای تخصصی (Provider/Sales/Pricing/Support/Data) |
| 9 | Content Agent + Automation |
| 10 | SEO System + SEO Agent |
| 11–15 | Telegram Bot → Instagram → Website → PWA → Mini App |
| 16 | Analytics + Monitoring |
| 17 | Fraud Detection + Advanced Security |
| 18 | Self-improvement loop |
| 19 | Load/Security/E2E Testing |
| 20 | Production Deployment |

---

## 11. تصمیمات باز که نیاز به تأیید شما دارد

این‌ها طبق بخش ۲۷ اسپک، تصمیمات معماری‌ای هستند که تأثیر مادی دارند و بهتر است پیش از Phase 1 مشخص شوند:

1. **REST vs tRPC** برای `api/` — پیشنهاد بالا (tRPC داخلی + REST برای Webhook/Bot) را تأیید می‌کنید؟
2. **اولین Providerهای واقعی** برای فاز MVP (بخش ۲۵ اسپک) — کدام دسته (Gaming top-up؟ Gift card؟ AI subscription؟) را برای اولین محصولات واقعی انتخاب می‌کنید؟ این روی طراحی اولین Provider Adapter در Phase 5 تأثیر مستقیم دارد.
3. **Payment Gateway اول** — کدام درگاه ایرانی/بین‌المللی برای MVP هدف است؟
4. **VPS/Infrastructure account** — آیا سرور/دامنه از قبل موجود است یا در Phase 1 باید تهیه شود؟

اگر پاسخ این‌ها را ندارید یا می‌خواهید بعداً تصمیم بگیرید، می‌توانم با فرض‌های منطقی (tRPC، بدون Provider واقعی در MVP اول به‌صورت Mock adapter مشخص، Docker Compose روی VPS فرضی) وارد Phase 1 شوم و صرفاً این فرض‌ها را در گزارش پایان فاز علامت بزنم.

---

**وضعیت:** Phase 0 کامل شد. منتظر تأیید شما برای شروع Phase 1 (Repository + Monorepo + Docker + Environment) هستم.
