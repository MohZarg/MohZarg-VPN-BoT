# GhYiAb V2 — چک‌لیست استقرار (Production Deployment)

> **توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg) | **حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

> این سند مراحل کامل استقرار را پوشش می‌دهد. کد کامل و تست‌گرفته است (264 تست)؛ فقط پیکربندی و مجوزها باقی مانده.

---

## ✅ پیش‌نیازهای سرور

| مورد | وضعیت | نکات |
|------|-------|------|
| Ubuntu 22.04+ / Debian 12+ | ☐ | |
| Python 3.11+ | ☐ | `apt install python3.11 python3.11-venv` |
| SQLite3 (سازماندهی WAL) | ☐ | `apt install sqlite3` |
| systemd | ☐ | پیش‌فرض |
| دسترسی sudo | ☐ | برای نصب سرویس |

---

## 📦 1. نصب کد

```bash
# ۱. کلون/کپی پروژه به /opt/ghyiab-v2
sudo mkdir -p /opt/ghyiab-v2
sudo cp -r . /opt/ghyiab-v2/
cd /opt/ghyiab-v2

# ۲. ایجاد کاربر اختصاصی
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/ghyiab-v2 ghyiab

# ۳. ایجاد دایرکتوری‌های داده و لاگ
sudo mkdir -p /var/lib/ghyiab-v2/backups /var/log/ghyiab-v2 /etc/ghyiab-v2
sudo chown -R ghyiab:ghyiab /var/lib/ghyiab-v2 /var/log/ghyiab-v2
sudo chmod 750 /var/lib/ghyiab-v2 /var/log/ghyiab-v2
sudo chmod 750 /etc/ghyiab-v2

# ۴. نصب وابستگی‌های پایتون
sudo -u ghyiab python3 -m pip install --user -r requirements.txt
# یا system-wide:
pip3 install -r requirements.txt --break-system-packages
```

---

## 🔐 2. متغیرهای محیطی (حیاتی)

```bash
# کپی فایل محیط
sudo cp /opt/ghyiab-v2/.env /etc/ghyiab-v2/env
sudo chmod 600 /etc/ghyiab-v2/env
sudo chown ghyiab:ghyiab /etc/ghyiab-v2/env
```

**مقادیر الزامی (در `/etc/ghyiab-v2/env`):**

| متغیر | مثال | توضیح |
|--------|------|-------|
| `TELEGRAM_BOT_TOKEN` | `123456:ABC-DEF...` | از @BotFather |
| `TELEGRAM_OWNER_ID` | `6790005926` | آیدی عددی ادمین اصلی |
| `TELEGRAM_CHANNEL_ID` | `@GhYiAb_IR` | کانال اجباری عضویت |
| `GHIYAB_DB_PATH` | `/var/lib/ghyiab-v2/ghyiab_v2.db` | مسیر دیتابیس SQLite |
| **`XUI_BASE_URL`** | `http://127.0.0.1:2053/secretpath` | **حیاتی برای VPN واقعی** |
| **`XUI_API_TOKEN`** | `eyJhbGciOiJIUzI1Ni...` | **حیاتی برای VPN واقعی** |
| `XUI_VERIFY_TLS` | `1` | `0` فقط برای self-signed در لوکال |
| `XUI_SUB_URL_BASE` | `https://sub.domain.com:2096/sub/` | اختیاری - لینک ساب‌اسکریپشن |

> ⚠️ **بدون `XUI_BASE_URL` و `XUI_API_TOKEN`، Provider در حالت `NOT_CONFIGURED` می‌ماند و هیچ سرویس VPN واقعی از پنل 3x-ui صادر نمی‌شود (فقط موجودی کسر نمی‌شود، خرید در صف می‌ماند).**

---

## 🖥️ 3. راه‌اندازی 3x-ui (پیش‌نیاز VPN)

### روی همان سرور (Single Server):
```bash
# 1. نصب 3x-ui (معمولاً در /opt/3x-ui)
# 2. در پنل 3x-ui: Settings → API Token → ایجاد توکن با دسترسی Admin
# 3. یک Inbound بسازید (VLESS/VMess/Trojan) و شناسه (ID) آن را یادداشت کنید
# 4. webBasePath را از تنظیمات پنل بخوانید (معمولاً یک رشته تصادفی)
# 5. در /etc/ghyiab-v2/env:
#    XUI_BASE_URL=http://127.0.0.1:2053/<webBasePath>
#    XUI_API_TOKEN=<توکن_ساخته_شده>
```

### روی سرور جدا (Remote 3x-ui):
```bash
# در /etc/ghyiab-v2/env:
# XUI_BASE_URL=https://panel.example.com:2053/<webBasePath>
# XUI_API_TOKEN=<توکن_ساخته_شده>
# XUI_VERIFY_TLS=1
# فایروال VPS-B: فقط IP سرور V2 اجازه دسترسی به پورت پنل را داشته باشد
```

---

## 🗄️ 4. مقداردهی اولیه دیتابیس

```bash
# اسکما به‌صورت خودکار در اولین اجرا ساخته می‌شود (bootstrap.py -> init_schema)
# اما برای اطمینان می‌توانید دستی اجرا کنید:
sudo -u ghyiab python3 -c "
from security.secret_loader import BotSecrets, secrets
from repository.sqlite.connection import init_schema
bs = BotSecrets(secrets)
init_schema(bs.db_path, owner_user_id=bs.owner_id)
print('✅ Schema initialized at', bs.db_path)
"
```

---

## 👑 5. ساخت ادمین اول (Owner)

```bash
# Owner از TELEGRAM_OWNER_ID به‌صورت خودکار ADMIN می‌شود (seed در bootstrap)
# برای ادمین‌های اضافه از پنل تلگرام: «پنل مدیریت ← ادمین‌ها ← افزودن ادمین»
```

---

## ⚙️ 6. پیکربندی پنل ادمین (پس از اجرای ربات)

از طریق ربات تلگرام (دکمه «🛠️ مدیریت» در منوی ادمین):

1. **پلن‌ها** → برای هر محصول VPN:
   - پروفایل Provisioning: Inbound ID، روزها، حجم (GB)، محدودیت IP
2. **تنظیمات عمومی** → کارت بانکی، فعال‌سازی:
   - `auto_renewal_enabled` (پیش‌فرض خاموش)
   - `dice_enabled`، `dice_cooldown_hours`
   - `referral_bonus_minor`، `referral_trigger` (signup/paid_order)
   - `provision_max_attempts` (پیش‌فرض ۳)
3. **Providerها** → وضعیت اتصال 3x-ui باید 🟢 OK باشد

---

## 🔧 7. نصب و فعال‌سازی systemd

```bash
# کپی فایل سرویس
sudo cp /opt/ghyiab-v2/ghyiab-v2.service /etc/systemd/system/

# بارگذاری و فعال‌سازی
sudo systemctl daemon-reload
sudo systemctl enable --now ghyiab-v2

# بررسی وضعیت
sudo systemctl status ghyiab-v2
sudo journalctl -u ghyiab-v2 -f
```

---

## ✅ 8. تست سلامت (Health Checks)

| تست | دستور / روش | خروجی مورد انتظار |
|------|-------------|------------------|
| سرویس در حال اجرا | `systemctl status ghyiab-v2` | `Active: active (running)` |
| اتصال تلگرام | `/start` در ربات | منوی اصلی نمایش داده شود |
| اتصال 3x-ui | پنل ادمین → Providerها | 🟢 OK + latency_ms |
| دیتابیس | `sqlite3 /var/lib/ghyiab-v2/ghyiab_v2.db ".tables"` | جداول نمایش داده شوند |
| لاگ‌ها | `journalctl -u ghyiab-v2 -n 50` | بدون ERROR |
| Backup | پنل ادمین → Backup/سلامت → ایجاد Backup | فایل در `/var/lib/ghyiab-v2/backups/` |

---

## 🧪 9. تست خرید اتمی (End-to-End)

1. در ربات: «خرید اشتراک» → پلن VPN → «پرداخت از کیف پول» (موجودی کافی داشته باشد)
2. بررسی: سفارش `COMPLETED`، سرویس در «سرویس‌های من» با وضعیت ACTIVE
3. دکمه «لینک‌ها» → لینک اتصال + QR نمایش داده شود
4. تست اتصال واقعی با کلاینت VLESS/VMess

---

## 📋 10. مانیتورینگ و نگهداری

### لاگ‌ها
```bash
# زنده
journalctl -u ghyiab-v2 -f

# خطاهای اخیر
journalctl -u ghyiab-v2 -p err -n 20

# با فیلتر
journalctl -u ghyiab-v2 -g "provision" -n 50
```

### Backup اتوماتیک
- ربات هر `GHIYAB_MAINTENANCE_INTERVAL` ثانیه (پیش‌فرض ۳۰۰ث) Backup می‌گیرد
- نگهداری: `GHIYAB_BACKUP_RETENTION` (پیش‌فرض ۷)
- مقصد: `GHIYAB_BACKUP_DIR` (`/var/lib/ghyiab-v2/backups/`)
- برای Backup خارجی: cron/rclone به storage ابری (راجع به TODO #10)

### به‌روزرسانی کد
```bash
cd /opt/ghyiab-v2
git pull  # یا کپی فایل‌های جدید
sudo systemctl restart ghyiab-v2
```

---

## 🚨 عیب‌یابی رایج

| مشکل | علت محتمل | راه‌حل |
|--------|-----------|--------|
| Provider 🔴 BLOCKED | توکن/آدرس اشتباه، فایروال | چک `XUI_BASE_URL`، `XUI_API_TOKEN`، فایروال |
| Provider 🟡 NOT_CONFIGURED | متغیرهای env ست نشده | ست کردن `XUI_BASE_URL` و `XUI_API_TOKEN` |
| خرید در PROVISIONING گیر کرده | پنل 3x-ui_down، inbound اشتباه | پنل ادمین → Providerها → Retry / چک inbound ID |
| Rate limit زیاد | `GHIYAB_RL_BURST`/`PER_SEC` کم | افزایش در env |
| دیتابیس Locked | پردازش سنگین هم‌زمان | افزایش `MemoryMax`، چک WAL mode |

---

## 📁 خلاصه مسیرهای مهم

| مسیر | مالک | مجوز | توضیح |
|------|------|------|-------|
| `/opt/ghyiab-v2/` | root:root | 755 | کد منبع (Read-only برای ghyiab) |
| `/etc/ghyiab-v2/env` | ghyiab:ghyiab | 600 | **حاوی توکن‌ها - محرمانه** |
| `/var/lib/ghyiab-v2/` | ghyiab:ghyiab | 750 | دیتابیس + Backupها |
| `/var/log/ghyiab-v2/` | ghyiab:ghyiab | 750 | لاگ‌های اپلیکیشن (اگر file logging فعال باشد) |

---

## 📚 مستندات ارجاع

- `DEPLOYMENT.md` — خلاصه استراتژی
- `SAME-SERVER.md` — استقرار هم‌سرور
- `REMOTE-3XUI.md` — استقرار سرور جدا
- `3XUI-INTEGRATION.md` — جزئیات API 3x-ui
- `SECURITY.md` — مدل تهدید و سخت‌سازی
- `FINAL-REPORT.md` — گزارش نهایی و وضعیت تست‌ها
- `TODO.md` — آیتم‌های نیازمند تصمیم Owner

---

## ✅ امضای تایید استقرار

| مرحله | انجام شده | تاریخ | امضا |
|-------|-----------|-------|------|
| سرور آماده | ☐ | | |
| کد کپی شده | ☐ | | |
| env ست شده | ☐ | | |
| 3x-ui پیکربندی شده | ☐ | | |
| دیتابیس ساخته شده | ☐ | | |
| systemd فعال | ☐ | | |
| تست سلامت پاس | ☐ | | |
| تست خرید E2E | ☐ | | |
| مانیتورینگ فعال | ☐ | | |

---

*استقرار کامل = همه تیک‌ها ☐ → ✅*