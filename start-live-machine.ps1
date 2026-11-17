# Run the private daily strategy monitor independently of the browser.
# Use -Stop to stop it; -Once to test a single cycle; -InstallAtLogon for
# Windows Task Scheduler automatic startup on user logon.
param(
    [switch]$Stop,
    [switch]$Once,
    [switch]$TestIMessage,
    [switch]$SendEmailReport,
    [switch]$SkipSetup,
    [switch]$InstallAtLogon,
    [switch]$Foreground,
    [int]$IntervalSeconds = 90
)
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$state=Join-Path $root ".local-state\live-machine"
New-Item -ItemType Directory -Path $state -Force | Out-Null
$pidFile=Join-Path $state "worker.pid"

function Existing-Worker {
    if (-not (Test-Path $pidFile)) { return $null }
    $stored = 0
    if (-not [int]::TryParse((Get-Content $pidFile -Raw).Trim(),[ref]$stored)) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$stored" -ErrorAction SilentlyContinue
    if ($null -ne $proc -and $proc.CommandLine -like "*backend.live_worker*") {
        return $proc
    }
    return $null
}

if ($Stop) {
    $old=Existing-Worker
    if ($null -ne $old) {
        Stop-Process -Id $old.ProcessId -Force
        Write-Host "[live] Stopped background strategy monitor." -ForegroundColor Yellow
    } else { Write-Host "[live] No running background strategy monitor." }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    $task=Get-ScheduledTask -TaskName "TradingSimulatorLiveMachine" -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq "Running") { Stop-ScheduledTask -TaskName "TradingSimulatorLiveMachine" }
    exit 0
}
if ($InstallAtLogon) {
    $launchArgs="-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " + ('"' + (Join-Path $root "start-live-machine.ps1") + '"') + " -SkipSetup -Foreground -IntervalSeconds $IntervalSeconds"
    $action=New-ScheduledTaskAction -Execute "powershell.exe" -Argument $launchArgs -WorkingDirectory $root
    $trigger=New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
    Register-ScheduledTask -TaskName "TradingSimulatorLiveMachine" -Action $action -Trigger $trigger -Settings $settings -Description "Owner private trading strategy monitor, no broker order execution" -Force | Out-Null
    Write-Host "[live] Windows logon task installed for this user." -ForegroundColor Green
    Write-Host "[live] PC must be powered on and this Windows user must log on." -ForegroundColor Yellow
    exit 0
}
if ($IntervalSeconds -lt 30 -or $IntervalSeconds -gt 3600) {
    throw "Worker interval must be between 30 and 3600 seconds."
}
if (-not $SkipSetup) {
    & (Join-Path $root "start-local.ps1") -SetupOnly
    if ($LASTEXITCODE -ne 0) { throw "Python and Node setup failed." }
}
$python=Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python environment missing. Run start-local.ps1 -SetupOnly." }

# Only parse allowlisted environment variables, never run arbitrary .env code.
# The worker does not require a cloud service or a broker API key.
$envFile=Join-Path $root ".env"
$allowed='^(TRADING_SIM_DISCORD_WEBHOOK|TRADING_SIM_SMTP_HOST|TRADING_SIM_SMTP_PORT|TRADING_SIM_SMTP_USER|TRADING_SIM_SMTP_PASSWORD|TRADING_SIM_EMAIL_TO|TRADING_SIM_EMAIL_FROM|TRADING_SIM_NOTIFICATION_CHANNELS|TRADING_SIM_EMAIL_DIGEST_ENABLED|TRADING_SIM_EMAIL_DIGEST_TIME|TRADING_SIM_IMESSAGE_SERVER_URL|TRADING_SIM_IMESSAGE_PASSWORD|TRADING_SIM_IMESSAGE_CHAT_GUID|TRADING_SIM_IMESSAGE_INCLUDE_DETAILS)\s*=\s*(.*)$'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        if ($line -match $allowed) {
            $value=$Matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($Matches[1],$value,"Process")
        }
    }
}
$env:TRADING_SIM_PUBLIC_DEMO="0"
if ($SendEmailReport) {
    Write-Host "[live] Email a complete live strategy and portfolio report to the recipient(s) configured in private .env." -ForegroundColor Cyan
    $approval=Read-Host "This sends private trading information by email. Continue? [y/N]"
    if ($approval -notmatch '^(y|yes)
    Write-Host "[live] Send one generic test message through your own Mac iMessage relay?" -ForegroundColor Cyan
    $approval=Read-Host "This sends a real iMessage to your configured chat. Continue? [y/N]"
    if ($approval -notmatch '^(y|yes)$') {
        Write-Host "[live] iMessage test canceled. Nothing was sent." -ForegroundColor Yellow
        exit 0
    }
    & $python -m backend.imessage_probe
    exit $LASTEXITCODE
}
if ($Once) {
    Write-Host "[live] Running one monitoring and notification cycle..." -ForegroundColor Cyan
    & $python -m backend.live_worker --once --interval $IntervalSeconds
    exit $LASTEXITCODE
}
if ($Foreground) {
    Write-Host "[live] Persistent worker started; Windows Task Scheduler can monitor and restart this process." -ForegroundColor Green
    & $python -m backend.live_worker --interval $IntervalSeconds
    exit $LASTEXITCODE
}
$old=Existing-Worker
if ($null -ne $old) {
    Write-Host "[live] Worker already running (PID $($old.ProcessId))." -ForegroundColor Yellow
    exit 0
}
$out=Join-Path $state "worker.stdout.log"
$err=Join-Path $state "worker.stderr.log"
$proc=Start-Process -FilePath $python -WorkingDirectory $root -PassThru -ArgumentList @("-m","backend.live_worker","--interval","$IntervalSeconds") -RedirectStandardOutput $out -RedirectStandardError $err
Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII
Start-Sleep -Milliseconds 1200
if ($proc.HasExited) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    throw "Strategy monitor exited unexpectedly. Check .local-state/live-machine/worker.stderr.log."
}
Write-Host "[live] Background strategy monitor running (PID $($proc.Id))." -ForegroundColor Green
Write-Host "[live] Research, saved strategies, signals, alerts and confirmed fills stay in ignored data/." -ForegroundColor Cyan
Write-Host "[live] Browser and localhost API may close; worker continues until stopped or Windows shuts down." -ForegroundColor Cyan
Write-Host "[live] To stop: .\start-live-machine.ps1 -Stop" -ForegroundColor Cyan
) {
        Write-Host "[live] Email report canceled. Nothing was sent." -ForegroundColor Yellow
        exit 0
    }
    & $python -m backend.email_report_probe
    exit $LASTEXITCODE
}
if ($TestIMessage) {
    Write-Host "[live] Send one generic test message through your own Mac iMessage relay?" -ForegroundColor Cyan
    $approval=Read-Host "This sends a real iMessage to your configured chat. Continue? [y/N]"
    if ($approval -notmatch '^(y|yes)$') {
        Write-Host "[live] iMessage test canceled. Nothing was sent." -ForegroundColor Yellow
        exit 0
    }
    & $python -m backend.imessage_probe
    exit $LASTEXITCODE
}
if ($Once) {
    Write-Host "[live] Running one monitoring and notification cycle..." -ForegroundColor Cyan
    & $python -m backend.live_worker --once --interval $IntervalSeconds
    exit $LASTEXITCODE
}
if ($Foreground) {
    Write-Host "[live] Persistent worker started; Windows Task Scheduler can monitor and restart this process." -ForegroundColor Green
    & $python -m backend.live_worker --interval $IntervalSeconds
    exit $LASTEXITCODE
}
$old=Existing-Worker
if ($null -ne $old) {
    Write-Host "[live] Worker already running (PID $($old.ProcessId))." -ForegroundColor Yellow
    exit 0
}
$out=Join-Path $state "worker.stdout.log"
$err=Join-Path $state "worker.stderr.log"
$proc=Start-Process -FilePath $python -WorkingDirectory $root -PassThru -ArgumentList @("-m","backend.live_worker","--interval","$IntervalSeconds") -RedirectStandardOutput $out -RedirectStandardError $err
Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII
Start-Sleep -Milliseconds 1200
if ($proc.HasExited) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    throw "Strategy monitor exited unexpectedly. Check .local-state/live-machine/worker.stderr.log."
}
Write-Host "[live] Background strategy monitor running (PID $($proc.Id))." -ForegroundColor Green
Write-Host "[live] Research, saved strategies, signals, alerts and confirmed fills stay in ignored data/." -ForegroundColor Cyan
Write-Host "[live] Browser and localhost API may close; worker continues until stopped or Windows shuts down." -ForegroundColor Cyan
Write-Host "[live] To stop: .\start-live-machine.ps1 -Stop" -ForegroundColor Cyan
