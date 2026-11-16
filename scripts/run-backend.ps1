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
        if ($line -match '^\s*(TRADING_SIM_AI_PROVIDER|TRADING_SIM_AI_MODEL|OPENAI_API_KEY)\s*=\s*(.+)') {
            $key = $Matches[1]
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}
& $python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
