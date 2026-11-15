$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
if (-not (Test-Path (Join-Path $root "node_modules"))) {
    throw "Node dependencies are missing. Run start-local.ps1 first."
}
& npm run dev
