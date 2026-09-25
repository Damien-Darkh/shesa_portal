"""
windows_launcher.py - Generates the two pieces of the Windows onboarding flow.

  1. A tiny, generic .cmd - the only file downloaded to disk. No secrets.
     Self-elevates, fetches the real script via irm ... | iex, runs it.

  2. The real PS1 script - personalized with WireGuard keys, served once
     by app.py's /devices/<id>/launcher-script route then wiped.

Flow in the PS1:
  - Shortcut to \\NAS_IP always created/verified first, unconditionally.
  - Detect WireGuard state and NAS direct-reachability.
  - Present a Windows Forms dialog for user choice.
  - Act on the choice (install/enable/disable/remove/skip).
  - Verify handshake + NAS reachability only when tunnel ends up active.
"""

CMD_TEMPLATE = """@echo off
setlocal

rem Self-elevate using net session (zero-dependency admin check).
rem Relaunching the .cmd directly avoids nested quote-escaping.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator permission...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Setting up company network access...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { irm '__PORTAL_URL__/devices/__DEVICE_ID__/launcher-script?token=__ONE_TIME_TOKEN__' | iex } catch { Write-Host ''; Write-Host 'Setup failed:' $_.Exception.Message -ForegroundColor Red; Write-Host ''; Write-Host 'Contact IT if this keeps happening.'; pause }"
"""


PS1_TEMPLATE = r"""
# ============================================================
# Company Network Setup
# Device: __DEVICE_ID__
# ============================================================

$ErrorActionPreference = "Stop"
$DeviceId  = "__DEVICE_ID__"
$TunnelName = "__TUNNEL_NAME__"
$NasIp      = "__NAS_IP__"
$ShareName  = "__SHARE_NAME__"

$WgPrivateKey     = "__WG_PRIVATE_KEY__"
$WgAddress        = "__WG_ADDRESS__"
$WgDns            = "__WG_DNS__"
$PeerPublicKey    = "__WG_PEER_PUBLIC_KEY__"
$PeerPresharedKey = "__WG_PRESHARED_KEY__"
$PeerEndpoint     = "__WG_ENDPOINT__"
$PeerAllowedIps   = "__WG_ALLOWED_IPS__"
$PeerKeepalive    = "__WG_KEEPALIVE__"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$LogFile = Join-Path $env:TEMP "connect-company-network.log"
$WorkDir = Join-Path $env:TEMP ("ccn-" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -Path $LogFile -Value $line
}

function Show-Info {
    param([string]$Text, [string]$Title = "Company Network Setup")
    [System.Windows.Forms.MessageBox]::Show(
        $Text, $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}

function Show-Error {
    param([string]$Text, [string]$Title = "Company Network Setup")
    [System.Windows.Forms.MessageBox]::Show(
        $Text, $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

function Cleanup-WorkDir {
    if (Test-Path $WorkDir) {
        Remove-Item -Path $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "Temporary working directory cleaned up"
    }
}

function Fail {
    param([string]$Message)
    Write-Log $Message "ERROR"
    Cleanup-WorkDir
    Show-Error "$Message`n`nDevice: $DeviceId`nLog: $LogFile"
    exit 1
}

try {
    Write-Log "=== Company Network Setup started. Device: $DeviceId ==="

    # ============================================================
    # STEP 1 - SHORTCUT (always, unconditionally, independent of VPN)
    # ============================================================

    $desktopPath  = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "SHESA.lnk"
    $uncTarget    = "\\$NasIp"

    if (-not (Test-Path $shortcutPath)) {
        try {
            $wsh = New-Object -ComObject WScript.Shell
            $sc  = $wsh.CreateShortcut($shortcutPath)
            # WScript.Shell TargetPath does not reliably handle UNC paths on all
            # Windows builds. Using explorer.exe + Arguments is the safe pattern:
            # the shortcut opens Explorer at the UNC location without COM path issues.
            $sc.TargetPath  = "explorer.exe"
            $sc.Arguments   = $uncTarget
            $sc.Description = "Company file server"
            $sc.Save()
            [Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null
            Write-Log "Desktop shortcut created -> $uncTarget"
        } catch {
            Write-Log "Could not create desktop shortcut (non-fatal): $_" "WARN"
        }
    } else {
        Write-Log "Desktop shortcut already exists - skipping"
    }

    # ============================================================
    # STEP 2 - DETECT STATE
    # ============================================================

    function Get-WireGuardExe {
        foreach ($c in @(
            "$env:ProgramFiles\WireGuard\wireguard.exe",
            "${env:ProgramFiles(x86)}\WireGuard\wireguard.exe"
        )) { if (Test-Path $c) { return $c } }
        return $null
    }

    function Get-WgCliExe {
        $wg = Get-WireGuardExe
        if ($wg) { return Join-Path (Split-Path $wg) "wg.exe" }
        return $null
    }

    function Get-TunnelService {
        $svcName = "WireGuardTunnel`$TunnelName"
        return Get-Service -Name $svcName -ErrorAction SilentlyContinue
    }

    function Test-NasDirect {
        # Probe NAS SMB port without the VPN - if it answers we're on the LAN.
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $ar  = $tcp.BeginConnect($NasIp, 445, $null, $null)
            $ok  = $ar.AsyncWaitHandle.WaitOne(2000)
            $tcp.Close()
            return $ok
        } catch { return $false }
    }

    $wgExe     = Get-WireGuardExe
    $wgInstalled = $null -ne $wgExe
    $tunnelSvc = Get-TunnelService
    $tunnelExists = $null -ne $tunnelSvc

    $state = if ($tunnelSvc) { $tunnelSvc.Status } else { "None" }
    Write-Log "WireGuard installed: $wgInstalled | Tunnel exists: $tunnelExists | State: $state"

    # ============================================================
    # STEP 3 - DIALOG AND ACTION
    # ============================================================

    # --- Helper: install WireGuard if not present ---
    function Install-WireGuard {
        if (Get-WireGuardExe) { Write-Log "WireGuard already installed"; return }

        Write-Log "Downloading WireGuard installer..."
        $installerPath = Join-Path $WorkDir "wireguard-installer.exe"
        $downloaded = $false
        for ($i = 0; $i -lt 3; $i++) {
            try {
                Invoke-WebRequest -Uri "https://download.wireguard.com/windows-client/wireguard-installer.exe" `
                    -OutFile $installerPath -UseBasicParsing
                $downloaded = $true; break
            } catch {
                Write-Log "Download attempt $($i+1) failed: $_" "WARN"
                Start-Sleep -Seconds 3
            }
        }
        if (-not $downloaded) { Fail "Could not download the WireGuard installer. Check internet connectivity." }

        $sig = Get-AuthenticodeSignature -FilePath $installerPath
        if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'WireGuard') {
            Fail "The WireGuard installer failed signature verification. Contact IT before retrying."
        }
        Write-Log "Installing WireGuard..."
        $p = Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fail "WireGuard installation failed (exit code $($p.ExitCode))." }
        if (-not (Get-WireGuardExe)) { Fail "WireGuard installation did not complete as expected." }
        Write-Log "WireGuard installed successfully"
    }

    # --- Helper: write config, install tunnel service ---
    function Import-Tunnel {
        # Remove stale service from a previous attempt if present
        $existing = Get-TunnelService
        if ($existing) {
            Write-Log "Removing stale tunnel service before reimporting..." "WARN"
            Start-Process -FilePath (Get-WireGuardExe) `
                -ArgumentList "/uninstalltunnelservice", "$TunnelName" `
                -Wait -WindowStyle Hidden | Out-Null
            Start-Sleep -Seconds 2
        }

        $configContent = @"
[Interface]
PrivateKey = $WgPrivateKey
Address = $WgAddress
DNS = $WgDns

[Peer]
PublicKey = $PeerPublicKey
PresharedKey = $PeerPresharedKey
Endpoint = $PeerEndpoint
AllowedIPs = $PeerAllowedIps
PersistentKeepalive = $PeerKeepalive
"@
        $configPath = Join-Path $WorkDir "$TunnelName.conf"
        Set-Content -Path $configPath -Value $configContent -Encoding ASCII
        Write-Log "Config written to $configPath"

        $p = Start-Process -FilePath (Get-WireGuardExe) `
            -ArgumentList "/installtunnelservice", $configPath `
            -Wait -PassThru -WindowStyle Hidden
        if ($p.ExitCode -ne 0) { Fail "Failed to import the WireGuard tunnel (exit code $($p.ExitCode))." }
        Write-Log "Tunnel service imported"
    }

    # --- Helper: start tunnel and poll until running ---
    function Enable-Tunnel {
        $svc = Get-TunnelService
        if ($svc -and $svc.Status -eq 'Running') { Write-Log "Tunnel already running"; return }
        $svcName = "WireGuardTunnel`$TunnelName"
        Start-Service -Name $svcName -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 2
            $svc = Get-TunnelService
            if ($svc -and $svc.Status -eq 'Running') { Write-Log "Tunnel running"; return }
        }
        Fail "Tunnel did not reach a running state. Check the log at $LogFile."
    }

    # --- Helper: stop tunnel service cleanly ---
    function Disable-Tunnel {
        $svcName = "WireGuardTunnel`$TunnelName"
        Stop-Service -Name $svcName -Force -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Seconds 1
            $svc = Get-TunnelService
            if (-not $svc -or $svc.Status -eq 'Stopped') { Write-Log "Tunnel stopped"; return }
        }
        Write-Log "Tunnel did not stop cleanly within timeout" "WARN"
    }

    # --- Helper: uninstall tunnel service ---
    function Remove-Tunnel {
        $wg = Get-WireGuardExe
        if (-not $wg) { Write-Log "WireGuard not found, nothing to uninstall"; return }
        Start-Process -FilePath $wg -ArgumentList "/uninstalltunnelservice", "$TunnelName" `
            -Wait -WindowStyle Hidden | Out-Null
        Write-Log "Tunnel service removed"
    }

    # --- Helper: uninstall WireGuard itself ---
    function Uninstall-WireGuard {
        $wg = Get-WireGuardExe
        if (-not $wg) { Write-Log "WireGuard not installed, nothing to remove"; return }
        $uninstaller = Join-Path (Split-Path $wg) "uninstall.exe"
        if (Test-Path $uninstaller) {
            $p = Start-Process -FilePath $uninstaller -ArgumentList "/S" -Wait -PassThru
            Write-Log "WireGuard uninstall exit code: $($p.ExitCode)"
        } else {
            # Fallback: WireGuard registers with Windows uninstall via its own installer
            $key = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" `
                -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match 'WireGuard' }
            if ($key -and $key.UninstallString) {
                $p = Start-Process -FilePath "cmd.exe" `
                    -ArgumentList "/c", $key.UninstallString, "/S" -Wait -PassThru
                Write-Log "WireGuard uninstall via registry, exit code: $($p.ExitCode)"
            } else {
                Write-Log "Could not find WireGuard uninstaller" "WARN"
            }
        }
    }

    # --- Helper: verify handshake + NAS reachability (only when tunnel is active) ---
    function Test-VpnAndNas {
        $wgCli = Get-WgCliExe
        $handshakeOk = $false
        if ($wgCli -and (Test-Path $wgCli)) {
            for ($i = 0; $i -lt 15; $i++) {
                $hs = & $wgCli show $TunnelName latest-handshakes 2>$null
                if ($hs -and ($hs -split "`t")[1] -match '^\d+$' -and [int](($hs -split "`t")[1]) -gt 0) {
                    $handshakeOk = $true; break
                }
                Start-Sleep -Seconds 2
            }
        }
        Write-Log "Handshake confirmed: $handshakeOk"

        $pingOk = $false
        for ($i = 0; $i -lt 5; $i++) {
            if (Test-Connection -ComputerName $NasIp -Count 1 -Quiet -ErrorAction SilentlyContinue) {
                $pingOk = $true; break
            }
            Start-Sleep -Seconds 2
        }

        $smbOk = $false
        for ($i = 0; $i -lt 10; $i++) {
            if (Test-NetConnection -ComputerName $NasIp -Port 445 -InformationLevel Quiet -ErrorAction SilentlyContinue) {
                $smbOk = $true; break
            }
            Start-Sleep -Seconds 2
        }
        Write-Log "Ping: $pingOk | SMB: $smbOk"

        if (-not $smbOk) {
            $reason = if (-not $handshakeOk) {
                "The VPN tunnel has no active handshake. Check that UDP port $PeerEndpoint is reachable from this network."
            } elseif (-not $pingOk) {
                "Cannot reach $NasIp over the VPN. Check OPNsense routing rules for this peer."
            } else {
                "Host at $NasIp responds to ping but not on the file-sharing port. Check the Synology SMB service."
            }
            Fail "VPN connected but company server is not reachable: $reason"
        }
        Write-Log "NAS reachable - all checks passed"
    }

    # ============================================================
    # BRANCH: Tunnel service already exists
    # ============================================================

    if ($tunnelExists) {
        $isRunning = $tunnelSvc.Status -eq 'Running'
        Write-Log "Tunnel exists, status: $($tunnelSvc.Status)"

        if ($isRunning) {
            $choice = [System.Windows.Forms.MessageBox]::Show(
                "The company VPN tunnel is already installed and active.`n`n  Yes    — Keep it enabled (run connectivity check)`n  No     — Disable the tunnel (leaves WireGuard installed)`n  Cancel — Remove the tunnel entirely",
                "Company Network Setup — Tunnel active",
                [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
                [System.Windows.Forms.MessageBoxIcon]::Question
            )
            switch ($choice) {
                'Yes' {
                    Write-Log "User chose: keep enabled - verifying"
                    Test-VpnAndNas
                    Show-Info "The company VPN is active and the file server is reachable.`n`nYour desktop shortcut is ready to use."
                }
                'No' {
                    Write-Log "User chose: disable"
                    Disable-Tunnel
                    Show-Info "The VPN tunnel has been disabled.`n`nTo reconnect, run this file again or enable the tunnel in the WireGuard app."
                }
                'Cancel' {
                    Write-Log "User chose: remove tunnel"
                    Disable-Tunnel
                    Remove-Tunnel
                    $also = [System.Windows.Forms.MessageBox]::Show(
                        "Tunnel removed.`n`nDo you also want to uninstall WireGuard completely?`n`nChoose No to keep WireGuard for other connections.",
                        "Company Network Setup — Also remove WireGuard?",
                        [System.Windows.Forms.MessageBoxButtons]::YesNo,
                        [System.Windows.Forms.MessageBoxIcon]::Question
                    )
                    if ($also -eq 'Yes') {
                        Uninstall-WireGuard
                        Show-Info "The VPN tunnel and WireGuard have been removed."
                    } else {
                        Show-Info "The VPN tunnel has been removed. WireGuard remains installed."
                    }
                }
            }
        } else {
            # Tunnel exists but is stopped
            $choice = [System.Windows.Forms.MessageBox]::Show(
                "The company VPN tunnel is installed but not active.`n`n  Yes    — Enable the tunnel now`n  No     — Keep it disabled`n  Cancel — Remove the tunnel entirely",
                "Company Network Setup — Tunnel disabled",
                [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
                [System.Windows.Forms.MessageBoxIcon]::Question
            )
            switch ($choice) {
                'Yes' {
                    Write-Log "User chose: enable existing tunnel"
                    Enable-Tunnel
                    Test-VpnAndNas
                    Show-Info "The company VPN is now active and the file server is reachable.`n`nYour desktop shortcut is ready to use."
                }
                'No' {
                    Write-Log "User chose: keep disabled"
                    Show-Info "No changes made. The tunnel remains installed but disabled.`n`nRun this file again when you want to enable it."
                }
                'Cancel' {
                    Write-Log "User chose: remove tunnel"
                    Remove-Tunnel
                    $also = [System.Windows.Forms.MessageBox]::Show(
                        "Tunnel removed.`n`nDo you also want to uninstall WireGuard completely?`n`n" +
                        "Choose No to keep WireGuard for other connections.",
                        "Company Network Setup — Also remove WireGuard?",
                        [System.Windows.Forms.MessageBoxButtons]::YesNo,
                        [System.Windows.Forms.MessageBoxIcon]::Question
                    )
                    if ($also -eq 'Yes') {
                        Uninstall-WireGuard
                        Show-Info "The VPN tunnel and WireGuard have been removed."
                    } else {
                        Show-Info "The VPN tunnel has been removed. WireGuard remains installed."
                    }
                }
            }
        }
        Write-Log "=== Setup complete ==="
        return
    }

    # ============================================================
    # BRANCH: Tunnel does not exist - detect LAN vs remote
    # ============================================================

    Write-Log "No existing tunnel. Probing NAS directly..."
    $onLan = Test-NasDirect
    Write-Log "NAS directly reachable (on LAN): $onLan"

    if ($onLan) {
        $choice = [System.Windows.Forms.MessageBox]::Show(
            "You're connected to the company network directly.`n`n" +
            "  Yes    — Install WireGuard and activate the tunnel`n" +
            "             (needed when working remotely)`n" +
            "  No     — Install WireGuard but leave the tunnel disabled`n" +
            "             (ready for remote use, not active now)`n" +
            "  Cancel — Skip — just use the desktop shortcut",
            "Company Network Setup — Office network detected",
            [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )
    } else {
        $choice = [System.Windows.Forms.MessageBox]::Show(
            "Remote network detected — the company server is not directly reachable.`n`n" +
            "  Yes    — Install WireGuard and activate the tunnel now`n" +
            "  No     — Install WireGuard but leave the tunnel disabled`n" +
            "             (you can enable it later from the WireGuard app)",
            "Company Network Setup — Remote network detected",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )
    }

    switch ($choice) {
        'Yes' {
            Write-Log "User chose: install + enable"
            Install-WireGuard
            Import-Tunnel
            Enable-Tunnel
            Test-VpnAndNas
            Show-Info "The company VPN is active and the file server is reachable.`n`nYour desktop shortcut is ready to use."
        }
        'No' {
            Write-Log "User chose: install + disabled"
            Install-WireGuard
            Import-Tunnel
            # Install-tunnelservice starts the service automatically - stop it immediately
            Start-Sleep -Seconds 2
            Disable-Tunnel
            # Verify the service actually stopped cleanly
            $svc = Get-TunnelService
            if ($svc -and $svc.Status -ne 'Stopped') {
                Write-Log "Service did not reach Stopped state, current: $($svc.Status)" "WARN"
            } else {
                Write-Log "Tunnel installed and confirmed stopped"
            }
            Show-Info "WireGuard is installed and the tunnel is ready.`n`nThe tunnel is not active right now. To connect, run this file again or open the WireGuard app and enable the tunnel manually."
        }
        'Cancel' {
            # Only reachable on the LAN branch (YesNoCancel dialog)
            Write-Log "User chose: skip"
            Show-Info "No VPN setup needed right now.`n`nYour desktop shortcut to the company server is ready — it will work while you're on the office network."
        }
        default {
            # User dismissed the dialog without choosing
            Write-Log "User dismissed the dialog - no action taken" "WARN"
        }
    }

    Write-Log "=== Setup complete ==="
} finally {
    Cleanup-WorkDir
}
"""


def render_cmd(device_id: int, token: str, portal_url: str) -> str:
    return (
        CMD_TEMPLATE
        .replace("__DEVICE_ID__", str(device_id))
        .replace("__ONE_TIME_TOKEN__", token)
        .replace("__PORTAL_URL__", portal_url.rstrip("/"))
    )


def render_ps1(device_id: int, tunnel_name: str, nas_ip: str, share_name: str, wg: dict) -> str:
    """wg is the dict returned by wg_manager.create_peer()."""
    return (
        PS1_TEMPLATE
        .replace("__DEVICE_ID__", str(device_id))
        .replace("__TUNNEL_NAME__", tunnel_name)
        .replace("__NAS_IP__", nas_ip)
        .replace("__SHARE_NAME__", share_name)
        .replace("__WG_PRIVATE_KEY__", wg["private_key"])
        .replace("__WG_ADDRESS__", wg["address_cidr"])
        .replace("__WG_DNS__", wg["dns"])
        .replace("__WG_PEER_PUBLIC_KEY__", wg["peer_public_key"])
        .replace("__WG_PRESHARED_KEY__", wg["preshared_key"])
        .replace("__WG_ENDPOINT__", wg["endpoint"])
        .replace("__WG_ALLOWED_IPS__", wg["allowed_ips"])
        .replace("__WG_KEEPALIVE__", wg["keepalive"])
    )