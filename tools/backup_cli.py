"""
CLI سبک Backup/Restore (بدون وابستگی اضافه):

    python -m tools.backup_cli create  [--db PATH] [--dir DIR]
    python -m tools.backup_cli verify  BACKUP_FILE
    python -m tools.backup_cli restore BACKUP_FILE [--db PATH]     # ربات را قبلاً متوقف کنید

پیش‌فرض‌ها از GHIYAB_DB_PATH / GHIYAB_BACKUP_DIR خوانده می‌شود.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="backup_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--db"); c.add_argument("--dir")
    v = sub.add_parser("verify"); v.add_argument("file")
    r = sub.add_parser("restore"); r.add_argument("file"); r.add_argument("--db")
    args = ap.parse_args(argv)
    from core.system.service import verify_backup, restore_backup, _apply_retention
    db = getattr(args, "db", None) or os.getenv("GHIYAB_DB_PATH", "ghyiab_v2.db")

    if args.cmd == "create":
        bdir = args.dir or os.getenv("GHIYAB_BACKUP_DIR", "backups")
        os.makedirs(bdir, exist_ok=True)
        dest = os.path.join(bdir, f"ghyiab_backup_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.db")
        src = sqlite3.connect(db)
        try:
            src.execute("VACUUM INTO ?", (dest,))
        finally:
            src.close()
        res = verify_backup(dest)
        print(dest, res)
        keep = int(os.getenv("GHIYAB_BACKUP_RETENTION", "7"))
        if keep > 0:
            _apply_retention(bdir, keep)
        return 0 if res["ok"] else 2
    if args.cmd == "verify":
        res = verify_backup(args.file)
        print(res)
        return 0 if res["ok"] else 2
    aside = restore_backup(args.file, db)
    print(f"restored. previous DB kept at: {aside}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
