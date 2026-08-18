<#
    Frivo — runtime setup (headless)
    ------------------------------------------------------------------
    Installs Python if needed, builds the private virtual environment,
    installs the dependencies and writes the initial settings files.

    No window, no prompts. This is the step a compiled installer runs
    after it has copied the program files into place; the PowerShell
    wizard performs the same work through the same module.

    Exit codes:
        0  success
        1  failure (details in the setup log)
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Target,
    [switch] $UpgradeLegacy,
    [string] $DataPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Force
$FrivoDataDir = if ($DataPath) { $DataPath } else { Get-DataPath }

$log = { param($m) if ($m) { Write-Host $m; Write-SetupLog ('runtime: ' + $m) } }

function Remove-LegacyVoiceConsole {
    # The compiled installer used to skip the migration work performed by
    # Install.ps1.  Only remove a registered legacy folder after verifying
    # its expected name and files; never trust a registry path by itself.
    $legacyKeys = @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
    )
    $removed = $false
    foreach ($key in $legacyKeys) {
        try {
            if (-not (Test-Path $key)) { continue }
            $location = [string] (Get-ItemProperty -Path $key -ErrorAction Stop).InstallLocation
            if (-not $location) { continue }
            $full = [System.IO.Path]::GetFullPath($location).TrimEnd('\', '/')
            $leaf = Split-Path -Leaf $full
            $looksLikeLegacy = $leaf -in @('Voice Console', 'VoiceConsole') -and
                (Test-Path -LiteralPath (Join-Path $full 'app.py')) -and
                (Test-Path -LiteralPath (Join-Path $full 'installer'))
            if (-not $looksLikeLegacy) {
                Write-SetupLog ('runtime: legacy entry was not removed because its folder could not be verified: ' + $location)
                continue
            }
            Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.ExecutablePath -and (Test-PathWithinDirectory -Path $_.ExecutablePath -Directory $full) } |
                ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { } }
            $shortcutRoots = @(
                [Environment]::GetFolderPath('Desktop'),
                [Environment]::GetFolderPath('CommonDesktopDirectory')
            )
            foreach ($startBase in @([Environment]::GetFolderPath('StartMenu'), [Environment]::GetFolderPath('CommonStartMenu'))) {
                if ($startBase) { $shortcutRoots += (Join-Path $startBase 'Programs') }
            }
            foreach ($shortcutRoot in $shortcutRoots) {
                if (-not $shortcutRoot) { continue }
                $shortcutPath = Join-Path $shortcutRoot 'Voice Console.lnk'
                if (-not (Test-Path -LiteralPath $shortcutPath)) { continue }
                try {
                    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
                    if (([string] $shortcut.TargetPath) -match [regex]::Escape($full) -or
                        ([string] $shortcut.Arguments) -match [regex]::Escape($full)) {
                        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction Stop
                    }
                } catch { }
            }
            Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            Remove-Item -Path $key -Recurse -Force -ErrorAction Stop
            $removed = $true
        } catch {
            Write-SetupLog ('runtime: legacy cleanup failed: ' + $_.Exception.Message)
        }
    }
    if ($removed) {
        Invoke-Tool -FilePath 'schtasks.exe' -Arguments @('/delete', '/tn', 'VoiceConsole', '/f') | Out-Null
        Invoke-Tool -FilePath 'netsh.exe' -Arguments @('advfirewall', 'firewall', 'delete', 'rule', 'name=Voice Console') | Out-Null
        & $log 'Removed the previous Voice Console installation.'
    }
}

try {
    Write-SetupLog ('Runtime setup starting for {0}' -f $Target)
    if ($UpgradeLegacy) { Remove-LegacyVoiceConsole }
    if (-not (Test-FrivoInstallOwnership $Target)) { Write-FrivoInstallMarker -Path $Target }

    & $log 'Checking for Python...'
    $python = Find-Python
    if (-not $python) {
        Install-Python -Log $log
        $python = Find-Python
        if (-not $python) {
            throw 'Python was installed but is not yet on the system path. Restart Windows and run setup again.'
        }
    }
    & $log ('Using Python {0}' -f $python.Version)

    $venvPython = New-Venv -Target $Target -Python $python -Log $log

    & $log 'Writing configuration files...'
    New-FrivoDataFiles -Path $FrivoDataDir | Out-Null

    # The certificate and the frivo.local address. Neither is fatal: the
    # app works without them, with a one-time browser warning and the
    # localhost address instead.
    & $log 'Creating the security certificate...'
    try {
        # Pinned explicitly: setup runs elevated and Program Files is
        # writable to an administrator, which would otherwise fool the
        # app's data-directory probe.
        $previousData = $env:VOICE_CONSOLE_DATA
        $env:VOICE_CONSOLE_DATA = $FrivoDataDir
        try {
            $r = Invoke-Tool -FilePath $venvPython -Arguments @('app.py', '--prepare-certs') -WorkingDirectory $Target
        } finally {
            $env:VOICE_CONSOLE_DATA = $previousData
        }
        if ($r.ExitCode -ne 0) { throw (Get-LastLines ($r.StdErr + "`r`n" + $r.StdOut)) }
        $caCrt = $FrivoDataDir + '\ca.crt'
        Install-FrivoRootCertificate -CertificatePath $caCrt | Out-Null
    } catch {
        Write-SetupLog ('runtime: certificate setup failed: ' + $_.Exception.Message)
    }
    try {
        Add-FrivoHostsEntry | Out-Null
    } catch {
        Write-SetupLog ('runtime: hosts entry failed: ' + $_.Exception.Message)
    }

    & $log 'Creating launchers...'
    $enc = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText((Join-Path $Target 'Frivo.vbs'), (Get-LauncherShim), $enc)
    [System.IO.File]::WriteAllText((Join-Path $Target 'Start Frivo.cmd'), (Get-LauncherScript), $enc)
    [System.IO.File]::WriteAllText((Join-Path $Target 'Start Frivo (background).cmd'), (Get-LauncherScript -Hidden), $enc)

    Write-SetupLog 'Runtime setup completed'
    exit 0
} catch {
    Write-SetupLog ('Runtime setup FAILED: ' + $_.Exception.Message)
    Write-Host ('ERROR: ' + $_.Exception.Message)
    exit 1
}
