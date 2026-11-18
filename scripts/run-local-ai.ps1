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
    "TRADING_SIM_LLAMA_UBATCH", "TRADING_SIM_LLAMA_DEVICE",
    "TRADING_SIM_LLAMA_FIT_TARGET"
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

# If one GGUF is allowlisted, show the router exactly that model.
# Use a same-SSD NTFS hard link without duplicating the original large file.
# The private managed folder is Git-ignored. Originals are never deleted.
$routerModels = $models
if (Test-Path -LiteralPath $envPath) {
    $choices = @()
    $selectedFilename = ""
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*TRADING_SIM_AI_MODELS\s*=\s*(.*?)\s*$') {
            $choices = @($Matches[1].Trim().Trim('"').Trim("'").Split(',') |
                ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        if ($line -match '^\s*TRADING_SIM_AI_MODEL\s*=\s*(.*?)\s*$') {
            $selectedFilename = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    if ($choices.Count -eq 1) {
        $filename = $choices[0]
        if ($filename -notmatch '^[A-Za-z0-9_.-]+[.]gguf$' -or
            $filename.StartsWith(".")) {
            throw "Invalid single-model allowlist entry. Use only a GGUF filename."
        }
        if ($selectedFilename -and $selectedFilename -ne $filename -and
            $selectedFilename -ne [IO.Path]::GetFileNameWithoutExtension($filename)) {
            throw "TRADING_SIM_AI_MODEL must match TRADING_SIM_AI_MODELS in single-model mode."
        }
        $source = Join-Path $models $filename
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Selected GGUF not found: $filename. Re-run the compact-model installer."
        }
        if ((Get-Item -LiteralPath $source).Length -lt 200MB) {
            throw "Selected GGUF appears incomplete: $filename"
        }
        $selectionDir = Join-Path $root ".local-state\ai-single-model"
        $marker = Join-Path $selectionDir ".trading-sim-managed"
        if (-not (Test-Path -LiteralPath $selectionDir)) {
            New-Item -ItemType Directory -Path $selectionDir -Force | Out-Null
            Set-Content -LiteralPath $marker -Value "Managed by Trading Simulator. Original models are in models/private."
        }
        if (-not (Test-Path -LiteralPath $marker)) {
            throw "AI model-view folder is not managed by Trading Simulator."
        }
        Get-ChildItem -LiteralPath $selectionDir -Filter "*.gguf" -File |
            Remove-Item -Force
        $link = Join-Path $selectionDir $filename
        try {
            New-Item -ItemType HardLink -Path $link -Target $source -ErrorAction Stop | Out-Null
        } catch {
            throw "Cannot create NTFS same-drive hard link. Check E: filesystem and folder access."
        }
        $routerModels = $selectionDir
        Write-Host "[ai] Selected only $filename through a zero-copy SSD hard link." -ForegroundColor Green
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

# Hybrid machines can expose Intel shared-memory graphics ahead of NVIDIA.
# Select NVIDIA explicitly by the exact device name advertised by llama.cpp.
# Prefer CUDA when available, then NVIDIA Vulkan (Vulkan1 on GTX 1050 Ti).
$detectedDevices = @()
try {
    $deviceOutput = @(& $executable --list-devices 2>&1)
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in $deviceOutput) {
            $display = [string]$line
            if ($display -match '^\s*(?<name>(?:CUDA|Vulkan|SYCL|Metal)\d+):\s*(?<label>.+?)\s*$') {
                $detectedDevices += @{ name = $Matches["name"]; label = $Matches["label"] }
            }
        }
    }
} catch {
    Write-Host "[ai] Device discovery failed; choosing CPU unless manually configured." -ForegroundColor Yellow
}
$deviceMode = "auto"
if ($settings.ContainsKey("TRADING_SIM_LLAMA_DEVICE")) {
    $deviceMode = $settings["TRADING_SIM_LLAMA_DEVICE"].Trim()
}
$selectedDevice = ""
if ($deviceMode -in @("cpu","none")) {
    $selectedDevice = "none"
} elseif ($deviceMode -eq "auto") {
    $nvidia = @($detectedDevices | Where-Object {
        $_.label -match 'NVIDIA' -and $_.name -match '^CUDA\d+$'
    })
    if ($nvidia.Count -eq 0) {
        $nvidia = @($detectedDevices | Where-Object {
            $_.label -match 'NVIDIA' -and $_.name -match '^Vulkan\d+$'
        })
    }
    if ($nvidia.Count -gt 0) { $selectedDevice = [string]$nvidia[0].name }
    # On Intel-only machines, default to CPU rather than consuming shared RAM.
    if (-not $selectedDevice) { $selectedDevice = "none" }
} else {
    $matching = @($detectedDevices | Where-Object { $_.name -eq $deviceMode })
    if ($deviceMode -notmatch '^(CUDA|Vulkan|SYCL|Metal)[0-9]+$') {
        throw "Invalid device name. Use auto, cpu, or exact name from llama-server --list-devices."
    }
    if ($detectedDevices.Count -gt 0 -and $matching.Count -ne 1) {
        throw "Configured device is not listed by llama.cpp. Check llama-server --list-devices."
    }
    # Discovery on Windows may fail when native diagnostics are sent to stderr.
    # If explicitly set, let the server itself validate the device.
    if ($detectedDevices.Count -eq 0) {
        Write-Host "[ai] Device discovery failed; attempting explicitly chosen $deviceMode." -ForegroundColor Yellow
    }
    $selectedDevice = $deviceMode
}

# Leave room for Windows graphics and Vulkan buffers. With --gpu-layers auto
# llama.cpp automatically fits partial GPU layers in dedicated VRAM.
$fitTarget = Int-Setting "TRADING_SIM_LLAMA_FIT_TARGET" 768 256 2048
if ($selectedDevice -eq "none") { $gpuLayers = "0" }
$actualGpu = @($detectedDevices | Where-Object { $_.name -eq $selectedDevice })
$deviceLabel = if ($actualGpu.Count -gt 0) { [string]$actualGpu[0].label } else { "CPU only" }
Write-Host "[ai] Selected device: $selectedDevice ($deviceLabel); reserved GPU margin=$($fitTarget) MiB."

Write-Host "[ai] Serving $($weights.Count) installed models locally, one loaded at a time."
Write-Host "[ai] Profile=$profile, physical_cores=$physical, logical_cpus=$logical, threads=$threads, batch_threads=$batchThreads."
Write-Host "[ai] Context=$ctx, batch=$batch, ubatch=$ubatch, GPU-layers=$gpuLayers (requires a GPU-enabled llama.cpp build)."
Write-Host "[ai] GGUF files stay on $models; drive paging is not a substitute for RAM."

$argsList = @(
    "--models-dir", $routerModels, "--models-max", "1",
    "--host", "127.0.0.1", "--port", "8081",
    "--parallel", "1",
    "--threads", [string]$threads,
    "--threads-batch", [string]$batchThreads,
    "--gpu-layers", $gpuLayers,
    "--device", $selectedDevice,
    "--split-mode", "none",
    "--fit", "on",
    "--fit-target", [string]$fitTarget,
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
