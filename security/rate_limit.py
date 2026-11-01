"""
Rate limiting درون‌پردازه (Token bucket) — مرزدار، بدون وابستگی و بدون نشت حافظه.

جایگزین debounce سراسریِ بی‌پایانِ V1 (`_last_action_at` که هیچ‌گاه پاک نمی‌شد):
- حداکثر ``max_keys`` کاربر نگه‌داری می‌شود؛ ورودی‌های قدیمی (غیرفعال > ttl) پاک می‌شوند.
- ادمین‌ها محدود نمی‌شوند (توسط صدازننده تصمیم‌گیری می‌شود).
یک پردازهٔ polling تک‌نمونه است؛ اگر روزی چندنمونه شد باید به DB/Redis برود (در SECURITY.md ثبت شده).
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict


class RateLimiter:
    def __init__(self, capacity: int = 8, refill_per_sec: float = 0.8, max_keys: int = 5000, ttl: float = 600.0,
                 clock=time.monotonic):
        self.capacity = capacity
        self.refill = refill_per_sec
        self.max_keys = max_keys
        self.ttl = ttl
        self._clock = clock
        self._buckets: "OrderedDict[int, list]" = OrderedDict()  # key -> [tokens, last_ts]
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "RateLimiter":
        def f(name, default, cast):
            try:
                return cast(os.getenv(name, default))
            except ValueError:
                return cast(default)
        return cls(capacity=max(1, f("GHIYAB_RL_BURST", "8", int)),
                   refill_per_sec=max(0.05, f("GHIYAB_RL_PER_SEC", "0.8", float)))

    def allow(self, key: int) -> bool:
        now = self._clock()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = [float(self.capacity), now]
                self._buckets[key] = b
                self._evict(now)
            else:
                b[0] = min(self.capacity, b[0] + (now - b[1]) * self.refill)
                b[1] = now
                self._buckets.move_to_end(key)
            if b[0] >= 1.0:
                b[0] -= 1.0
                return True
            return False

    def _evict(self, now: float) -> None:
        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)
        # پاک‌سازی تنبل: فقط از ابتدای صف (قدیمی‌ترین‌ها)
        for k in list(self._buckets.keys())[:20]:
            if now - self._buckets[k][1] > self.ttl:
                del self._buckets[k]
            else:
                break

    def __len__(self) -> int:
        return len(self._buckets)
