$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python environment is missing. Run start-local.ps1 first."
}
# Load only explicit AI settings from the private, git-ignored .env file.
# Do not evaluate its content as shell commands or print any credentials.
$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*(TRADING_SIM_AI_PROVIDER|TRADING_SIM_AI_MODEL|OPENAI_API_KEY)\s*=\s*(.*?)\s*
) {
            $key = $Matches[1]
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}
& $python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
