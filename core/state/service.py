"""
GhYiAb V2 — Persistent Conversation State Service
=====================================================

جایگزین مستقیم dict سراسری `user_states` قدیمی (رفع P0-5 در Audit). این
ماژول فقط یک Wrapper نازک روی `StateRepository` است تا Adapter تلگرام دقیقاً
همان الگوی قبلی (`user_states[user_id] = ...` / `user_states.get(user_id)`)
را با یک API مشابه و ساده صدا بزند، بدون آنکه از جزئیات ذخیره‌سازی خبر داشته
باشد.
"""

from __future__ import annotations


class ConversationStateService:
    def __init__(self, state_repo):
        self._repo = state_repo

    def get(self, user_id: int):
        return self._repo.get(user_id)

    def set(self, user_id: int, state) -> None:
        self._repo.set(user_id, state)

    def clear(self, user_id: int) -> None:
        self._repo.clear(user_id)

    def purge_stale(self, hours: int = 24) -> int:
        return self._repo.purge_stale(hours)
