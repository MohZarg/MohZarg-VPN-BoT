# امنیت

> **توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg) | **حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

| حوزه | وضعیت |
|---|---|
| Secrets | فقط env / `EnvironmentFile`؛ `.env` در `.gitignore`؛ توکن‌ها هرگز لاگ نمی‌شوند (Redaction روی `bot<id>:<secret>`، `Bearer`, `token=`؛ لاگ httpx روی WARNING چون PTB URL حاوی توکن را در INFO می‌نویسد) |
| احراز/مجوز | RBAC per-permission؛ Presetهای ADMIN/SUPPORT/FINANCE؛ OWNER_ONLY قابل واگذاری نیست؛ هر عملیات حساس: Permission → تأیید دو‌مرحله‌ای (توکن یک‌بارمصرف با TTL) → اجرا → Audit |
| Callback | `svc:` با regex سخت‌گیر؛ مالکیت سرویس همیشه در core چک می‌شود (پیام یکسان NotFound) |
| Rate limit | Token-bucket به‌ازای کاربر (مرزدار، بدون نشت حافظه)؛ Owner معاف. تک‌نمونه؛ برای چندنمونه باید به DB/Redis برود |
| مالی | اتمیک (`BEGIN IMMEDIATE`)، Idempotency Key روی کیف پول/سفارش/درخواست/تمدید، تمدید دو‌فازی با بازپرداخت Idempotent |
| Provider | TLS verify پیش‌فرض روشن، timeout، retry محدود (فقط GET)، circuit breaker |
| خطاها | پیام امن به کاربر؛ جزئیات فقط در لاگ (redacted) |
| سخت‌سازی سرویس | `deploy/ghyiab-v2.service`: کاربر جدا، `ProtectSystem=strict`، `InaccessiblePaths=/opt/3x-ui /etc/x-ui`، `MemoryMax` |
| Audit | همهٔ اقدامات ادمین/مالی/Provider در `audit_logs` |

## مرور امنیتی این نسخه (یافته‌ها و اقدام)
- **رفع شد:** لاگ INFO کتابخانهٔ httpx توکن ربات را در URL می‌نوشت → فیلتر + سطح WARNING.
- **رفع شد:** تماس شبکه درون تراکنش SQLite (قفل نوشتن تا ۱۵ثانیه = DoS خودی) → Provisioning/تمدید سه‌مرحله‌ای.
- **رفع شد:** debounce سراسری بی‌پایان (نشت حافظه) → RateLimiter مرزدار.
- **رفع شد:** نبود محدودیت مالکیت روی سرویس → `_load_owned`.
- **باقی/ریسک پذیرفته:** پرداخت کارت‌به‌کارت دستی است (اعتبار رسید با ادمین)؛ Rate limit و state تک‌پردازه‌اند؛ قطع و وصل شبکه در لحظهٔ POST ممکن است حالت مبهم بسازد → Recovery و بازپرداخت پس از ۲۴ساعت.
- **هشدار عملیاتی:** اگر توکن ربات یا `.env` هرگز در ZIP/چت/Git قرار گرفته، آن را در @BotFather **revoke** کنید.
