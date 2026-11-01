# GhYiAb V2 - Windows helper: venv + deps + .env + schema + healthcheck.
# Idempotent; never overwrites an existing .env.
$ErrorActionPreference = "Stop"
$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $AppDir

$python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if ($python -eq "py") { & py -3 -m venv .venv } else { & python -m venv .venv }
}
$py = Join-Path $AppDir ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    # .env.example uses Linux absolute paths; make a fresh Windows install work.
    $envPath = Join-Path $AppDir ".env"
    $content = Get-Content $envPath -Raw
    $content = $content -replace '(?m)^GHIYAB_DB_PATH=.*$', 'GHIYAB_DB_PATH=ghyiab_v2.db'
    $content = $content -replace '(?m)^GHIYAB_BACKUP_DIR=.*$', 'GHIYAB_BACKUP_DIR=backups'
    $content = $content -replace '(?m)^GHIYAB_LOG_DIR=.*$', 'GHIYAB_LOG_DIR=logs'
    [System.IO.File]::WriteAllText($envPath, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Created .env from .env.example - edit it before starting the bot."
} else {
    Write-Host "Keeping existing .env (not overwritten)."
}

$env:GHIYAB_ENV_FILE = (Join-Path $AppDir ".env")
& $py -m tools.init_db
if ($LASTEXITCODE -ne 0) { Write-Warning "Set TELEGRAM_OWNER_ID in .env, then re-run." }
& $py -m tools.healthcheck
Write-Host "Install complete."
