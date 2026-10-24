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
    [string] $DataPath,
    # NEW (2.0.0): what this PC is for. Both: Frivo and the Frivo app. Server:
    # Frivo and its launcher, as before. App: just the app. The wizard asks;
    # a silent update keeps what was chosen.
    [ValidateSet('Both', 'Server', 'App')]
    [string] $Role
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PackageDir = Split-Path -Parent $ScriptDir
$SourceApp  = Join-Path $PackageDir 'app'

Import-Module (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Force
# NEW (updates): the updater task and its folder. See Frivo.Update.psm1.
Import-Module (Join-Path $ScriptDir 'Frivo.Update.psm1') -Force

$AppName    = 'Frivo'
# One file decides the version for the whole app: the Apps & features
# entry, the setup wizard's welcome page, the compiled host's file
# properties, and the Inno container. It lives at the repo root as VERSION
# and is shipped in the setup payload so this script can read it there too.
#
# The literal is a fallback, not a second source of truth. If VERSION is
# ever missing from a payload, setup should still install rather than die
# over a cosmetic string — it just says "unknown" where a number would be.
function Get-FrivoVersion {
    $names = @()
    $scriptDir = Split-Path -Parent $PSCommandPath
    if ($scriptDir) {
        $names += (Join-Path $scriptDir 'VERSION')
        $parent = Split-Path -Parent $scriptDir
        if ($parent) {
            $names += (Join-Path $parent 'VERSION')
            $grandparent = Split-Path -Parent $parent
            if ($grandparent) { $names += (Join-Path $grandparent 'VERSION') }
        }
    }
    foreach ($candidate in $names) {
        try {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $text = (Get-Content -LiteralPath $candidate -Raw -ErrorAction Stop).Trim()
                if ($text) { return $text }
            }
        } catch { }
    }
    return 'unknown'
}

$AppVersion = Get-FrivoVersion
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

function Get-FrivoRunningUsers {
    <#
        NEW (restart): the Windows accounts Frivo is running as right now,
        from this install. Asked before an update stops Frivo, so it can be
        started again afterwards as the same people, in their own sessions.

        This lives in setup rather than in the updater on purpose: during an
        update, the updater that runs is the OLD version's, but this script
        is always the NEW version's. A restart fix put here works on the
        very next update instead of the one after.
    #>
    param([string] $Target)

    $users = New-Object System.Collections.ArrayList
    try {
        $processes = @(Get-CimInstance Win32_Process `
            -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'FrivoHost.exe'" `
            -ErrorAction Stop |
            Where-Object { $_.ExecutablePath -and (Test-PathWithinDirectory -Path $_.ExecutablePath -Directory $Target) })
    } catch {
        return ,@()
    }
    foreach ($process in $processes) {
        try {
            $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner -ErrorAction Stop
            if ($owner.ReturnValue -ne 0 -or -not $owner.User) { continue }
            $name = if ($owner.Domain) { '{0}\{1}' -f $owner.Domain, $owner.User } else { [string] $owner.User }
            # Never SYSTEM or a service account: Frivo started as one of
            # those would run invisibly, with somebody else's settings.
            if ($name -match '^(NT AUTHORITY|BUILTIN|Window Manager|Font Driver Host)\\') { continue }
            if (-not ($users -contains $name)) { [void] $users.Add($name) }
        } catch { }
    }
    return ,$users.ToArray()
}

function Test-FrivoRunningFrom {
    param([string] $Target)
    try {
        $found = @(Get-CimInstance Win32_Process `
            -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'FrivoHost.exe'" `
            -ErrorAction Stop |
            Where-Object { $_.ExecutablePath -and (Test-PathWithinDirectory -Path $_.ExecutablePath -Directory $Target) })
        return $found.Count -gt 0
    } catch {
        return $false
    }
}

function Start-FrivoAsUser {
    <#
        NEW (restart): starts Frivo the way Windows sign-in does —
        Frivo.vbs -Tray, which starts the server and its tray icon — as
        $User, in that user's own session, on this machine.

        Setup runs as SYSTEM during an in-app update, and anything it
        started directly would run as SYSTEM: invisible, in the wrong
        account, reading the wrong settings. A one-off scheduled task with
        an Interactive logon runs in the session the user already has open,
        and needs no password for exactly that reason. It is removed again
        straight away.

        NEW (2.0.0): -Window opens Frivo's window (or the Frivo app, in app
        mode) instead of starting in the tray. "Launch Frivo now" at the end
        of setup uses it, so Frivo doesn't run as administrator.
    #>
    param([string] $Target, [string] $User, [switch] $Window)

    $shim = Join-Path $Target 'Frivo.vbs'
    if (-not (Test-Path -LiteralPath $shim -PathType Leaf)) {
        Write-SetupLog ('restart: {0} is missing' -f $shim)
        return $false
    }
    $root = if ($env:SystemRoot) { $env:SystemRoot } else { 'C:\Windows' }
    $taskName = 'Frivo Restart'
    try {
        $shimArgs = if ($Window) { '"{0}"' -f $shim } else { '"{0}" -Tray' -f $shim }   # CHANGED (2.0.0)
        $action = New-ScheduledTaskAction -Execute ($root.TrimEnd('\') + '\System32\wscript.exe') `
            -Argument $shimArgs -WorkingDirectory $Target
        $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
        # No time limit: Task Scheduler's default would end what it started
        # after three days.
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal `
            -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline) {
            if (Test-FrivoRunningFrom $Target) {
                Write-SetupLog ('restart: Frivo is running again as {0}' -f $User)
                return $true
            }
            Start-Sleep -Milliseconds 500
        }
        Write-SetupLog ('restart: started the task for {0}, but Frivo is not running. Is that account signed in?' -f $User)
        return $false
    } catch {
        Write-SetupLog ('restart: could not start Frivo as {0}: {1}' -f $User, $_.Exception.Message)
        return $false
    } finally {
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop } catch { }
    }
}

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

    # NEW (1.7.0): the built-in AI's engine, which runs from the data folder.
    $engines = Stop-FrivoBuiltinAI -Folders @($script:SetupDataDir, $Target)
    if ($engines) { Write-SetupLog ('Stopped {0} built-in AI engine(s) before setup.' -f $engines) }

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
    # NEW (2.0.0): built-in dictation's package, installed on its own (Sync-FrivoDictation).
    Copy-Item (Join-Path $SourceApp 'requirements-dictation.txt') -Destination $Target -Force
    # CHANGED (1.5.0): the helper that speaks the voices built into Windows.
    # (The Kokoro voices and their requirements-voices.txt have been removed.)
    Copy-Item (Join-Path $SourceApp 'windows_speech.ps1') -Destination $Target -Force
    # NEW (1.5.0): gets Frivo's own voices (see Sync-FrivoVoices).
    Copy-Item (Join-Path $SourceApp 'voice_pack.py')      -Destination $Target -Force
    # NEW (1.6.0): Clean up without AI, and the built-in AI.
    Copy-Item (Join-Path $SourceApp 'cleanup_rules.py')   -Destination $Target -Force
    Copy-Item (Join-Path $SourceApp 'builtin_ai.py')      -Destination $Target -Force
    # NEW (2.0.0): built-in dictation.
    Copy-Item (Join-Path $SourceApp 'builtin_dictation.py') -Destination $Target -Force
    # Installed alongside the app so a running Frivo can say which version
    # it is — /diagnose reads it. Written rather than copied, because the
    # payload keeps VERSION one level up from the app folder and this is
    # the value setup already resolved.
    try {
        [IO.File]::WriteAllText((Join-Path $Target 'VERSION'), $AppVersion,
                                [Text.UTF8Encoding]::new($false))
    } catch { }
    Copy-Item (Join-Path $SourceApp 'templates\*')      -Destination (Join-Path $Target 'templates') -Recurse -Force
    Copy-Item (Join-Path $SourceApp 'static\*')         -Destination (Join-Path $Target 'static')    -Recurse -Force
    Copy-Item (Join-Path $ScriptDir 'Uninstall.ps1')           -Destination (Join-Path $Target 'installer') -Force
    Copy-Item (Join-Path $ScriptDir 'Launcher.ps1')            -Destination (Join-Path $Target 'installer') -Force
    Copy-Item (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Destination (Join-Path $Target 'installer') -Force
    Copy-Item (Join-Path $ScriptDir 'Frivo.Ui.psm1')    -Destination (Join-Path $Target 'installer') -Force
    # NEW (updates): the in-app updater. update-policy.json is read by both
    # the updater and app.py, so it ships beside them rather than in either.
    foreach ($name in @('Frivo.Update.psm1', 'Update-Frivo.ps1', 'Update-Watch.ps1', 'update-policy.json')) {
        Copy-Item (Join-Path $ScriptDir $name) -Destination (Join-Path $Target 'installer') -Force
    }
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

function Update-ShellIconCache {
    <#
        Makes replaced icon artwork actually appear.

        Windows caches icons per path, so writing new artwork to the same
        .ico changes nothing on screen — Explorer keeps drawing what it
        cached, through uninstalls and reinstalls, which reads as "the new
        icon did not install".

        Two mechanisms, because one is not enough:

          SHChangeNotify(SHCNE_ASSOCCHANGED) is the documented way to tell
          the shell its icon associations changed. Explorer re-reads icons
          on the next paint, with no restart.

          ie4uinit rebuilds the on-disk cache database, which SHChangeNotify
          alone does not touch.

        Neither covers an icon compiled into an .exe as a resource — that
        needs the executable rebuilt, not a cache refresh.

        Best effort throughout: a stale icon is cosmetic and must never
        fail an install.
    #>
    try {
        if (-not ('FrivoShell.Notify' -as [type])) {
            $signature = @'
[DllImport("shell32.dll", CharSet = CharSet.Auto, SetLastError = true)]
public static extern void SHChangeNotify(int eventId, uint flags, IntPtr item1, IntPtr item2);
'@
            Add-Type -Namespace FrivoShell -Name Notify -MemberDefinition $signature -ErrorAction Stop
        }
        # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
        [FrivoShell.Notify]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
    } catch { }

    try {
        $ie4uinit = Join-Path ([Environment]::GetFolderPath('System')) 'ie4uinit.exe'
        if (Test-Path -LiteralPath $ie4uinit -PathType Leaf) {
            # -show on Windows 10/11, -ClearIconCache on older builds. The
            # wrong one is simply ignored, so try both.
            Start-Process -FilePath $ie4uinit -ArgumentList '-show' -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
            Start-Process -FilePath $ie4uinit -ArgumentList '-ClearIconCache' -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
        }
    } catch { }
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

function Get-InstallSettings {
    <#
        Reads the choices made during setup. Older installations did not
        store them, so infer those choices from their current Windows state
        once and save the result during the next update.
    #>
    $settings = [pscustomobject] @{
        DesktopShortcut = (Test-Path -LiteralPath (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Frivo.lnk'))
        StartMenuShortcut = (Test-Path -LiteralPath (Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs\Frivo.lnk'))
        Startup = $false
        Firewall = $false
        # NEW (2.0.0): installs from before this was asked: "Both" if the app
        # was installed separately and runs Frivo here (app mode), else
        # "Server", what they were.
        Role = 'Server'
        RoleSaved = $false
    }
    try {
        $appPath = Get-FrivoLauncherAppPath -DataDir $script:SetupDataDir
        if ($appPath -and (Test-Path -LiteralPath $appPath -PathType Leaf)) { $settings.Role = 'Both' }
    } catch { }

    try {
        $run = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction Stop
        $settings.Startup = -not [string]::IsNullOrWhiteSpace([string] $run.Frivo)
    } catch { }
    try {
        $settings.Firewall = $null -ne (Get-NetFirewallRule -Name 'Frivo' -ErrorAction SilentlyContinue | Select-Object -First 1)
    } catch { }

    foreach ($key in $FrivoRegKeys) {
        try {
            if (-not (Test-Path -LiteralPath $key)) { continue }
            $registered = Get-ItemProperty -Path $key -ErrorAction Stop
            foreach ($item in @(
                @{ Name = 'FrivoDesktopShortcut'; Property = 'DesktopShortcut' },
                @{ Name = 'FrivoStartMenuShortcut'; Property = 'StartMenuShortcut' },
                @{ Name = 'FrivoStartup'; Property = 'Startup' },
                @{ Name = 'FrivoFirewall'; Property = 'Firewall' }
            )) {
                if ($registered.PSObject.Properties.Name -contains $item.Name) {
                    $settings.($item.Property) = [bool] ([int] $registered.($item.Name))
                }
            }
            # NEW (2.0.0)
            if ($registered.PSObject.Properties.Name -contains 'FrivoRole' -and
                [string] $registered.FrivoRole -in @('Both', 'Server')) {
                $settings.Role = [string] $registered.FrivoRole
                $settings.RoleSaved = $true
            }
            break
        } catch { }
    }
    return $settings
}

function Save-InstallSettings {
    param(
        [bool] $DesktopShortcut,
        [bool] $StartMenuShortcut,
        [bool] $Startup,
        [bool] $Firewall,
        [string] $Role = 'Server'   # NEW (2.0.0)
    )

    # This key is created by Register-Uninstaller immediately before us.
    Set-ItemProperty -Path $RegKey -Name 'FrivoDesktopShortcut' -Value ([int] $DesktopShortcut) -Type DWord
    Set-ItemProperty -Path $RegKey -Name 'FrivoStartMenuShortcut' -Value ([int] $StartMenuShortcut) -Type DWord
    Set-ItemProperty -Path $RegKey -Name 'FrivoStartup' -Value ([int] $Startup) -Type DWord
    Set-ItemProperty -Path $RegKey -Name 'FrivoFirewall' -Value ([int] $Firewall) -Type DWord
    # NEW (2.0.0). Not when it's only a guess (a silent update of an install
    # from before this was asked, running as SYSTEM, can't see the person's
    # settings to guess from).
    if ($Role) { Set-ItemProperty -Path $RegKey -Name 'FrivoRole' -Value $Role -Type String }
}

function Get-FrivoStandaloneOSC {
    <#
        NEW (2.0.0): the separate FrivOSC, if it's installed here: its
        uninstaller script, or $null. FrivOSC is built into the Frivo app
        now, so with the app here it's no longer needed.
    #>
    try {
        $key = Get-ItemProperty -LiteralPath 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FrivOSC' -ErrorAction Stop
        $folder = [string] $key.InstallLocation
        if (-not $folder) { return $null }
        $script = Join-Path $folder 'FrivOSC-Uninstall.ps1'
        if (Test-Path -LiteralPath $script -PathType Leaf) { return $script }
    } catch { }
    return $null
}

function Remove-FrivoStandaloneOSC {
    <#
        NEW (2.0.0): uninstalls the separate FrivOSC (its own uninstaller,
        silently), once the app that replaces it is installed. Never fatal.
    #>
    param([scriptblock] $Log)
    $script = Get-FrivoStandaloneOSC
    if (-not $script) { return }
    & $Log 'Removing the separate FrivOSC (it''s built into the Frivo app now)...'
    try {
        # The folder is passed in: FrivOSC 1.2.0's uninstaller can't work it
        # out under Windows PowerShell and stops before doing anything.
        $folder = Split-Path -Parent $script
        $p = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru -Wait -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $script), '-Silent',
            '-InstallPath', ('"{0}"' -f $folder))
        if (Get-FrivoStandaloneOSC) {
            & $Log 'The separate FrivOSC could not be removed. Remove it from Apps & features; the app stands aside while it runs.'
            Write-SetupLog ('FrivOSC uninstall exit code {0}' -f $p.ExitCode)
        } else {
            Write-SetupLog 'FrivOSC removed'
        }
    } catch {
        Write-SetupLog ('FrivOSC uninstall failed: ' + $_.Exception.Message)
        & $Log 'The separate FrivOSC could not be removed. Remove it from Apps & features.'
    }
}

function Get-FrivoBundledApp {
    <#
        NEW (2.0.0): the Frivo app that comes inside this setup
        (installer\app\FrivoApp-Setup.exe and app.json, put there by
        Build.bat). Running from the source tree without a build, the newest
        desktop\dist\FrivoApp-Setup-<version>.exe instead. $null when there
        isn't one.
    #>
    $folder = Join-Path $ScriptDir 'app'
    $exe = Join-Path $folder 'FrivoApp-Setup.exe'
    if (Test-Path -LiteralPath $exe -PathType Leaf) {
        try {
            $meta = Get-Content -LiteralPath (Join-Path $folder 'app.json') -Raw -ErrorAction Stop | ConvertFrom-Json
            if ([string] $meta.version -match '^\d+\.\d+\.\d+$') {
                return [pscustomobject] @{ Path = $exe; Version = [version] [string] $meta.version; Folder = $folder }
            }
        } catch { }
    }
    $best = $null
    $dist = Join-Path $PackageDir 'desktop\dist'
    if (Test-Path -LiteralPath $dist -PathType Container) {
        foreach ($file in @(Get-ChildItem -LiteralPath $dist -Filter 'FrivoApp-Setup-*.exe' -File -ErrorAction SilentlyContinue)) {
            $m = [regex]::Match($file.Name, '^FrivoApp-Setup-(\d+\.\d+\.\d+)\.exe$')
            if (-not $m.Success) { continue }
            $version = [version] $m.Groups[1].Value
            if (-not $best -or $version -gt $best.Version) {
                $best = [pscustomobject] @{ Path = $file.FullName; Version = $version; Folder = '' }
            }
        }
    }
    return $best
}

function Copy-FrivoAppInstaller {
    <#
        NEW (2.0.0): keeps the app's installer beside Frivo (app-installer\
        in the install folder), on every install and update. Frivo hands it
        to the app connected to it, which updates itself from it, and to a
        browser on another PC (Settings > Updates). That's how the app stays
        up to date with nothing but FrivoSetup.exe on GitHub.
    #>
    param([string] $Target, [scriptblock] $Log)
    $bundled = Get-FrivoBundledApp
    if (-not $bundled) { return }
    try {
        $dest = Join-Path $Target 'app-installer'
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        Copy-Item -LiteralPath $bundled.Path -Destination (Join-Path $dest 'FrivoApp-Setup.exe') -Force
        $json = (@{ version = $bundled.Version.ToString(3) } | ConvertTo-Json)
        [System.IO.File]::WriteAllText((Join-Path $dest 'app.json'), $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-SetupLog ('app installer copy failed: ' + $_.Exception.Message)
    }
}

function Install-FrivoApp {
    <#
        NEW (2.0.0): the Frivo app (desktop\ in the repo), from inside this
        setup, run as the person signed in at this PC: it's a per-person
        app, in their own AppData, and runs as them. Skipped when a newer
        one is already installed. Returns the app's .exe; throws with a
        reason when it can't.

        CHANGED (2.0.0): it's inside FrivoSetup.exe now, not downloaded from
        GitHub, so there's one file to publish and nothing to download here.
    #>
    param([scriptblock] $Log, [scriptblock] $OnProgress)

    $person = Get-FrivoDesktopUser
    $paths = Get-FrivoAppPaths -LocalAppData $person.LocalAppData
    $bundled = Get-FrivoBundledApp
    if (Test-Path -LiteralPath $paths.Exe -PathType Leaf) {
        # Compared as three parts: Windows may report the exe's version as
        # 1.0.0.0, and [version] 1.0.0.0 counts as newer than 1.0.0.
        $installed = $null
        try {
            $v = [version] ((Get-Item -LiteralPath $paths.Exe).VersionInfo.ProductVersion -replace '[^\d.].*$', '')
            $installed = [version]::new($v.Major, $v.Minor, [Math]::Max($v.Build, 0))
        } catch { }
        if (-not $bundled -or ($installed -and $installed -gt $bundled.Version)) {
            & $Log 'The Frivo app is already installed.'
            return $paths.Exe
        }
    }
    if (-not $bundled) { throw 'This setup doesn''t include the Frivo app. Build it with Build.bat.' }

    # In the person's own temp folder: the installer runs as them, and
    # setup's own temp folder may not be theirs to read.
    $folder = Join-Path $person.LocalAppData 'Temp\FrivoSetup'
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $file = Join-Path $folder ('FrivoApp-Setup-{0}.exe' -f $bundled.Version.ToString(3))
    Copy-Item -LiteralPath $bundled.Path -Destination $file -Force
    & $Log ('Installing the Frivo app {0}...' -f $bundled.Version.ToString(3))
    if ($OnProgress) { & $OnProgress 1 2 }
    try {
        $finished = Invoke-FrivoAsDesktopUser -User $person.User -FilePath $file -Arguments '/S' -Wait -TimeoutSeconds 300
    } finally {
        Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $paths.Exe -PathType Leaf)) {
        if (-not $finished) { throw 'The app''s installer did not finish in time.' }
        throw ('The app''s installer ran, but the app is not where it should be: {0}' -f $paths.Exe)
    }
    if ($OnProgress) { & $OnProgress 2 2 }
    & $Log ('The Frivo app {0} is installed.' -f $bundled.Version.ToString(3))
    Write-SetupLog ('app installed at {0} for {1}' -f $paths.Exe, $person.User)
    return $paths.Exe
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

function Set-FrivoBootStart {
    <#
        NEW (2.0.0): the "Frivo (at startup)" task, for a PC that's only a
        Frivo server: Frivo starts with Windows, as the person installing it,
        before anyone signs in. Never fatal.
    #>
    param([string] $Target, [bool] $Enabled, [scriptblock] $Log)
    try {
        if (-not $Enabled) {
            if (Unregister-FrivoBootTask -InstallDir $Target) {
                & $Log 'Frivo no longer starts before anyone signs in.'
                Write-SetupLog 'boot task removed'
            }
            return
        }
        $person = Get-FrivoDesktopUser
        if (-not $person.User) { throw 'Nobody is signed in at this PC to run Frivo as.' }
        & $Log ('Setting Frivo to start with Windows, as {0}...' -f $person.User)
        [void] (Register-FrivoBootTask -InstallDir $Target -DataDir $script:SetupDataDir -User $person.User)
        Write-SetupLog ('boot task registered for ' + $person.User)
    } catch {
        Write-SetupLog ('boot task failed: ' + $_.Exception.Message)
        & $Log ('Frivo could not be set to start before sign-in: {0} It still starts when you sign in, if that''s on.' -f $_.Exception.Message)
    }
}

# Frivo was running from the at-startup task before setup stopped it, and
# nothing has started it since: start it the same way.
function Resume-FrivoBootTask {
    param([string] $Target)
    if (-not $script:bootTaskWasRunning) { return }
    if (Test-FrivoRunningFrom $Target) { return }
    if (-not (Start-FrivoBootTask)) { return }
    Write-SetupLog 'restart: started the at-startup task again'
    # Until Frivo answers, so nothing else (Launch Frivo now, the restart
    # below in silent mode) starts a second copy alongside it.
    for ($i = 0; $i -lt 60; $i++) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $wait = $client.BeginConnect([System.Net.IPAddress]::Loopback, 5000, $null, $null)
            if ($wait.AsyncWaitHandle.WaitOne(250) -and $client.Connected) { return }
        } catch { } finally { $client.Close() }
        Start-Sleep -Milliseconds 250
    }
    Write-SetupLog 'restart: the at-startup task started, but Frivo did not answer within 30 seconds'
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
    # Deleting by name+program clears every rule this installer has ever
    # added under that name, including the UDP one below, so a reinstall
    # never stacks duplicates.
    Invoke-Tool -FilePath 'netsh.exe' -Arguments @(
        'advfirewall', 'firewall', 'delete', 'rule', 'name=Frivo', ('program=' + $pythonw)
    ) | Out-Null

    # ('program=' + $pythonw) — the parentheses are load-bearing. Inside an
    # array literal the comma binds tighter than +, so 'program=' + $pythonw
    # parses as ('action=allow', 'program=') + $pythonw: the path lands as
    # its own element and netsh receives an empty program= plus a stray
    # argument. It rejects that, and the failure is only logged, so the rule
    # silently never existed. The delete call above always had the
    # parentheses; this one did not.
    $r = Invoke-Tool -FilePath 'netsh.exe' -Arguments @(
        'advfirewall', 'firewall', 'add', 'rule', 'name=Frivo',
        'dir=in', 'action=allow', ('program=' + $pythonw),
        # CHANGED (1.5.0): this subnet and the other private networks, so a PC on
        # another VLAN (routed by the router) can reach Frivo too. Still never
        # the internet, and still only on a Private network.
        'profile=private', 'remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16', 'protocol=TCP', 'localport=5000'
    )
    if ($r.ExitCode -ne 0) {
        & $Log 'The firewall rule could not be added. Continuing.'
    }
}

function Register-FrivoUpdater {
    <#
        NEW (updates): the "Frivo Updater" task and the folder it shares
        with Frivo. Done on every install, repair and update — including the
        first update FROM a version that had no updater, which is how an
        existing install gets one. Never fatal: without it Frivo works, and
        updating falls back to asking Windows for permission each time.
    #>
    param([string] $Target, [scriptblock] $Log)

    & $Log 'Setting up in-app updates...'
    try {
        [void] (Initialize-FrivoUpdateFolder)
        $result = Register-FrivoUpdaterTask -InstallDir $Target
        Write-SetupLog ('updater task: ' + $result)
    } catch {
        Write-SetupLog ('updater setup failed: ' + $_.Exception.Message)
        & $Log 'In-app updates could not be set up. Frivo will ask for permission when it updates.'
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
        [scriptblock] $Progress,
        # NEW (2.0.0): 'Both' adds the Frivo app; $InstallApp says whether to
        # download it now (never in a silent update), $AppProgress follows
        # the download. $ClearAppMode: changed from Both to Server.
        [ValidateSet('Both', 'Server')]
        [string]      $Role = 'Server',
        [bool]        $InstallApp = $false,
        [bool]        $ClearAppMode = $false,
        [scriptblock] $AppProgress,
        [bool]        $SaveRole = $true,
        # NEW (2.0.0): start Frivo's server when Windows starts, before
        # anyone signs in. $null leaves it as it is (silent runs).
        [object]      $BootStart = $null
    )

    $check = Test-InstallPathUsable -Path $Target -AllowKnownExistingInstall:$AllowKnownLegacyInstall
    if (-not $check.Ok) { throw $check.Reason }
    $Target = $check.Path

    # NEW (2.0.0): Frivo started by the at-startup task is started the same
    # way again once this is done (Resume-FrivoBootTask). Before Repair's
    # clean-up, which stops it.
    $script:bootTaskWasRunning = Test-FrivoBootTaskRunning
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
    Copy-FrivoAppInstaller -Target $Target -Log $Log   # NEW (2.0.0)
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
    # NEW (2.0.0): built-in dictation's package. Allowed to fail: everything
    # else works without it, and Settings › Dictation says so.
    [void] (Sync-FrivoDictation -VenvPython $venvPython -Target $Target -Log $Log)
    # NEW (1.5.0): Frivo's free voices, into voices\piper in the install
    # folder. Updates and Repair keep them; uninstalling removes them.
    [void] (Sync-FrivoVoices -VenvPython $venvPython -Target $Target -Log $Log)
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
    # New artwork at an existing path is invisible until the shell cache
    # is rebuilt, which is what makes a new icon look like it did not
    # install. Runs whether or not shortcuts were just created, because an
    # update replaces the .ico without touching the .lnk.
    Update-ShellIconCache

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
        if ($null -ne $BootStart) { Set-FrivoBootStart -Target $Target -Enabled ([bool] $BootStart) -Log $Log }
    }
    Register-Uninstaller -Target $Target -Log $Log
    Save-InstallSettings -DesktopShortcut $DesktopShortcut -StartMenuShortcut $StartMenuShortcut `
        -Startup $Startup -Firewall $Firewall -Role $(if ($SaveRole) { $Role } else { '' })
    Register-FrivoUpdater -Target $Target -Log $Log   # NEW (updates)
    & $Progress 92
    if ($Action -ne 'Update') {
        Set-FirewallRule -Enabled $Firewall -Target $Target -Log $Log
    }
    & $Progress 94

    # NEW (2.0.0): the Frivo app. Frivo itself is installed by now, so a
    # problem here never undoes that: Frivo works in a browser meanwhile.
    $script:appExe = ''
    $script:appProblem = ''
    # CHANGED: never on a plain update (the in-app updater runs as SYSTEM,
    # and the app may since have been pointed at another PC): only when
    # installing, repairing, or adding the app.
    if ($Role -eq 'Both' -and ($Action -ne 'Update' -or $InstallApp)) {
        try {
            if ($InstallApp) {
                $script:appExe = Install-FrivoApp -Log $Log -OnProgress $AppProgress
            } else {
                $existingApp = (Get-FrivoAppPaths -LocalAppData (Get-FrivoDesktopUser).LocalAppData).Exe
                if (Test-Path -LiteralPath $existingApp -PathType Leaf) { $script:appExe = $existingApp }
            }
            if ($script:appExe) {
                # The launcher keeps to the background and opens the app, and
                # the app opens straight to Frivo on this PC.
                Set-FrivoLauncherAppPath -DataDir $script:SetupDataDir -AppPath $script:appExe
                Set-FrivoAppMode -RoamingAppData (Get-FrivoDesktopUser).RoamingAppData -Mode 'local'
                if ($script:removeStandaloneOSC) { Remove-FrivoStandaloneOSC -Log $Log }   # NEW (2.0.0)
            }
        } catch {
            $script:appProblem = $_.Exception.Message
            Write-SetupLog ('app: ' + $script:appProblem)
            & $Log ('The Frivo app could not be installed: ' + $script:appProblem)
            & $Log 'Frivo works in your browser meanwhile. Run setup again to try again.'
        }
    } elseif ($ClearAppMode) {
        # Server only from now on: the launcher shows itself again. The app,
        # if it's installed, stays; it asks where Frivo runs next time it
        # opens, rather than putting the launcher back in the background.
        try { Set-FrivoLauncherAppPath -DataDir $script:SetupDataDir -AppPath '' } catch { }
        try { Set-FrivoAppMode -RoamingAppData (Get-FrivoDesktopUser).RoamingAppData -Mode $null } catch { }
    }
    # NEW (2.0.0): one "Frivo" in Apps & features. With Frivo here, the app
    # isn't listed on its own; uninstalling Frivo offers to remove it too.
    try {
        $person = Get-FrivoDesktopUser
        if ($person.User -and (Test-Path -LiteralPath (Get-FrivoAppPaths -LocalAppData $person.LocalAppData).Exe -PathType Leaf)) {
            [void] (Set-FrivoAppListed -User $person.User -Listed $false)
        }
    } catch { Write-SetupLog ('app listing: ' + $_.Exception.Message) }
    & $Progress 100

    & $Log 'Installation complete.'
    Write-SetupLog 'Installation completed successfully'
    return $shim
}

# ==================================================================
# Silent mode
# ==================================================================

if ($Silent) {
    # CHANGED (updates): this is what an in-app update runs — FrivoSetup.exe
    # /VERYSILENT, started by the updater task as SYSTEM, with no desktop
    # and nobody to answer anything. So:
    #  - an update goes to wherever Frivo is installed, not the default path
    #  - -Action Update means update and nothing else. A half-installed
    #    Frivo is refused rather than repaired: repairing as SYSTEM would
    #    build the venv and the settings files in SYSTEM's own profile.
    #  - progress goes to the setup log, never Write-Host (there is no host)
    #  - a failure is logged as "FAILED: <reason>" — the updater reads that
    #    line back to say why — and then thrown, so FrivoHost returns 1 and
    #    Setup exits non-zero.
    $restartUsers = @()   # NEW (restart)
    $restartTarget = ''
    try {
        # NEW (2.0.0): just the app is installed through the wizard, as the
        # person signed in; a silent run only ever installs or updates Frivo.
        if ($Role -eq 'App') { throw 'Just the Frivo app cannot be installed silently. Run FrivoSetup.exe and choose it.' }
        $existing = Get-ExistingInstall
        if ($Action -eq 'Update' -and $existing.State -ne 'Installed') {
            throw 'Frivo is not fully installed on this PC, so it cannot be updated in place. Run FrivoSetup.exe to repair it.'
        }
        $target = if ($InstallPath) {
            $InstallPath
        } elseif ($existing.State -eq 'Installed') {
            $existing.Path
        } else {
            Get-DefaultInstallPath
        }
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
        Write-SetupLog ('Silent {0} of {1} -> {2} at {3}' -f $effectiveAction, $existing.Version, $AppVersion, $target)
        # NEW (restart): who Frivo is running as, before Install-Frivo stops it.
        $restartTarget = $target
        $restartUsers = Get-FrivoRunningUsers -Target $target
        Write-SetupLog ('restart: Frivo is running as: {0}' -f $(if ($restartUsers.Count) { $restartUsers -join ', ' } else { 'nobody' }))
        $cleanFirst = ($effectiveAction -eq 'Repair')
        $savedSettings = if ($effectiveAction -eq 'Update') { Get-InstallSettings } else { $null }
        Install-Frivo -Target $target `
            -DesktopShortcut $(if ($savedSettings) { $savedSettings.DesktopShortcut } else { -not $NoShortcut }) `
            -StartMenuShortcut $(if ($savedSettings) { $savedSettings.StartMenuShortcut } else { -not $NoShortcut }) `
            -Startup $(if ($savedSettings) { $savedSettings.Startup } else { [bool] $RunAtStartup }) `
            -Firewall $(if ($savedSettings) { $savedSettings.Firewall } else { [bool] $AllowFirewall }) `
            -CleanFirst $cleanFirst -AllowKnownLegacyInstall $knownExisting -Action $effectiveAction `
            -Role $(if ($savedSettings) { $savedSettings.Role } elseif ($Role -eq 'Both') { 'Both' } else { 'Server' }) `
            -InstallApp $false -SaveRole $(-not $savedSettings -or $savedSettings.RoleSaved) `
            -Log { param($m) if ($m) { Write-SetupLog ('silent: ' + $m) } } -Progress { param($p) } | Out-Null
    } catch {
        Write-SetupLog ('FAILED: ' + $_.Exception.Message)
        throw
    } finally {
        # NEW (restart): Frivo was running and this update stopped it, so it
        # is started again — after a failure too, because a stopped Frivo
        # is the one outcome nobody can fix from a browser on another PC.
        # Only if it is not already back (an older version's watcher may
        # have managed it): a second launcher would pop the first one open.
        # NEW (2.0.0): Frivo started before sign-in (the at-startup task):
        # started that way first, since nobody may be signed in.
        if ($restartTarget) { try { Resume-FrivoBootTask -Target $restartTarget } catch { } }
        foreach ($user in $restartUsers) {
            if (Test-FrivoRunningFrom $restartTarget) { break }
            [void] (Start-FrivoAsUser -Target $restartTarget -User $user)
        }
    }
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
$existingInstallSettings = if ($existing.State -ne 'None') { Get-InstallSettings } else { $null }
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
    -Text 'Removes the program. You choose whether to keep your settings and saves for next time.' `
    -X 38 -Y 160 -W 516 -H 30 -Font $Theme.FontSmall -Color $Theme.Dim
# NEW (2.0.0): a backup before changing anything, restorable in Frivo.
$chkSetupBackup = New-FrivoCheck -Theme $Theme -Parent $pageExisting `
    -Text 'Save a backup of my settings and saves first, to Documents\Frivo backups' -X 28 -Y 312 -W 564
$script:setupBackupTouched = $false
$chkSetupBackup.Add_Click({ $script:setupBackupTouched = $true })
# NEW (2.0.0): the API keys can go in the backup too, when asked for.
$chkSetupBackupKeys = New-FrivoCheck -Theme $Theme -Parent $pageExisting `
    -Text 'Include my API keys in it (keep that file private)' -X 48 -Y 336 -W 544
$chkSetupBackup.Add_CheckedChanged({ $chkSetupBackupKeys.Enabled = $chkSetupBackup.Checked -and $chkSetupBackup.Enabled })

# ---------- welcome ----------
$pageWelcome = New-Page
[void] (New-FrivoLabel -Theme $Theme -Parent $pageWelcome `
    -Text ('This wizard will install {0} on your computer.' -f $AppName) `
    -X 28 -Y 12 -W 564 -H 22 -Font $Theme.FontMid -Color $Theme.Ink)
# CHANGED (2.0.0): what Frivo is now: no keys needed to start, and the app.
[void] (New-FrivoLabel -Theme $Theme -Parent $pageWelcome -Text @"
Frivo turns what you type or say into speech, for VRChat and anywhere else.
It runs on this PC and opens in the Frivo app or your browser; phones and
other PCs on your network can use it too. It brings everything it needs,
including a private Python runtime, and changes nothing else on this PC.

Free voices and Clean up work without any accounts. OpenAI, ElevenLabs,
Ollama and Evora are optional, and are set up in Frivo's Settings.
"@ -X 28 -Y 44 -W 564 -H 180 -Font $Theme.FontUI -Color $Theme.Dim)
[void] (New-FrivoLabel -Theme $Theme -Parent $pageWelcome -Text 'Click Next to continue.' `
    -X 28 -Y 230 -W 564 -H 20 -Font $Theme.FontUI -Color $Theme.Ink)

# ---------- NEW (2.0.0): what this PC is for ----------
# One card: radio buttons only exclude each other inside the same container.
$pageRole = New-Page
[void] (New-FrivoLabel -Theme $Theme -Parent $pageRole -Text 'WHAT IS THIS PC FOR?' `
    -X 30 -Y 4 -W 400 -H 14 -Font $Theme.FontCaps -Color $Theme.Faint)
$cardRole = New-FrivoCard -Theme $Theme -Parent $pageRole -X 24 -Y 22 -W 572 -H 266
$radioBoth = New-FrivoRadio -Theme $Theme -Parent $cardRole -Text 'Run Frivo here, in the Frivo app (recommended)' -X 18 -Y 14 -W 536 -Checked $true
[void] (New-FrivoLabel -Theme $Theme -Parent $cardRole `
    -Text 'Frivo runs in the background and opens in its own window. Phones and other PCs can still connect to it.' `
    -X 38 -Y 38 -W 516 -H 34 -Font $Theme.FontSmall -Color $Theme.Dim)
$radioServer = New-FrivoRadio -Theme $Theme -Parent $cardRole -Text 'Run Frivo here, without the app' -X 18 -Y 96 -W 536
[void] (New-FrivoLabel -Theme $Theme -Parent $cardRole `
    -Text 'Frivo with its launcher window, used in a browser. For a PC that phones and other PCs connect to.' `
    -X 38 -Y 120 -W 516 -H 34 -Font $Theme.FontSmall -Color $Theme.Dim)
$radioApp = New-FrivoRadio -Theme $Theme -Parent $cardRole -Text 'Just the Frivo app' -X 18 -Y 178 -W 536
$appOnlyNote = New-FrivoLabel -Theme $Theme -Parent $cardRole `
    -Text 'Connects to Frivo running on another PC on your network. Nothing else is installed here.' `
    -X 38 -Y 202 -W 516 -H 34 -Font $Theme.FontSmall -Color $Theme.Dim
$roleNote = New-FrivoLabel -Theme $Theme -Parent $pageRole `
    -Text 'The app comes with this setup. After that it updates along with Frivo.' `
    -X 30 -Y 298 -W 560 -H 50 -Font $Theme.FontSmall -Color $Theme.Dim
# NEW (2.0.0): FrivOSC is built into the app. With the separate one here,
# offer to remove it (the app stands aside while it runs, so both would
# otherwise sit there doing nothing).
$chkRemoveOSC = New-FrivoCheck -Theme $Theme -Parent $pageRole `
    -Text 'Remove the separate FrivOSC: it''s built into the Frivo app now' -X 30 -Y 298 -W 560 -Checked $true
$chkRemoveOSC.Visible = $false
$script:removeStandaloneOSC = $false

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
# CHANGED (2.0.0): on by default; and starting before anyone signs in.
$cardStartup = New-FrivoCard -Theme $Theme -Parent $pageOptions -X 24 -Y 130 -W 572 -H 104
$chkStartup = New-FrivoCheck -Theme $Theme -Parent $cardStartup -Text ('Start {0} automatically when I sign in' -f $AppName) -X 18 -Y 12 -W 536 -Checked $true
[void] (New-FrivoLabel -Theme $Theme -Parent $cardStartup `
    -Text 'In the notification area, ready for phones and other PCs.' `
    -X 38 -Y 34 -W 516 -H 18 -Font $Theme.FontSmall -Color $Theme.Dim)
$chkBoot = New-FrivoCheck -Theme $Theme -Parent $cardStartup -Text ('Also start {0} before anyone signs in' -f $AppName) -X 18 -Y 56 -W 536
[void] (New-FrivoLabel -Theme $Theme -Parent $cardStartup `
    -Text 'For a PC that only runs Frivo for others: it starts with Windows, as you, with no window.' `
    -X 38 -Y 78 -W 516 -H 18 -Font $Theme.FontSmall -Color $Theme.Dim)

[void] (New-FrivoLabel -Theme $Theme -Parent $pageOptions -Text 'NETWORK' `
    -X 30 -Y 244 -W 400 -H 14 -Font $Theme.FontCaps -Color $Theme.Faint)
$cardNet = New-FrivoCard -Theme $Theme -Parent $pageOptions -X 24 -Y 262 -W 572 -H 66
$chkFirewall = New-FrivoCheck -Theme $Theme -Parent $cardNet -Text 'Allow connections from other devices on this network' -X 18 -Y 12 -W 536
[void] (New-FrivoLabel -Theme $Theme -Parent $cardNet `
    -Text 'Allows other devices on your private network to open Frivo.' `
    -X 38 -Y 36 -W 516 -H 18 -Font $Theme.FontSmall -Color $Theme.Dim)
$updateSettingsNote = New-FrivoLabel -Theme $Theme -Parent $pageOptions `
    -Text 'Your choices from the existing installation will be kept during this update.' `
    -X 30 -Y 336 -W 560 -H 22 -Font $Theme.FontSmall -Color $Theme.Dim
$updateSettingsNote.Visible = $false

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

# NEW (2.0.0): what happened with the app, when it's part of this install.
$doneAppNote = New-FrivoLabel -Theme $Theme -Parent $pageDone -Text '' `
    -X 28 -Y 190 -W 564 -H 80 -Font $Theme.FontSmall -Color $Theme.Dim
$doneAppNote.Visible = $false

# ---------- navigation ----------
# The existing-install page is only in the running order when there is
# something already on the machine.
$pages = New-Object System.Collections.ArrayList
if ($existing.State -ne 'None') {
    [void] $pages.Add(@{ Panel = $pageExisting; Title = ('{0} is already installed' -f $AppName); Sub = 'Choose what you would like to do'; Next = 'Next' })
}
[void] $pages.Add(@{ Panel = $pageWelcome;  Title = ('Welcome to {0} Setup' -f $AppName); Sub = ('Version {0}' -f $AppVersion); Next = 'Next' })
[void] $pages.Add(@{ Panel = $pageRole;     Title = 'How you''ll use Frivo';             Sub = 'Frivo, the Frivo app, or both';          Next = 'Next' })   # NEW (2.0.0)
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
    # CHANGED (2.0.0): says which kind of install it is.
    $kind = if ($existingInstallSettings -and $existingInstallSettings.Role -eq 'Server') { ' (without the app)' } else { ' (in the Frivo app)' }
    $existingText.Text = ("{0} version {1}{3} is already installed at:`r`n{2}`r`n`r`nSelect an option to continue." -f `
        $AppName, $(if ($existing.Version) { $existing.Version } else { 'unknown' }), $existing.Path, $kind)
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

# NEW (2.0.0): an existing Frivo keeps running here; the choice is whether
# the app comes with it. "Just the app" would mean removing Frivo, which is
# what Uninstall is for.
if ($existing.State -ne 'None') {
    $radioApp.Visible = $false
    $appOnlyNote.Visible = $false
}
if ($existingInstallSettings -and $existingInstallSettings.Role -eq 'Server') { $radioServer.Checked = $true }

# NEW (2.0.0): what's already here, said where the choice is made. Adding
# the app to Frivo (or Frivo to the app) happens in place: nothing has to
# be uninstalled first, and settings, profiles and saved replies stay.
$script:appAlreadyHere = $false
try {
    $script:appAlreadyHere = Test-Path -LiteralPath (Get-FrivoAppPaths -LocalAppData (Get-FrivoDesktopUser).LocalAppData).Exe -PathType Leaf
} catch { }
# CHANGED (2.0.0): what's installed is picked to start with, so running
# this setup again updates what this PC already is (app only, Frivo without
# the app, or both) unless you choose otherwise.
$script:appVersionHere = ''
if ($script:appAlreadyHere) {
    try {
        $v = [version] ((Get-Item -LiteralPath (Get-FrivoAppPaths -LocalAppData (Get-FrivoDesktopUser).LocalAppData).Exe).VersionInfo.ProductVersion -replace '[^\d.].*$', '')
        $script:appVersionHere = [version]::new($v.Major, $v.Minor, [Math]::Max($v.Build, 0)).ToString(3)
    } catch { }
}
$script:installedRole = if ($existing.State -eq 'None') { if ($script:appAlreadyHere) { 'App' } else { '' } }
    elseif ($existingInstallSettings -and $existingInstallSettings.Role -eq 'Server') { 'Server' } else { 'Both' }
if ($existing.State -eq 'Installed' -and $script:installedRole -eq 'Server' -and -not $script:appAlreadyHere) {
    $roleNote.ForeColor = $Theme.Ink
    $roleNote.Text = 'Installed here now: Frivo without the app, so that''s picked. To add the app, choose the first option: nothing needs uninstalling, and your settings, profiles and saved replies stay.'
} elseif ($script:installedRole -eq 'App') {
    # NEW (2.0.0): just the app is here: update it, as it is.
    $radioApp.Checked = $true
    $roleNote.ForeColor = $Theme.Ink
    $roleNote.Text = ('Installed here now: just the Frivo app{0}, so that''s picked: setup updates it and keeps its settings. To run Frivo on this PC as well, choose the first option.' -f
        $(if ($script:appVersionHere) { ' ' + $script:appVersionHere } else { '' }))
} elseif ($existing.State -eq 'Installed' -and $script:installedRole -eq 'Both' -and -not $script:appAlreadyHere) {
    $roleNote.ForeColor = $Theme.Ink
    $roleNote.Text = 'Installed here now: Frivo in the app, but the app itself is missing (it was uninstalled). Setup puts it back, or choose the second option to keep Frivo without it.'
} elseif ($script:appAlreadyHere) {
    $roleNote.Text = ('Installed here now: Frivo in the app{0}, so that''s picked. Setup updates the app if this one is newer.' -f
        $(if ($script:appVersionHere) { ' (app ' + $script:appVersionHere + ')' } else { '' }))
}

# NEW (2.0.0): FrivOSC, now built into the app.
if (Get-FrivoStandaloneOSC) {
    $chkRemoveOSC.Visible = $true
    $roleNote.Location = New-Object System.Drawing.Point(30, 324)
    $roleNote.Height = 34
    $syncRemoveOSC = { $chkRemoveOSC.Enabled = -not $radioServer.Checked }
    $radioServer.Add_CheckedChanged($syncRemoveOSC)
    & $syncRemoveOSC
}

# NEW (2.0.0): the backup box, only with something to back up. Ticked for
# Repair, which rebuilds everything; for an update it's your call.
$script:hasSetupData = $false
try { $script:hasSetupData = Test-FrivoHasData -DataDir $script:SetupDataDir } catch { }
$chkSetupBackup.Visible = $script:hasSetupData -and $existing.State -ne 'None'
$chkSetupBackup.Checked = ($existing.State -eq 'Partial')
$chkSetupBackupKeys.Visible = $chkSetupBackup.Visible   # NEW (2.0.0)
$chkSetupBackupKeys.Enabled = $chkSetupBackup.Checked
$radioRepair.Add_CheckedChanged({ if (-not $script:setupBackupTouched) { $chkSetupBackup.Checked = $radioRepair.Checked } })
$radioRemove.Add_CheckedChanged({
    $chkSetupBackup.Enabled = -not $radioRemove.Checked   # the uninstaller asks itself
    $chkSetupBackupKeys.Enabled = $chkSetupBackup.Enabled -and $chkSetupBackup.Checked
})
$script:wantBackup = $false
$script:wantBackupKeys = $false   # NEW (2.0.0)
$script:savedRole = if ($existingInstallSettings) { $existingInstallSettings.Role } else { '' }
$script:appOnly = $false

if ($existingInstallSettings) {
    $chkDesktop.Checked  = $existingInstallSettings.DesktopShortcut
    $chkStart.Checked    = $existingInstallSettings.StartMenuShortcut
    $chkStartup.Checked  = $existingInstallSettings.Startup
    $chkFirewall.Checked = $existingInstallSettings.Firewall
}
$chkBoot.Checked = ($existing.State -ne 'None') -and (Test-FrivoBootTask)   # NEW (2.0.0)

function Set-ConfigurationForAction {
    param([ValidateSet('Install', 'Update', 'Repair')] [string] $Action)

    $updating = ($Action -eq 'Update')
    foreach ($control in @($chkDesktop, $chkStart, $chkStartup, $chkBoot, $chkFirewall)) {
        $control.Enabled = -not $updating
    }
    $updateSettingsNote.Visible = $updating
}

$radioUpdate.Add_CheckedChanged({ if ($radioUpdate.Checked) { Set-ConfigurationForAction -Action 'Update' } })
$radioRepair.Add_CheckedChanged({ if ($radioRepair.Checked) { Set-ConfigurationForAction -Action 'Repair' } })
if ($existing.State -eq 'Installed') {
    Set-ConfigurationForAction -Action 'Update'
} else {
    Set-ConfigurationForAction -Action 'Install'
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
        $script:wantBackup = $chkSetupBackup.Visible -and $chkSetupBackup.Checked   # NEW (2.0.0)
        $script:wantBackupKeys = $script:wantBackup -and $chkSetupBackupKeys.Checked   # NEW (2.0.0)
        if ($radioUpdate.Visible -and $radioUpdate.Checked) {
            $script:installAction = 'Update'
        } else {
            $script:installAction = 'Repair'
        }
    }

    # NEW (2.0.0): just the app: no destination or options to ask about.
    if ($current.Panel -eq $pageRole) {   # NEW (2.0.0)
        $script:removeStandaloneOSC = $chkRemoveOSC.Visible -and $chkRemoveOSC.Enabled -and $chkRemoveOSC.Checked
    }
    if ($current.Panel -eq $pageRole -and $radioApp.Checked) {
        $script:appOnly = $true
        $script:index = $idxInstalling
        Show-Page $script:index
        $btnBack.Visible = $false
        try {
            Write-Log 'Installing the Frivo app...'
            $bar.SetValue(2)
            $script:appExe = Install-FrivoApp -Log { param($m) Write-Log $m } -OnProgress {
                param($done, $total)
                if ($total -gt 0) { $bar.SetValue([int] [Math]::Min(95, 2 + 93 * $done / $total)) }
                [System.Windows.Forms.Application]::DoEvents()
            }
            if ($script:removeStandaloneOSC) { Remove-FrivoStandaloneOSC -Log { param($m) Write-Log $m } }   # NEW (2.0.0)
            $bar.SetValue(100)
            Write-Log 'Done.'
            $chkLaunch.Text = 'Open the Frivo app now'
            $doneAppNote.Text = 'The Frivo app is installed, with shortcuts named Frivo. Open it, pick the PC Frivo runs on, and type the pairing code its launcher shows. It also connects VRChat to Frivo while VRChat runs here, and keeps itself up to date.'
            $doneAppNote.Visible = $true
            $script:launcherPath = $script:appExe
            $script:index = $idxDone
            Show-Page $script:index
        } catch {
            $message = $_.Exception.Message
            Write-SetupLog ('FAILED: ' + $message)
            $bar.SetValue(0)
            Write-Log ''
            Write-Log 'The Frivo app could not be installed.'
            Write-Log $message
            [System.Windows.Forms.MessageBox]::Show(
                ("The Frivo app could not be installed.`r`n`r`n{0}`r`n`r`nA detailed log has been saved to:`r`n{1}" -f $message, $LogPath),
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

        # Update keeps the saved shortcut, startup, and network choices, so
        # there is nothing to configure. Go straight from destination to the
        # installation work step instead of showing disabled checkboxes.
        if ($script:installAction -eq 'Update') {
            $current = @{ Panel = $pageOptions }
        }
    }

    if ($current.Panel -eq $pageOptions) {
        $script:index = $idxInstalling
        Show-Page $script:index
        try {
            # NEW (2.0.0): the backup first, before anything is stopped or
            # changed. If it can't be made, nothing changes unless you say so.
            if ($script:wantBackup) {
                Write-Log 'Saving a backup of your settings and saves...'
                [System.Windows.Forms.Application]::DoEvents()
                try {
                    $backupFile = New-FrivoBackup -DataDir $script:SetupDataDir -Version $existing.Version `
                        -Destination (Get-FrivoBackupFolder -RoamingAppData (Get-FrivoDesktopUser).RoamingAppData) `
                        -IncludeKeys:$script:wantBackupKeys   # NEW (2.0.0)
                    Write-Log ('Backup saved: {0}' -f $backupFile)
                    Write-SetupLog ('backup: ' + $backupFile)
                } catch {
                    Write-SetupLog ('backup failed: ' + $_.Exception.Message)
                    $answer = [System.Windows.Forms.MessageBox]::Show(
                        ("The backup couldn't be made:`r`n{0}`r`n`r`nContinue without a backup? Your settings are normally kept either way." -f $_.Exception.Message),
                        ('{0} Setup' -f $AppName),
                        [System.Windows.Forms.MessageBoxButtons]::YesNo,
                        [System.Windows.Forms.MessageBoxIcon]::Warning)
                    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
                        throw 'Setup stopped before changing anything, since the backup could not be made.'
                    }
                    Write-Log 'Continuing without a backup.'
                }
            }
            # NEW (2.0.0)
            $role = if ($radioBoth.Checked) { 'Both' } else { 'Server' }
            $script:launcherPath = Install-Frivo `
                -Target $txtPath.Text `
                -DesktopShortcut $chkDesktop.Checked `
                -StartMenuShortcut $chkStart.Checked `
                -Startup $chkStartup.Checked `
                -Firewall $chkFirewall.Checked `
                -CleanFirst ($script:installAction -eq 'Repair') -AllowKnownLegacyInstall $script:knownExisting `
                -Action $script:installAction `
                -Role $role -InstallApp ($role -eq 'Both') `
                -BootStart $(if ($script:installAction -eq 'Update') { $null } else { $chkBoot.Checked }) `
                -ClearAppMode ($role -eq 'Server' -and $script:savedRole -eq 'Both') `
                -AppProgress {
                    param($done, $total)
                    if ($total -gt 0) { $bar.SetValue([int] [Math]::Min(99, 94 + 5 * $done / $total)) }
                    [System.Windows.Forms.Application]::DoEvents()
                } `
                -Log { param($m) Write-Log $m } `
                -Progress { param($p) $bar.SetValue($p); [System.Windows.Forms.Application]::DoEvents() }
            $doneWarning.Visible = -not $script:certificateReady
            try { Resume-FrivoBootTask -Target $txtPath.Text } catch { }   # NEW (2.0.0)
            # NEW (2.0.0)
            if ($role -eq 'Both' -and $script:appProblem) {
                $doneAppNote.ForeColor = $Theme.Warn
                $doneAppNote.Text = ('The Frivo app could not be installed: {0} Frivo works in your browser meanwhile. Run setup again to try again.' -f $script:appProblem)
                $doneAppNote.Visible = $true
            } elseif ($role -eq 'Both' -and $script:appExe) {
                $doneAppNote.Text = 'Frivo runs in the background and opens in the Frivo app. Phones and other PCs can still connect to it.'
                $doneAppNote.Visible = $true
            }
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
        # NEW (2.0.0): just the app: open it, as the person signed in.
        if ($script:appOnly) {
            if ($chkLaunch.Checked -and $script:appExe) {
                try {
                    $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
                    [void] (Invoke-FrivoAsDesktopUser -User (Get-FrivoDesktopUser).User -FilePath $script:appExe)
                } catch { Write-SetupLog ('could not open the app: ' + $_.Exception.Message) }
            }
            $form.Close()
            return
        }
        $startedAsUser = $false   # NEW (2.0.0)
        if ($chkLaunch.Checked -and $script:launcherPath) {
            # CHANGED (2.0.0): as the person signed in to this PC, not as
            # administrator (setup's own rights). Frivo started from here used
            # to run as administrator: its files and settings were the same,
            # but nothing running as that person (the Frivo app, a new
            # launcher) could stop it. Falls back to the old way.
            try {
                $desktopUser = [string] (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName
                if ($desktopUser) {
                    $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
                    $startedAsUser = Start-FrivoAsUser -Target $txtPath.Text -User $desktopUser -Window
                }
            } catch { $startedAsUser = $false }
        }
        if ($chkLaunch.Checked -and $script:launcherPath -and -not $startedAsUser) {
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
