# V2 و 3x-ui روی یک VPS

1. 3x-ui را مثل همیشه نصب کنید (`/opt/3x-ui` یا مسیر نصب خودش). V2 هرگز به DB/فایل/Xray آن دست نمی‌زند.
2. در پنل 3x-ui: Settings → API Token بسازید (دسترسی ادمین) و یک Inbound بسازید؛ شمارهٔ inbound را یادداشت کنید.
3. پنل را روی loopback یا پورت داخلی نگه دارید؛ `webBasePath` را از تنظیمات پنل بخوانید.
4. در `/etc/ghyiab-v2/env`:
```
XUI_BASE_URL=http://127.0.0.1:2053/<webBasePath>
XUI_API_TOKEN=<token>
XUI_VERIFY_TLS=1
```
5. `systemctl restart ghyiab-v2` → ادمین: «Providerها» باید 🟢 نشان دهد.
6. برای هر محصول VPN: «پلن‌ها» ← محصول ← پروفایل Provisioning (inbound، مدت روز، حجم GB).

نکته: اگر پنل با HTTPS و گواهی self-signed روی loopback است، فقط برای همین حالت `XUI_VERIFY_TLS=0` بگذارید؛ برای آدرس خارجی هرگز.
مصرف منابع: 3x-ui/Xray و V2 هر دو سبک‌اند؛ برای ۱GB RAM کافی است (`MemoryMax` را در unit تنظیم کنید).
