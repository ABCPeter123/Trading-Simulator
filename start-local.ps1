# Windows PowerShell launcher for Trading Simulator.
# Reuses existing Python/npm installations. Only updates dependencies when needed.
param(
    [switch]$SetupOnly,
    [switch]$NoBrowser,
    [switch]$Mobile
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

if (Test-LocalPort 8000) {
    Write-Host "[run] Port 8000 is already in use. Not starting a duplicate API." -ForegroundColor Yellow
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
