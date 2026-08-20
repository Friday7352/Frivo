<#
    Frivo — installer
    ------------------------------------------------------------------
    A standard Windows setup wizard. Everything that isn't drawing the
    window lives in Frivo.Setup.psm1 next door.

    No console window is ever shown. Every external tool the installer
    runs — winget, the Python installer, pip — is started hidden with its
    output captured, and that output is written to the setup log and, when
    something fails, shown in the wizard.
#>

[CmdletBinding()]
param(
    [switch] $Silent,
    [string] $InstallPath,
    [switch] $NoShortcut,
    [switch] $RunAtStartup,
    [switch] $AllowFirewall,
    [ValidateSet('Install', 'Update', 'Repair')]
    [string] $Action = 'Install',
    # Retained across UAC elevation so settings stay with the person who
    # launched setup, even when they supply separate admin credentials.
    [string] $DataPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PackageDir = Split-Path -Parent $ScriptDir
$SourceApp  = Join-Path $PackageDir 'app'

Import-Module (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Force

$AppName    = 'Frivo'
$AppVersion = '1.1.1'
$LogPath    = Get-SetupLogPath
$script:SetupDataDir = if ($DataPath) { $DataPath } else { Get-DataPath }

# ==================================================================
# Running external tools
# ==================================================================

# ==================================================================
# Elevation
# ==================================================================

if (-not (Test-IsAdministrator)) {
    # Installing into Program Files and registering under HKLM both need
    # administrator rights. One prompt, up front, like any other installer.
    $relaunch = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA',
        '-WindowStyle', 'Hidden', '-File', ('"{0}"' -f $PSCommandPath)
    )
    foreach ($kv in $PSBoundParameters.GetEnumerator()) {
        if ($kv.Value -is [switch]) {
            if ($kv.Value.IsPresent) { $relaunch += ('-{0}' -f $kv.Key) }
        } else {
            $relaunch += @(('-{0}' -f $kv.Key), ('"{0}"' -f $kv.Value))
        }
    }
    # If a different administrator account approves the UAC prompt, keep
    # Frivo's settings with the person who launched setup, not that admin.
    if (-not $DataPath) {
        $relaunch += @('-DataPath', ('"{0}"' -f (Get-DataPath)))
    }
    try {
        $elevated = Start-Process -FilePath 'powershell.exe' -ArgumentList $relaunch -Verb RunAs -WindowStyle Hidden -PassThru
        # The packaged installer keeps its source files in a temporary
        # folder. Waiting prevents Windows from clearing that folder while
        # the elevated Frivo window is still using it.
        $elevated.WaitForExit()
        exit $elevated.ExitCode
    } catch {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "Setup requires administrator privileges to install into Program Files.`r`n`r`nRight-click the installer and choose 'Run as administrator'.",
            ('{0} Setup' -f $AppName),
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
    exit
}

Write-SetupLog '--------------------------------------------------'
Write-SetupLog ('{0} {1} setup started' -f $AppName, $AppVersion)

# ==================================================================
# Existing / partial installs
# ==================================================================

$RegKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
$FrivoRegKeys = @(
    $RegKey
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    'HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
)
$LegacyRegKeys = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
    'HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
)

function Get-ExistingInstall {
    <#
        Returns what is already on this machine, if anything.

        State is one of:
          None       nothing found
          Installed  registered, and the files are there
          Partial    files or a registry entry, but not a working pair
    #>
    $registered = $null
    foreach ($key in $FrivoRegKeys) {
        if (-not (Test-Path $key)) { continue }
        try {
            $p = Get-ItemProperty -Path $key -ErrorAction Stop
            $registered = [pscustomobject] @{
                Key     = $key
                Path    = [string] $p.InstallLocation
                Version = [string] $p.DisplayVersion
            }
            break
        } catch { }
    }

    # A machine that had the app under its previous name counts as an
    # existing install: its folder, task and rule all still need removing.
    if (-not $registered) {
        foreach ($legacyKey in $LegacyRegKeys) {
            if (-not (Test-Path $legacyKey)) { continue }
            try {
                $lp = Get-ItemProperty -Path $legacyKey -ErrorAction Stop
                $registered = [pscustomobject] @{ Key = $legacyKey; Path = [string] $lp.InstallLocation; Version = 'previous' }
                break
            } catch { }
        }
    }

    # A previous release could remove its files while leaving an Apps &
    # features record behind (notably when it was registered in the 32-bit
    # registry view). Remove that record only when neither the application
    # nor its own uninstaller remains at the registered location.
    if ($registered -and $registered.Path) {
        $oldApp = Join-Path $registered.Path 'app.py'
        $oldUninstaller = Join-Path $registered.Path 'Uninstall.cmd'
        if (-not (Test-Path -LiteralPath $oldApp) -and -not (Test-Path -LiteralPath $oldUninstaller)) {
            try {
                Remove-Item -LiteralPath $registered.Key -Recurse -Force -ErrorAction Stop
                Write-SetupLog ('Removed stale Apps & features entry: ' + $registered.Path)
                $registered = $null
            } catch {
                Write-SetupLog ('Could not remove stale Apps & features entry: ' + $_.Exception.Message)
            }
        }
    }

    $candidatePath = if ($registered -and $registered.Path) { $registered.Path } else { Get-DefaultInstallPath }
    $hasFiles = Test-Path -LiteralPath (Join-Path $candidatePath 'app.py')
    $hasVenv  = Test-Path -LiteralPath (Join-Path $candidatePath '.venv\Scripts\python.exe')

    if ($registered -and $hasFiles -and $hasVenv) {
        return [pscustomobject] @{ State = 'Installed'; Path = $candidatePath; Version = $registered.Version }
    }
    if ($registered -or $hasFiles) {
        return [pscustomobject] @{ State = 'Partial'; Path = $candidatePath; Version = '' }
    }
    return [pscustomobject] @{ State = 'None'; Path = $candidatePath; Version = '' }
}

function Clear-PartialInstall {
    <#
        Removes a partial program installation before retrying. User data is
        stored outside the program folder and is not touched.
    #>
    param(
        [string] $Target,
        [scriptblock] $Log,
        [switch] $AllowKnownLegacyInstall
    )

    if ((Test-Path -LiteralPath $Target) -and -not (Test-FrivoInstallOwnership $Target) -and -not $AllowKnownLegacyInstall) {
        throw 'Refusing to clean a folder that was not created by Frivo.'
    }

    & $Log 'Removing incomplete installation...'
    Write-SetupLog ('Cleaning partial install at {0}' -f $Target)

    Stop-FrivoProcesses -Target $Target -Log $Log

    if (Test-Path -LiteralPath $Target) {
        # The venv is the part that most often survives half-written.
        Remove-Item -LiteralPath (Join-Path $Target '.venv') -Recurse -Force -ErrorAction SilentlyContinue
    }

    # Never try to infer ownership of old stray folders such as C:\Program.
    # A folder containing pyvenv.cfg can still be someone else's environment.
    # Both the current key and the one used before the rename, so an
    # upgrade from "Voice Console" doesn't leave a dead Apps & features
    # entry pointing at a folder that no longer exists.
    foreach ($key in @($FrivoRegKeys + $LegacyRegKeys)) {
        try {
            if (-not (Test-Path $key)) { continue }
            $registeredPath = [string] (Get-ItemProperty -Path $key -ErrorAction Stop).InstallLocation
            if ($registeredPath -and [System.IO.Path]::GetFullPath($registeredPath).TrimEnd('\', '/').Equals(
                    [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/'),
                    [System.StringComparison]::OrdinalIgnoreCase)) {
                Remove-Item -Path $key -Recurse -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
}

# ==================================================================
# Work
# ==================================================================

function Stop-FrivoProcesses {
    <#
        The running app can hold images and scripts open, preventing an
        update from replacing them. Only stop processes whose executable is
        inside this exact Frivo installation; never touch another Python
        application on the machine.
    #>
    param([string] $Target, [scriptblock] $Log)

    $processes = @(Get-CimInstance Win32_Process `
        -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'FrivoHost.exe'" `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and (Test-PathWithinDirectory -Path $_.ExecutablePath -Directory $Target) })

    if ($processes.Count -eq 0) { return }

    & $Log 'Closing the running Frivo application...'
    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            Write-SetupLog ('Stopped Frivo process {0} ({1}) before setup.' -f $process.ProcessId, $process.Name)
        } catch {
            Write-SetupLog ('Could not stop Frivo process {0}: {1}' -f $process.ProcessId, $_.Exception.Message)
        }
    }

    # Stop-Process initiates termination; wait briefly for Windows to release
    # file handles before copying the refreshed program files.
    foreach ($process in $processes) {
        try { Wait-Process -Id $process.ProcessId -Timeout 5 -ErrorAction Stop } catch { }
    }
}

function Copy-AppFiles {
    param([string] $Target, [scriptblock] $Log)

    & $Log 'Copying application files...'
    foreach ($sub in @('templates', 'static', 'installer')) {
        $dest = Join-Path $Target $sub
        if (-not (Test-Path -LiteralPath $dest)) {
            New-Item -ItemType Directory -Path $dest -Force | Out-Null
        }
    }
    Copy-Item (Join-Path $SourceApp 'app.py')           -Destination $Target -Force
    Copy-Item (Join-Path $SourceApp 'requirements.txt') -Destination $Target -Force
    Copy-Item (Join-Path $SourceApp 'templates\*')      -Destination (Join-Path $Target 'templates') -Recurse -Force
    Copy-Item (Join-Path $SourceApp 'static\*')         -Destination (Join-Path $Target 'static')    -Recurse -Force
    Copy-Item (Join-Path $ScriptDir 'Uninstall.ps1')           -Destination (Join-Path $Target 'installer') -Force
    Copy-Item (Join-Path $ScriptDir 'Launcher.ps1')            -Destination (Join-Path $Target 'installer') -Force
    Copy-Item (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Destination (Join-Path $Target 'installer') -Force
    Copy-Item (Join-Path $ScriptDir 'Frivo.Ui.psm1')    -Destination (Join-Path $Target 'installer') -Force
    # The native host gives the launcher the Frivo process identity.
    $nativeHost = Join-Path $ScriptDir 'FrivoHost.exe'
    if (Test-Path -LiteralPath $nativeHost -PathType Leaf) {
        Copy-Item $nativeHost -Destination (Join-Path $Target 'installer') -Force
    }
}

function Test-RequirementsChanged {
    <#
        Compares the requirements bundled with this setup to the copy in an
        existing installation.  An update can reuse its virtual environment
        when they are identical, which avoids downloading and reinstalling
        the complete dependency set on every release.
    #>
    param([string] $Target)

    $source = Join-Path $SourceApp 'requirements.txt'
    $installed = Join-Path $Target 'requirements.txt'
    if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) { return $true }

    return (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne
           (Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash
}

function New-Shortcut {
    param(
        [string] $Path, [string] $Target, [string] $WorkingDir,
        [string] $Description, [string] $IconPath, [string] $Arguments
    )
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath       = $Target
    $link.WorkingDirectory = $WorkingDir
    $link.Description      = $Description
    if ($Arguments) { $link.Arguments = $Arguments }
    # Without this a shortcut to wscript/.cmd shows a generic icon.
    if ($IconPath -and (Test-Path -LiteralPath $IconPath)) {
        $link.IconLocation = ('{0},0' -f $IconPath)
    }
    $link.Save()
}

function Register-Uninstaller {
    param([string] $Target, [scriptblock] $Log)

    & $Log 'Registering the application...'
    New-Item -Path $RegKey -Force | Out-Null
    Set-ItemProperty -Path $RegKey -Name 'DisplayName'     -Value $AppName
    Set-ItemProperty -Path $RegKey -Name 'DisplayVersion'  -Value $AppVersion
    Set-ItemProperty -Path $RegKey -Name 'Publisher'       -Value 'Friday'
    Set-ItemProperty -Path $RegKey -Name 'InstallLocation' -Value $Target
    Set-ItemProperty -Path $RegKey -Name 'UninstallString' -Value (Get-UninstallCommand -InstallPath $Target)
    Set-ItemProperty -Path $RegKey -Name 'DisplayIcon'     -Value ('{0}\static\Frivo.ico' -f $Target)
    Set-ItemProperty -Path $RegKey -Name 'EstimatedSize'   -Value 260000 -Type DWord
    Set-ItemProperty -Path $RegKey -Name 'NoModify'        -Value 1 -Type DWord
    Set-ItemProperty -Path $RegKey -Name 'NoRepair'        -Value 1 -Type DWord
}

function Set-StartupEntry {
    param([string] $Target, [bool] $Enabled, [bool] $RemoveLegacyTasks, [scriptblock] $Log)

    # Earlier versions used a scheduled task.  Remove one only while
    # repairing its verified legacy install; task names alone are not proof
    # of ownership.
    if ($RemoveLegacyTasks) {
        foreach ($stale in @('Frivo', 'VoiceConsole')) {
            $query = Invoke-Tool -FilePath 'schtasks.exe' -Arguments @('/query', '/tn', $stale, '/fo', 'LIST', '/v')
            if ($query.ExitCode -eq 0 -and $query.StdOut -match [regex]::Escape($Target)) {
                Invoke-Tool -FilePath 'schtasks.exe' -Arguments @('/delete', '/tn', $stale, '/f') | Out-Null
            }
        }
    }

    # The per-user Run key can be managed later without elevation.
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if (-not $Enabled) {
        Remove-ItemProperty -Path $runKey -Name 'Frivo' -ErrorAction SilentlyContinue
        return
    }

    & $Log 'Configuring automatic startup...'
    try {
        $cmd = '"{0}" "{1}\Frivo.vbs" -Tray' -f (Get-WScriptPath), $Target.TrimEnd('\', '/')
        New-ItemProperty -Path $runKey -Name 'Frivo' -Value $cmd -PropertyType String -Force | Out-Null
    } catch {
        & $Log 'Automatic startup could not be configured. Continuing.'
        Write-SetupLog ('startup entry failed: ' + $_.Exception.Message)
    }
}

function Install-Certificate {
    <#
        Generates the app's certificate pair and trusts it machine-wide, so
        browsers on this PC get a clean padlock at https://frivo.local:5000
        instead of a warning page. Never fatal: without it Frivo still
        works, with a one-time warning per browser.
    #>
    param([string] $Target, [string] $VenvPython, [scriptblock] $Log)

    & $Log 'Creating the security certificate...'
    try {
        # Earlier setups let the certificate land inside the program folder
        # (see below). Anything of that kind found there is stale, refers to
        # a CA nothing trusts, and is removed so it can't be picked up.
        foreach ($stray in @('ca.crt', 'ca.pem', 'ca-key.pem', 'cert.pem', 'key.pem', 'server.log')) {
            Remove-Item -LiteralPath (Join-Path $Target $stray) -Force -ErrorAction SilentlyContinue
        }
        # The data directory is pinned explicitly. Setup runs elevated, and
        # an administrator CAN write to Program Files — so left to guess,
        # Python would put the certificate next to app.py instead of where
        # the app (running unelevated later) will look for it.
        $previousData = $env:VOICE_CONSOLE_DATA
        $env:VOICE_CONSOLE_DATA = $script:SetupDataDir
        try {
            $r = Invoke-Tool -FilePath $VenvPython -Arguments @('app.py', '--prepare-certs') -WorkingDirectory $Target
        } finally {
            $env:VOICE_CONSOLE_DATA = $previousData
        }
        if ($r.ExitCode -ne 0) {
            throw (Get-LastLines ($r.StdErr + "`r`n" + $r.StdOut))
        }
        $caCrt = $script:SetupDataDir + '\ca.crt'
        if (-not (Test-Path -LiteralPath $caCrt)) {
            throw ('ca.crt was not created at {0}' -f $caCrt)
        }
        & $Log 'Adding the certificate to Trusted Root Certification Authorities...'
        Install-FrivoRootCertificate -CertificatePath $caCrt | Out-Null
        return $true
    } catch {
        Write-SetupLog ('certificate setup failed: ' + $_.Exception.Message)
        & $Log 'The certificate could not be prepared. Frivo will still work; browsers will show a one-time security warning.'
        return $false
    }
}

function Install-LocalAddress {
    <#
        Points frivo.local at this machine via the hosts file. Also never
        fatal — https://localhost:5000 always works without it.
    #>
    param([scriptblock] $Log)

    & $Log 'Registering the frivo.local address...'
    try {
        Add-FrivoHostsEntry | Out-Null
        return $true
    } catch {
        Write-SetupLog ('hosts entry failed: ' + $_.Exception.Message)
        & $Log 'The frivo.local address could not be added. Use https://localhost:5000 instead.'
        return $false
    }
}

function Set-FirewallRule {
    param([bool] $Enabled, [string] $Target, [scriptblock] $Log)
    if (-not $Enabled) { return }

    & $Log 'Configuring Windows Firewall...'
    $pythonw = Join-Path $Target '.venv\Scripts\pythonw.exe'
    Invoke-Tool -FilePath 'netsh.exe' -Arguments @(
        'advfirewall', 'firewall', 'delete', 'rule', 'name=Frivo', ('program=' + $pythonw)
    ) | Out-Null
    $r = Invoke-Tool -FilePath 'netsh.exe' -Arguments @(
        'advfirewall', 'firewall', 'add', 'rule', 'name=Frivo',
        'dir=in', 'action=allow', 'program=' + $pythonw,
        'profile=private', 'remoteip=localsubnet', 'protocol=TCP', 'localport=5000'
    )
    if ($r.ExitCode -ne 0) {
        & $Log 'The firewall rule could not be added. Continuing.'
    }
}

function Install-Frivo {
    param(
        [string]      $Target,
        [bool]        $DesktopShortcut,
        [bool]        $StartMenuShortcut,
        [bool]        $Startup,
        [bool]        $Firewall,
        [bool]        $CleanFirst,
        [bool]        $AllowKnownLegacyInstall,
        [ValidateSet('Install', 'Update', 'Repair')]
        [string]      $Action = 'Install',
        [scriptblock] $Log,
        [scriptblock] $Progress
    )

    $check = Test-InstallPathUsable -Path $Target -AllowKnownExistingInstall:$AllowKnownLegacyInstall
    if (-not $check.Ok) { throw $check.Reason }
    $Target = $check.Path

    if ($CleanFirst) { Clear-PartialInstall -Target $Target -Log $Log -AllowKnownLegacyInstall:$AllowKnownLegacyInstall }

    $requirementsChanged = $false
    if ($Action -eq 'Update') {
        $requirementsChanged = Test-RequirementsChanged -Target $Target
        Stop-FrivoProcesses -Target $Target -Log $Log
        & $Log 'Preserving the existing installation settings.'
    }

    & $Progress 5
    $python = $null
    if ($Action -ne 'Update') {
        & $Log 'Checking for Python...'
        $python = Find-Python
        if (-not $python) {
            Install-Python -Log $Log
            $python = Find-Python
            if (-not $python) {
                throw 'Python was installed but is not yet on the system path. Restart Windows and run setup again.'
            }
        }
        & $Log ('Using Python {0}' -f $python.Version)
    } else {
        & $Log 'Keeping the existing Python environment.'
    }
    & $Progress 15

    if (-not (Test-Path -LiteralPath $Target)) {
        New-Item -ItemType Directory -Path $Target -Force | Out-Null
    }
    if (-not (Test-FrivoInstallOwnership $Target)) {
        Write-FrivoInstallMarker -Path $Target
    }
    Copy-AppFiles -Target $Target -Log $Log
    & $Progress 30

    if ($Action -eq 'Update') {
        $venvPython = Join-Path $Target '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
            throw 'The existing Python environment is incomplete. Choose Repair to rebuild Frivo.'
        }
        if ($requirementsChanged) {
            & $Log 'Dependencies changed. Updating them...'
            Sync-VenvDependencies -VenvPython $venvPython -Target $Target -Log $Log
        } else {
            & $Log 'Dependencies are unchanged; keeping the existing Python environment.'
        }
    } else {
        $venvPython = New-Venv -Target $Target -Python $python -Log $Log
    }
    & $Progress 65

    if ($Action -ne 'Update') {
        & $Log 'Writing configuration files...'
        $dataDir = $script:SetupDataDir
        # PowerShell unwraps a one-item return value, so force an array before
        # checking Count on a first install.
        $created = @(New-FrivoDataFiles -Path $dataDir)
        if ($created.Count -eq 0) {
            & $Log 'Existing settings found and preserved.'
        }
        $script:certificateReady = Install-Certificate -Target $Target -VenvPython $venvPython -Log $Log
        $script:localAddressReady = Install-LocalAddress -Log $Log
    } else {
        & $Log 'Keeping existing settings, certificate, and local address.'
        $script:certificateReady = $true
    }
    & $Progress 70
    & $Progress 78
    & $Progress 82

    & $Log 'Creating launchers...'
    $shim    = Join-Path $Target 'Frivo.vbs'
    $visible = Join-Path $Target 'Start Frivo.cmd'
    $hidden  = Join-Path $Target 'Start Frivo (background).cmd'
    $enc = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($shim, (Get-LauncherShim), $enc)
    # The .cmd pair stays as a plain fallback that shows the raw console —
    # useful when something is wrong and the Frivo window can't say why.
    [System.IO.File]::WriteAllText($visible, (Get-LauncherScript), $enc)
    [System.IO.File]::WriteAllText($hidden,  (Get-LauncherScript -Hidden), $enc)
    [System.IO.File]::WriteAllText((Join-Path $Target 'Uninstall.cmd'), (Get-UninstallLauncher), $enc)
    & $Progress 86

    # Shipped in static\ so the running app can serve it as a favicon too.
    $iconPath = Join-Path $Target 'static\Frivo.ico'
    # User shortcuts open Frivo's window; the Windows sign-in entry starts in
    # the tray.
    $nativeLauncher = Join-Path $Target 'installer\FrivoHost.exe'
    $launcherScript = Join-Path $Target 'installer\Launcher.ps1'
    $openArguments = ('--script "{0}"' -f $launcherScript)

    if ($Action -ne 'Update' -and $DesktopShortcut) {
        & $Log 'Creating desktop shortcut...'
        if (Test-Path -LiteralPath $nativeLauncher -PathType Leaf) {
            New-Shortcut -Path (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Frivo.lnk') `
                         -Target $nativeLauncher -Arguments $openArguments `
                         -WorkingDir $Target -Description $AppName -IconPath $iconPath
        } else {
            New-Shortcut -Path (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Frivo.lnk') `
                         -Target (Get-WScriptPath) -Arguments ('"{0}"' -f $shim) `
                         -WorkingDir $Target -Description $AppName -IconPath $iconPath
        }
    }
    if ($Action -ne 'Update' -and $StartMenuShortcut) {
        & $Log 'Creating Start Menu entry...'
        $programs = Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs'
        if (-not (Test-Path -LiteralPath $programs)) {
            New-Item -ItemType Directory -Path $programs -Force | Out-Null
        }
        if (Test-Path -LiteralPath $nativeLauncher -PathType Leaf) {
            New-Shortcut -Path (Join-Path $programs 'Frivo.lnk') `
                         -Target $nativeLauncher -Arguments $openArguments `
                         -WorkingDir $Target -Description $AppName -IconPath $iconPath
        } else {
            New-Shortcut -Path (Join-Path $programs 'Frivo.lnk') `
                         -Target (Get-WScriptPath) -Arguments ('"{0}"' -f $shim) `
                         -WorkingDir $Target -Description $AppName -IconPath $iconPath
        }
    }
    & $Progress 90

    if ($Action -ne 'Update') {
        Set-StartupEntry -Target $Target -Enabled $Startup -RemoveLegacyTasks $AllowKnownLegacyInstall -Log $Log
    }
    Register-Uninstaller -Target $Target -Log $Log
    & $Progress 95
    if ($Action -ne 'Update') {
        Set-FirewallRule -Enabled $Firewall -Target $Target -Log $Log
    }
    & $Progress 100

    & $Log 'Installation complete.'
    Write-SetupLog 'Installation completed successfully'
    return $shim
}

# ==================================================================
# Silent mode
# ==================================================================

if ($Silent) {
    $target = if ($InstallPath) { $InstallPath } else { Get-DefaultInstallPath }
    $existing = Get-ExistingInstall
    $knownExisting = $false
    try {
        $knownExisting = ($existing.State -ne 'None' -and
            [System.IO.Path]::GetFullPath($target).TrimEnd('\', '/').Equals(
                [System.IO.Path]::GetFullPath($existing.Path).TrimEnd('\', '/'),
                [System.StringComparison]::OrdinalIgnoreCase)) -or (Test-FrivoRecoverableResidue $target)
    } catch { }
    if ($existing.State -ne 'None' -and -not $knownExisting) {
        throw 'Frivo is already installed in a different folder. Uninstall it before choosing a new destination.'
    }
    $effectiveAction = $Action
    if ($effectiveAction -eq 'Install' -and $existing.State -eq 'Installed') {
        $effectiveAction = 'Update'
    } elseif ($effectiveAction -eq 'Install' -and $existing.State -eq 'Partial') {
        $effectiveAction = 'Repair'
    }
    $cleanFirst = ($effectiveAction -eq 'Repair')
    Install-Frivo -Target $target `
        -DesktopShortcut (-not $NoShortcut) -StartMenuShortcut (-not $NoShortcut) `
        -Startup ([bool] $RunAtStartup) -Firewall ([bool] $AllowFirewall) `
        -CleanFirst $cleanFirst -AllowKnownLegacyInstall $knownExisting -Action $effectiveAction `
        -Log { param($m) if ($m) { Write-Host $m } } -Progress { param($p) } | Out-Null
    exit 0
}

# ==================================================================
# Wizard
# ==================================================================

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

Import-Module (Join-Path $ScriptDir 'Frivo.Ui.psm1') -Force
$Theme = Get-FrivoTheme

$existing = Get-ExistingInstall
Write-SetupLog ('Existing install state: {0} at {1}' -f $existing.State, $existing.Path)

$form = New-FrivoForm -Theme $Theme -Title ('{0} Setup' -f $AppName) -Width 620 -Height 500 `
    -IconPath (Join-Path $SourceApp 'static\Frivo.ico')

$header = New-FrivoHeader -Theme $Theme -Form $form -Title ('{0} Setup' -f $AppName) -Subtitle '' `
    -LogoPngPath (Join-Path $SourceApp 'static\icon.png')

# ---------- footer ----------
$footer = New-Object System.Windows.Forms.Panel
$footer.Location = New-Object System.Drawing.Point(0, 438)
$footer.Size = New-Object System.Drawing.Size(620, 62)
$footer.BackColor = $Theme.Bg
$form.Controls.Add($footer)

$btnBack   = New-FrivoButton -Theme $Theme -Parent $footer -Text 'Back'   -X 272 -Y 14 -W 96 -H 36
$btnNext   = New-FrivoButton -Theme $Theme -Parent $footer -Text 'Next'   -X 380 -Y 14 -W 110 -H 36 -Primary $true
$btnCancel = New-FrivoButton -Theme $Theme -Parent $footer -Text 'Cancel' -X 502 -Y 14 -W 96 -H 36

# ---------- body ----------
$body = New-Object System.Windows.Forms.Panel
$body.Location = New-Object System.Drawing.Point(0, 76)
$body.Size = New-Object System.Drawing.Size(620, 362)
$body.BackColor = $Theme.Bg
$form.Controls.Add($body)

function New-Page {
    $p = New-Object System.Windows.Forms.Panel
    $p.Location = New-Object System.Drawing.Point(0, 0)
    $p.Size = New-Object System.Drawing.Size(620, 362)
    $p.BackColor = $Theme.Bg
    $p.Visible = $false
    $body.Controls.Add($p)
    return $p
}

# ---------- existing install ----------
$pageExisting = New-Page
$existingText = New-FrivoLabel -Theme $Theme -Parent $pageExisting -Text '' -X 28 -Y 10 -W 564 -H 88 -Font $Theme.FontUI -Color $Theme.Ink

$cardExisting = New-FrivoCard -Theme $Theme -Parent $pageExisting -X 24 -Y 104 -W 572 -H 202
$radioUpdate = New-FrivoRadio -Theme $Theme -Parent $cardExisting -Text 'Update Frivo' -X 18 -Y 14 -W 536 -Checked $true
$updateNote  = New-FrivoLabel -Theme $Theme -Parent $cardExisting `
    -Text 'Updates program files and keeps the existing Python environment. Dependencies are only updated when they change.' `
    -X 38 -Y 36 -W 516 -H 30 -Font $Theme.FontSmall -Color $Theme.Dim
$radioRepair = New-FrivoRadio -Theme $Theme -Parent $cardExisting -Text '' -X 18 -Y 76 -W 536
$repairNote  = New-FrivoLabel -Theme $Theme -Parent $cardExisting -Text '' -X 38 -Y 98 -W 516 -H 30 -Font $Theme.FontSmall -Color $Theme.Dim
$radioRemove = New-FrivoRadio -Theme $Theme -Parent $cardExisting -Text ('Uninstall {0}' -f $AppName) -X 18 -Y 138 -W 536
$removeNote  = New-FrivoLabel -Theme $Theme -Parent $cardExisting `
    -Text 'Removes the program. You will be asked whether to keep your API keys and profiles.' `
    -X 38 -Y 160 -W 516 -H 30 -Font $Theme.FontSmall -Color $Theme.Dim

# ---------- welcome ----------
$pageWelcome = New-Page
[void] (New-FrivoLabel -Theme $Theme -Parent $pageWelcome `
    -Text ('This wizard will install {0} on your computer.' -f $AppName) `
    -X 28 -Y 12 -W 564 -H 22 -Font $Theme.FontMid -Color $Theme.Ink)
[void] (New-FrivoLabel -Theme $Theme -Parent $pageWelcome -Text @"
Frivo is a browser-based dashboard for conversational speech. It includes
everything required to run, including a private Python runtime, and does not
modify any existing software on this system.

After installation you will need an OpenAI API key and an ElevenLabs API key,
which are entered in the application's Settings screen.

Local Whisper and Ollama are optional and are not installed by this wizard.
"@ -X 28 -Y 44 -W 564 -H 180 -Font $Theme.FontUI -Color $Theme.Dim)
[void] (New-FrivoLabel -Theme $Theme -Parent $pageWelcome -Text 'Click Next to continue.' `
    -X 28 -Y 230 -W 564 -H 20 -Font $Theme.FontUI -Color $Theme.Ink)

# ---------- location ----------
$pageLocation = New-Page
[void] (New-FrivoLabel -Theme $Theme -Parent $pageLocation -Text 'DESTINATION FOLDER' `
    -X 30 -Y 10 -W 400 -H 14 -Font $Theme.FontCaps -Color $Theme.Faint)

$cardLoc = New-FrivoCard -Theme $Theme -Parent $pageLocation -X 24 -Y 30 -W 572 -H 58
$txtPath = New-FrivoTextBox -Theme $Theme -Parent $cardLoc -X 16 -Y 16 -W 428 -H 26
$txtPath.Text = (Get-DefaultInstallPath)
$btnBrowse = New-FrivoButton -Theme $Theme -Parent $cardLoc -Text 'Browse…' -X 456 -Y 12 -W 100 -H 32
$btnBrowse.Font = $Theme.FontUI


$btnBrowse.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = 'Select a destination folder'
    if ($dlg.ShowDialog() -eq 'OK') {
        $txtPath.Text = (Join-Path $dlg.SelectedPath 'Frivo')
    }
})

# ---------- options ----------
$pageOptions = New-Page
[void] (New-FrivoLabel -Theme $Theme -Parent $pageOptions -Text 'SHORTCUTS' `
    -X 30 -Y 8 -W 400 -H 14 -Font $Theme.FontCaps -Color $Theme.Faint)
$cardShort = New-FrivoCard -Theme $Theme -Parent $pageOptions -X 24 -Y 26 -W 572 -H 74
$chkDesktop = New-FrivoCheck -Theme $Theme -Parent $cardShort -Text 'Create a desktop shortcut' -X 18 -Y 12 -W 536 -Checked $true
$chkStart   = New-FrivoCheck -Theme $Theme -Parent $cardShort -Text 'Add a Start Menu entry'    -X 18 -Y 40 -W 536 -Checked $true

[void] (New-FrivoLabel -Theme $Theme -Parent $pageOptions -Text 'STARTUP' `
    -X 30 -Y 112 -W 400 -H 14 -Font $Theme.FontCaps -Color $Theme.Faint)
$cardStartup = New-FrivoCard -Theme $Theme -Parent $pageOptions -X 24 -Y 130 -W 572 -H 66
$chkStartup = New-FrivoCheck -Theme $Theme -Parent $cardStartup -Text ('Start {0} automatically when I sign in' -f $AppName) -X 18 -Y 12 -W 536
[void] (New-FrivoLabel -Theme $Theme -Parent $cardStartup `
    -Text 'Runs minimized in the notification area, so the dashboard is available immediately.' `
    -X 38 -Y 36 -W 516 -H 18 -Font $Theme.FontSmall -Color $Theme.Dim)

[void] (New-FrivoLabel -Theme $Theme -Parent $pageOptions -Text 'NETWORK' `
    -X 30 -Y 208 -W 400 -H 14 -Font $Theme.FontCaps -Color $Theme.Faint)
$cardNet = New-FrivoCard -Theme $Theme -Parent $pageOptions -X 24 -Y 226 -W 572 -H 66
$chkFirewall = New-FrivoCheck -Theme $Theme -Parent $cardNet -Text 'Allow connections from other devices on this network' -X 18 -Y 12 -W 536
[void] (New-FrivoLabel -Theme $Theme -Parent $cardNet `
    -Text 'Allows other devices on your private network to open Frivo.' `
    -X 38 -Y 36 -W 516 -H 18 -Font $Theme.FontSmall -Color $Theme.Dim)

# ---------- installing ----------
$pageInstall = New-Page
$bar = New-FrivoProgress -Theme $Theme -Parent $pageInstall -X 24 -Y 14 -W 572 -H 10
$logBox = New-FrivoTextBox -Theme $Theme -Parent $pageInstall -X 24 -Y 38 -W 572 -H 300 -Multiline

# ---------- done ----------
$pageDone = New-Page
[void] (New-FrivoLabel -Theme $Theme -Parent $pageDone `
    -Text ('{0} is ready.' -f $AppName) `
    -X 28 -Y 12 -W 564 -H 22 -Font $Theme.FontMid -Color $Theme.Ink)

[void] (New-FrivoLabel -Theme $Theme -Parent $pageDone -Text @"
Open Frivo, then add your API keys in Settings.
"@ -X 28 -Y 52 -W 564 -H 28 -Font $Theme.FontUI -Color $Theme.Dim)

$doneWarning = New-FrivoLabel -Theme $Theme -Parent $pageDone `
    -Text 'Your browser may show a security warning the first time you open Frivo.' `
    -X 28 -Y 92 -W 564 -H 38 -Font $Theme.FontSmall -Color $Theme.Dim
$doneWarning.Visible = $false

$chkLaunch = New-FrivoCheck -Theme $Theme -Parent $pageDone -Text ('Launch {0} now' -f $AppName) -X 28 -Y 152 -W 400 -Checked $true

# ---------- navigation ----------
# The existing-install page is only in the running order when there is
# something already on the machine.
$pages = New-Object System.Collections.ArrayList
if ($existing.State -ne 'None') {
    [void] $pages.Add(@{ Panel = $pageExisting; Title = ('{0} is already installed' -f $AppName); Sub = 'Choose what you would like to do'; Next = 'Next' })
}
[void] $pages.Add(@{ Panel = $pageWelcome;  Title = ('Welcome to {0} Setup' -f $AppName); Sub = ('Version {0}' -f $AppVersion); Next = 'Next' })
[void] $pages.Add(@{ Panel = $pageLocation; Title = 'Select destination';                Sub = 'Choose where to install the application'; Next = 'Next' })
[void] $pages.Add(@{ Panel = $pageOptions;  Title = 'Configuration';                     Sub = 'Shortcuts, startup and network access';   Next = 'Install' })
[void] $pages.Add(@{ Panel = $pageInstall;  Title = 'Installing';                        Sub = 'Please wait';                             Next = 'Next' })
[void] $pages.Add(@{ Panel = $pageDone;     Title = 'Setup complete';                    Sub = 'Ready to use';                           Next = 'Finish' })

$idxInstalling = $pages.Count - 2
$idxDone       = $pages.Count - 1
$index = 0
$launcherPath = $null
$certificateReady = $false
$localAddressReady = $false
$script:knownExisting = $false
$script:installFailed = $false
$script:installAction = 'Install'

if ($existing.State -eq 'Installed') {
    $existingText.Text = ("{0} version {1} is already installed at:`r`n{2}`r`n`r`nSelect an option to continue." -f `
        $AppName, $(if ($existing.Version) { $existing.Version } else { 'unknown' }), $existing.Path)
    $radioRepair.Text = 'Repair Frivo'
    $repairNote.Text  = 'Rebuilds program files and dependencies. Your API keys, profiles and usage history are preserved.'
    $txtPath.Text     = $existing.Path
} elseif ($existing.State -eq 'Partial') {
    $existingText.Text = ("A previous installation of {0} did not complete.`r`n`r`nLocation:`r`n{1}`r`n`r`nSetup can remove the incomplete files and install again." -f $AppName, $existing.Path)
    $radioUpdate.Visible = $false
    $updateNote.Visible  = $false
    $radioRepair.Checked = $true
    $radioRepair.Location = New-Object System.Drawing.Point(18, 14)
    $repairNote.Location  = New-Object System.Drawing.Point(38, 36)
    $radioRemove.Location = New-Object System.Drawing.Point(18, 74)
    $removeNote.Location  = New-Object System.Drawing.Point(38, 96)
    $radioRepair.Text = 'Clean up and install'
    $repairNote.Text  = 'Removes the incomplete installation, then installs normally. Your settings are not affected.'
    $txtPath.Text     = $existing.Path
}

function Show-Page {
    param([int] $i)
    foreach ($p in $pages) { $p.Panel.Visible = $false }
    $pages[$i].Panel.Visible = $true
    $header.Title.Text = $pages[$i].Title
    $header.Subtitle.Text = $pages[$i].Sub
    $btnNext.Text = $pages[$i].Next
    $btnBack.Enabled   = ($i -gt 0 -and $i -lt $idxInstalling)
    $btnBack.Visible   = $btnBack.Enabled
    $btnCancel.Enabled = ($i -lt $idxInstalling)
    $btnNext.Enabled   = ($i -ne $idxInstalling)
}

function Write-Log {
    param([string] $Message)
    $logBox.AppendText($Message + "`r`n")
    $logBox.SelectionStart = $logBox.TextLength
    $logBox.ScrollToCaret()
    Write-SetupLog ('UI: ' + $Message)
    [System.Windows.Forms.Application]::DoEvents()
}

$btnBack.Add_Click({ if ($index -gt 0) { $script:index--; Show-Page $script:index } })
$btnCancel.Add_Click({ $form.Close() })

$btnNext.Add_Click({
    if ($script:installFailed) {
        $form.Close()
        return
    }
    $current = $pages[$script:index]

    # Existing-install page: uninstall instead of continuing; remember the
    # requested update/repair behavior for the work step.
    if ($current.Panel -eq $pageExisting -and $radioRemove.Checked) {
        $un = Join-Path $existing.Path 'Uninstall.cmd'
        if (Test-Path -LiteralPath $un) {
            Start-Process -FilePath $un
        } else {
            Start-Process -FilePath 'powershell.exe' -ArgumentList @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-WindowStyle', 'Hidden',
                '-File', ('"{0}"' -f (Join-Path $existing.Path 'installer\Uninstall.ps1'))
            )
        }
        $form.Close()
        return
    }
    if ($current.Panel -eq $pageExisting) {
        if ($radioUpdate.Visible -and $radioUpdate.Checked) {
            $script:installAction = 'Update'
        } else {
            $script:installAction = 'Repair'
        }
    }

    if ($current.Panel -eq $pageLocation) {
        $script:knownExisting = $false
        try {
            $script:knownExisting = ($existing.State -ne 'None' -and
                [System.IO.Path]::GetFullPath($txtPath.Text).TrimEnd('\', '/').Equals(
                    [System.IO.Path]::GetFullPath($existing.Path).TrimEnd('\', '/'),
                    [System.StringComparison]::OrdinalIgnoreCase)) -or (Test-FrivoRecoverableResidue $txtPath.Text)
        } catch { }
        if ($existing.State -ne 'None' -and -not $script:knownExisting) {
            [System.Windows.Forms.MessageBox]::Show(
                'Frivo is already installed in a different folder. Uninstall it before choosing a new destination.',
                ('{0} Setup' -f $AppName),
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
            return
        }
        $check = Test-InstallPathUsable -Path $txtPath.Text -AllowKnownExistingInstall:$script:knownExisting
        if (-not $check.Ok) {
            [System.Windows.Forms.MessageBox]::Show($check.Reason, ('{0} Setup' -f $AppName),
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
            return
        }
        $txtPath.Text = $check.Path
    }

    if ($current.Panel -eq $pageOptions) {
        $script:index = $idxInstalling
        Show-Page $script:index
        try {
            $script:launcherPath = Install-Frivo `
                -Target $txtPath.Text `
                -DesktopShortcut $chkDesktop.Checked `
                -StartMenuShortcut $chkStart.Checked `
                -Startup $chkStartup.Checked `
                -Firewall $chkFirewall.Checked `
                -CleanFirst ($script:installAction -eq 'Repair') -AllowKnownLegacyInstall $script:knownExisting `
                -Action $script:installAction `
                -Log { param($m) Write-Log $m } `
                -Progress { param($p) $bar.SetValue($p); [System.Windows.Forms.Application]::DoEvents() }
            $doneWarning.Visible = -not $script:certificateReady
            $script:index = $idxDone
            Show-Page $script:index
        } catch {
            $message = $_.Exception.Message
            Write-SetupLog ('FAILED: ' + $message)
            Write-SetupLog ('At: ' + $_.InvocationInfo.PositionMessage)
            $bar.SetValue(0)
            Write-Log ''
            Write-Log 'Setup failed.'
            Write-Log $message
            [System.Windows.Forms.MessageBox]::Show(
                ("Setup was unable to complete.`r`n`r`n{0}`r`n`r`nA detailed log has been saved to:`r`n{1}" -f $message, $LogPath),
                ('{0} Setup' -f $AppName),
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
            $script:installFailed = $true
            $btnNext.Enabled = $true
            $btnNext.Text = 'Close'
            $btnCancel.Enabled = $false
            $btnCancel.Visible = $false
        }
        return
    }

    if ($current.Panel -eq $pageDone) {
        if ($chkLaunch.Checked -and $script:launcherPath) {
            # Launch directly through the native host. The VBScript shim is
            # reserved for optional sign-in startup, where -Tray is desired.
            $nativeLauncher = Join-Path $txtPath.Text 'installer\FrivoHost.exe'
            $launcherScript = Join-Path $txtPath.Text 'installer\Launcher.ps1'
            if (Test-Path -LiteralPath $nativeLauncher -PathType Leaf) {
                Start-Process -FilePath $nativeLauncher `
                    -ArgumentList ('--script "{0}"' -f $launcherScript) `
                    -WorkingDirectory $txtPath.Text
            } else {
                Start-Process -FilePath (Get-WScriptPath) `
                    -ArgumentList ('"{0}"' -f $script:launcherPath) `
                    -WorkingDirectory $txtPath.Text
            }
        }
        $form.Close()
        return
    }

    $script:index++
    Show-Page $script:index
})

Show-Page 0
[void] $form.ShowDialog()
