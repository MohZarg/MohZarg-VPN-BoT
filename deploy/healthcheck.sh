#!/usr/bin/env bash
# Thin wrapper: repo healthcheck from the deployment directory.
set -euo pipefail
APP_DIR="${GHIYAB_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="$APP_DIR/venv/bin/python"
[ -x "$PY" ] || PY="${PYTHON:-python3}"
exec "$PY" -m tools.healthcheck "$@"
