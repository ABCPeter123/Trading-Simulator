param([switch]$Lan)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
if (-not (Test-Path (Join-Path $root "node_modules"))) {
    throw "Node dependencies are missing. Run start-local.ps1 first."
}
# Local Vite must never inherit the Vercel-only gateway or public-demo mode.
# These settings affect only this frontend process, not the hosted website.
$env:VITE_CLOUD_FRONTEND = "0"
$env:VITE_PUBLIC_DEMO = "0"
Write-Host "[local] Development frontend: direct access, no password prompt." -ForegroundColor Cyan
if ($Lan) {
    # Frontend is reachable on trusted local Wi-Fi; API remains loopback-only
    # behind Vite's /api development proxy.
    & npm run dev -- --host 0.0.0.0
} else {
    & npm run dev
}
