# Deployment

Two independent processes: the bot (`ghyiab-v2`) and 3x-ui. They talk only over the 3x-ui REST API.

## Fresh server (Linux)

```bash
sudo git clone <repo> /opt/ghyiab-v2
cd /opt/ghyiab-v2
sudo bash deploy/install.sh
sudo nano /etc/ghyiab-v2/env     # token, owner id, channel id
sudo bash deploy/install.sh      # idempotent re-run: schema + service
sudo deploy/healthcheck.sh --strict
```

Installer guarantees: idempotent, non-destructive, never overwrites `.env`, sets `600` on the env file, creates a dedicated system user and data/log dirs, substitutes the real app path into the systemd unit, starts the service only when a token is present.

## Update

```bash
sudo bash deploy/update.sh
```

`pull → dependencies → idempotent schema → healthcheck → restart`. It does not restart when the healthcheck fails. Set `GHIYAB_SKIP_PULL=1` to skip `git pull`.

## Windows / local development

```powershell
powershell -ExecutionPolicy Bypass -File deploy\install.ps1
.\.venv\Scripts\python.exe -m adapters.telegram_bot.bot
```

## Healthcheck

`python -m tools.healthcheck [--strict]` checks DB file/integrity/WAL/critical tables, backup dir writability, Telegram env presence, and reports 3x-ui as `CONFIGURED`/`NOT_CONFIGURED` (no network call, no secrets printed).

## CI

`.github/workflows/ci.yml`: compile, dependency check, security scan, pytest, fresh-install simulation (schema + strict healthcheck + backup CLI + app build) on Python 3.12/3.13.
