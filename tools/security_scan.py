"""Dependency-free static security scan for source and deploy files.

    python -m tools.security_scan

Flags likely secrets and dangerous API usage. Excludes tests/.venv/backups
(deliberate fake-server TLS and fixture tokens live there).
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".venv", "venv", "__pycache__", ".pytest_cache", "backups", "tests", "docs", ".git"}
RULES = (
    ("telegram_token", re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
    ("tls_verify_disabled", re.compile(r"\bverify\s*=\s*False\b")),
    ("shell_true", re.compile(r"\bshell\s*=\s*True\b")),
    ("os_system", re.compile(r"\bos\.system\s*\(")),
    ("eval_call", re.compile(r"(?<![\w.])eval\s*\(")),
    ("exec_call", re.compile(r"(?<![\w.])exec\s*\(")),
    ("pickle_loads", re.compile(r"\bpickle\.loads\s*\(")),
    ("debug_true", re.compile(r"\bdebug\s*=\s*True\b")),
)


def iter_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith((".py", ".sh", ".ps1", ".yml", ".yaml")):
                yield os.path.join(base, name)


def main() -> int:
    findings = []
    for path in iter_files():
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for lineno, line in enumerate(fh, 1):
                    for rule, rx in RULES:
                        if rx.search(line):
                            findings.append(f"{os.path.relpath(path, ROOT)}:{lineno}: {rule}")
        except OSError:
            continue
    for f in findings:
        print(f)
    print(f"security_scan: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
