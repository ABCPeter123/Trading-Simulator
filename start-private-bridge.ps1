# Temporary owner-only tunnel: no strategies or private data deployed to Vercel.
param(
    [Parameter(Mandatory=$true)][string]$AllowedOrigin,
    [string]$CloudflaredPath = "",
    [switch]$RotateToken,
    [switch]$SkipSetup
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$stateDir = Join-Path $root ".local-state\private-bridge"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$uri = $null
if (-not [Uri]::TryCreate($AllowedOrigin, [UriKind]::Absolute, [ref]$uri) -or
    $uri.Scheme -ne "https" -or $uri.AbsolutePath -ne "/" -or
    $uri.Query -ne "" -or $uri.Fragment -ne "" -or $uri.UserInfo -ne "") {
    throw "Use the exact HTTPS Vercel origin: -AllowedOrigin 'https://your-site.vercel.app'"
}
$AllowedOrigin = $uri.GetLeftPart([System.UriPartial]::Authority).TrimEnd("/")
. (Join-Path $root "scripts\find-cloudflared.ps1")
$cloudflareExe = Find-CloudflaredExecutable -ExplicitPath $CloudflaredPath
if (-not $cloudflareExe) {
    throw "cloudflared missing. Install it or use -CloudflaredPath 'C:\path\to\cloudflared.exe'."
}
if (-not $SkipSetup) {
    & (Join-Path $root "start-local.ps1") -SetupOnly
    if ($LASTEXITCODE -ne 0) { throw "Project setup failed." }
}
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python missing. Run start-local.ps1 -SetupOnly." }
$tokenFile = Join-Path $stateDir "api-token.txt"
if ($RotateToken -or -not (Test-Path $tokenFile)) {
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $bytes = New-Object byte[] 48
        $generator.GetBytes($bytes)
        $token = [System.BitConverter]::ToString($bytes).Replace("-", "").ToLowerInvariant()
    } finally { $generator.Dispose() }
    Set-Content -LiteralPath $tokenFile -Value $token -NoNewline -Encoding ASCII
} else { $token = (Get-Content -LiteralPath $tokenFile -Raw).Trim() }
if ($token.Length -lt 48) { throw "Access token too short. Run with -RotateToken." }
$client = New-Object System.Net.Sockets.TcpClient
try {
    $client.Connect("127.0.0.1", 8002)
    throw "Port 8002 already in use. Stop the previous private bridge first."
} catch [System.Net.Sockets.SocketException] {
    # Nothing listening.
} finally { $client.Dispose() }
$env:TRADING_SIM_PRIVATE_BRIDGE = "1"
$env:TRADING_SIM_PRIVATE_API_TOKEN = $token
$env:TRADING_SIM_ALLOWED_ORIGINS = $AllowedOrigin
Remove-Item Env:TRADING_SIM_PUBLIC_DEMO -ErrorAction SilentlyContinue
$backend = $null
try {
    $backend = Start-Process -FilePath $python -WorkingDirectory $root -PassThru -ArgumentList @("-m","uvicorn","backend.main:app","--host","127.0.0.1","--port","8002") -RedirectStandardOutput (Join-Path $stateDir "api.stdout.log") -RedirectStandardError (Join-Path $stateDir "api.stderr.log")
    $ready = $false
    for ($i=0; $i -lt 60; $i++) {
        if ($backend.HasExited) { break }
        try {
            $response = Invoke-RestMethod -TimeoutSec 2 -Headers @{Authorization=("Bearer " + $token)} -Uri "http://127.0.0.1:8002/api/health"
            if ($response.mode -eq "private-bridge" -and $response.status -eq "ok") { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Private API failed authentication. Check .local-state/private-bridge/api.stderr.log." }
    Write-Host ""
    Write-Host "[private] Authenticated API ready. No databases uploaded." -ForegroundColor Green
    Write-Host "[private] Allowed Vercel origin: $AllowedOrigin" -ForegroundColor Cyan
    Write-Host "[private] Paste this access token into the Vercel site. Never share it with visitors:" -ForegroundColor Yellow
    Write-Host $token -ForegroundColor Yellow
    Write-Host ""
    Write-Host "[private] Cloudflare will print an HTTPS URL. Enter it as Engine URL on Vercel." -ForegroundColor Cyan
    Write-Host "[private] Keep your PC online. Ctrl+C stops the tunnel." -ForegroundColor Cyan
    Write-Host "[private] To revoke a leaked token, restart with -RotateToken." -ForegroundColor Yellow
    & $cloudflareExe tunnel --url http://127.0.0.1:8002
} finally {
    if ($null -ne $backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
