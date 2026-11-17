# Local-only portfolio research worker for the Vite development environment.
# Runs queued jobs in the owner's Git-ignored SQLite database. No Vercel usage.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python environment missing. Run start-local.ps1 to install dependencies."
}
& $python -m backend.research_worker --interval 3
exit $LASTEXITCODE
