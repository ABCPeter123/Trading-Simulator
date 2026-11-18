# Read-only diagnostic for local llama.cpp and Trading Simulator.
# Never prints environment variables, tokens, private strategies or model contents.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$models = Join-Path $root "models\private"
$logs = Join-Path $root ".local-state\logs"
Write-Host "[ai] Checking local llama.cpp connectivity..." -ForegroundColor Cyan
# Hardware capacity, but no private process arguments or credentials.
try {
    $machine = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $memoryGiB = [Math]::Round([double]$machine.TotalPhysicalMemory / 1GB, 1)
    Write-Host "[hardware] Installed RAM: $memoryGiB GiB"
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    Write-Host "[hardware] Free physical memory: $([Math]::Round([double]$os.FreePhysicalMemory / 1MB, 1)) GiB"
    $processors = @(Get-CimInstance Win32_Processor -ErrorAction Stop)
    $cores = 0
    foreach ($cpu in $processors) { $cores += [int]$cpu.NumberOfCores }
    Write-Host "[hardware] Physical cores: $cores; logical CPUs: $([Environment]::ProcessorCount)"
} catch {
    Write-Host "[hardware] Memory and CPU information unavailable." -ForegroundColor Yellow
}
try {
    $drives = @(Get-PhysicalDisk -ErrorAction Stop |
        Select-Object -ExpandProperty MediaType -Unique)
    Write-Host "[storage] Disk media detected: $($drives -join ', ')"
    Write-Host "[storage] E: holds GGUFs. Paging to SSD may prevent crashes but slows inference."
} catch {
    Write-Host "[storage] Storage media type unavailable."
}
try {
    $gpuTool = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($gpuTool) {
        $gpuRows = & $gpuTool.Source --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0) {
            foreach ($gpuRow in $gpuRows) { Write-Host "[gpu] NVIDIA: $gpuRow (MiB total/free)" }
        }
    } else {
        Write-Host "[gpu] nvidia-smi not installed. GPU offloading depends on your GPU and llama.cpp backend."
    }
} catch {
    Write-Host "[gpu] NVIDIA query unavailable."
}
$server = Get-Command llama-server -ErrorAction SilentlyContinue
if ($server) {
    Write-Host "[ai] Executable: $($server.Source)"
    Write-Host "[ai] GPU backend support: run llama-server --list-devices"
} else {
    Write-Host "[ai] llama-server is not on PATH." -ForegroundColor Yellow
}
if (Test-Path -LiteralPath $models -PathType Container) {
    $weights = @(Get-ChildItem -LiteralPath $models -Filter "*.gguf" -File -ErrorAction SilentlyContinue)
    Write-Host "[ai] Local GGUF count: $($weights.Count)"
    foreach ($weight in $weights) { Write-Host "[ai] GGUF: $($weight.Name)" }
} else {
    Write-Host "[ai] Model folder missing: $models" -ForegroundColor Yellow
}
try {
    $listener = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8081 -State Listen -ErrorAction Stop)
    foreach ($entry in $listener) { Write-Host "[ai] TCP listener on port 8081, PID $($entry.OwningProcess)" }
    if ($listener.Count -eq 0) { Write-Host "[ai] No listener on 127.0.0.1:8081." -ForegroundColor Yellow }
} catch {
    Write-Host "[ai] No confirmed TCP listener on port 8081."
}
$inventoryOK = $false
foreach ($endpoint in @("/models","/v1/models")) {
    try {
        $modelsResponse = Invoke-RestMethod -Uri ("http://127.0.0.1:8081" + $endpoint) -TimeoutSec 4 -ErrorAction Stop
        if ($null -eq $modelsResponse.data) { continue }
        Write-Host "[ai] GET $endpoint succeeded (router or single-model mode)." -ForegroundColor Green
        foreach ($item in @($modelsResponse.data)) {
            if ($item -and $item.id) { Write-Host "[ai] Available: $($item.id)" }
        }
        $inventoryOK = $true
        break
    } catch {
        continue
    }
}
if (-not $inventoryOK) {
    Write-Host "[ai] Both /models and /v1/models failed; llama.cpp is not available." -ForegroundColor Yellow
}
try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/ai/status" -TimeoutSec 4 -ErrorAction Stop
    Write-Host "[app] Provider: $($status.provider); ready: $($status.ready); state: $($status.connection_state)"
} catch {
    Write-Host "[app] Backend AI status unavailable ($($_.Exception.GetType().Name))." -ForegroundColor Yellow
}
foreach ($name in @("ai.err.log","ai.out.log")) {
    $path = Join-Path $logs $name
    if (Test-Path -LiteralPath $path) {
        Write-Host "[ai] Last lines of $name :" -ForegroundColor Cyan
        Get-Content -LiteralPath $path -Tail 12 -ErrorAction SilentlyContinue
    }
}
