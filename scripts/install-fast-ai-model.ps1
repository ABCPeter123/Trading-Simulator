# Opt-in installer for the public, compact Qwen3.5-4B Q4_K_M GGUF.
# Run locally on Windows. Never uploads or prints .env, keys, or trading data.
# Downloads weights only to the Git-ignored models/private/ directory.
param([switch]$SetAsDefault)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$weightsDir = Join-Path $root "models\private"
$filename = "Qwen3.5-4B-Q4_K_M.gguf"
$repository = "unsloth/Qwen3.5-4B-GGUF"
$modelId = [IO.Path]::GetFileNameWithoutExtension($filename)
if (-not (Test-Path -LiteralPath $weightsDir)) {
    New-Item -ItemType Directory -Force -Path $weightsDir | Out-Null
}
$target = Join-Path $weightsDir $filename
if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or
    (Get-Item -LiteralPath $target).Length -lt 200MB) {
    $hf = Get-Command hf -ErrorAction SilentlyContinue
    if (-not $hf) {
        throw "The Hugging Face 'hf' command is missing. Run: python -m pip install -U huggingface_hub"
    }
    Write-Host "[ai] Downloading public Qwen3.5-4B Q4_K_M GGUF into models/private/ on your E: drive." -ForegroundColor Cyan
    & $hf.Source download $repository $filename --local-dir $weightsDir
    if ($LASTEXITCODE -ne 0) { throw "Hugging Face download failed; local config was not modified." }
}
if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or
    (Get-Item -LiteralPath $target).Length -lt 200MB) {
    throw "Downloaded GGUF was not found or appears too small; local config was not modified."
}

$envPath = Join-Path $root ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    $example = Join-Path $root ".env.example"
    if (-not (Test-Path -LiteralPath $example)) {
        throw "Missing .env.example. Cannot safely create local config."
    }
    Copy-Item -LiteralPath $example -Destination $envPath -ErrorAction Stop
}
# Only edit designated AI settings; preserve unrelated private environment
# settings, financial data paths, and webhook/notification configurations.
$lines = [Collections.Generic.List[string]]::new()
foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
    $lines.Add($line)
}
function Set-Config([string]$Name,[string]$Value) {
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*='
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) {
            $lines[$i] = "$Name=$Value"
            return
        }
    }
    $lines.Add("$Name=$Value")
}
$models = @()
foreach ($line in $lines) {
    if ($line -match '^\s*TRADING_SIM_AI_MODELS\s*=\s*(.*)$') {
        $models = @($Matches[1].Trim().Trim('"').Trim("'") -split "," |
                    ForEach-Object { $_.Trim() } | Where-Object { $_ })
        break
    }
}
if ($models.Count -eq 0) {
    $models = @("TwIL-8B-Q4_K_M-balanced.gguf","Qwen3.5-9B-Q4_K_M.gguf")
}
if ($models -notcontains $filename) {
    $models = @($models) + $filename
}
if ($models.Count -gt 8) {
    throw "Backend accepts at most 8 local models. Edit TRADING_SIM_AI_MODELS manually."
}
Set-Config "TRADING_SIM_AI_PROVIDER" "llama_cpp"
Set-Config "TRADING_SIM_AI_MODELS" ($models -join ",")
if ($SetAsDefault) {
    Set-Config "TRADING_SIM_AI_MODEL" $filename
    Set-Config "TRADING_SIM_AI_MAX_OUTPUT_TOKENS" "768"
}
# Write UTF-8 without BOM so PowerShell and Python parse the first key
# consistently. Never output config content.
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($envPath, ($lines -join [Environment]::NewLine) + [Environment]::NewLine, $utf8)
Write-Host "[ai] Compact model installed locally: $modelId" -ForegroundColor Green
Write-Host "[ai] Local allowlist updated. Only 1 model is loaded at once." -ForegroundColor Green
if ($SetAsDefault) {
    Write-Host "[ai] Selected compact model as default with 768 output tokens." -ForegroundColor Green
}
Write-Host "[ai] Run stop-local.ps1 then start-local.ps1 -NoBrowser to refresh the model inventory." -ForegroundColor Cyan
