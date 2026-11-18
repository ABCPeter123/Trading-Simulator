# Local llama.cpp router tuned for modest-RAM Windows machines.
# Both models stay on E: (or the checkout drive); only one may load in RAM.
# PowerShell launcher remains private and binds the router to 127.0.0.1 only.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$models = Join-Path $root "models\private"
if (-not (Test-Path -LiteralPath $models -PathType Container)) {
    throw "Model directory missing: $models"
}
$weights = @(Get-ChildItem -LiteralPath $models -Filter "*.gguf" -File -ErrorAction Stop)
if ($weights.Count -lt 1) {
    throw "No .gguf weights in $models. Download local models before starting."
}

# Resolve the exact executable path in the calling launcher to avoid PATH
# differences between the visible parent and this hidden PowerShell process.
$executable = $env:TRADING_SIM_LLAMA_SERVER_EXE
if (-not $executable -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    $command = Get-Command "llama-server" -ErrorAction SilentlyContinue
    if (-not $command) { throw "llama-server executable not found on PATH." }
    $executable = $command.Source
}

# The .env file is never evaluated as PowerShell. Only bounded, recognized
# performance settings are accepted; credentials or arbitrary args are ignored.
$settings = @{}
$envPath = Join-Path $root ".env"
$allowed = @(
    "TRADING_SIM_LLAMA_PROFILE", "TRADING_SIM_LLAMA_THREADS",
    "TRADING_SIM_LLAMA_THREADS_BATCH", "TRADING_SIM_LLAMA_GPU_LAYERS",
    "TRADING_SIM_LLAMA_CONTEXT", "TRADING_SIM_LLAMA_BATCH",
    "TRADING_SIM_LLAMA_UBATCH"
)
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$') {
            $name = $Matches[1]
            if ($allowed -contains $name) {
                $settings[$name] = $Matches[2].Trim().Trim('"').Trim("'")
            }
        }
    }
}

function Int-Setting([string]$Name,[int]$Default,[int]$Min,[int]$Max) {
    $textValue = $settings[$Name]
    if ([string]::IsNullOrWhiteSpace($textValue)) { return $Default }
    $value = 0
    if (-not [int]::TryParse($textValue, [ref]$value) -or
        $value -lt $Min -or $value -gt $Max) {
        Write-Host "[ai] Ignoring invalid $Name, using $Default." -ForegroundColor Yellow
        return $Default
    }
    return $value
}

$profile = "speed"
if ($settings.ContainsKey("TRADING_SIM_LLAMA_PROFILE")) {
    $candidate = $settings["TRADING_SIM_LLAMA_PROFILE"].ToLowerInvariant()
    if ($candidate -in @("speed","balanced","quality")) {
        $profile = $candidate
    } else {
        Write-Host "[ai] Unknown performance profile. Using speed." -ForegroundColor Yellow
    }
}

# 16 GB RAM: avoid oversized KV caches and prompt batching. This keeps
# headroom for Windows, Vite, Python, and the market/research workers.
$contextDefault = switch ($profile) {
    "speed"    { 4096 }
    "balanced" { 6144 }
    "quality"  { 8192 }
}
$batchDefault = switch ($profile) {
    "speed"    { 512 }
    "balanced" { 1024 }
    "quality"  { 1024 }
}
$ubatchDefault = switch ($profile) {
    "speed"    { 256 }
    "balanced" { 256 }
    "quality"  { 512 }
}

# Using more threads than physical CPU cores can be slower and increase
# contention. Logical threads are useful during prompt batch ingestion.
$logical = [Math]::Max(1,[Environment]::ProcessorCount)
$physical = 0
try {
    $cpus = @(Get-CimInstance Win32_Processor -ErrorAction Stop)
    foreach ($cpu in $cpus) { $physical += [int]$cpu.NumberOfCores }
} catch { $physical = 0 }
if ($physical -le 0) { $physical = [Math]::Max(1,[int][Math]::Ceiling($logical / 2)) }
$threads = Int-Setting "TRADING_SIM_LLAMA_THREADS" ([Math]::Min(12,$physical)) 1 64
$batchThreads = Int-Setting "TRADING_SIM_LLAMA_THREADS_BATCH" ([Math]::Min(16,$logical)) 1 64
$ctx = Int-Setting "TRADING_SIM_LLAMA_CONTEXT" $contextDefault 2048 16384
$batch = Int-Setting "TRADING_SIM_LLAMA_BATCH" $batchDefault 128 2048
$ubatch = Int-Setting "TRADING_SIM_LLAMA_UBATCH" $ubatchDefault 64 1024
$ubatch = [Math]::Min($ubatch,$batch)

# 'auto' offloads layers when the installed llama.cpp binary actually
# contains a compatible GPU backend. CPU-only binaries ignore GPU VRAM.
$gpuLayers = "auto"
if ($settings.ContainsKey("TRADING_SIM_LLAMA_GPU_LAYERS")) {
    $requested = $settings["TRADING_SIM_LLAMA_GPU_LAYERS"].ToLowerInvariant()
    if ($requested -in @("auto","all")) {
        $gpuLayers = $requested
    } else {
        $parsed = 0
        if ([int]::TryParse($requested,[ref]$parsed) -and $parsed -ge 0 -and $parsed -le 200) {
            $gpuLayers = [string]$parsed
        } else {
            Write-Host "[ai] Invalid GPU-layer setting. Using auto." -ForegroundColor Yellow
        }
    }
}

Write-Host "[ai] Serving $($weights.Count) installed models locally, one loaded at a time."
Write-Host "[ai] Profile=$profile, physical_cores=$physical, logical_cpus=$logical, threads=$threads, batch_threads=$batchThreads."
Write-Host "[ai] Context=$ctx, batch=$batch, ubatch=$ubatch, GPU-layers=$gpuLayers (requires a GPU-enabled llama.cpp build)."
Write-Host "[ai] GGUF files stay on $models; drive paging is not a substitute for RAM."

$argsList = @(
    "--models-dir", $models, "--models-max", "1",
    "--host", "127.0.0.1", "--port", "8081",
    "--parallel", "1",
    "--threads", [string]$threads,
    "--threads-batch", [string]$batchThreads,
    "--gpu-layers", $gpuLayers,
    "--flash-attn", "auto",
    "--ctx-size", [string]$ctx,
    "--batch-size", [string]$batch,
    "--ubatch-size", [string]$ubatch
)
& $executable @argsList
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "llama-server exited with code $exitCode. Read .local-state/logs/ai.err.log."
}
