# GhYiAb V2 — Phase 0: Audit گزارش بررسی سورس فعلی

نسخه: 0.1 | دامنه: بررسی کامل دو فایل سورس یکسان ارسال‌شده (`srckde_6a941bdc0d8be.py` و «ربات سورس کــده») — یک ربات فروش VPN با Python + python-telegram-bot + SQLite.

> ⚠️ **نکته مهم پیش از هر چیز (باید توسط Owner تصمیم‌گیری شود):**
> در حافظهٔ پروژه، «GhYiAb» یک پلتفرم چندکاناله با استک **Node.js/TypeScript + Next.js + Prisma/PostgreSQL** بود که در **Phase 3 (Auth/RBAC)** در حال تکمیل بود (Session model، argon2id، CSRF، RBAC middleware و...). سورسی که اکنون بررسی شد یک **ربات مستقل Python + SQLite** برای فروش VPN است که هیچ ارتباط کدی با آن مونوریپو ندارد.
> طبق اصل «هیچ‌گاه بنیاد قبلی را فرض/بازنویسی نکن»، من این دو را **ادغام یا جایگزین یکدیگر فرض نکردم**. این آیتم به‌عنوان مهم‌ترین `NEED-INFO` در `TODO.md` ثبت شده و پاسخ آن مسیر Phase 1 به بعد را تعیین می‌کند.

---

## 1. روش بررسی

هر دو فایل ارسالی از نظر محتوا **یکسان** هستند (تفاوتی در منطق پیدا نشد) — بنابراین یک‌بار Audit شدند. بررسی خط‌به‌خط روی: دیتابیس، هندلرهای callback/متن/عکس/تماس، State Machine (`user_states`)، عملیات مالی (`adjust_balance`, `purchase_with_wallet`, `claim_free_test`, `claim_dice_turn`), Admin Panel، Referral، و امنیت انجام شد.

---

## 2. یافته‌ها بر اساس اولویت

### 🔴 P0 — Critical / Security / Financial / Data Loss

| # | یافته | فایل/تابع | ریسک | تصمیم |
|---|---|---|---|---|
| P0-1 | مبالغ (`balance`, `price`, `amount`) به‌صورت `INTEGER` تومان ذخیره می‌شوند؛ هیچ ستون ارز (`currency`) وجود ندارد. الزامات V2 شامل تومان/USD/Crypto است. | جدول `users`, `products`, `transactions` | نادرستی مالی هنگام افزودن چندارزی؛ ناسازگار با «Financial integrity: Decimal + currency column» | **REFACTOR** (در Phase 2: schema جدید با `amount_minor`/`Decimal` + `currency`) |
| P0-2 | هیچ جدول `AuditLog` مجزا برای اقدامات حساس ادمین (تغییر موجودی، تأیید/رد رسید، بن کردن، اعطای نمایندگی) وجود ندارد؛ فقط `transactions` برای مالی، و برای بقیه هیچ ردی ثبت نمی‌شود. | سراسر `handle_callbacks`, `handle_text_messages` | عدم قابلیت Audit/Rollback طبق اصل «Everything Auditable» | **ADD** (جدول AuditLog + middleware ثبت خودکار) |
| P0-3 | `TOKEN`, `OWNER_ID`, `CHANNEL_ID` به‌صورت متغیر Python هاردکد در بالای فایل تعریف شده‌اند (فعلاً Placeholder، ولی الگوی کد این‌طور نوشته که مقدار واقعی هم همان‌جا هاردکد می‌شود). | بالای فایل | نقض اصل «No plaintext secrets»؛ ریسک نشت توکن در Git/فوروارد فایل | **REFACTOR** (انتقال به `.env` + بارگذاری در Runtime، هرگز کامیت نشود) |
| P0-4 | تخفیف نماینده (`* 0.9`) و منطق قیمت‌گذاری مستقیم داخل Handlerها تکرار شده (در `purchase_with_wallet`, `buy_prod_`, و تأیید ادمین `ok_by_`) — سه‌جا duplicate. اگر نرخ تخفیف تغییر کند، احتمال ناهماهنگی قیمت واقعی/نمایشی وجود دارد. | 3 محل مجزا | ریسک مالی از عدم تطابق قیمت نمایشی و کسرشده | **REFACTOR** (تجمیع در یک Pricing Service واحد — Phase‑Core آینده) |
| P0-5 | State کاربر (`user_states`) کاملاً In-Memory (dict پایتون) است؛ با ری‌استارت پردازه یا Deploy، همهٔ جریان‌های نیمه‌کاره (پرداخت، ثبت کانفیگ ادمین و...) گم می‌شوند، بدون اطلاع‌رسانی به کاربر. | `user_states = {}` سراسری | از دست رفتن جریان تراکنش، تجربهٔ کاربری بد، ریسک سکهٔ ازدست‌رفته/مبهم در لحظهٔ ری‌استارت | **REFACTOR** (انتقال به DB/Redis با TTL برای V2) |
| P0-6 | مخزن کانفیگ (`configs`) کاملاً دستی توسط ادمین پر می‌شود (Paste متنی)؛ هیچ اتصال واقعی به 3x-ui وجود ندارد — یعنی «Provider» اصلاً پیاده نشده. | `m_add_`, `claim_config_locked` | با توجه به الزام صریح «Backend = 3x-ui» در V2، این بخش باید از صفر به‌عنوان Provider Adapter طراحی شود؛ فروش فعلی کاملاً Manual/Mock است | **NEED-INFO + ADD** (طراحی 3x-ui Provider Adapter در Phase بعد؛ فعلاً باید صریحاً به‌عنوان `NOT_CONFIGURED` مستند شود، نه شبیه‌سازی) |

### 🟠 P1 — Production / Reliability

| # | یافته | فایل/تابع | ریسک | تصمیم |
|---|---|---|---|---|
| P1-1 | `debounce()` یک دیکشنری سراسری بدون پاک‌سازی (`_last_action_at`) است — با رشد کاربران، Memory Leak آهسته. | ماژول سطح بالا | نشت حافظه بلندمدت | **REFACTOR** (TTL cache یا جابه‌جایی به Redis) |
| P1-2 | Broadcast/شارژ همگانی (`cap_8`, `waiting_for_broadcast`) به ازای هر کاربر یک `await` جدا و یک تراکنش DB جدا انجام می‌دهد؛ برای هزاران کاربر می‌تواند timeout/rate-limit تلگرام بخورد و کل عملیات را برای مدت طولانی بلاک کند (بدون Queue). | `p_cap_8`, `waiting_for_broadcast` | مسدود شدن Event loop، ریسک Rate limit تلگرام، عدم تفکیک موفق/ناموفق قابل Retry | **REFACTOR** (انتقال به Queue/Worker — BullMQ یا معادل n8n/کرون در V2) |
| P1-3 | اتصال SQLite با `sqlite3.connect` در هر عملیات باز/بسته می‌شود (`get_conn` contextmanager) بدون Connection Pool؛ روی VPS کوچک با Concurrency بالا کندی/قفل ایجاد می‌کند. | `get_conn` | گلوگاه کارایی زیر بار هم‌زمان | **KEEP فعلاً** (SQLite با WAL مورد تأیید صریح Owner است)؛ طراحی لایهٔ Repository باید از روز اول Postgres-ready باشد |
| P1-4 | خطاهای عمومی به‌صورت `except Exception` بی‌صدا بلعیده می‌شوند (مثلاً `react_heart`) بدون تفکیک نوع خطا؛ کمک به دیباگ سخت می‌شود. | چند تابع | مخفی‌ماندن خطاهای واقعی | **REFACTOR** (Exception typed + لاگ ساختاریافته) |
| P1-5 | هیچ RBAC واقعی وجود ندارد — فقط جدول تخت `admins(user_id)`؛ همهٔ ادمین‌ها دسترسی کامل یکسان دارند (No least-privilege). این با نیاز صریح «RBAC-ready» ناسازگار است. | `is_admin` | عدم امکان محدودسازی نقش (مثلاً پشتیبانی بدون دسترسی مالی) | **REFACTOR** (طراحی مدل Role/Permission در Phase Core، حتی اگر فعلاً یک نقش «Owner» باشد) |

### 🟡 P2 — Performance / Maintainability

| # | یافته | ریسک | تصمیم |
|---|---|---|---|
| P2-1 | همهٔ منطق (DB + UI + Business Logic) در یک فایل تک‌بخشی ۹۰۰+ خطی — تفکیک Core/Adapter مطابق اصل معماری V2 وجود ندارد. | سخت‌شدن نگهداری، تست‌ناپذیری | **REFACTOR** (استخراج به لایه‌های Core/Service/Repository/Bot-Adapter مطابق معماری پیشنهادی) |
| P2-2 | Callback data به‌صورت رشته‌های دستی parse می‌شود (`data.split("_")[2]`) بدون اعتبارسنجی متمرکز/typed router. | خطای Runtime روی callback ناقص | **REFACTOR** |
| P2-3 | متن‌ها (فارسی) مستقیم در کد هاردکد شده‌اند؛ بدون لایهٔ i18n — با نیاز صریح FA/EN ناسازگار. | عدم امکان افزودن EN بدون بازنویسی گسترده | **REFACTOR** (استخراج به فایل‌های i18n) |
| P2-4 | نبود Test (Unit/Integration) برای منطق مالی حساس (`claim_config_locked`, `purchase_with_wallet`). | ریسک رگرسیون هنگام تغییر | **ADD** (تست‌های Concurrency برای عملیات اتمیک) |

### 🟢 P3 — Improvement

| # | یافته | تصمیم |
|---|---|---|
| P3-1 | پاداش رفرال فقط هنگام پذیرش قوانین پرداخت می‌شود؛ بدون سقف/ضدسوءاستفاده (چند اکانت جعلی = پاداش نامحدود). | **NEED-INFO** (سیاست ضدتقلب رفرال باید توسط Owner مشخص شود) |
| P3-2 | گردونهٔ شانس (Dice) بدون هیچ سقف بودجهٔ روزانه/کلی؛ در تئوری اگر ترافیک بالا رود هزینهٔ پاداش کنترل‌نشده رشد می‌کند. | **NEED-INFO** (سقف بودجه؟) |
| P3-3 | نام‌گذاری‌ها (`p_cap_1..18`) خوانایی پایینی دارند. | **REFACTOR** بلندمدت |

---

## 3. نکات مثبت (KEEP — درست و حرفه‌ای پیاده‌سازی شده‌اند)

این‌ها **حذف یا تغییر اساسی نمی‌خواهند** و باید در V2 به همین سطح دقت (یا بهتر) حفظ شوند:

- ✅ استفاده از `BEGIN IMMEDIATE` + بررسی `rowcount` برای عملیات اتمیک ضدِ race-condition (`claim_config_locked`, `purchase_with_wallet`, `claim_dice_turn`) — دقیقاً الگوی درست برای جلوگیری از باگ «دو کاربر، یک کانفیگ».
- ✅ جدول `transactions` با `balance_after` برای ردیابی تاریخچهٔ مالی (Historical integrity در سطح پایه رعایت شده).
- ✅ `resolve_pending_request` با شرط `status='pending'` از تأیید/رد دوباره (double-approve) جلوگیری می‌کند — الگوی Idempotency درست.
- ✅ نرمال‌سازی شمارهٔ موبایل ایران (`normalize_ir_phone`) و تبدیل ارقام فارسی/عربی به انگلیسی (`to_en_digits`) — ورودی‌سازی تمیز.
- ✅ `safe_send` مدیریت `Forbidden` (بلاک‌شدن کاربر) را جدا از خطاهای دیگر تلگرام هندل می‌کند.
- ✅ مهاجرت ستون‌ها با `ensure_column` — از دست رفتن داده در آپدیت جلوگیری می‌کند.

---

## 4. جمع‌بندی وضعیت

سورس فعلی یک **MVP کارکردیِ تک‌فایلی** است — منطق مالی هستهٔ آن (claim/purchase) درست و اتمیک نوشته شده، اما معماری آن (تک‌فایل، بدون لایه‌بندی، بدون Audit Log، بدون چندارزی، بدون اتصال واقعی Provider، بدون RBAC واقعی) با اصول معماری V2 (`Controller → Use-case → Repository`, `No Fake Integration`, `Everything Auditable`, RBAC-ready, چندارزی) فاصلهٔ زیادی دارد.

**رویکرد پیشنهادی:** منطق مالی اتمیک فعلی به‌عنوان **مرجع رفتار صحیح** حفظ شود، اما در V2 داخل لایهٔ `core`/`repository` جدید با اسکیمای PostgreSQL-ready بازنویسی گردد؛ نه Rewrite کورکورانه، بلکه Port با حفظ تضمین‌های Concurrency.
