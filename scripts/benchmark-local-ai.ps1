# Synthetic, read-only inference benchmark. No trading inputs or outputs.
# Only timing counters are displayed. Local server never leaves loopback.
param(
    [ValidateSet("TwIL-8B-Q4_K_M-balanced","Qwen3.5-9B-Q4_K_M")]
    [string]$Model = "Qwen3.5-9B-Q4_K_M",
    [ValidateRange(32,256)]
    [int]$MaxTokens = 128
)
$ErrorActionPreference = "Stop"
$origin = "http://127.0.0.1:8081"
$inventory = Invoke-RestMethod -Uri "$origin/models" -TimeoutSec 4
$available = @($inventory.data | Where-Object { $_.id -eq $Model })
if ($available.Count -eq 0) {
    throw "The selected model is not listed by the local router."
}
Write-Host "[benchmark] Model: $Model; max generated tokens: $MaxTokens." -ForegroundColor Cyan
$payload = @{
    model=$Model
    stream=$false
    temperature=0
    max_tokens=$MaxTokens
    cache_prompt=$false
    messages=@(
        @{role="system";content="Answer basic, general mathematics questions without private data."},
        @{role="user";content="Explain arithmetic mean versus geometric mean in plain English."}
    )
} | ConvertTo-Json -Depth 6 -Compress
$watch = [Diagnostics.Stopwatch]::StartNew()
try {
    $result = Invoke-RestMethod -Method Post -Uri "$origin/v1/chat/completions" -Body $payload -ContentType "application/json" -TimeoutSec 600
} catch {
    Write-Host "[benchmark] Local request failed ($($_.Exception.GetType().Name)). Check port 8081 and model logs." -ForegroundColor Red
    throw
} finally {
    $watch.Stop()
}
Write-Host "[benchmark] Total time (including first model load): $([Math]::Round($watch.Elapsed.TotalSeconds,1)) s" -ForegroundColor Green
if ($result.timings) {
    $t = $result.timings
    Write-Host "[benchmark] Prompt processing: $([Math]::Round([double]$t.prompt_per_second,2)) tokens/s"
    Write-Host "[benchmark] Generation: $([Math]::Round([double]$t.predicted_per_second,2)) tokens/s"
    Write-Host "[benchmark] Generated tokens: $($t.predicted_n)"
} elseif ($result.usage) {
    Write-Host "[benchmark] Generated tokens: $($result.usage.completion_tokens); server timings unavailable."
} else {
    Write-Host "[benchmark] Server timings unavailable on this build."
}
Write-Host "[benchmark] To compare with CPU, restart router with TRADING_SIM_LLAMA_DEVICE=cpu in .env." -ForegroundColor DarkGray
