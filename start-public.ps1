# Start a temporary, public Cloudflare Tunnel with fully isolated demo data.
param([switch]$SkipSetup)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$demo = Join-Path $root ".local-state\public-demo"
New-Item -ItemType Directory -Path $demo -Force | Out-Null

$cloudflare = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflare) {
    throw "Install cloudflared with: winget install -e --id Cloudflare.cloudflared. Then reopen PowerShell and rerun this script."
}
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Node.js missing. Install Node.js 22+." }
if (-not $SkipSetup) {
    & (Join-Path $root "start-local.ps1") -SetupOnly
    if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
}
$python = Join-Path $root ".venv\Scripts\python.exe"
$vite = Join-Path $root "node_modules\vite\bin\vite.js"
if (-not (Test-Path $python)) { throw "Python environment missing. Run start-local.ps1 -SetupOnly." }
if (-not (Test-Path $vite)) { throw "Node dependencies missing. Run start-local.ps1 -SetupOnly." }

function Test-Port([int]$Port) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try { $tcp.Connect("127.0.0.1", $Port); return $true }
    catch { return $false }
    finally { $tcp.Dispose() }
}
foreach ($port in @(8001,4173)) {
    if (Test-Port $port) { throw "Port $port is in use. Stop the earlier public demo." }
}

# Dedicated public sandbox. None of these paths is under the private data/ folder.
$env:TRADING_SIM_ARCADE_DB = Join-Path $demo "arcade.sqlite3"
$env:TRADING_SIM_DB = Join-Path $demo "trading.sqlite3"
$env:TRADING_SIM_STRATEGY_DB = Join-Path $demo "strategy_library.sqlite3"
$env:TRADING_SIM_CUSTOM_INSTRUMENTS = Join-Path $demo "custom_instruments.json"
$env:TRADING_SIM_MARKET_DIR = Join-Path $demo "market"
$env:TRADING_SIM_AI_PROVIDER = "off"
$env:TRADING_SIM_PUBLIC_DEMO = "1"
$env:VITE_PUBLIC_DEMO = "1"
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

Write-Host "[build] Building production site for the public sandbox..." -ForegroundColor Cyan
& npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }

$api = $null
$frontend = $null
try {
    # Run localhost-only services on DIFFERENT ports from the private app.
    $api = Start-Process -FilePath $python -WorkingDirectory $root -PassThru -ArgumentList @("-m","uvicorn","backend.main:app","--host","127.0.0.1","--port","8001") -RedirectStandardOutput (Join-Path $demo "api.stdout.log") -RedirectStandardError (Join-Path $demo "api.stderr.log")
    $quotedVite = '"' + $vite + '"'
    $frontend = Start-Process -FilePath $node.Source -WorkingDirectory $root -PassThru -ArgumentList @($quotedVite,"preview","--host","127.0.0.1","--port","4173","--strictPort") -RedirectStandardOutput (Join-Path $demo "preview.stdout.log") -RedirectStandardError (Join-Path $demo "preview.stderr.log")
    $apiReady = $false
    $previewReady = $false
    for ($i=0; $i -lt 80; $i++) {
        if ($api.HasExited -or $frontend.HasExited) {
            throw "Public process exited. Check .local-state/public-demo/*.stderr.log."
        }
        if (-not $apiReady) {
            try {
                $check = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:8001/api/health"
                $apiReady = $check.StatusCode -eq 200
            } catch {}
        }
        if (-not $previewReady) {
            try {
                $check = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:4173/"
                $previewReady = $check.StatusCode -eq 200
            } catch {}
        }
        if ($apiReady -and $previewReady) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not ($apiReady -and $previewReady)) {
        throw "Demo did not become ready. Check .local-state/public-demo/*.stderr.log."
    }
    $status = Invoke-RestMethod -TimeoutSec 5 -Uri "http://127.0.0.1:4173/api/health"
    if ($status.status -ne "ok" -or $status.mode -ne "public-demo") {
        throw "Demo isolation health check failed. Tunnel was NOT opened."
    }
    Write-Host ""
    Write-Host "[ready] Public demo locally available at http://127.0.0.1:4173" -ForegroundColor Green
    Write-Host "[public] Private data, local account, and Ollama are isolated." -ForegroundColor Green
    Write-Host "[public] This is a shared sandbox: visitors can see/change other demo sessions." -ForegroundColor Yellow
    Write-Host "[public] Cloudflare will print the public HTTPS trycloudflare.com URL below." -ForegroundColor Cyan
    Write-Host "[public] Keep this terminal and PC running. Press Ctrl+C to stop the public tunnel." -ForegroundColor Cyan
    Write-Host ""
    & $cloudflare.Source tunnel --url http://127.0.0.1:4173
} finally {
    Write-Host "[public] Stopping demo backend and preview..." -ForegroundColor Yellow
    foreach ($process in @($frontend,$api)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
