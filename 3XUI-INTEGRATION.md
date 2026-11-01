# یکپارچگی 3x-ui

مرجع: سورس 3x-ui v3.x (`internal/web/controller/client.go`). احراز هویت: `Authorization: Bearer <XUI_API_TOKEN>` (CSRF برای توکن اعمال نمی‌شود).
مبنای واحدها: `totalGB` در پنل **بایت** است؛ `expiryTime` میلی‌ثانیهٔ epoch (۰ = بدون انقضا).

## نگاشت عملیات
| عملیات V2 | endpoint |
|---|---|
| health | `GET /panel/api/inbounds/list/slim` (fallback: `/inbounds/list`) |
| list inbounds | `GET /panel/api/inbounds/list/slim` |
| get/traffic | `GET /panel/api/clients/traffic/{email}` (`obj=null` ⇒ وجود ندارد) + `GET /clients/get/{email}` |
| create | `POST /panel/api/clients/add` `{client, inboundIds}` |
| update / enable / disable | `POST /panel/api/clients/update/{email}` (Read-Modify-Write با فهرست فیلد امن) |
| renew | `POST /clients/resetTraffic/{email}` + update با انقضا/سقف **مطلق** |
| delete | `POST /panel/api/clients/del/{email}` |
| links | `GET /panel/api/clients/links/{email}` |
| subscription | `XUI_SUB_URL_BASE + subId` (حدس زده نمی‌شود؛ بدون آن `None`) |

## تضمین‌ها
- فقط REST؛ هرگز DB/فایل/Xray/`/etc/x-ui`.
- `NOT_CONFIGURED` اگر `XUI_BASE_URL` یا `XUI_API_TOKEN` خالی باشد: همهٔ عملیات `NotConfiguredError`؛ فروش محصول VPN-واقعی **قبل از کسر پول** مسدود.
- پس از هر create/update پاسخ پنل **تأیید خوانده می‌شود**؛ «success» بدون اثر (پنل دروغگو) موفقیت حساب نمی‌شود.
- GET: حداکثر `XUI_MAX_RETRIES` با backoff نمایی؛ POST هرگز خودکار Retry نمی‌شود (Idempotency در core: ایمیل قطعی `gy<order>`، adopt-if-exists، مقدار مطلق).
- توکن هرگز در لاگ/خطا/`repr` نمی‌آید؛ خطاهای داخلی به کاربر نمی‌رسد.

## راه‌اندازی
۱) Inbound بسازید ۲) API Token ۳) env ۴) ادمین ← پلن‌ها ← پروفایل Provisioning (inbound، روز، GB) ۵) خرید آزمایشی.

## محدودیت‌های مستند
- لینک ساب‌اسکریپشن به تنظیمات Subscription پنل شما بستگی دارد → `XUI_SUB_URL_BASE` دستی.
- «پیکربندی واقعی» (آدرس/توکن/inbound) را من نداشتم؛ آداپتر روی fake سرور HTTP که قرارداد را از سورس بازتولید می‌کند تست شده، نه روی پنل زنده (FINAL-REPORT).
