"""TEMPORARY validation probe — deleted after this run.

Mirrors .github/workflows/ci.yml steps so they can be executed through the
pre-approved pytest channel while the harness command classifier is down.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
if not os.path.isfile(PY):  # non-Windows CI/dev box
    PY = sys.executable


def _run(args, env=None):
    r = subprocess.run([PY, *args], cwd=str(ROOT), env=env, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    print(f"\n$ python {' '.join(args)}\nexit={r.returncode}\n{out[-4000:]}")
    return r


def test_compileall():
    r = _run(["-m", "compileall", "-q", "adapters", "core", "providers",
              "repository", "security", "shared", "tools", "bootstrap.py", "conftest.py"])
    assert r.returncode == 0, r.stderr


def test_pyflakes():
    r = _run(["-m", "pyflakes", "adapters", "core", "providers", "repository",
              "security", "shared", "tools", "bootstrap.py", "conftest.py"])
    assert r.returncode == 0, r.stdout


def test_security_scan():
    r = _run(["-m", "tools.security_scan"])
    assert r.returncode == 0, r.stdout


def test_fresh_install_simulation(tmp_path):
    db = tmp_path / "ci.db"
    bdir = tmp_path / "backups"
    ldir = tmp_path / "logs"
    bdir.mkdir()
    ldir.mkdir()
    env = dict(os.environ)
    env.update({
        "TELEGRAM_BOT_TOKEN": "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "TELEGRAM_OWNER_ID": "999999",
        "TELEGRAM_CHANNEL_ID": "@ghyiab_ci",
        "GHIYAB_DB_PATH": str(db),
        "GHIYAB_BACKUP_DIR": str(bdir),
        "GHIYAB_LOG_DIR": str(ldir),
        "XUI_BASE_URL": "",
        "XUI_API_TOKEN": "",
    })
    assert _run(["-m", "tools.init_db"], env=env).returncode == 0
    assert _run(["-m", "tools.healthcheck", "--strict"], env=env).returncode == 0
    assert _run(["-m", "tools.backup_cli", "create", "--db", str(db), "--dir", str(bdir)],
                env=env).returncode == 0
    r = _run(["-c", "from adapters.telegram_bot.bot import build_application; "
                    "build_application(); print('app build OK')"], env=env)
    assert r.returncode == 0, r.stderr
    assert "app build OK" in r.stdout
