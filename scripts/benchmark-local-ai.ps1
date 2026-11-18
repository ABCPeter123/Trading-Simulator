# Read-only local AI throughput benchmark. No real strategies, fills or prompts.
# Send a short, synthetic question to the already-running loopback router.
# Print periodic progress while the model loads and generates. This script
# does NOT start more PowerShell windows or change Windows paging settings.
param(
    [ValidateSet("TwIL-8B-Q4_K_M-balanced","Qwen3.5-9B-Q4_K_M","Qwen3.5-4B-Q4_K_M")]
    [string]$Model = "Qwen3.5-9B-Q4_K_M",
    [ValidateRange(16,256)]
    [int]$MaxTokens = 64,
    [ValidateRange(30,600)]
    [int]$TimeoutSeconds = 300,
    [ValidateRange(1024,65535)]
    [int]$Port = 8081
)
$ErrorActionPreference = "Stop"
$origin = "http://127.0.0.1:$Port"

# A healthy router may list unloaded models. Do not trigger inference during
# connectivity checks or interpret 'unloaded' as unavailable.
try {
    $inventory = Invoke-RestMethod -Uri "$origin/models" -TimeoutSec 5 -ErrorAction Stop
} catch {
    throw "[benchmark] Local llama.cpp router is unreachable at $origin. Check .\scripts\diagnose-local-ai.ps1."
}
$entries = @($inventory.data | Where-Object { $_ -and $_.id -eq $Model })
if ($entries.Count -eq 0) {
    throw "[benchmark] $Model is not listed by $origin/models."
}
$initial = $entries[0].status
$initialState = if ($initial -is [string]) { $initial } elseif ($initial -and $initial.value) { [string]$initial.value } else { "unknown" }
Write-Host "[benchmark] Model: $Model; maximum completion tokens: $MaxTokens; initial state: $initialState." -ForegroundColor Cyan
Write-Host "[benchmark] Sending synthetic inference request. Timing includes model loading." -ForegroundColor DarkGray
Write-Host "[benchmark] Progress will appear every 5 seconds. Press Ctrl+C to cancel." -ForegroundColor DarkGray

$payload = @{
    model = $Model
    stream = $false
    temperature = 0
    max_tokens = $MaxTokens
    messages = @(
        @{role="system";content="Answer a general math question briefly. No private financial information."},
        @{role="user";content="What is the arithmetic mean of 2, 4, and 6? Answer in one sentence."}
    )
} | ConvertTo-Json -Depth 6 -Compress

Add-Type -AssemblyName System.Net.Http
$handler = [System.Net.Http.HttpClientHandler]::new()
$handler.UseProxy = $false
$http = [System.Net.Http.HttpClient]::new($handler)
$http.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
$body = [System.Net.Http.StringContent]::new($payload, [Text.Encoding]::UTF8, "application/json")
$watch = [Diagnostics.Stopwatch]::StartNew()
$nextReport = 5
try {
    # Async HTTP lets PowerShell show heartbeat messages while a large model
    # loads. Invoke-RestMethod normally displays nothing until the entire
    # completion arrives, which can look like a frozen benchmark.
    $pending = $http.PostAsync("$origin/v1/chat/completions", $body)
    while (-not $pending.IsCompleted) {
        Start-Sleep -Milliseconds 250
        if ($watch.Elapsed.TotalSeconds -ge $nextReport) {
            $elapsedSeconds = [int][Math]::Floor($watch.Elapsed.TotalSeconds)
            Write-Host "[benchmark] $elapsedSeconds s elapsed. Model may be loading or generating..." -ForegroundColor Yellow
            $nextReport += 5
        }
    }
    $response = $pending.GetAwaiter().GetResult()
    try {
        if (-not $response.IsSuccessStatusCode) {
            throw "[benchmark] llama.cpp returned HTTP $([int]$response.StatusCode) ($($response.ReasonPhrase)). Check .local-state/logs/ai.err.log."
        }
        $readTask = $response.Content.ReadAsStringAsync()
        while (-not $readTask.IsCompleted) {
            Start-Sleep -Milliseconds 250
            if ($watch.Elapsed.TotalSeconds -ge $nextReport) {
                $elapsedSeconds = [int][Math]::Floor($watch.Elapsed.TotalSeconds)
                Write-Host "[benchmark] $elapsedSeconds s elapsed, reading response..." -ForegroundColor Yellow
                $nextReport += 5
            }
        }
        $raw = $readTask.GetAwaiter().GetResult()
        $result = $raw | ConvertFrom-Json -ErrorAction Stop
    } finally {
        $response.Dispose()
    }

    $elapsed = [Math]::Round($watch.Elapsed.TotalSeconds, 2)
    Write-Host "[benchmark] Request completed in $elapsed seconds, including any cold model load." -ForegroundColor Green
    if ($result.timings -and
        $null -ne $result.timings.predicted_n -and
        $null -ne $result.timings.predicted_per_second) {
        $t = $result.timings
        Write-Host "[benchmark] Generation: $([Math]::Round([double]$t.predicted_per_second, 2)) tokens/sec" -ForegroundColor Green
        Write-Host "[benchmark] Generated tokens: $($t.predicted_n)"
        if ($null -ne $t.prompt_per_second) {
            Write-Host "[benchmark] Prompt processing: $([Math]::Round([double]$t.prompt_per_second, 2)) tokens/sec"
        }
    } elseif ($result.usage -and $null -ne $result.usage.completion_tokens) {
        $count = [int]$result.usage.completion_tokens
        Write-Host "[benchmark] Generated tokens: $count"
        Write-Host "[benchmark] Throughput including load: $([Math]::Round($count / [Math]::Max(0.001, $watch.Elapsed.TotalSeconds), 2)) tokens/sec (not pure generation speed)"
        Write-Host "[benchmark] This build did not include llama.cpp timings." -ForegroundColor Yellow
    } else {
        Write-Host "[benchmark] HTTP succeeded but returned no token timings. Check llama.cpp build." -ForegroundColor Yellow
    }
    Write-Host "[benchmark] Repeat once for warm-model performance. Compare CPU vs Vulkan only after a controlled router restart." -ForegroundColor DarkGray
} catch {
    $elapsed = [Math]::Round($watch.Elapsed.TotalSeconds, 1)
    Write-Host "[benchmark] Failed after $elapsed seconds: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[benchmark] Check .local-state/logs/ai.err.log and available physical RAM; the router may have exited during model loading." -ForegroundColor Yellow
    throw
} finally {
    $watch.Stop()
    $body.Dispose()
    $http.Dispose()
}
