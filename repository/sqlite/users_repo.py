from __future__ import annotations
import sqlite3
from typing import Sequence
from repository.interface import UserRecord
from repository.sqlite._util import paged, like_escape


class SqliteUsersRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def get_or_create(self, user_id: int) -> UserRecord:
        row = self._c.execute(
            "SELECT user_id, is_agent, is_banned, has_accepted_rules, referred_by, "
            "last_test_date, phone_number, phone_verified, last_dice_at, blocked_by_bot, "
            "reseller_tier_id, created_at FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if row is None:
            self._c.execute(
                "INSERT INTO users (user_id, created_at) VALUES (?, datetime('now'))",
                (user_id,),
            )
            return UserRecord(
                user_id=user_id, is_agent=False, is_banned=False,
                has_accepted_rules=False, referred_by=0, last_test_date=None,
                phone_number=None, phone_verified=False, last_dice_at=None,
                blocked_by_bot=False,
            )
        return UserRecord(
            user_id=row[0], is_agent=bool(row[1]), is_banned=bool(row[2]),
            has_accepted_rules=bool(row[3]), referred_by=row[4],
            last_test_date=row[5], phone_number=row[6],
            phone_verified=bool(row[7]), last_dice_at=row[8],
            blocked_by_bot=bool(row[9]),
            reseller_tier_id=row[10], created_at=row[11],
        )

    def get_lang(self, user_id: int) -> str:
        r = self._c.execute("SELECT lang FROM users WHERE user_id=?", (user_id,)).fetchone()
        return r[0] if r and r[0] else "fa"

    def set_lang(self, user_id: int, lang: str) -> None:
        self._c.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))

    def set_banned(self, user_id: int, banned: bool) -> None:
        self._c.execute("UPDATE users SET is_banned=? WHERE user_id=?", (int(banned), user_id))

    def set_agent(self, user_id: int, is_agent: bool) -> None:
        self._c.execute("UPDATE users SET is_agent=? WHERE user_id=?", (int(is_agent), user_id))

    def set_accepted_rules(self, user_id: int) -> None:
        self._c.execute("UPDATE users SET has_accepted_rules=1 WHERE user_id=?", (user_id,))

    def set_referred_by(self, user_id: int, referrer_id: int) -> None:
        self._c.execute(
            "UPDATE users SET referred_by=? WHERE user_id=? AND referred_by=0",
            (referrer_id, user_id),
        )

    def set_last_test_date(self, user_id: int, date_str: str) -> None:
        self._c.execute("UPDATE users SET last_test_date=? WHERE user_id=?", (date_str, user_id))

    def set_last_dice_at(self, user_id: int, iso_ts: str) -> None:
        self._c.execute("UPDATE users SET last_dice_at=? WHERE user_id=?", (iso_ts, user_id))

    def set_phone(self, user_id: int, phone: str) -> None:
        self._c.execute(
            "UPDATE users SET phone_number=?, phone_verified=1 WHERE user_id=?",
            (phone, user_id),
        )

    def set_blocked_by_bot(self, user_id: int, blocked: bool) -> None:
        self._c.execute(
            "UPDATE users SET blocked_by_bot=? WHERE user_id=?", (int(blocked), user_id)
        )

    def count_all(self) -> int:
        return self._c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def list_ids_not_blocked(self) -> Sequence[int]:
        rows = self._c.execute(
            "SELECT user_id FROM users WHERE blocked_by_bot=0 OR blocked_by_bot IS NULL"
        ).fetchall()
        return [r[0] for r in rows]

    _COLS = ("user_id, is_agent, is_banned, has_accepted_rules, referred_by, last_test_date, "
             "phone_number, phone_verified, last_dice_at, blocked_by_bot, reseller_tier_id, created_at")

    @staticmethod
    def _map(row) -> UserRecord:
        return UserRecord(
            user_id=row[0], is_agent=bool(row[1]), is_banned=bool(row[2]),
            has_accepted_rules=bool(row[3]), referred_by=row[4], last_test_date=row[5],
            phone_number=row[6], phone_verified=bool(row[7]), last_dice_at=row[8],
            blocked_by_bot=bool(row[9]), reseller_tier_id=row[10], created_at=row[11],
        )

    def exists(self, user_id: int) -> bool:
        return self._c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone() is not None

    def set_reseller_tier(self, user_id: int, tier_id) -> None:
        self._c.execute("UPDATE users SET reseller_tier_id=? WHERE user_id=?", (tier_id, user_id))

    def count_referred_by(self, referrer_id: int) -> int:
        return self._c.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by=?", (referrer_id,)
        ).fetchone()[0]

    def list_all_ids(self):
        return [r[0] for r in self._c.execute("SELECT user_id FROM users").fetchall()]

    _FILTERS = {
        "all": "1=1", "banned": "is_banned=1", "agents": "is_agent=1",
        "blocked": "blocked_by_bot=1", "verified": "phone_verified=1",
    }

    def page(self, *, flt: str = "all", query=None, page: int = 0, per_page: int = 8):
        cond = self._FILTERS.get(flt, "1=1")
        params: list = []
        if query:
            q = query.strip()
            if q.isdigit():
                cond += " AND (user_id=? OR phone_number LIKE ? ESCAPE '\\')"
                params += [int(q), f"%{like_escape(q)}%"]
            else:
                cond += " AND 0=1"
        return paged(
            self._c, columns=self._COLS, frm="users", where=f"WHERE {cond}", params=params,
            order="user_id DESC", page=page, per_page=per_page, mapper=self._map,
        )
