"""
Structured logging امن:
- Redaction: توکن ربات تلگرام (`bot<digits>:<secret>`)، `Bearer ...`، مقادیر `token=`/`password=` ماسک می‌شوند.
- لاگ‌های httpx/httpcore روی WARNING (PTB در INFO کل URL شامل توکن ربات را لاگ می‌کند!).
- چرخش فایل (RotatingFileHandler) → مصرف دیسک محدود روی VPS ارزان.
خروجی JSON-lines اگر GHIYAB_LOG_JSON=1.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re

_PATTERNS = [
    (re.compile(r"bot\d{6,}:[A-Za-z0-9_\-]{20,}"), "bot<REDACTED>"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1<REDACTED>"),
    (re.compile(r"(?i)\b(token|password|secret|api_key)=([^\s&]+)"), r"\1=<REDACTED>"),
]


def redact(text: str) -> str:
    for rx, rep in _PATTERNS:
        text = rx.sub(rep, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        d = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
             "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            d["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(d, ensure_ascii=False)


def setup_logging() -> None:
    level = getattr(logging, os.getenv("GHIYAB_LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = _JsonFormatter() if os.getenv("GHIYAB_LOG_JSON") == "1" else logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_dir = os.getenv("GHIYAB_LOG_DIR", "")
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "ghyiab.log"), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"))
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactingFilter())
        root.addHandler(h)
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "telegram.ext.ExtBot", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
