# Optional local GGUF router, launched by start-local.ps1 without a console window.
# Models and inference never leave the PC. The server is not exposed to LAN.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$models = Join-Path $root "models\private"
if (-not (Test-Path $models)) {
    throw "Local models directory is missing. Download GGUF models to models/private."
}
$weights = @(Get-ChildItem -LiteralPath $models -Filter "*.gguf" -File -ErrorAction Stop)
if ($weights.Count -lt 1) {
    throw "No GGUF files installed in models/private."
}
$server = Get-Command "llama-server" -ErrorAction Stop
Write-Host "[ai] Starting local llama.cpp router on 127.0.0.1:8081"
& $server.Source --models-dir $models --models-max 1 --host 127.0.0.1 --port 8081 -c 8192 -n 8192
exit $LASTEXITCODE
