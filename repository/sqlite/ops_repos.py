"""Repositoryهای Tickets / Broadcasts / Confirmations / Jobs / Provisioning / Reports."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from repository.interface import (
    TicketRecord, TicketMessageRecord, BroadcastRecord, ConfirmationRecord, JobRecord,
    ProvisioningProfileRecord, ProvisionedClientRecord, RenewalRecord,
)
from repository.sqlite._util import paged


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class SqliteTicketsRepository:
    _T = "id, user_id, subject, status, created_at, updated_at"

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, user_id: int, subject: str, body: str) -> TicketRecord:
        cur = self._c.execute(
            "INSERT INTO tickets (user_id, subject, status, created_at, updated_at) "
            "VALUES (?, ?, 'OPEN', datetime('now'), datetime('now'))", (user_id, subject))
        tid = cur.lastrowid
        self.add_message(tid, user_id, False, body)
        return self.get(tid)

    def get(self, ticket_id: int):
        r = self._c.execute(f"SELECT {self._T} FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return TicketRecord(*r) if r else None

    def add_message(self, ticket_id, sender_id, is_staff, body) -> TicketMessageRecord:
        cur = self._c.execute(
            "INSERT INTO ticket_messages (ticket_id, sender_id, is_staff, body, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))", (ticket_id, sender_id, int(is_staff), body))
        self._c.execute("UPDATE tickets SET updated_at=datetime('now') WHERE id=?", (ticket_id,))
        r = self._c.execute("SELECT id, ticket_id, sender_id, is_staff, body, created_at "
                            "FROM ticket_messages WHERE id=?", (cur.lastrowid,)).fetchone()
        return TicketMessageRecord(r[0], r[1], r[2], bool(r[3]), r[4], r[5])

    def set_status(self, ticket_id: int, status: str) -> None:
        self._c.execute("UPDATE tickets SET status=?, updated_at=datetime('now') WHERE id=?",
                        (status, ticket_id))

    def messages(self, ticket_id: int, limit: int = 20):
        rows = self._c.execute(
            "SELECT id, ticket_id, sender_id, is_staff, body, created_at FROM ticket_messages "
            "WHERE ticket_id=? ORDER BY id DESC LIMIT ?", (ticket_id, limit)).fetchall()
        return [TicketMessageRecord(r[0], r[1], r[2], bool(r[3]), r[4], r[5]) for r in reversed(rows)]

    def page(self, *, status=None, user_id=None, page: int = 0, per_page: int = 8):
        conds, params = [], []
        if status:
            conds.append("status=?"); params.append(status)
        if user_id is not None:
            conds.append("user_id=?"); params.append(user_id)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return paged(self._c, columns=self._T, frm="tickets", where=where, params=params,
                     order="updated_at DESC, id DESC", page=page, per_page=per_page,
                     mapper=lambda r: TicketRecord(*r))

    def count_open_for_user(self, user_id: int) -> int:
        return self._c.execute(
            "SELECT COUNT(*) FROM tickets WHERE user_id=? AND status IN ('OPEN','ANSWERED')",
            (user_id,)).fetchone()[0]

    def count_by_status(self, status: str) -> int:
        return self._c.execute("SELECT COUNT(*) FROM tickets WHERE status=?", (status,)).fetchone()[0]


class SqliteBroadcastsRepository:
    _C = "id, actor_id, text, status, total, sent, failed, created_at, finished_at"

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, actor_id: int, text: str, total: int) -> BroadcastRecord:
        cur = self._c.execute(
            "INSERT INTO broadcasts (actor_id, text, total, created_at) VALUES (?, ?, ?, datetime('now'))",
            (actor_id, text, total))
        return self.get(cur.lastrowid)

    def get(self, broadcast_id: int):
        r = self._c.execute(f"SELECT {self._C} FROM broadcasts WHERE id=?", (broadcast_id,)).fetchone()
        return BroadcastRecord(*r) if r else None

    def update_progress(self, broadcast_id: int, sent: int, failed: int) -> None:
        self._c.execute("UPDATE broadcasts SET sent=?, failed=? WHERE id=?", (sent, failed, broadcast_id))

    def set_status(self, broadcast_id: int, status: str) -> None:
        fin = ", finished_at=datetime('now')" if status in ("DONE", "CANCELLED") else ""
        self._c.execute(f"UPDATE broadcasts SET status=?{fin} WHERE id=?", (status, broadcast_id))

    def page(self, *, page: int = 0, per_page: int = 8):
        return paged(self._c, columns=self._C, frm="broadcasts", where="", params=[], order="id DESC",
                     page=page, per_page=per_page, mapper=lambda r: BroadcastRecord(*r))


class SqliteConfirmationsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def create(self, token, actor_id, action, payload_json, ttl_seconds) -> None:
        now = datetime.now(timezone.utc)
        self._c.execute(
            "INSERT INTO confirmations (token, actor_id, action, payload_json, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token, actor_id, action, payload_json, now.strftime("%Y-%m-%d %H:%M:%S"),
             (now + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")))

    def get(self, token: str):
        r = self._c.execute("SELECT token, actor_id, action, payload_json, created_at, expires_at, "
                            "consumed_at FROM confirmations WHERE token=?", (token,)).fetchone()
        return ConfirmationRecord(*r) if r else None

    def consume(self, token: str) -> bool:
        cur = self._c.execute(
            "UPDATE confirmations SET consumed_at=? WHERE token=? AND consumed_at IS NULL",
            (_now_iso(), token))
        return cur.rowcount > 0

    def purge_expired(self) -> int:
        cur = self._c.execute(
            "DELETE FROM confirmations WHERE expires_at < datetime('now', '-1 day')")
        return cur.rowcount


class SqliteJobsRepository:
    _C = "name, enabled, interval_minutes, last_run_at, last_status, last_detail"

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    @staticmethod
    def _j(r):
        return JobRecord(r[0], bool(r[1]), r[2], r[3], r[4], r[5])

    def ensure(self, name: str, interval_minutes: int) -> None:
        self._c.execute("INSERT OR IGNORE INTO jobs (name, interval_minutes) VALUES (?, ?)",
                        (name, interval_minutes))

    def get(self, name: str):
        r = self._c.execute(f"SELECT {self._C} FROM jobs WHERE name=?", (name,)).fetchone()
        return self._j(r) if r else None

    def list_all(self):
        return [self._j(r) for r in self._c.execute(f"SELECT {self._C} FROM jobs ORDER BY name").fetchall()]

    def set_enabled(self, name: str, enabled: bool) -> None:
        self._c.execute("UPDATE jobs SET enabled=? WHERE name=?", (int(enabled), name))

    def record_run(self, name: str, status: str, detail: str) -> None:
        self._c.execute(
            "UPDATE jobs SET last_run_at=datetime('now'), last_status=?, last_detail=? WHERE name=?",
            (status, detail[:500], name))


class SqliteProvisioningRepository:
    _P = "id, product_id, provider_name, inbound_id, duration_days, traffic_gb, limit_ip, is_active, created_at"
    _K = ("id, order_id, provider_name, inbound_id, client_uuid, email, sub_id, expires_at_ms, status, "
          "last_error, auto_renew, auto_renew_consent_at, created_at, attempts, notified_expiry_ms, "
          "cached_used_bytes, cached_total_bytes, synced_at")

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    @staticmethod
    def _p(r):
        return ProvisioningProfileRecord(r[0], r[1], r[2], r[3], r[4], r[5], r[6], bool(r[7]), r[8])

    @staticmethod
    def _k(r):
        return ProvisionedClientRecord(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                                       bool(r[10]), r[11], r[12], r[13], r[14], r[15], r[16], r[17])

    def upsert_profile(self, product_id, provider_name, inbound_id, duration_days, traffic_gb, limit_ip):
        self._c.execute(
            "INSERT INTO provisioning_profiles (product_id, provider_name, inbound_id, duration_days, "
            "traffic_gb, limit_ip, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(product_id) DO UPDATE SET provider_name=excluded.provider_name, "
            "inbound_id=excluded.inbound_id, duration_days=excluded.duration_days, "
            "traffic_gb=excluded.traffic_gb, limit_ip=excluded.limit_ip",
            (product_id, provider_name, inbound_id, duration_days, traffic_gb, limit_ip))
        return self.get_profile(product_id)

    def get_profile(self, product_id: int):
        r = self._c.execute(f"SELECT {self._P} FROM provisioning_profiles WHERE product_id=?",
                            (product_id,)).fetchone()
        return self._p(r) if r else None

    def list_profiles(self):
        return [self._p(r) for r in self._c.execute(
            f"SELECT {self._P} FROM provisioning_profiles ORDER BY id").fetchall()]

    def set_profile_active(self, product_id: int, active: bool) -> None:
        self._c.execute("UPDATE provisioning_profiles SET is_active=? WHERE product_id=?",
                        (int(active), product_id))

    def create_client(self, order_id, provider_name, inbound_id, client_uuid, email, sub_id, expires_at_ms):
        self._c.execute(
            "INSERT INTO provisioned_clients (order_id, provider_name, inbound_id, client_uuid, email, "
            "sub_id, expires_at_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (order_id, provider_name, inbound_id, client_uuid, email, sub_id, expires_at_ms))
        return self.get_client_by_order(order_id)

    def get_client_by_order(self, order_id: int):
        r = self._c.execute(f"SELECT {self._K} FROM provisioned_clients WHERE order_id=?",
                            (order_id,)).fetchone()
        return self._k(r) if r else None

    def set_client_status(self, order_id: int, status: str, error=None) -> None:
        self._c.execute("UPDATE provisioned_clients SET status=?, last_error=? WHERE order_id=?",
                        (status, error, order_id))

    def list_clients(self, status: str):
        return [self._k(r) for r in self._c.execute(
            f"SELECT {self._K} FROM provisioned_clients WHERE status=? ORDER BY id", (status,)).fetchall()]

    def set_auto_renew(self, order_id: int, enabled: bool, consent_at) -> None:
        self._c.execute("UPDATE provisioned_clients SET auto_renew=?, auto_renew_consent_at=? WHERE order_id=?",
                        (int(enabled), consent_at, order_id))

    def set_expiry(self, order_id: int, expires_at_ms: int) -> None:
        self._c.execute("UPDATE provisioned_clients SET expires_at_ms=? WHERE order_id=?",
                        (expires_at_ms, order_id))

    def list_expiring(self, before_ms: int):
        return [self._k(r) for r in self._c.execute(
            f"SELECT {self._K} FROM provisioned_clients WHERE status='ACTIVE' AND auto_renew=1 "
            "AND expires_at_ms > 0 AND expires_at_ms <= ? ORDER BY expires_at_ms", (before_ms,)).fetchall()]


    # --- چرخهٔ عمر سرویس (V2 Final) ---
    def list_by_user(self, user_id: int):
        return [self._k(r) for r in self._c.execute(
            "SELECT " + ", ".join("pc." + c.strip() for c in self._K.split(",")) +
            " FROM provisioned_clients pc JOIN orders o ON o.id = pc.order_id "
            "WHERE o.user_id=? ORDER BY pc.id DESC", (user_id,)).fetchall()]

    def list_active_expired(self, before_ms: int):
        return [self._k(r) for r in self._c.execute(
            f"SELECT {self._K} FROM provisioned_clients WHERE status='ACTIVE' "
            "AND expires_at_ms > 0 AND expires_at_ms <= ? ORDER BY expires_at_ms", (before_ms,)).fetchall()]

    def list_active_expiring_soon(self, before_ms: int, not_notified_for_ms: int):
        """ACTIVEهایی که تا before_ms منقضی می‌شوند و برای همین انقضا هنوز یادآوری نشده‌اند."""
        return [self._k(r) for r in self._c.execute(
            f"SELECT {self._K} FROM provisioned_clients WHERE status='ACTIVE' "
            "AND expires_at_ms > 0 AND expires_at_ms <= ? AND notified_expiry_ms <> expires_at_ms "
            "AND expires_at_ms > ? ORDER BY expires_at_ms",
            (before_ms, not_notified_for_ms)).fetchall()]

    def bump_attempts(self, order_id: int) -> int:
        self._c.execute("UPDATE provisioned_clients SET attempts=attempts+1 WHERE order_id=?", (order_id,))
        r = self._c.execute("SELECT attempts FROM provisioned_clients WHERE order_id=?", (order_id,)).fetchone()
        return r[0] if r else 0

    def set_notified(self, order_id: int, expiry_ms: int) -> None:
        self._c.execute("UPDATE provisioned_clients SET notified_expiry_ms=? WHERE order_id=?", (expiry_ms, order_id))

    def set_cache(self, order_id: int, used: int, total: int, expires_at_ms: int) -> None:
        self._c.execute(
            "UPDATE provisioned_clients SET cached_used_bytes=?, cached_total_bytes=?, expires_at_ms=?, "
            "synced_at=datetime('now') WHERE order_id=?", (used, total, expires_at_ms, order_id))

    def count_by_status(self) -> dict:
        return {r[0]: r[1] for r in self._c.execute(
            "SELECT status, COUNT(*) FROM provisioned_clients GROUP BY status").fetchall()}

    def reset_for_retry(self, order_id: int, client_uuid: str) -> None:
        """بعد از Retry موفقِ ساخت (adopt/create)، رکورد قبلی FAILED را تازه می‌کند."""
        self._c.execute("UPDATE provisioned_clients SET client_uuid=?, last_error=NULL WHERE order_id=?",
                        (client_uuid, order_id))


class SqliteRenewalsRepository:
    _C = ("id, order_id, user_id, amount_minor, currency, idempotency_key, new_expiry_ms, total_bytes, "
          "status, source, error, created_at, resolved_at")

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    @staticmethod
    def _r(r):
        return RenewalRecord(*r)

    def create(self, order_id, user_id, amount_minor, currency, key, new_expiry_ms, total_bytes, source):
        self._c.execute(
            "INSERT INTO service_renewals (order_id, user_id, amount_minor, currency, idempotency_key, "
            "new_expiry_ms, total_bytes, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (order_id, user_id, amount_minor, currency, key, new_expiry_ms, total_bytes, source))
        return self.get_by_key(key)

    def get_by_key(self, key: str):
        r = self._c.execute(f"SELECT {self._C} FROM service_renewals WHERE idempotency_key=?", (key,)).fetchone()
        return self._r(r) if r else None

    def set_status(self, renewal_id: int, status: str, error=None) -> None:
        self._c.execute(
            "UPDATE service_renewals SET status=?, error=?, resolved_at=CASE WHEN ? IN ('COMPLETED','REFUNDED') "
            "THEN datetime('now') ELSE resolved_at END WHERE id=?", (status, error, status, renewal_id))

    def list_stuck(self, older_than_minutes: int):
        return [self._r(r) for r in self._c.execute(
            f"SELECT {self._C} FROM service_renewals WHERE status='CHARGED' "
            "AND created_at <= datetime('now', ?) ORDER BY id", (f"-{int(older_than_minutes)} minutes",)).fetchall()]

    def list_for_order(self, order_id: int):
        return [self._r(r) for r in self._c.execute(
            f"SELECT {self._C} FROM service_renewals WHERE order_id=? ORDER BY id DESC", (order_id,)).fetchall()]


class SqliteReportsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def _n(self, sql: str, *p) -> int:
        return self._c.execute(sql, p).fetchone()[0] or 0

    def dashboard(self) -> dict:
        return {
            "users_total": self._n("SELECT COUNT(*) FROM users"),
            "users_today": self._n("SELECT COUNT(*) FROM users WHERE date(created_at)=date('now')"),
            "users_banned": self._n("SELECT COUNT(*) FROM users WHERE is_banned=1"),
            "agents": self._n("SELECT COUNT(*) FROM users WHERE is_agent=1"),
            "orders_total": self._n("SELECT COUNT(*) FROM orders WHERE status='COMPLETED'"),
            "orders_today": self._n(
                "SELECT COUNT(*) FROM orders WHERE status='COMPLETED' AND date(created_at)=date('now')"),
            "orders_problem": self._n("SELECT COUNT(*) FROM orders WHERE status IN ('PROVISIONING','FAILED')"),
            "pending_charge": self._n("SELECT COUNT(*) FROM pending_requests WHERE status='pending' AND type='charge'"),
            "pending_buy": self._n("SELECT COUNT(*) FROM pending_requests WHERE status='pending' AND type='buy'"),
            "pending_agency": self._n("SELECT COUNT(*) FROM pending_requests WHERE status='pending' AND type='agency'"),
            "tickets_open": self._n("SELECT COUNT(*) FROM tickets WHERE status IN ('OPEN','ANSWERED')"),
            "stock_total": self._n("SELECT COUNT(*) FROM inventory_items WHERE status='AVAILABLE'"),
        }

    def revenue(self) -> dict:
        rows = self._c.execute(
            "SELECT currency, "
            "COALESCE(SUM(CASE WHEN date(created_at)=date('now') THEN price_minor END),0), "
            "COALESCE(SUM(price_minor),0) FROM orders WHERE status='COMPLETED' GROUP BY currency").fetchall()
        return {r[0]: {"today": r[1], "total": r[2]} for r in rows}

    def liabilities(self) -> dict:
        rows = self._c.execute(
            "SELECT currency, COALESCE(SUM(amount_minor),0), COUNT(*) FROM wallets "
            "WHERE amount_minor<>0 GROUP BY currency").fetchall()
        return {r[0]: {"sum": r[1], "wallets": r[2]} for r in rows}

    def low_stock(self, threshold: int):
        return self._c.execute(
            "SELECT p.id, p.name, COALESCE(SUM(CASE WHEN i.status='AVAILABLE' THEN 1 ELSE 0 END),0) AS c "
            "FROM products p LEFT JOIN inventory_items i ON i.product_id=p.id "
            "WHERE p.is_active=1 GROUP BY p.id HAVING c <= ? ORDER BY c, p.id", (threshold,)).fetchall()
