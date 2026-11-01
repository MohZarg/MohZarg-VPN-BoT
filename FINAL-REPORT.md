# GhYiAb V2 — گزارش نهایی

> **توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg) | **حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

تاریخ: 2026-10-12 · دامنه: فقط ربات VPN/V2Ray (بدون پلتفرم چندخدماتی).

## نتیجهٔ تست (واقعاً اجرا شد)
`python -m pytest -q` → **262 passed** (خط پایه قبل از کار: 172). ۹۰ تست جدید:

| ماژول | تست | پوشش |
|---|---|---|
| `test_xui_provider.py` | 17 | NOT_CONFIGURED، env جدید/قدیمی، توکن در لاگ/خطا، health، inbound، CRUD، حفظ فیلدها، renew مطلق، لینک/ساب، پنل قطع، retry GET، عدم retry POST، circuit-breaker، میزبان غیرقابل‌دسترس، رد/دروغ پنل، base-path مخفی، **HTTPS راه‌دور + TLS verify پیش‌فرض**، توکن اشتباه |
| `test_vpn_lifecycle.py` | 23 | provisioning واقعی، NOT_CONFIGURED بدون کسر، قطعی→Retry، adopt-after-crash، تأیید دستی، وضعیت/ترافیک/کش، مالکیت، لینک، تمدید (موفق/ناکافی/رد→بازپرداخت/مبهم→Recovery)، **هم‌زمانی تمدید (کلید یکسان و متفاوت)**، auto-renew، یادآوری، ادمین+RBAC+Audit، cancel+refund |
| `test_bot_services_ui.py` | 25 | Callbackهای نامعتبر، نمایش/لینک/QR، stale، EN، تمدید با تأیید و **دوبار-تپ**، خطای Provider بدون نشت، خرید→صدور→تحویل، قطعی→تحویل بعدی توسط نگهداری، **ری‌استارت**، backup روزانه |
| `test_admin_services_backup.py` | 10 | RBAC پنل سرویس‌ها، Confirm یک‌بارمصرف، Audit، سلامت، **Backup/Verify/Restore/CLI** |
| `test_security_hardening.py` | 8 | Rate limit، لاگ Redaction، .env loader، اسکن توکن در سورس، کوپن (حداقل سفارش/محصول) |
| `test_referral_v2.py` | 5 | پاداش پس از اولین سفارش، یک‌بار، خودارجاعی، trigger/phone، پس از صدور موفق |

حالت‌های Provider: configured ✅ · unavailable ✅ · NOT_CONFIGURED ✅ · same-server (loopback HTTP، با/بدون base-path) ✅ · remote (HTTPS، TLS verify، توکن اشتباه) ✅ — همه روی **سرور HTTP واقعی محلی** (`tests/fake_xui.py`) که قرارداد API را از سورس 3x-ui بازتولید می‌کند. **روی پنل 3x-ui زنده تست نشده** (آدرس/توکن در دسترس نبود).

بررسی‌های دیگر: `compileall` تمیز؛ `pyflakes` روی سورس بدون خطای منطقی (فقط چند f-string/متغیر بی‌ضرر قدیمی)؛ نصب تمیز در venv جدید از `requirements-dev.txt` و اجرای مجدد تست‌ها (بخش «اعتبارسنجی بسته»).

## آنچه کامل شد
- Adapter واقعی 3x-ui (همهٔ عملیات خواسته‌شده) پشت `VPNProvider`؛ فقط REST+توکن؛ NOT_CONFIGURED/BLOCKED صریح.
- **کشف مهم:** `provision_for_order` قبلاً هرگز به خرید وصل نبود و تماس شبکه داخل تراکنش SQLite بود → سه‌مرحله‌ای و متصل شد (کیف پول + تأیید کارت‌به‌کارت). دکمهٔ «Retry Provisioning» ادمین هم عملاً از کار افتاده بود؛ درست شد.
- چرخهٔ عمر سرویس، «سرویس‌های من» (وضعیت/ترافیک/انقضا/لینک/ساب/QR)، تمدید دو‌فازی Idempotent، تمدید خودکار Opt-in، یادآوری، پنل ادمین سرویس‌ها.
- RBAC: Presetهای ADMIN/SUPPORT/FINANCE روی مدل per-user. رفرال امن، کوپن کامل، قیمت‌گذاری واحد (موجود؛ تمدید و نمایش از همان `price_for_user`).
- Backup روزانه/تأیید/Retention/Restore، حلقهٔ نگهداری تک‌Task، Rate limit، لاگ امن، i18n FA/EN (صفحه‌های سرویس)، مستندات.

## مرور امنیت و منابع
یافته‌ها/اقدام‌ها در `SECURITY.md`. مهم‌ترین: نشت توکن ربات در لاگ httpx (رفع)، قفل SQLite هنگام I/O شبکه (رفع)، debounce نشت‌دار (رفع). منابع: idle ≈ 50MB RSS (اندازه‌گیری شد)، بدون Redis/Docker/n8n؛ فقط یک وابستگی جدید کوچک (`segno`، اختیاری، خالص-پایتون)؛ `pytest` از runtime جدا شد.

## محدودیت‌ها / بلاکرهای واقعی
1. **اعتبارنامهٔ 3x-ui** (`XUI_BASE_URL`, `XUI_API_TOKEN`, شمارهٔ Inbound، در صورت نیاز `XUI_SUB_URL_BASE`) — بدون آن همه چیز `NOT_CONFIGURED`. اولین اتصال زنده باید با یک خرید آزمایشی راستی‌آزمایی شود (فرمت لینک ساب به تنظیمات پنل بستگی دارد).
2. TODO #3 (نرخ ارز)، #5 (درگاه ارزی)، #7 (سقف Dice)، #11 (لوگو)، مقصد Backup خارجی (#10)، معیار سطوح/Reseller (#4) — حدس زده نشد.
3. i18n: صفحه‌های سرویس/اعلان‌ها دوزبانه‌اند؛ **منوی اصلی و پنل ادمین V1 هنوز فقط فارسی‌اند** (استخراج کامل ≈ کار جداگانه). RTL/LTR را خود تلگرام برای هر پیام مدیریت می‌کند.
4. Rate limit و State تک‌پردازه‌اند (مناسب polling تک‌نمونه).
5. (رفع شد) پاداش رفرال مسیر «اولین سفارش» توسط حلقهٔ نگهداری یک‌بار به معرف اعلام می‌شود.
6. `.env`ی که داخل ZIP ورودی بود **حاوی توکن واقعی** بود؛ از بستهٔ نهایی حذف شد — توصیه می‌شود توکن را در @BotFather revoke/عوض کنید.
7. نبود تست زنده با Telegram واقعی (شبکهٔ سندباکس بسته است)؛ لایهٔ Adapter با Fake تست شده و ربات بدون خطا ساخته می‌شود.

## تغییرات رفتاری
پیش‌فرض رفرال (`first_order`)، `backup_retention_count=7`، مسدودی `refund_order` برای سرویس فعال Provider، حذف `XUI_USERNAME/PASSWORD`. جزئیات: `CHANGELOG.md`.
