"""Idempotent schema/migration init for installers and CI.

    python -m tools.init_db

Reads GHIYAB_ENV_FILE (default .env) and GHIYAB_DB_PATH, then runs the
same idempotent schema initialization the bot runs at startup. Never prints
secret values.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    from security.env_file import load_env_file

    load_env_file()
    db_path = os.getenv("GHIYAB_DB_PATH", "ghyiab_v2.db")
    raw_owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    if not raw_owner.isdigit():
        print("ERROR: TELEGRAM_OWNER_ID must be set to a numeric Telegram user id.", file=sys.stderr)
        return 2
    from repository.sqlite.connection import init_schema

    init_schema(db_path, owner_user_id=int(raw_owner))
    print(f"schema ready: {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
