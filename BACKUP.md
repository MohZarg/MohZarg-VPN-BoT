# Backup / Restore

> **توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg) | **حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

## خودکار
حلقهٔ نگهداری هر روز (در صورت روشن بودن تنظیم `backup_daily_enabled`، پیش‌فرض روشن) با `VACUUM INTO` یک snapshot سازگار از DB زنده می‌سازد، **فوراً تأیید می‌کند** (`integrity_check` + وجود جدول‌های حیاتی) و Audit می‌نویسد. نگهداری: `backup_retention_count` (پیش‌فرض ۷، ۰=همه). مسیر: `GHIYAB_BACKUP_DIR`.

## دستی
```bash
python -m tools.backup_cli create  --dir /var/lib/ghyiab-v2/backups
python -m tools.backup_cli verify  /var/lib/ghyiab-v2/backups/ghyiab_backup_YYYYmmdd_HHMMSS.db
```
یا از پنل ادمین: Backup/سلامت (دریافت فایل فقط Owner).

## بازیابی (آفلاین)
```bash
sudo systemctl stop ghyiab-v2
python -m tools.backup_cli restore /path/to/ghyiab_backup_XXXX.db --db /var/lib/ghyiab-v2/ghyiab_v2.db
sudo systemctl start ghyiab-v2
```
بازیابی ابتدا فایل را تأیید می‌کند، DB فعلی را کنار می‌گذارد (`*.pre-restore-<ts>`) و جایگزینی اتمیک می‌کند؛ فایل نامعتبر هرگز جایگزین نمی‌شود. بعد از بازیابی: سرویس‌ها از DB می‌آیند؛ تمدیدهای `CHARGED` توسط Recovery تعیین تکلیف می‌شوند. توجه: تراکنش‌های بعد از Backup از دست می‌روند؛ وضعیت 3x-ui مستقل است و با DB V2 بازیابی نمی‌شود.

## مقصد خارجی
فقط لوکال پیاده شد (TODO #10 هنوز بی‌پاسخ). برای کپی خارجی: `rsync`/`rclone` را روی `GHIYAB_BACKUP_DIR` با cron بگذارید (کد لازم نیست).
