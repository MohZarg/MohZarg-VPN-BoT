# نصب

> **توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg) | **حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

## پیش‌نیاز
Python ≥ 3.10 (تست‌شده 3.12)، دسترسی خروجی به `api.telegram.org`، یک ربات از @BotFather، شناسهٔ عددی Owner.

## مراحل (Ubuntu)
```bash
sudo useradd --system --home /opt/ghyiab-v2 --shell /usr/sbin/nologin ghyiab
sudo mkdir -p /opt/ghyiab-v2 /var/lib/ghyiab-v2/backups /var/log/ghyiab-v2 /etc/ghyiab-v2
sudo cp -r . /opt/ghyiab-v2 && cd /opt/ghyiab-v2
sudo python3 -m venv venv && sudo venv/bin/pip install -r requirements.txt
sudo cp .env.example /etc/ghyiab-v2/env && sudo chmod 600 /etc/ghyiab-v2/env && sudo nano /etc/ghyiab-v2/env
sudo chown -R ghyiab:ghyiab /var/lib/ghyiab-v2 /var/log/ghyiab-v2 && sudo chown root:ghyiab /etc/ghyiab-v2/env && sudo chmod 640 /etc/ghyiab-v2/env
sudo cp deploy/ghyiab-v2.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now ghyiab-v2 && journalctl -u ghyiab-v2 -f
```
اولین اجرا اسکیما را می‌سازد (`init_schema`، additive و idempotent) و Owner را seed می‌کند.

## متغیرهای محیطی
در `.env.example` مستند شده‌اند. الزامی: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID`, `TELEGRAM_CHANNEL_ID`. بقیه پیش‌فرض دارند. `XUI_*` را وقتی 3x-ui آماده شد پر کنید (`3XUI-INTEGRATION.md`).

## ارتقا از نسخهٔ قبل
DB قدیمی بدون تغییر کار می‌کند (ستون/جدول‌ها فقط اضافه می‌شوند). قبل از ارتقا: `python -m tools.backup_cli create`.
نام‌های قدیمی `XUI_PANEL_URL`/`XUI_PANEL_TIMEOUT` هنوز خوانده می‌شوند؛ `XUI_USERNAME/PASSWORD` حذف شد (فقط توکن API).

## تست
`pip install -r requirements-dev.txt && python -m pytest -q`
