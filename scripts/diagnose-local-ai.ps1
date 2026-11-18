# Read-only diagnostic for local llama.cpp and Trading Simulator.
# Never prints environment variables, tokens, private strategies or model contents.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$models = Join-Path $root "models\private"
$logs = Join-Path $root ".local-state\logs"
Write-Host "[ai] Checking local llama.cpp connectivity..." -ForegroundColor Cyan
$server = Get-Command llama-server -ErrorAction SilentlyContinue
if ($server) {
    Write-Host "[ai] Executable: $($server.Source)"
} else {
    Write-Host "[ai] llama-server is not on PATH." -ForegroundColor Yellow
}
if (Test-Path -LiteralPath $models -PathType Container) {
    $weights = @(Get-ChildItem -LiteralPath $models -Filter "*.gguf" -File -ErrorAction SilentlyContinue)
    Write-Host "[ai] Local GGUF count: $($weights.Count)"
    foreach ($weight in $weights) { Write-Host "[ai] GGUF: $($weight.Name)" }
} else {
    Write-Host "[ai] Model folder missing: $models" -ForegroundColor Yellow
}
try {
    $listener = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8081 -State Listen -ErrorAction Stop)
    foreach ($entry in $listener) { Write-Host "[ai] TCP listener on port 8081, PID $($entry.OwningProcess)" }
    if ($listener.Count -eq 0) { Write-Host "[ai] No listener on 127.0.0.1:8081." -ForegroundColor Yellow }
} catch {
    Write-Host "[ai] No confirmed TCP listener on port 8081."
}
try {
    $modelsResponse = Invoke-RestMethod -Uri "http://127.0.0.1:8081/models" -TimeoutSec 4 -ErrorAction Stop
    Write-Host "[ai] Router GET /models succeeded." -ForegroundColor Green
    foreach ($item in @($modelsResponse.data)) {
        if ($item -and $item.id) { Write-Host "[ai] Available: $($item.id)" }
    }
} catch {
    Write-Host "[ai] Router GET /models failed ($($_.Exception.GetType().Name))." -ForegroundColor Yellow
}
try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/ai/status" -TimeoutSec 4 -ErrorAction Stop
    Write-Host "[app] Provider: $($status.provider); ready: $($status.ready); state: $($status.connection_state)"
} catch {
    Write-Host "[app] Backend AI status unavailable ($($_.Exception.GetType().Name))." -ForegroundColor Yellow
}
foreach ($name in @("ai.err.log","ai.out.log")) {
    $path = Join-Path $logs $name
    if (Test-Path -LiteralPath $path) {
        Write-Host "[ai] Last lines of $name :" -ForegroundColor Cyan
        Get-Content -LiteralPath $path -Tail 12 -ErrorAction SilentlyContinue
    }
}
