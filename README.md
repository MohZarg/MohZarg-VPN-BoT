# GhYiAb V2 — ربات فروش و مدیریت VPN/V2Ray (تلگرام)

> V2 **فقط** ربات VPN/V2Ray است. پلتفرم چندخدماتی آیندهٔ GhYiAb جداگانه ساخته می‌شود و از طریق API به این موتور وصل می‌شود (`providers/vpn/base.py` + لایهٔ core مرز تمیز آن است).

Python + SQLite (WAL) — مصرف idle حدود ۵۰MB RAM، بدون Redis/Docker/n8n/Postgres. Repository پشت Interface است (PostgreSQL-ready).

---

## 💝 توسعه‌دهنده

**توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg)

**حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

اگر این پروژه برای شما مفید بود، از توسعه‌دهنده حمایت کنید تا توسعه ادامه یابد.

## معماری

```
Telegram (adapters/telegram_bot) ──► core (use-cases/services) ──► repository (SQLite)
                                          └──► providers/vpn (Interface) ──► 3x-ui Adapter ──► 3x-ui REST API ──► Xray
```

| لایه | مسیر |
|---|---|
| Bot/UI (بدون منطق کسب‌وکار) | `adapters/telegram_bot/` (`bot.py`, `admin_panel.py`, `services_ui.py`, `maintenance.py`) |
| Use-case/Service | `core/*` (wallet, orders, pricing, coupons, referral/reseller, provisioning, vpn_services, rbac, audit, settings, system…) |
| Repository | `repository/interface.py` + `repository/sqlite/` |
| Provider | `providers/vpn/base.py` (قرارداد) + `providers/vpn/xui/provider.py` |
| امنیت | `security/` (secret loader, rate limit, logging با redaction, .env loader, permission catalog) |
| i18n | `shared/i18n/` (fa + en) |
| ابزار | `tools/backup_cli.py` |

## قابلیت‌ها

مشتری: ثبت‌نام/قوانین/عضویت کانال، کاتالوگ و خرید (کیف پول یا کارت‌به‌کارت+رسید)، **سرویس‌های من** (وضعیت، ترافیک مصرفی/باقی‌مانده، انقضا، لینک اتصال، ساب‌اسکریپشن، QR)، **تمدید** (با تأیید و قیمت دقیقاً همان قیمتِ کسرشده)، **تمدید خودکار** (Opt-in)، یادآوری انقضا، تست رایگان، رفرال، کوپن، پشتیبانی/تیکت، آموزش، `/lang` (FA/EN).

ادمین (RBAC، تأیید دو‌مرحله‌ای، Audit): داشبورد، کاربران، سرویس‌ها (تعلیق/فعال‌سازی/ریست ترافیک/لغو/لغو+بازپرداخت)، سفارش‌ها، محصولات، Providerها و Inbound، پرداخت‌های معلق، کیف پول، کوپن، رفرال/Reseller، پیام همگانی، Jobها، Audit Log، سلامت سیستم، Backup، تنظیمات (Feature flag).

نقش‌ها: `OWNER` (همه) و Presetهای `ADMIN`/`SUPPORT`/`FINANCE` (اعطا توسط Owner؛ مدل Permission همچنان per-user و قابل‌توسعه است).

## اصول سخت

No Fake Integration · No plaintext secrets · مالی اتمیک/Idempotent · همه‌چیز Audit · Least privilege · هیچ تماس شبکه‌ای داخل تراکنش DB.

## شروع سریع

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q                      # ۲۶۴ تست
cp .env.example .env && nano .env        # توکن ربات و Owner
python -m adapters.telegram_bot.bot
```

نصب کامل: `INSTALL.md` · استقرار: `DEPLOYMENT.md` (`SAME-SERVER.md`, `REMOTE-3XUI.md`) · 3x-ui: `3XUI-INTEGRATION.md` · امنیت: `SECURITY.md` · Backup: `BACKUP.md` · گزارش نهایی: `FINAL-REPORT.md`.

مستندات مرجع فاز ۰ در `docs/`.
