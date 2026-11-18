# Windows CI regression: exercise the real AI tuning script with a fake
# executable and a synthetic empty GGUF placeholder. Never touch owner models.
$ErrorActionPreference = "Stop"
$sourceRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("trading-ai-ci-" + [guid]::NewGuid().ToString("N"))
try {
    $scriptsDir = Join-Path $testRoot "scripts"
    $modelDir = Join-Path $testRoot "models\private"
    New-Item -ItemType Directory -Force -Path $scriptsDir,$modelDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot "scripts\run-local-ai.ps1") -Destination (Join-Path $scriptsDir "run-local-ai.ps1") -ErrorAction Stop
    Set-Content -LiteralPath (Join-Path $modelDir "Synthetic-Q4_K_M.gguf") -Value "synthetic placeholder"
    $fake = Join-Path $testRoot "fake-llama-server.ps1"
    Set-Content -LiteralPath $fake -Value @'
Set-Content -LiteralPath $env:TEST_LOCAL_AI_ARGS_PATH -Value ($args -join [Environment]::NewLine)
$global:LASTEXITCODE = 0
'@
    $env:TEST_LOCAL_AI_ARGS_PATH = Join-Path $testRoot "captured.txt"
    $env:TRADING_SIM_LLAMA_SERVER_EXE = $fake
    Set-Content -LiteralPath (Join-Path $testRoot ".env") -Value @(
        "TRADING_SIM_LLAMA_PROFILE=speed",
        "TRADING_SIM_LLAMA_THREADS=4",
        "TRADING_SIM_LLAMA_THREADS_BATCH=6",
        "TRADING_SIM_LLAMA_GPU_LAYERS=auto"
    )
    & (Join-Path $scriptsDir "run-local-ai.ps1")
    $observed = @(Get-Content -LiteralPath $env:TEST_LOCAL_AI_ARGS_PATH)
    foreach ($expected in @("--models-dir",$modelDir,"--models-max","1",
                             "--host","127.0.0.1","--port","8081",
                             "--ctx-size","4096","--threads","4",
                             "--threads-batch","6","--gpu-layers","auto",
                             "--parallel","1","--batch-size","512",
                             "--ubatch-size","256")) {
        if ($observed -notcontains $expected) {
            throw "Missing required AI server argument: $expected"
        }
    }
    if ($observed -contains "0.0.0.0") { throw "Router must not expose model on LAN" }

    Set-Content -LiteralPath (Join-Path $testRoot ".env") -Value @(
        "TRADING_SIM_LLAMA_PROFILE=quality",
        "TRADING_SIM_LLAMA_THREADS=9999",
        "TRADING_SIM_LLAMA_CONTEXT=7777",
        "TRADING_SIM_LLAMA_GPU_LAYERS=0",
        "TRADING_SIM_LLAMA_UBATCH=128"
    )
    & (Join-Path $scriptsDir "run-local-ai.ps1")
    $observed = @(Get-Content -LiteralPath $env:TEST_LOCAL_AI_ARGS_PATH)
    foreach ($expected in @("--ctx-size","7777","--gpu-layers","0",
                             "--ubatch-size","128")) {
        if ($observed -notcontains $expected) {
            throw "Config override not honored: $expected"
        }
    }
    if ($observed -contains "9999") { throw "Invalid thread count accepted" }
    Write-Host "Local AI tuning regression checks passed." -ForegroundColor Green
} finally {
    Remove-Item Env:\TEST_LOCAL_AI_ARGS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\TRADING_SIM_LLAMA_SERVER_EXE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
