# Windows PowerShell launcher for Trading Simulator.
# Reuses existing Python/npm installations. Only updates dependencies when needed.
param(
    [switch]$SetupOnly,
    [switch]$NoBrowser,
    [switch]$Mobile,
    [switch]$NoResearchWorker,
    [switch]$CompareVercel
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$stateDir = Join-Path $root ".local-state"
if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir | Out-Null
}

function Manifest-Signature([string[]]$Paths) {
    $values = foreach ($path in $Paths) {
        if (Test-Path $path) {
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        } else {
            "MISSING"
        }
    }
    return ($values -join "|")
}

function Read-Stamp([string]$Path) {
    if (Test-Path $Path) {
        return (Get-Content -LiteralPath $Path -Raw).Trim()
    }
    return ""
}

function Assert-Success([string]$Description) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
}

$python = Join-Path $root ".venv\Scripts\python.exe"
$createdVenv = $false
if (-not (Test-Path $python)) {
    Write-Host "[setup] Python environment missing. Creating it once..." -ForegroundColor Cyan
    $venvPath = Join-Path $root ".venv"
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $venvPath
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venvPath
    } else {
        throw "Python 3 is not installed. Install Python 3.11+ and rerun this launcher."
    }
    Assert-Success "Creating Python virtual environment"
    $createdVenv = $true
}

# A fresh checkout might already have dependencies installed manually. In that
# case, check imports before deciding to run pip. Once a stamp exists, a changed
# requirements file always forces an update.
$requirements = Join-Path $root "backend\requirements.txt"
$pythonStamp = Join-Path $stateDir "python-requirements.sha256"
$pythonSignature = Manifest-Signature @($requirements)
$oldPythonSignature = Read-Stamp $pythonStamp
& $python -c "import importlib.util as u, sys; packages = ('fastapi','uvicorn','httpx','yfinance','pytest','numpy','polars','duckdb'); sys.exit(0 if all(u.find_spec(n) for n in packages) else 1)" 2>$null
$modulesPresent = $LASTEXITCODE -eq 0
$updatePython = $createdVenv -or (-not $modulesPresent) -or ($oldPythonSignature -ne "" -and $oldPythonSignature -ne $pythonSignature)
if ($updatePython) {
    Write-Host "[setup] Python packages missing or requirements changed. Updating..." -ForegroundColor Cyan
    & $python -m pip install -r $requirements
    Assert-Success "Installing Python requirements"
} else {
    Write-Host "[setup] Python packages already present. Skipping pip install." -ForegroundColor Green
}
Set-Content -LiteralPath $pythonStamp -Value $pythonSignature

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found. Install Node.js 22+ and rerun this launcher."
}
$packageJson = Join-Path $root "package.json"
$packageLock = Join-Path $root "package-lock.json"
$nodeStamp = Join-Path $stateDir "node-dependencies.sha256"
$nodeSignature = Manifest-Signature @($packageJson, $packageLock)
$oldNodeSignature = Read-Stamp $nodeStamp
$nodeModules = Join-Path $root "node_modules"

$nodeHealthy = $false
if (Test-Path $nodeModules) {
    & npm ls --depth=0 --silent *> $null
    $nodeHealthy = $LASTEXITCODE -eq 0
}
$updateNode = (-not $nodeHealthy) -or ($oldNodeSignature -ne "" -and $oldNodeSignature -ne $nodeSignature)
if ($updateNode) {
    Write-Host "[setup] Node dependencies missing or changed. Updating..." -ForegroundColor Cyan
    & npm install --no-audit --no-fund
    Assert-Success "Installing Node dependencies"
} else {
    Write-Host "[setup] Node dependencies already present. Skipping npm install." -ForegroundColor Green
}
# npm install can create/change package-lock.json, so compute signature afterwards.
Set-Content -LiteralPath $nodeStamp -Value (Manifest-Signature @($packageJson, $packageLock))

# Install a local commit-time strategy/privacy check in Git checkouts.
# The installer never overwrites a developer's existing pre-commit hook.
$privacyInstaller = Join-Path $root "scripts\install_privacy_hook.py"
if (Test-Path $privacyInstaller) {
    & $python $privacyInstaller
    Assert-Success "Installing strategy privacy guard"
}

if ($SetupOnly) {
    Write-Host "[ready] Dependencies checked. No servers started." -ForegroundColor Green
    exit 0
}

function Test-LocalPort([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

# Start long-running services without opening four separate console windows.
# Child output stays in ignored .local-state/logs for diagnosis.
$logsDir = Join-Path $stateDir "logs"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
$servicesPath = Join-Path $stateDir "local-services.json"
$serviceRecords = @{}
if (Test-Path $servicesPath) {
    try {
        $saved = Get-Content -LiteralPath $servicesPath -Raw | ConvertFrom-Json
        foreach ($property in $saved.PSObject.Properties) {
            $serviceRecords[$property.Name] = $property.Value
        }
    } catch {
        Write-Host "[local] Previous service registry unreadable; new services will be tracked." -ForegroundColor Yellow
    }
}
function Start-LocalBackground([string]$Name,[string]$Script,[string]$ExtraArgs = "") {
    $args = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Script`""
    if ($ExtraArgs) { $args += " $ExtraArgs" }
    $stdout = Join-Path $logsDir "$Name.out.log"
    $stderr = Join-Path $logsDir "$Name.err.log"
    # Clear old logs before launching, because Start-Process cannot redirect
    # to a file still opened by a previously running process.
    $started = Start-Process -FilePath "powershell.exe" -WorkingDirectory $root `
        -ArgumentList $args -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $serviceRecords[$Name] = @{
        pid = $started.Id
        started_utc = $started.StartTime.ToUniversalTime().ToString("o")
        script = $Script
    }
    $serviceRecords | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $servicesPath
    Write-Host "[$Name] Started in background (PID $($started.Id)). Logs: .local-state/logs/$Name.*.log" -ForegroundColor Green
}

# Only the intended AI provider is allowed to auto-start local inference.
# Keep the router bound to loopback; never expose an unauthenticated model on LAN.
$aiProvider = "llama_cpp"
$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*TRADING_SIM_AI_PROVIDER\s*=\s*(.+?)\s*
    # Never silently proxy the password-free local frontend into a protected
    # private-bridge API or an unrelated application occupying this port.
    try {
        $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3 -ErrorAction Stop
    } catch {
        throw "Port 8000 is occupied but a password-free local API could not be verified. Stop the other process and restart start-local.ps1."
    }
    if ($health.mode -ne "local") {
        throw "Port 8000 is serving '$($health.mode)' instead of local mode. Stop the private bridge or conflicting process before starting password-free local development."
    }
    Write-Host "[run] Reusing verified password-free local API on port 8000." -ForegroundColor Green
    try {
        $runningAi = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/ai/status" -TimeoutSec 3
        if ($runningAi.provider -ne $aiProvider) {
            Write-Host "[ai] Backend still uses '$($runningAi.provider)' but .env requests '$aiProvider'. Stop the older local backend and rerun this launcher." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[ai] Could not inspect running backend AI configuration." -ForegroundColor Yellow
    }
} else {
    $script = Join-Path $root "scripts\run-backend.ps1"
    Start-LocalBackground "backend" $script
}
$mobileFrontendReady = $Mobile
if (Test-LocalPort 5173) {
    Write-Host "[run] Port 5173 is already in use. Not starting a duplicate frontend." -ForegroundColor Yellow
    if ($Mobile) {
        $mobileFrontendReady = $false
        Write-Host "[mobile] Stop the existing frontend process and rerun with -Mobile to enable LAN access." -ForegroundColor Yellow
    }
} else {
    $script = Join-Path $root "scripts\run-frontend.ps1"
    Start-LocalBackground "frontend" $script $(if ($Mobile) { "-Lan" } else { "" })
}
# Optionally launch the local GGUF router, if it is not already running.
# A missing llama-server executable never prevents the rest of the app starting.
if ($aiProvider -eq "llama_cpp") {
    if (Test-LocalPort 8081) {
        Write-Host "[ai] Reusing existing llama.cpp router on 127.0.0.1:8081." -ForegroundColor Green
    } elseif ((Get-Command llama-server -ErrorAction SilentlyContinue) -and
              (Test-Path (Join-Path $root "models\\private"))) {
        $modelFiles = @(Get-ChildItem -LiteralPath (Join-Path $root "models\\private") -Filter *.gguf -File -ErrorAction SilentlyContinue)
        if ($modelFiles.Count -gt 0) {
            Start-LocalBackground "ai" (Join-Path $root "scripts\\run-local-ai.ps1")
        } else {
            Write-Host "[ai] No local GGUF models found. Download TwIL and Qwen into models/private." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[ai] Install llama.cpp and place GGUF models in models/private to start AI automatically." -ForegroundColor Yellow
    }
}

# Incremental market data collector runs locally. A second start-local.ps1
# invocation must not duplicate the existing polling process.
try {
    $ingestWorkers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -match 'backend[.]market_ingest_worker' })
    if ($ingestWorkers.Count -eq 0) {
        $marketScript = Join-Path $root "scripts\run-market-ingest-worker.ps1"
        Start-LocalBackground "market" $marketScript
    } else {
        Write-Host "[market] Reusing existing incremental data collector." -ForegroundColor Green
    }
} catch {
    Write-Host "[market] Could not inspect collector processes; start scripts\run-market-ingest-worker.ps1 manually." -ForegroundColor Yellow
}

# Portfolio research is a durable laptop process, not a browser action.
# Start a single consumer for local development, reusing a worker already
# started by the private bridge when present.
if (-not $NoResearchWorker) {
    $foundWorker = $false
    try {
        $existingWorkers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -match 'backend[.]research_worker' })
        $foundWorker = $existingWorkers.Count -gt 0
    } catch {
        Write-Host "[research] Unable to inspect existing worker processes; start manually if queue remains idle." -ForegroundColor Yellow
        $foundWorker = $true
    }
    if ($foundWorker) {
        Write-Host "[research] Existing laptop portfolio worker reused." -ForegroundColor Green
    } else {
        $researchScript = Join-Path $root "scripts\run-research-worker.ps1"
        Start-LocalBackground "research" $researchScript
    }
}

if ($CompareVercel) {
    # Keep the real deployed source on a separate loopback port while the
    # evolving main branch stays on 5173. Never reset or deploy anything.
    if (Test-LocalPort 5174) {
        Write-Host "[baseline] Port 5174 is in use. Reusing the existing listener; verify it is your baseline preview." -ForegroundColor Yellow
    } else {
        $baselineScript = Join-Path $root "scripts\start-vercel-baseline.ps1"
        Start-LocalBackground "baseline" $baselineScript
    }
    Write-Host "[baseline] Published source: http://127.0.0.1:5174" -ForegroundColor Cyan
}

Write-Host "[ready] PC browser: http://127.0.0.1:5173" -ForegroundColor Cyan
if ($mobileFrontendReady) {
    # Suggest private IPv4 addresses; the user picks their Wi-Fi adapter.
    $privateIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' } |
        Select-Object -ExpandProperty IPAddress -Unique)
    foreach ($ip in $privateIps) {
        Write-Host "[mobile] On the same Wi-Fi, open http://$($ip):5173" -ForegroundColor Cyan
    }
    if ($privateIps.Count -eq 0) {
        Write-Host "[mobile] Find your PC's IPv4 address with ipconfig, then open http://<PC-IP>:5173." -ForegroundColor Yellow
    }
    Write-Host "[mobile] Trusted private network only. The development server has no user authentication." -ForegroundColor Yellow
    Write-Host "[mobile] If your phone cannot connect, allow Node.js through Windows Firewall on Private networks." -ForegroundColor Yellow
}
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:5173"
}
) {
            $aiProvider = $Matches[1].Trim().Trim('"').Trim("'").ToLowerInvariant()
        }
    }
}

if (Test-LocalPort 8000) {
    # Never silently proxy the password-free local frontend into a protected
    # private-bridge API or an unrelated application occupying this port.
    try {
        $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3 -ErrorAction Stop
    } catch {
        throw "Port 8000 is occupied but a password-free local API could not be verified. Stop the other process and restart start-local.ps1."
    }
    if ($health.mode -ne "local") {
        throw "Port 8000 is serving '$($health.mode)' instead of local mode. Stop the private bridge or conflicting process before starting password-free local development."
    }
    Write-Host "[run] Reusing verified password-free local API on port 8000." -ForegroundColor Green
} else {
    $script = Join-Path $root "scripts\run-backend.ps1"
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$script`""
    Write-Host "[run] Started backend in another PowerShell window." -ForegroundColor Green
}
$mobileFrontendReady = $Mobile
if (Test-LocalPort 5173) {
    Write-Host "[run] Port 5173 is already in use. Not starting a duplicate frontend." -ForegroundColor Yellow
    if ($Mobile) {
        $mobileFrontendReady = $false
        Write-Host "[mobile] Stop the existing frontend process and rerun with -Mobile to enable LAN access." -ForegroundColor Yellow
    }
} else {
    $script = Join-Path $root "scripts\run-frontend.ps1"
    $frontendArgs = "-NoExit -ExecutionPolicy Bypass -File `"$script`""
    if ($Mobile) { $frontendArgs += " -Lan" }
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList $frontendArgs
    Write-Host "[run] Started frontend in another PowerShell window." -ForegroundColor Green
}
# Incremental market data collector runs locally. A second start-local.ps1
# invocation must not duplicate the existing polling process.
try {
    $ingestWorkers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -match 'backend[.]market_ingest_worker' })
    if ($ingestWorkers.Count -eq 0) {
        $marketScript = Join-Path $root "scripts\run-market-ingest-worker.ps1"
        Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList ("-NoExit -ExecutionPolicy Bypass -File " + ('"' + $marketScript + '"'))
        Write-Host "[market] Local incremental data collector started." -ForegroundColor Green
    } else {
        Write-Host "[market] Reusing existing incremental data collector." -ForegroundColor Green
    }
} catch {
    Write-Host "[market] Could not inspect collector processes; start scripts\run-market-ingest-worker.ps1 manually." -ForegroundColor Yellow
}

# Portfolio research is a durable laptop process, not a browser action.
# Start a single consumer for local development, reusing a worker already
# started by the private bridge when present.
if (-not $NoResearchWorker) {
    $foundWorker = $false
    try {
        $existingWorkers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -match 'backend[.]research_worker' })
        $foundWorker = $existingWorkers.Count -gt 0
    } catch {
        Write-Host "[research] Unable to inspect existing worker processes; start manually if queue remains idle." -ForegroundColor Yellow
        $foundWorker = $true
    }
    if ($foundWorker) {
        Write-Host "[research] Existing laptop portfolio worker reused." -ForegroundColor Green
    } else {
        $researchScript = Join-Path $root "scripts\run-research-worker.ps1"
        Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$researchScript`""
        Write-Host "[research] Started background research queue worker in another PowerShell window." -ForegroundColor Green
    }
}

if ($CompareVercel) {
    # Keep the real deployed source on a separate loopback port while the
    # evolving main branch stays on 5173. Never reset or deploy anything.
    if (Test-LocalPort 5174) {
        Write-Host "[baseline] Port 5174 is in use. Reusing the existing listener; verify it is your baseline preview." -ForegroundColor Yellow
    } else {
        $baselineScript = Join-Path $root "scripts\start-vercel-baseline.ps1"
        $baselineArgs = "-NoExit -NoProfile -ExecutionPolicy Bypass -File " + ('"' + $baselineScript + '"')
        Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList $baselineArgs
        Write-Host "[baseline] Starting the exact deployed Vercel source in a separate PowerShell terminal." -ForegroundColor Green
    }
    Write-Host "[baseline] Published source: http://127.0.0.1:5174" -ForegroundColor Cyan
}

Write-Host "[ready] PC browser: http://127.0.0.1:5173" -ForegroundColor Cyan
if ($mobileFrontendReady) {
    # Suggest private IPv4 addresses; the user picks their Wi-Fi adapter.
    $privateIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' } |
        Select-Object -ExpandProperty IPAddress -Unique)
    foreach ($ip in $privateIps) {
        Write-Host "[mobile] On the same Wi-Fi, open http://$($ip):5173" -ForegroundColor Cyan
    }
    if ($privateIps.Count -eq 0) {
        Write-Host "[mobile] Find your PC's IPv4 address with ipconfig, then open http://<PC-IP>:5173." -ForegroundColor Yellow
    }
    Write-Host "[mobile] Trusted private network only. The development server has no user authentication." -ForegroundColor Yellow
    Write-Host "[mobile] If your phone cannot connect, allow Node.js through Windows Firewall on Private networks." -ForegroundColor Yellow
}
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:5173"
}
