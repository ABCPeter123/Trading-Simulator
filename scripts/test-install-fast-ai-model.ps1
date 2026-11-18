# Offline Windows CI test. Never touches owner data or downloads weights.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("trading-fast-ci-" + [guid]::NewGuid().ToString("N"))
try {
    $scriptsDir = Join-Path $tempRoot "scripts"
    $modelDir = Join-Path $tempRoot "models\private"
    New-Item -Path $scriptsDir,$modelDir -ItemType Directory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root "scripts\install-fast-ai-model.ps1") -Destination (Join-Path $scriptsDir "install-fast-ai-model.ps1")
    $file = [IO.File]::OpenWrite((Join-Path $modelDir "Qwen3.5-4B-Q4_K_M.gguf"))
    try { $file.SetLength(220MB) } finally { $file.Dispose() }
    Set-Content -LiteralPath (Join-Path $tempRoot ".env.example") -Value "TRADING_SIM_AI_PROVIDER=llama_cpp"
    $envFile = Join-Path $tempRoot ".env"
    Set-Content -LiteralPath $envFile -Value @(
        "TRADING_SIM_AI_PROVIDER=llama_cpp",
        "TRADING_SIM_AI_MODEL=TwIL-8B-Q4_K_M-balanced.gguf",
        "TRADING_SIM_AI_MODELS=TwIL-8B-Q4_K_M-balanced.gguf,Qwen3.5-9B-Q4_K_M.gguf",
        "TRADING_SIM_AI_MAX_OUTPUT_TOKENS=4096",
        "SYNTHETIC_PRIVATE_SETTING=never-echo-this-example"
    )
    $output = & (Join-Path $scriptsDir "install-fast-ai-model.ps1") -SetAsDefault | Out-String
    if ($output -match 'never-echo-this-example') { throw "Installer exposed private config." }
    $data = Get-Content -LiteralPath $envFile -Raw
    foreach ($expected in @(
        "SYNTHETIC_PRIVATE_SETTING=never-echo-this-example",
        "TRADING_SIM_AI_MODEL=Qwen3.5-4B-Q4_K_M.gguf",
        "TRADING_SIM_AI_MAX_OUTPUT_TOKENS=768"
    )) {
        if (-not $data.Contains($expected)) { throw "Installer did not preserve or set a required value." }
    }
    if ($data -notmatch '(?m)^TRADING_SIM_AI_MODELS=.*Qwen3.5-4B-Q4_K_M.gguf') {
        throw "Fast model missing from allowlist."
    }
    & (Join-Path $scriptsDir "install-fast-ai-model.ps1") | Out-Null
    $second = Get-Content -LiteralPath $envFile -Raw
    $allowlistLine = @($second.Split([char]10) | Where-Object { $_ -match '^TRADING_SIM_AI_MODELS=' })
    if ($allowlistLine.Count -ne 1) { throw "Duplicate allowlist setting." }
    if (($allowlistLine[0].Split([string[]]@("Qwen3.5-4B-Q4_K_M.gguf"),[StringSplitOptions]::None)).Count -ne 2) {
        throw "Duplicate compact model."
    }
    Write-Host "Fast model installer synthetic test passed." -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
