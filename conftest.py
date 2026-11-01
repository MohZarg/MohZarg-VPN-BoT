"""
Root conftest — با قرارگیری در ریشهٔ پروژه (نه داخل tests/)، pytest ریشهٔ
پروژه را به sys.path اضافه می‌کند تا importهای مطلق مثل `from core.wallet
import service` در تست‌ها کار کنند، بدون نیاز به نصب پکیج یا تنظیم
PYTHONPATH دستی.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# تست‌های Adapter عمداً بسیار سریع و پشت‌سرهم از یک کاربر Callback می‌زنند؛ Rate limit فقط در
# تست اختصاصی خودش (tests/test_security_hardening.py) فعال می‌شود.
import os as _os
_os.environ.setdefault("GHIYAB_RL_DISABLED", "1")
import tempfile as _tf
_os.environ.setdefault("GHIYAB_BACKUP_DIR", _tf.mkdtemp(prefix="ghyiab_bk_"))
