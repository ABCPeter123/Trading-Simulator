# Stop only services previously launched and tracked by start-local.ps1.
# Do not terminate a manually started llama.cpp server or another project.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$registry = Join-Path $root ".local-state\local-services.json"
if (-not (Test-Path $registry)) {
    Write-Host "[local] No tracked background services. Close older untracked terminal windows manually." -ForegroundColor Yellow
    exit 0
}
$services = Get-Content -LiteralPath $registry -Raw | ConvertFrom-Json
foreach ($property in $services.PSObject.Properties) {
    $name = $property.Name
    $item = $property.Value
    try {
        $process = Get-Process -Id ([int]$item.pid) -ErrorAction Stop
        $started = [datetime]::Parse([string]$item.started_utc).ToUniversalTime()
        $actual = $process.StartTime.ToUniversalTime()
        if ([math]::Abs(($actual - $started).TotalSeconds) -gt 5) {
            Write-Host "[$name] PID was reused. Refusing to stop unrelated process." -ForegroundColor Yellow
            continue
        }
        & taskkill.exe /PID $process.Id /T /F *> $null
        Write-Host "[$name] Stopped." -ForegroundColor Green
    } catch {
        Write-Host "[$name] Not running or inaccessible." -ForegroundColor DarkGray
    }
}
Remove-Item -LiteralPath $registry -Force
Write-Host "[local] Done. Existing data, strategy files and models were preserved." -ForegroundColor Cyan
