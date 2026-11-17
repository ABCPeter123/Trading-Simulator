# Offline Windows test for cloudflared resolution, independent of real installation.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $root "scripts\find-cloudflared.ps1")
$testDir = Join-Path $env:TEMP ("cloudflared-resolver-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $testDir -Force | Out-Null
$exe = Join-Path $testDir "cloudflared.exe"
Set-Content -LiteralPath $exe -Value "Synthetic test binary. Do not execute." -Encoding ASCII
$oldValue = $env:TRADING_SIM_CLOUDFLARED
try {
    $actual = Find-CloudflaredExecutable -ExplicitPath $exe
    if ($actual -ne $exe) { throw "Explicit cloudflared executable path was not respected." }
    $env:TRADING_SIM_CLOUDFLARED = $exe
    $actual = Find-CloudflaredExecutable
    if ($actual -ne $exe) { throw "Environment-provided cloudflared path was not respected." }
    $missing = Join-Path $testDir "missing.exe"
    $caught = $false
    try { Find-CloudflaredExecutable -ExplicitPath $missing | Out-Null }
    catch { $caught = $true }
    if (-not $caught) { throw "Bad explicit path must cause a clear error." }
    Write-Host "cloudflared installed executable resolution tests passed." -ForegroundColor Green
} finally {
    if ($null -eq $oldValue) {
        Remove-Item Env:TRADING_SIM_CLOUDFLARED -ErrorAction SilentlyContinue
    } else { $env:TRADING_SIM_CLOUDFLARED = $oldValue }
    Remove-Item $testDir -Recurse -Force -ErrorAction SilentlyContinue
}
