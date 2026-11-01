# CHANGELOG

> **توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg) | **حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

https://github.com/x4gpanell/Faoxima
از این ریپو بالا گیت هاب هم میتونی ایده بگیری کامله تقریبا
## V2 Final
**3x-ui:** Adapter بازنویسی‌شده روی API مدرن (`/panel/api/clients/*`, Bearer token): health, inbounds, get/traffic, create, update, enable/disable, renew (مطلق+reset), delete, links, subscription. Retry/backoff/circuit-breaker، تأیید پس از نوشتن، `NOT_CONFIGURED/BLOCKED`. Interface مستقل `providers/vpn/base.py`. env: `XUI_BASE_URL/XUI_API_TOKEN/XUI_TIMEOUT/XUI_VERIFY_TLS` (+fallback نام‌های قدیمی؛ `XUI_USERNAME/PASSWORD` حذف).
**Provisioning:** سه‌مرحله‌ای بدون قفل DB؛ adopt-if-exists؛ Retry خودکار محدود؛ اتصال واقعی به خرید کیف پول و تأیید کارت‌به‌کارت (قبلاً وصل نبود)؛ بلاک خرید قبل از کسر پول اگر NOT_CONFIGURED.
**چرخهٔ عمر سرویس:** وضعیت‌های PENDING/ACTIVE/EXPIRED/SUSPENDED/FAILED/CANCELLED؛ سرویس‌های من (وضعیت/ترافیک/انقضا/لینک/ساب/QR)؛ تمدید دو‌فازی Idempotent با بازپرداخت و Recovery؛ تمدید خودکار Opt-in؛ یادآوری انقضا؛ عملیات ادمین (suspend/enable/reset/cancel/+refund).
**RBAC:** Presetهای SUPPORT/FINANCE/ADMIN؛ permission جدید `services.view/manage`.
**رفرال:** پاداش فقط پس از اولین سفارش موفق (پیش‌فرض جدید؛ `referral_trigger=signup` = رفتار قدیمی)، ضدخودارجاعی، شرط شمارهٔ تأییدشده اختیاری، اعلان یک‌بارهٔ پاداش به معرف.
**کوپن:** حداقل سفارش و محدودیت محصول.
**امنیت/عملکرد:** RateLimiter مرزدار، Redaction لاگ + چرخش فایل، .env loader، کاهش ۷ کوئری RBAC برای کاربر عادی در هر Callback، GC حالت/تأییدیه/درخواست‌های معلق.
**Backup:** روزانه + تأیید + Retention(۷) + CLI + Restore.
**i18n:** کاتالوگ EN، `/lang`، صفحه‌های سرویس دوزبانه.
**State:** TTL و purge.
**تغییرات رفتاری:** پیش‌فرض رفرال تغییر کرد؛ `backup_retention_count` پیش‌فرض ۰→۷؛ `refund_order` برای سرویس فعال Provider مسدود است (از «لغو+بازپرداخت» استفاده شود).

## Production validation — 2026-10-21
- **Fixed (financial):** wallet purchase now takes an idempotency key (`buy:<user>:<message_id>`); a double-tap on “pay from wallet” no longer creates a second order or debits twice.
- **Fixed (availability):** admin health screen performs the 3x-ui check outside the SQLite write transaction (no network call while holding `BEGIN IMMEDIATE`).
- **Fixed (config):** `RateLimiter` is rebuilt after `.env` loading, so `GHYIAB_RL_*` settings actually apply.
- **Lint/cleanup:** pyflakes-clean source; removed unused imports/vars and the dead empty `package-lock.json` (no `package.json`).
- **Deploy layer:** `deploy/install.sh`, `deploy/install.ps1`, `deploy/update.sh`, `deploy/healthcheck.*`, `.github/workflows/ci.yml`; tools `init_db`, `healthcheck`, `security_scan`.
- **Validation:** 264 tests passed; compile, pyflakes (source), pip check, security scan, strict healthcheck, backup CLI and Telegram app build all green. Live Telegram/3x-ui connectivity not tested (no credentials).
