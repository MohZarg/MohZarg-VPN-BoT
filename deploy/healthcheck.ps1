# GhYiAb V2 - Windows healthcheck wrapper.
$ErrorActionPreference = "Stop"
$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Py = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
Set-Location $AppDir
& $Py -m tools.healthcheck @args
exit $LASTEXITCODE
