# Start the local llama.cpp model router without creating a visible console.
# This process never accepts external connections and does not use credentials.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$models = Join-Path $root "models\private"
if (-not (Test-Path -LiteralPath $models -PathType Container)) {
    throw "Model directory missing: $models"
}
$weights = @(Get-ChildItem -LiteralPath $models -Filter "*.gguf" -File -ErrorAction Stop)
if ($weights.Count -lt 1) {
    throw "No .gguf model weights in $models. Download TwIL and Qwen into this directory."
}

# start-local.ps1 resolves this executable in its own environment and hands
# down the absolute path. This avoids a different PATH in hidden PowerShell.
$executable = $env:TRADING_SIM_LLAMA_SERVER_EXE
if (-not $executable -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    $command = Get-Command "llama-server" -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "llama-server not found. Install llama.cpp or ensure llama-server is on PATH."
    }
    $executable = $command.Source
}
Write-Host "[ai] Executable: $executable"
Write-Host "[ai] Installed model files: $($weights.Count); serving only 127.0.0.1:8081"
& $executable --models-dir $models --models-max 1 --host 127.0.0.1 --port 8081 -c 8192 -n 8192
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "llama-server exited with code $exitCode. Inspect .local-state/logs/ai.err.log for details."
}
