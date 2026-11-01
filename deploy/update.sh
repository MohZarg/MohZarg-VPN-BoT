#!/usr/bin/env bash
# GhYiAb V2 — safe update: pull → deps → migrations → healthcheck → restart.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${GHIYAB_APP_DIR:-$SCRIPT_DIR}"
PY="$APP_DIR/venv/bin/python"
[ -x "$PY" ] || { echo "venv not found; run deploy/install.sh first" >&2; exit 1; }

if [ "${GHIYAB_SKIP_PULL:-0}" != "1" ] && command -v git >/dev/null 2>&1 \
   && git -C "$APP_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$APP_DIR" pull --ff-only
fi

"$PY" -m pip install -r "$APP_DIR/requirements.txt"

if GHIYAB_ENV_FILE="${GHIYAB_ENV_FILE:-$APP_DIR/.env}" "$PY" -m tools.init_db; then
  echo "Schema up to date."
else
  echo "Schema init skipped (configuration incomplete)." >&2
fi

GHIYAB_ENV_FILE="${GHIYAB_ENV_FILE:-$APP_DIR/.env}" "$PY" -m tools.healthcheck || {
  echo "Healthcheck failed — not restarting." >&2; exit 1; }

if command -v systemctl >/dev/null 2>&1 && systemctl is-enabled ghyiab-v2.service >/dev/null 2>&1; then
  systemctl restart ghyiab-v2.service
  systemctl is-active --quiet ghyiab-v2.service && echo "Service restarted."
fi
echo "Update complete."
