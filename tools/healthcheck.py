"""Deployment healthcheck (no network, no secrets printed).

    python -m tools.healthcheck [--strict]

Checks: DB file/integrity/WAL/critical tables, backup dir writability,
required env presence, and 3x-ui configuration presence (NOT_CONFIGURED is
reported, not silently treated as success). Exit 1 on failures; with
--strict, env warnings also fail.
"""
from __future__ import annotations

import os
import sqlite3
import sys

REQUIRED_TABLES = (
    "users", "wallets", "wallet_transactions", "orders", "order_items",
    "audit_logs", "settings", "provisioned_clients", "pending_requests",
)


def main(argv=None) -> int:
    from security.env_file import load_env_file

    load_env_file()
    strict = "--strict" in (argv or sys.argv[1:])
    db_path = os.getenv("GHIYAB_DB_PATH", "ghyiab_v2.db")
    failures: list[str] = []
    warnings: list[str] = []

    if not os.path.isfile(db_path):
        failures.append(f"db_missing:{db_path}")
    else:
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
            if integrity != "ok":
                failures.append(f"db_integrity:{integrity}")
            else:
                print(f"OK db_integrity={integrity}")
            if journal.lower() != "wal":
                warnings.append(f"db_journal_mode:{journal}")
            else:
                print("OK db_journal_mode=wal")
            missing = [t for t in REQUIRED_TABLES if t not in have]
            if missing:
                failures.append("db_missing_tables:" + ",".join(missing))
            else:
                print(f"OK db_tables={len(have)}")
        except sqlite3.Error as exc:
            failures.append(f"db_error:{type(exc).__name__}")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    channel = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token:
        warnings.append("env_TELEGRAM_BOT_TOKEN_empty")
    if not owner.isdigit():
        warnings.append("env_TELEGRAM_OWNER_ID_invalid")
    if not channel:
        warnings.append("env_TELEGRAM_CHANNEL_ID_empty")
    if token and owner.isdigit() and channel:
        print("OK telegram_env=configured")

    xui = bool(os.getenv("XUI_BASE_URL", "").strip() and os.getenv("XUI_API_TOKEN", "").strip())
    print(f"INFO xui={'CONFIGURED' if xui else 'NOT_CONFIGURED'}")

    backup_dir = os.getenv("GHIYAB_BACKUP_DIR", "backups")
    if os.path.isdir(backup_dir):
        if not os.access(backup_dir, os.W_OK):
            warnings.append(f"backup_dir_not_writable:{backup_dir}")
        else:
            print("OK backup_dir=writable")
    else:
        warnings.append(f"backup_dir_missing:{backup_dir}")

    for w in warnings:
        print(("FAIL " if strict else "WARN ") + w)
    for f in failures:
        print("FAIL " + f)
    if failures or (strict and warnings):
        return 1
    print("HEALTHY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
