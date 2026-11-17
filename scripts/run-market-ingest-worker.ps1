$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python is not configured. Run .\start-local.ps1 -SetupOnly first."
}
$env:TRADING_SIM_PUBLIC_DEMO = "0"
& $python -m backend.market_ingest_worker --interval 30
exit $LASTEXITCODE
