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
if ($args -contains "--list-devices") {
    Write-Output "Available devices:"
    Write-Output "  Vulkan0: Intel(R) UHD Graphics 630 (8119 MiB, 7457 MiB free)"
    Write-Output "  Vulkan1: NVIDIA GeForce GTX 1050 Ti (4221 MiB, 3619 MiB free)"
    $global:LASTEXITCODE = 0
    return
}
Set-Content -LiteralPath $env:TEST_LOCAL_AI_ARGS_PATH -Value ($args -join [Environment]::NewLine)
$global:LASTEXITCODE = 0
'@
    $env:TEST_LOCAL_AI_ARGS_PATH = Join-Path $testRoot "captured.txt"
    $env:TRADING_SIM_LLAMA_SERVER_EXE = $fake
    Set-Content -LiteralPath (Join-Path $testRoot ".env") -Value @(
        "TRADING_SIM_LLAMA_PROFILE=speed",
        "TRADING_SIM_LLAMA_THREADS=4",
        "TRADING_SIM_LLAMA_THREADS_BATCH=6",
        "TRADING_SIM_LLAMA_GPU_LAYERS=auto",
        "TRADING_SIM_LLAMA_DEVICE=auto",
        "TRADING_SIM_LLAMA_FIT_TARGET=768"
    )
    & (Join-Path $scriptsDir "run-local-ai.ps1")
    $observed = @(Get-Content -LiteralPath $env:TEST_LOCAL_AI_ARGS_PATH)
    foreach ($expected in @("--models-dir",$modelDir,"--models-max","1",
                             "--host","127.0.0.1","--port","8081",
                             "--ctx-size","4096","--threads","4",
                             "--threads-batch","6","--gpu-layers","auto",
                             "--parallel","1","--batch-size","512",
                             "--device","Vulkan1","--fit","on",
                             "--fit-target","768","--split-mode","none",
                             "--ubatch-size","256")) {
        if ($observed -notcontains $expected) {
            throw "Missing required AI server argument: $expected"
        }
    }
    if ($observed -contains "0.0.0.0") { throw "Router must not expose model on LAN" }
    if ($observed -contains "Vulkan0") { throw "Incorrectly selected integrated Intel GPU" }

    Set-Content -LiteralPath (Join-Path $testRoot ".env") -Value @(
        "TRADING_SIM_LLAMA_PROFILE=quality",
        "TRADING_SIM_LLAMA_THREADS=9999",
        "TRADING_SIM_LLAMA_CONTEXT=7777",
        "TRADING_SIM_LLAMA_GPU_LAYERS=0",
        "TRADING_SIM_LLAMA_UBATCH=128",
        "TRADING_SIM_LLAMA_DEVICE=cpu"
    )
    & (Join-Path $scriptsDir "run-local-ai.ps1")
    $observed = @(Get-Content -LiteralPath $env:TEST_LOCAL_AI_ARGS_PATH)
    foreach ($expected in @("--ctx-size","7777","--gpu-layers","0",
                             "--ubatch-size","128","--device","none",
                             "--fit-target","768")) {
        if ($observed -notcontains $expected) {
            throw "Config override not honored: $expected"
        }
    }
    if ($observed -contains "9999") { throw "Invalid thread count accepted" }
    if ($observed -notcontains "0") { throw "CPU mode did not disable GPU layers" }
    if ($observed -contains "Vulkan1") { throw "Explicit CPU mode used NVIDIA GPU" }
    # Qwen-only selection must run the single model directly, without
    # advertising TwIL or 9B weights through the router.
    $compactFile = Join-Path $modelDir "Qwen3.5-4B-Q4_K_M.gguf"
    $handle = [IO.File]::OpenWrite($compactFile)
    try { $handle.SetLength(220MB) } finally { $handle.Dispose() }
    Set-Content -LiteralPath (Join-Path $testRoot ".env") -Value @(
        "TRADING_SIM_AI_PROVIDER=llama_cpp",
        "TRADING_SIM_AI_MODEL=Qwen3.5-4B-Q4_K_M.gguf",
        "TRADING_SIM_AI_MODELS=Qwen3.5-4B-Q4_K_M.gguf",
        "TRADING_SIM_LLAMA_DEVICE=Vulkan1"
    )
    & (Join-Path $scriptsDir "run-local-ai.ps1")
    $observed = @(Get-Content -LiteralPath $env:TEST_LOCAL_AI_ARGS_PATH)
    $modelIndex = [array]::IndexOf($observed, "--model")
    if ($modelIndex -lt 0 -or $observed[$modelIndex+1] -ne $compactFile) {
        throw "Qwen-only mode did not select exactly the Qwen4B GGUF path."
    }
    $aliasIndex = [array]::IndexOf($observed, "--alias")
    if ($aliasIndex -lt 0 -or $observed[$aliasIndex+1] -ne "Qwen3.5-4B-Q4_K_M") {
        throw "Qwen-only mode missing expected public model alias."
    }
    if ($observed -contains "--models-dir" -or $observed -contains "--models-max") {
        throw "Qwen-only mode must not launch the multi-model router."
    }
    if ($observed -notcontains "Vulkan1") {
        throw "Explicit NVIDIA device was not used."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $modelDir "Synthetic-Q4_K_M.gguf"))) {
        throw "Existing GGUF weights changed during Qwen-only launch."
    }
    Write-Host "Local AI tuning regression checks passed." -ForegroundColor Green
} finally {
    Remove-Item Env:\TEST_LOCAL_AI_ARGS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\TRADING_SIM_LLAMA_SERVER_EXE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
