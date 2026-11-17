$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python environment is missing. Run start-local.ps1 first."
}

# Read only allowlisted settings from the local, git-ignored file.
# Never evaluate the file as PowerShell or print API keys.
$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*(TRADING_SIM_AI_PROVIDER|TRADING_SIM_AI_MODEL|TRADING_SIM_AI_TIMEOUT_SECONDS|OPENAI_API_KEY)\s*=\s*(.+)') {
            $key = $Matches[1]
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}
# Only this loopback-bound development process bypasses remote authentication.
# The private Cloudflare bridge starts a separate process with independent
# authorization settings and must continue requiring login.
$env:TRADING_SIM_PRIVATE_BRIDGE = "0"
$env:TRADING_SIM_PUBLIC_DEMO = "0"
Write-Host "[local] FastAPI bound to 127.0.0.1:8000. No local login required." -ForegroundColor Cyan
& $python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
