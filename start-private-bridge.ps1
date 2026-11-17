# Owner-only bridge launcher. Website visitors enter ONE shared password.
param(
    [string]$AllowedOrigin = "https://trading-simulator-pp-48b0.vercel.app",
    [string]$CloudflaredPath = "",
    [switch]$SetPassword,
    [switch]$ResetVercelToken,
    [switch]$SkipSetup,
    [switch]$LegacyToken,
    [switch]$RotateToken
)
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$stateDir=Join-Path $root ".local-state\private-bridge"
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$uri=$null
if (-not [Uri]::TryCreate($AllowedOrigin,[UriKind]::Absolute,[ref]$uri) -or $uri.Scheme -ne "https" -or $uri.AbsolutePath -ne "/" -or $uri.Query -ne "" -or $uri.Fragment -ne "" -or $uri.UserInfo -ne "") {
    throw "Use the exact HTTPS Vercel website origin with -AllowedOrigin."
}
$AllowedOrigin=$uri.GetLeftPart([System.UriPartial]::Authority).TrimEnd("/")
. (Join-Path $root "scripts\find-cloudflared.ps1")
$cloudflareExe=Find-CloudflaredExecutable -ExplicitPath $CloudflaredPath
if (-not $cloudflareExe) { throw "cloudflared not found. Install with winget install -e --id Cloudflare.cloudflared" }
if (-not $SkipSetup) {
    & (Join-Path $root "start-local.ps1") -SetupOnly
    if ($LASTEXITCODE -ne 0) { throw "Local Python dependency setup failed." }
}
$python=Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Missing .venv Python. Run start-local.ps1 -SetupOnly." }
$client=New-Object System.Net.Sockets.TcpClient
try {
    $client.Connect("127.0.0.1",8002)
    throw "The private bridge is already running on port 8002. Stop that bridge first."
} catch [System.Net.Sockets.SocketException] {
    # No existing listener.
} finally { $client.Dispose() }
$env:TRADING_SIM_PRIVATE_BRIDGE="1"
$env:TRADING_SIM_ALLOWED_ORIGINS=$AllowedOrigin
$env:TRADING_SIM_AI_PROVIDER="ollama"
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:TRADING_SIM_PUBLIC_DEMO -ErrorAction SilentlyContinue
if ($LegacyToken) {
    Remove-Item Env:TRADING_SIM_PRIVATE_PASSWORD_HASH -ErrorAction SilentlyContinue
    $tokenFile=Join-Path $stateDir "api-token.txt"
    if ($RotateToken -or -not (Test-Path $tokenFile)) {
        $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $bytes=New-Object byte[] 48
            $rng.GetBytes($bytes)
            $secret=[BitConverter]::ToString($bytes).Replace("-","").ToLowerInvariant()
        } finally { $rng.Dispose() }
        Set-Content -LiteralPath $tokenFile -Value $secret -NoNewline -Encoding ASCII
    }
    $secret=(Get-Content -LiteralPath $tokenFile -Raw).Trim()
    if ($secret.Length -lt 48) { throw "Invalid legacy API token. Rerun with -RotateToken." }
    $env:TRADING_SIM_PRIVATE_API_TOKEN=$secret
} else {
    Remove-Item Env:TRADING_SIM_PRIVATE_API_TOKEN -ErrorAction SilentlyContinue
    $hashFile=Join-Path $stateDir "password-hash.txt"
    if ($SetPassword -or -not (Test-Path $hashFile)) {
        Write-Host "[setup] Choose the ONE password to share with approved website visitors." -ForegroundColor Cyan
        & $python (Join-Path $root "scripts\setup_bridge_password.py")
        if ($LASTEXITCODE -ne 0) { throw "Password setup was not completed." }
    }
    $hash=(Get-Content -LiteralPath $hashFile -Raw).Trim()
    if (-not $hash.StartsWith("pbkdf2-sha256$")) {
        throw "Invalid private password verifier. Restart with -SetPassword."
    }
    $env:TRADING_SIM_PRIVATE_PASSWORD_HASH=$hash
    $vercelFile=Join-Path $stateDir "vercel-token.txt"
    if ($ResetVercelToken -or -not (Test-Path $vercelFile)) {
        Write-Host "[setup] Create a Vercel access token at https://vercel.com/account/tokens" -ForegroundColor Yellow
        Write-Host "[setup] IMPORTANT: select the Vercel TEAM that owns Trading Simulator, not your Personal Account." -ForegroundColor Yellow
        Write-Host "[setup] The token must be permitted to WRITE Global Config items in that team." -ForegroundColor Yellow
        $secure=Read-Host -AsSecureString "Paste Vercel access token (hidden, local storage only)"
        $bstr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $vercelToken=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if ([string]::IsNullOrWhiteSpace($vercelToken)) { throw "Vercel token is required for automatic tunnel discovery." }
        Set-Content -LiteralPath $vercelFile -Value $vercelToken.Trim() -Encoding ASCII -NoNewline
        Remove-Variable vercelToken -ErrorAction SilentlyContinue
        Write-Host "[setup] Vercel token stored locally in the Git-ignored bridge directory." -ForegroundColor Green
    }
}
$backend=$null
$tunnel=$null
try {
    $backend=Start-Process -FilePath $python -WorkingDirectory $root -PassThru -ArgumentList @("-m","uvicorn","backend.main:app","--host","127.0.0.1","--port","8002") -RedirectStandardOutput (Join-Path $stateDir "api.stdout.log") -RedirectStandardError (Join-Path $stateDir "api.stderr.log")
    $ready=$false
    for($i=0;$i -lt 70;$i++){
        if($backend.HasExited){break}
        try{
            if($LegacyToken){
                $response=Invoke-RestMethod -TimeoutSec 2 -Headers @{Authorization=("Bearer "+$secret)} -Uri "http://127.0.0.1:8002/api/health"
                if($response.mode -eq "private-bridge"){$ready=$true;break}
            }else{
                $response=Invoke-RestMethod -TimeoutSec 2 -Uri "http://127.0.0.1:8002/api/auth/status"
                if($response.mode -eq "private-bridge-password"){$ready=$true;break}
            }
        }catch{}
        Start-Sleep -Milliseconds 500
    }
    if(-not $ready){throw "Private API did not start. See .local-state/private-bridge/api.stderr.log."}
    Write-Host "[private] Local password-protected trading API is ready." -ForegroundColor Green
    $log=Join-Path $stateDir "cloudflared.stderr.log"
    $out=Join-Path $stateDir "cloudflared.stdout.log"
    if(Test-Path $log){Remove-Item $log -Force}
    if(Test-Path $out){Remove-Item $out -Force}
    $tunnel=Start-Process -FilePath $cloudflareExe -WorkingDirectory $root -PassThru -ArgumentList @("tunnel","--url","http://127.0.0.1:8002") -RedirectStandardOutput $out -RedirectStandardError $log
    $tunnelUrl=$null
    for($i=0;$i -lt 120;$i++){
        if($tunnel.HasExited){break}
        if(Test-Path $log){
            $raw=(Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue)
            if($raw -match 'https://[a-z0-9-]+\.trycloudflare\.com'){
                $tunnelUrl=$Matches[0];break
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if(-not $tunnelUrl){throw "Could not obtain Cloudflare Quick Tunnel address. See .local-state/private-bridge/cloudflared.stderr.log."}
    if(-not $LegacyToken){
        & $python (Join-Path $root "scripts\publish_tunnel.py") $tunnelUrl
        if($LASTEXITCODE -ne 0){
            throw "Tunnel directory publish failed (exit $LASTEXITCODE). See the safe HTTP status above. To replace the local Vercel token, rerun with -ResetVercelToken."
        }
        Write-Host "[private] Website: $AllowedOrigin" -ForegroundColor Green
        Write-Host "[private] Visitors enter ONLY the shared password. Do not give them the tunnel address." -ForegroundColor Green
    }else{
        Write-Host "[legacy] Private tunnel: $tunnelUrl" -ForegroundColor Cyan
        Write-Host "[legacy] API token (never share publicly): $secret" -ForegroundColor Yellow
    }
    Write-Host "[private] Keep your computer on and this PowerShell window open. Ctrl+C stops the tunnel." -ForegroundColor Cyan
    while(-not $tunnel.HasExited){Start-Sleep -Seconds 1}
    throw "Cloudflare tunnel exited. Restart this script to publish the next tunnel address."
} finally {
    if($null -ne $tunnel -and -not $tunnel.HasExited){Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue}
    if($null -ne $backend -and -not $backend.HasExited){Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue}
}
