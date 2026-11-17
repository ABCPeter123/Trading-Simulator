# Resolve a Windows cloudflared binary even if the winget MSI did not
# register its installation directory in the current terminal's PATH.
function Find-CloudflaredExecutable {
    [CmdletBinding()]
    param([string]$ExplicitPath = "")

    $overridden = if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $ExplicitPath
    } elseif (-not [string]::IsNullOrWhiteSpace($env:TRADING_SIM_CLOUDFLARED)) {
        $env:TRADING_SIM_CLOUDFLARED
    } else { "" }

    if ($overridden) {
        $overridden = [Environment]::ExpandEnvironmentVariables($overridden.Trim('"'))
        if (-not (Test-Path -LiteralPath $overridden -PathType Leaf)) {
            throw "Specified cloudflared executable does not exist: $overridden"
        }
        return (Resolve-Path -LiteralPath $overridden).Path
    }

    $fromPath = Get-Command cloudflared.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($fromPath -and (Test-Path -LiteralPath $fromPath.Source -PathType Leaf)) {
        return $fromPath.Source
    }

    # MSI-based winget releases have used Program Files (x86) even on x64.
    # Include both Program Files locations, current and persisted PATH, and
    # per-user package-manager and portable-install directories.
    $folders = New-Object 'System.Collections.Generic.List[string]'
    foreach ($folder in @(
        "${env:ProgramFiles(x86)}\cloudflared",
        "$env:ProgramFiles\cloudflared",
        "$env:ProgramFiles\Cloudflare",
        "${env:ProgramFiles(x86)}\Cloudflare",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:LOCALAPPDATA\Programs\cloudflared",
        "$env:USERPROFILE\scoop\apps\cloudflared\current",
        "$env:ProgramData\chocolatey\bin",
        "C:\cloudflared",
        "$env:USERPROFILE\Downloads"
    )) {
        if ($folder -and (Test-Path -LiteralPath $folder -PathType Container)) {
            $folders.Add($folder)
        }
    }

    # After an MSI install, the running shell may have a stale PATH.
    foreach ($scope in @("Machine", "User")) {
        $storedPath = [Environment]::GetEnvironmentVariable("Path", $scope)
        if (-not $storedPath) { continue }
        foreach ($entry in ($storedPath -split ";")) {
            $expanded = [Environment]::ExpandEnvironmentVariables($entry.Trim('"'))
            if ($expanded -and (Test-Path -LiteralPath $expanded -PathType Container)) {
                $folders.Add($expanded)
            }
        }
    }

    foreach ($folder in ($folders | Select-Object -Unique)) {
        foreach ($name in @("cloudflared.exe", "cloudflared-windows-amd64.exe", "cloudflared-windows-386.exe", "cloudflared-windows-arm64.exe")) {
            $candidate = Join-Path $folder $name
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
        }
    }

    # Portable winget packages can install into versioned directories.
    if ($env:LOCALAPPDATA) {
        $packages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
        if (Test-Path -LiteralPath $packages -PathType Container) {
            $packageDirs = Get-ChildItem -Path $packages -Directory -Filter "Cloudflare.cloudflared*" -ErrorAction SilentlyContinue
            foreach ($dir in $packageDirs) {
                $binary = Get-ChildItem -LiteralPath $dir.FullName -Recurse -File -Filter "cloudflared*.exe" -ErrorAction SilentlyContinue |
                    Select-Object -First 1
                if ($binary) { return $binary.FullName }
            }
        }
    }
    return $null
}
