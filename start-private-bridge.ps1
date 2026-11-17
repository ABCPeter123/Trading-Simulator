# Owner-only bridge launcher. Website visitors enter ONE shared password.
param(
    [string]$AllowedOrigin = "https://trading-simulator-pp-48b0.vercel.app",
    [string]$CloudflaredPath = "",
    [switch]$SetPassword,
    [switch]$ResetVercelToken,
    [switch]$ManualDirectory,
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
    if (-not $ManualDirectory -and ($ResetVercelToken -or -not (Test-Path $vercelFile))) {
        Write-Host "[setup] Create a Vercel access token at https://vercel.com/account/tokens" -ForegroundColor Yellow
        Write-Host "[setup] IMPORTANT: select the Vercel team PP (pp-48b0), not your Personal Account." -ForegroundColor Yellow
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
$researchWorker=$null
$marketWorker=$null
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
    # A separate local worker consumes persisted research jobs even if the
    # browser disconnects. It never uploads job data to Vercel or GitHub.
    $researchWorker=Start-Process -FilePath $python -WorkingDirectory $root -PassThru -ArgumentList @("-m","backend.research_worker","--interval","3") -RedirectStandardOutput (Join-Path $stateDir "research.stdout.log") -RedirectStandardError (Join-Path $stateDir "research.stderr.log")
    Start-Sleep -Milliseconds 600
    if($researchWorker.HasExited) {
        throw "Local research worker exited unexpectedly. See .local-state/private-bridge/research.stderr.log."
    }
    Write-Host "[research] Background portfolio job processor is active on this PC." -ForegroundColor Green
    # Market collection must continue when the private website disconnects.
    # Reuse a collector launched by the local npm environment to avoid double
    # polling anonymous market data providers.
    $marketAlreadyRunning=$false
    try {
        $marketAlreadyRunning=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -match 'backend[.]market_ingest_worker' }).Count -gt 0
    }catch{
        # Do not start a potential duplicate if inspection is unavailable.
        $marketAlreadyRunning=$true
    }
    if(-not $marketAlreadyRunning){
        $marketWorker=Start-Process -FilePath $python -WorkingDirectory $root -PassThru -ArgumentList @("-m","backend.market_ingest_worker","--interval","30") -RedirectStandardOutput (Join-Path $stateDir "market.stdout.log") -RedirectStandardError (Join-Path $stateDir "market.stderr.log")
        Start-Sleep -Milliseconds 300
        if($marketWorker.HasExited){throw "Market data collector exited unexpectedly. Check market.stderr.log."}
    }
    Write-Host "[market] Incremental local market collector available." -ForegroundColor Green
    # Supervise the temporary Cloudflare URL. Each new tunnel requires a fresh
    # directory publication, but visitors keep using the same Vercel address.
    $restartCount=0
    while($true){
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
    if(-not $tunnelUrl){
        if($tunnel.HasExited){
            $restartCount++
            $pause=[Math]::Min(60, 5 * $restartCount)
            Write-Host "[private] Cloudflare exited before publishing an address. Retrying in $pause seconds." -ForegroundColor Yellow
            $tunnel=$null
            Start-Sleep -Seconds $pause
            continue
        }
        throw "Could not obtain Cloudflare Quick Tunnel address. See .local-state/private-bridge/cloudflared.stderr.log."
    }
    # The tunnel opened successfully; reset the exponential retry delay.
    $restartCount=0
    if($ManualDirectory -and -not $LegacyToken){
        Write-Host "[private] Directory registration skipped by owner request." -ForegroundColor Yellow
        Write-Host "[private] This password-protected tunnel is running at: $tunnelUrl" -ForegroundColor Cyan
        Write-Host "[private] Only the tunnel URL (not your password or tokens) can be published manually through the connected Vercel account." -ForegroundColor Cyan
        Write-Host "[private] Website: $AllowedOrigin" -ForegroundColor Green
    }elseif(-not $LegacyToken){
        $statusFile=Join-Path $stateDir "publish-status.txt"
        Remove-Item Env:TRADING_SIM_PUBLISH_STATUS_PATH -ErrorAction SilentlyContinue
        $env:TRADING_SIM_PUBLISH_STATUS_PATH=$statusFile
        Remove-Item -LiteralPath $statusFile -ErrorAction SilentlyContinue
        # Child Python stderr may be hidden by terminal launchers; always read
        # back the safe structured diagnostic from local, ignored state.
        & $python (Join-Path $root "scripts\publish_tunnel.py") $tunnelUrl
        $publishExit=$LASTEXITCODE
        $published=($publishExit -eq 0)
        if(-not $published){
            $detail="Publisher failed before recording a diagnosis; see the local Python environment."
            if(Test-Path -LiteralPath $statusFile){
                $saved=(Get-Content -LiteralPath $statusFile -Raw -ErrorAction SilentlyContinue).Trim()
                if(-not [string]::IsNullOrWhiteSpace($saved)){ $detail=$saved }
            }
            if($detail -match 'HTTP 40[13]' -and -not $SkipSetup){
                # Repair the credential while the password-protected tunnel stays up.
                Write-Host "[setup] Your local Vercel credential cannot update team PP (pp-48b0)." -ForegroundColor Yellow
                $repair=Read-Host "Paste a replacement PP-scoped Vercel access token now? [y/N]"
                if($repair -match '^(y|yes)$'){
                    $secure=Read-Host -AsSecureString "Paste new team Vercel token (hidden)"
                    $bstr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
                    try { $replacement=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
                    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
                    if(-not [string]::IsNullOrWhiteSpace($replacement)){
                        Set-Content -LiteralPath $vercelFile -Value $replacement.Trim() -NoNewline -Encoding ASCII
                        Remove-Variable replacement -ErrorAction SilentlyContinue
                        & $python (Join-Path $root "scripts\publish_tunnel.py") $tunnelUrl
                        $published=($LASTEXITCODE -eq 0)
                        if($published){
                            Write-Host "[private] Link publishing authorized. Future tunnel URLs will synchronize automatically." -ForegroundColor Green
                        }elseif(Test-Path -LiteralPath $statusFile){
                            $detail=(Get-Content -LiteralPath $statusFile -Raw -ErrorAction SilentlyContinue).Trim()
                        }
                    }
                }
            }
            if(-not $published -and $detail -match 'HTTP 40[13]'){
                # A bad/mis-scoped Vercel token must not kill an otherwise healthy
                # password-protected API or Cloudflare tunnel.
                Write-Host "[private] Auto-registration failed: $detail" -ForegroundColor Yellow
                Write-Host "[private] Recovery mode: the protected bridge stays online." -ForegroundColor Yellow
                Write-Host "[private] Temporary tunnel URL (owner only): $tunnelUrl" -ForegroundColor Cyan
                Write-Host "[private] Publish ONLY that URL into the PP team's Global Config bridge item via your connected Vercel account." -ForegroundColor Cyan
                Write-Host "[private] For automatic registration next time, restart with -ResetVercelToken and a PP-scoped Vercel token." -ForegroundColor Yellow
            }elseif(-not $published){
                throw "Could not publish private tunnel address: $detail (exit $publishExit)"
            }
        }
        Write-Host "[private] Website: $AllowedOrigin" -ForegroundColor Green
        if($published){
            Write-Host "[private] Visitors enter ONLY the shared password. Do not give them the tunnel address." -ForegroundColor Green
        }else{
            Write-Host "[private] Website discovery is offline until the tunnel URL is registered manually." -ForegroundColor Yellow
        }
    }else{
        Write-Host "[legacy] Private tunnel: $tunnelUrl" -ForegroundColor Cyan
        Write-Host "[legacy] API token (never share publicly): $secret" -ForegroundColor Yellow
    }
    Write-Host "[private] Keep your computer on and this PowerShell window open. Ctrl+C stops the tunnel." -ForegroundColor Cyan
    # The publisher may fail temporarily during a network interruption.
    # Retry automatically when the problem was not an invalid/mis-scoped
    # credential (401/403). Never retry a rejected credential continuously.
    $retryAt=(Get-Date).AddSeconds(30)
    while(-not $tunnel.HasExited){
        Start-Sleep -Seconds 3
        if(-not $LegacyToken -and -not $ManualDirectory -and -not $published -and (Get-Date) -ge $retryAt){
            $lastStatus=""
            if(Test-Path -LiteralPath $statusFile){
                $lastStatus=(Get-Content -LiteralPath $statusFile -Raw -ErrorAction SilentlyContinue)
            }
            if($lastStatus -notmatch 'HTTP 40[13]'){
                & $python (Join-Path $root "scripts\\publish_tunnel.py") $tunnelUrl
                $published=($LASTEXITCODE -eq 0)
                if($published){
                    Write-Host "[private] Directory connection recovered automatically." -ForegroundColor Green
                }else{
                    Write-Host "[private] Directory publish retry failed; will retry if recoverable." -ForegroundColor Yellow
                }
            }
            $retryAt=(Get-Date).AddSeconds(60)
        }
    }
    # A Quick Tunnel URL is ephemeral. Replace it automatically after a
    # Cloudflare exit rather than asking the owner to copy/paste the new URL.
    $tunnel=$null
    $restartCount++
    $pause=[Math]::Min(60, 5 * $restartCount)
    Write-Host "[private] Cloudflare disconnected. Reconnecting in $pause seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds $pause
    }

} finally {
    if($null -ne $tunnel -and -not $tunnel.HasExited){Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue}
    if($null -ne $researchWorker -and -not $researchWorker.HasExited){Stop-Process -Id $researchWorker.Id -Force -ErrorAction SilentlyContinue}
    if($null -ne $marketWorker -and -not $marketWorker.HasExited){Stop-Process -Id $marketWorker.Id -Force -ErrorAction SilentlyContinue}
    if($null -ne $backend -and -not $backend.HasExited){Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue}
}
