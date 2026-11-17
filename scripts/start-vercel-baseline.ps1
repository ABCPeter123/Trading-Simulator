# Serve the exact committed production Vercel UI alongside current npm dev.
# This script does not deploy, reset, check out, or modify the main worktree.
param(
    [switch]$Status,
    [switch]$NoInstall,
    [int]$Port = 5174
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$settings = Get-Content -LiteralPath (Join-Path $root "config\production-baseline.json") -Raw | ConvertFrom-Json
$commit = [string]$settings.deployed_commit
$baselinePath = Join-Path (Split-Path -Parent $root) "Trading-Simulator-Vercel-Baseline"

if ($commit -notmatch '^[0-9a-f]{40}$') {
    throw "Invalid pinned deployment commit. Inspect config/production-baseline.json."
}
if ($Port -lt 1024 -or $Port -gt 65535 -or $Port -eq 5173 -or $Port -eq 8000) {
    throw "Use a separate unprivileged local port, normally 5174."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to create the local Vercel baseline snapshot."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue) -and -not $Status) {
    throw "npm is required to run the local baseline frontend."
}
$branch = (& git -C $root rev-parse --abbrev-ref HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the project worktree." }
$developmentHead = (& git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the development revision." }
Write-Host "[baseline] Production Vercel commit: $commit" -ForegroundColor Cyan
Write-Host "[baseline] Current development: $developmentHead ($branch)" -ForegroundColor Cyan
Write-Host "[baseline] Production URL: $($settings.deployment_url)" -ForegroundColor Cyan

if ($Status) {
    & git -C $root cat-file -e "$commit^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[baseline] Deployed source commit is not fetched locally yet." -ForegroundColor Yellow
    } else {
        & git -C $root diff --stat $commit $developmentHead -- src package.json vite.config.ts
        if ($LASTEXITCODE -ne 0) { throw "Could not compare frontend changes." }
    }
    if (Test-Path -LiteralPath $baselinePath) {
        $existing = (& git -C $baselinePath rev-parse HEAD 2>$null).Trim()
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[baseline] Local snapshot path: $baselinePath" -ForegroundColor Green
            if ($existing -ne $commit) {
                Write-Host "[baseline] Snapshot revision differs from the pinned production SHA. No automatic reset." -ForegroundColor Yellow
            }
        } else {
            Write-Host "[baseline] Snapshot path is occupied by a non-Git directory. No changes made." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[baseline] Snapshot has not been created yet." -ForegroundColor Yellow
    }
    exit 0
}

# Fetching Git objects does not deploy to Vercel or change the working branch.
& git -C $root cat-file -e "$commit^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[baseline] Fetching production revision without updating the worktree." -ForegroundColor Cyan
    & git -C $root fetch --no-tags origin main
    if ($LASTEXITCODE -ne 0) { throw "Could not fetch the deployed source commit." }
}
& git -C $root cat-file -e "$commit^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Production SHA is unavailable from Git. The baseline was not changed."
}
if (-not (Test-Path -LiteralPath $baselinePath)) {
    Write-Host "[baseline] Creating read-only-in-practice detached worktree." -ForegroundColor Cyan
    & git -C $root worktree add --detach $baselinePath $commit
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the deployed source snapshot." }
}
$existing = (& git -C $baselinePath rev-parse HEAD 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or $existing -ne $commit) {
    throw "Local snapshot is not the pinned production commit. Refusing to modify it."
}
if (-not $NoInstall) {
    Push-Location $baselinePath
    try {
        & npm ls --depth=0 --silent *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[baseline] Installing dependencies only in the separate baseline worktree." -ForegroundColor Cyan
            if (Test-Path -LiteralPath "package-lock.json") {
                & npm ci --no-audit --no-fund
            } else {
                & npm install --no-audit --no-fund
            }
            if ($LASTEXITCODE -ne 0) { throw "npm package installation failed in baseline worktree." }
        }
    } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $baselinePath "node_modules"))) {
    throw "Baseline npm packages missing. Run without -NoInstall first."
}

# The production build uses VITE_CLOUD_FRONTEND=1 for its remote password gate.
# The LOCAL snapshot intentionally uses Vite's loopback /api proxy instead:
# identical source UI behind login, with laptop API rather than Cloudflare.
$env:VITE_CLOUD_FRONTEND = "0"
$env:VITE_PUBLIC_DEMO = "0"
Write-Host "[baseline] Frozen Vercel-source UI: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "[baseline] Ongoing dev UI:        http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "[baseline] Both use your local API on 127.0.0.1:8000. Start .\start-local.ps1 first." -ForegroundColor Yellow
Write-Host "[baseline] Do not edit or commit from the detached baseline worktree." -ForegroundColor Yellow
Push-Location $baselinePath
try {
    & npm run dev -- --host 127.0.0.1 --port $Port --strictPort
    if ($LASTEXITCODE -ne 0) { throw "Baseline Vite server failed." }
} finally { Pop-Location }
