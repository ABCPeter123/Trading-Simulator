$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python environment is missing. Run start-local.ps1 first."
}
& $python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
