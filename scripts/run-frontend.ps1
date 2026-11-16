param([switch]$Lan)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
if (-not (Test-Path (Join-Path $root "node_modules"))) {
    throw "Node dependencies are missing. Run start-local.ps1 first."
}
if ($Lan) {
    # Frontend is reachable on trusted local Wi-Fi; API remains loopback-only
    # behind Vite's /api development proxy.
    & npm run dev -- --host 0.0.0.0
} else {
    & npm run dev
}
