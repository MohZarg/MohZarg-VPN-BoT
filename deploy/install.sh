#!/usr/bin/env bash
# GhYiAb V2 — idempotent installer (Linux). Safe to re-run; never overwrites .env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${GHIYAB_APP_DIR:-$SCRIPT_DIR}"
SERVICE_USER="${GHIYAB_SERVICE_USER:-ghyiab}"
DATA_DIR="${GHIYAB_DATA_DIR:-/var/lib/ghyiab-v2}"
LOG_DIR="${GHIYAB_LOG_DIR:-/var/log/ghyiab-v2}"
ETC_DIR="${GHIYAB_ETC_DIR:-/etc/ghyiab-v2}"
PYTHON="${PYTHON:-python3}"
IS_ROOT=0
[ "$(id -u)" -eq 0 ] && IS_ROOT=1

say() { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

command -v "$PYTHON" >/dev/null 2>&1 || { warn "python3 not found"; exit 1; }
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || { warn "Python 3.10+ required"; exit 1; }

if [ "$IS_ROOT" -eq 1 ]; then
  ENV_FILE="$ETC_DIR/env"
  mkdir -p "$ETC_DIR" "$DATA_DIR" "$DATA_DIR/backups" "$LOG_DIR"
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    say "Created system user $SERVICE_USER"
  fi
  chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" "$LOG_DIR" "$ETC_DIR"
else
  ENV_FILE="$APP_DIR/.env"
  warn "Not root: installing a local venv only (no system user/service/dirs)."
fi

if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cp "$APP_DIR/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  say "Created $ENV_FILE from .env.example — edit it before starting the bot."
else
  say "Keeping existing $ENV_FILE (not overwritten)."
fi

if [ ! -d "$APP_DIR/venv" ]; then
  "$PYTHON" -m venv "$APP_DIR/venv"
  say "Created venv."
fi
"$APP_DIR/venv/bin/python" -m pip install --upgrade pip >/dev/null
"$APP_DIR/venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
say "Dependencies installed."

if [ "$IS_ROOT" -eq 1 ]; then
  chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/venv"
fi

# Schema is idempotent; skipped with a clear message until TELEGRAM_OWNER_ID is set.
if GHIYAB_ENV_FILE="$ENV_FILE" "$APP_DIR/venv/bin/python" -m tools.init_db; then
  say "Database schema ready."
else
  warn "Set TELEGRAM_OWNER_ID in $ENV_FILE, then re-run this installer (or tools.init_db)."
fi

if [ "$IS_ROOT" -eq 1 ] && command -v systemctl >/dev/null 2>&1; then
  UNIT_SRC="$APP_DIR/deploy/ghyiab-v2.service"
  UNIT_DST="/etc/systemd/system/ghyiab-v2.service"
  if [ -f "$UNIT_SRC" ]; then
    sed -e "s#/opt/ghyiab-v2#$APP_DIR#g" -e "s#User=ghyiab#User=$SERVICE_USER#" \
      "$UNIT_SRC" > "$UNIT_DST"
    systemctl daemon-reload
    systemctl enable ghyiab-v2.service >/dev/null 2>&1 || warn "systemctl enable failed"
    say "Installed systemd unit."
    # Never start with an empty token; report instead.
    if grep -Eq '^TELEGRAM_BOT_TOKEN=[^[:space:]]+' "$ENV_FILE"; then
      systemctl restart ghyiab-v2.service
      say "Service (re)started."
    else
      say "TELEGRAM_BOT_TOKEN is empty — service enabled but not started. Edit $ENV_FILE then: systemctl start ghyiab-v2"
    fi
  fi
fi

GHIYAB_ENV_FILE="$ENV_FILE" "$APP_DIR/venv/bin/python" -m tools.healthcheck || true
say "Install complete. Re-run this script after changing configuration."
