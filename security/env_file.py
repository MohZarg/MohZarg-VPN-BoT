"""بارگذار .env سبک (stdlib) — هرگز متغیرهای موجود در محیط را بازنویسی نمی‌کند و مقداری را لاگ نمی‌کند."""
from __future__ import annotations

import os


def load_env_file(path: str | None = None) -> int:
    path = path or os.getenv("GHIYAB_ENV_FILE", ".env")
    if not os.path.isfile(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v
                n += 1
    return n
