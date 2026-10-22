<#
    Frivo — uninstaller
    ------------------------------------------------------------------
    A small window in the application's own style: one confirmation with
    a checkbox for the settings, live progress while it removes things,
    and a summary of exactly what was done.

    Each step is recorded, and the result is shown in the window and log.
#>

[CmdletBinding()]
param(
    [switch] $Silent,
    [switch] $KeepSettings,
    [switch] $RemoveSettings,
    # NEW (1.8.0): silent uninstalls leave the Frivo app alone unless asked.
    [switch] $RemoveApp,
    # Captured before elevation so a standard user who supplies separate
    # administrator credentials still has their own settings addressed.
    [string] $DataPath
)

Set-StrictMode -Version Latest
# Continue cleanup after individual errors and report failed steps.
$ErrorActionPreference = 'Continue'

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Split-Path -Parent $ScriptDir
$AppName    = 'Frivo'

Import-Module (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Force
# NEW (updates): for removing the updater task. Guarded: an install whose
# files are already half gone should still uninstall.
$script:HasUpdateModule = $false
try {
    Import-Module (Join-Path $ScriptDir 'Frivo.Update.psm1') -Force -ErrorAction Stop
    $script:HasUpdateModule = $true
} catch { }
$DataDir = if ($DataPath) { $DataPath } else { Get-DataPath }
$LogPath = Get-SetupLogPath

# A process holds a handle on its own working directory, and that stops the
# folder being deleted. Step out before doing anything else.
try { Set-Location ([Environment]::GetFolderPath('Windows')) } catch { Set-Location 'C:\' }

# Names used by this version and by the version that shipped as
# "Voice Console". Both are cleaned up, so upgrading past the rename does
# not strand a scheduled task or a firewall rule nobody will ever find.
$TaskNames = @('Frivo', 'VoiceConsole')
$RuleNames = @('Frivo', 'Voice Console')
$RegKeys   = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    'HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
    'HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\VoiceConsole'
)

# NEW (1.8.0): the Frivo app, if it's installed for the person signed in
# here, and whether setup installed it with Frivo ("Both"): then removing
# it is the default. One installed on its own is only removed if asked.
$script:AppPaths = $null
$script:AppWithFrivo = $false
try {
    $person = Get-FrivoDesktopUser
    $candidate = Get-FrivoAppPaths -LocalAppData $person.LocalAppData
    if (Test-Path -LiteralPath $candidate.Uninstaller -PathType Leaf) { $script:AppPaths = $candidate }
} catch { }
foreach ($key in $RegKeys) {
    try {
        $r = Get-ItemProperty -Path $key -ErrorAction Stop
        if ($r.PSObject.Properties.Name -contains 'FrivoRole') { $script:AppWithFrivo = ([string] $r.FrivoRole -eq 'Both'); break }
    } catch { }
}

$steps    = New-Object System.Collections.ArrayList
$problems = New-Object System.Collections.ArrayList
$script:StepSink = $null   # the GUI's live log, when there is one

function Add-Step {
    param([string] $Text, [bool] $Ok = $true)
    [void] $steps.Add(@{ Text = $Text; Ok = $Ok })
    Write-SetupLog ('uninstall: {0}{1}' -f $Text, $(if ($Ok) { '' } else { '  [FAILED]' }))
    if (-not $Ok) { [void] $problems.Add($Text) }
    if ($script:StepSink) { & $script:StepSink $Text $Ok }
}

# ==================================================================
# Elevation
# ==================================================================

if (-not (Test-IsAdministrator)) {
    $relaunch = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA',
        '-WindowStyle', 'Hidden', '-File', ('"{0}"' -f $PSCommandPath)
    )
    if ($Silent)         { $relaunch += '-Silent' }
    if ($KeepSettings)   { $relaunch += '-KeepSettings' }
    if ($RemoveSettings) { $relaunch += '-RemoveSettings' }
    if ($DataDir)        { $relaunch += @('-DataPath', ('"{0}"' -f $DataDir)) }
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $relaunch -Verb RunAs -WindowStyle Hidden | Out-Null
    } catch {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            'Administrator privileges are required to uninstall Frivo.',
            ('Uninstall {0}' -f $AppName),
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
    exit
}

Write-SetupLog '--------------------------------------------------'
Write-SetupLog ('{0} uninstall started, target {1}' -f $AppName, $InstallDir)

$script:InstallOwned = Test-FrivoInstallOwnership $InstallDir
if (-not $script:InstallOwned) {
    # Installations made before the marker existed can still be removed if
    # their own Apps & features entry points back to this exact folder.
    foreach ($key in $RegKeys) {
        try {
            $location = [string] (Get-ItemProperty -Path $key -ErrorAction Stop).InstallLocation
            if ($location -and [System.IO.Path]::GetFullPath($location).TrimEnd('\', '/').Equals(
                    [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\', '/'),
                    [System.StringComparison]::OrdinalIgnoreCase)) {
                $script:InstallOwned = $true
                break
            }
        } catch { }
    }
}

# ==================================================================
# The removal itself
# ==================================================================

function Get-FrivoBuiltinAIFolders {
    <#
        NEW (1.7.0): every folder that may hold the built-in AI: the data
        folder, the program folder, and the one picked in Settings > Storage
        (config.json's storage_builtin_ai), each with builtin_ai inside.
    #>
    $parents = @($DataDir, $InstallDir)
    try {
        $config = Join-Path $DataDir 'config.json'
        if (Test-Path -LiteralPath $config) {
            $picked = [string] ((Get-Content -LiteralPath $config -Raw -ErrorAction Stop | ConvertFrom-Json).storage_builtin_ai)
            if ($picked -and [System.IO.Path]::IsPathRooted($picked)) { $parents += $picked }
        }
    } catch { }
    return $parents
}

function Invoke-Removal {
    # $PreserveSettings, never $keepSettings: that name collides with the
    # [switch] $KeepSettings parameter (variable names are case-insensitive),
    # and a switch silently turns $null into $false — which once made
    # cancelling delete settings anyway.
    param([bool] $PreserveSettings, [bool] $RemoveTheApp)

    if (-not $script:InstallOwned) {
        Add-Step 'Refused to remove an unverified program folder' $false
        return
    }

    # --- NEW (1.8.0): the Frivo app ---
    # Its own uninstaller, silently, as the person it was installed for. It
    # closes the app if it's open.
    if ($RemoveTheApp -and $script:AppPaths) {
        try {
            [void] (Invoke-FrivoAsDesktopUser -User (Get-FrivoDesktopUser).User `
                -FilePath $script:AppPaths.Uninstaller -Arguments '/S' -Wait -TimeoutSeconds 180)
            # The uninstaller hands over to a copy of itself and exits at once,
            # so wait for the app itself to be gone.
            $until = (Get-Date).AddSeconds(90)
            while ((Test-Path -LiteralPath $script:AppPaths.Exe) -and (Get-Date) -lt $until) {
                Start-Sleep -Milliseconds 300
                if ('System.Windows.Forms.Application' -as [type]) { [System.Windows.Forms.Application]::DoEvents() }
            }
            if (-not (Test-Path -LiteralPath $script:AppPaths.Exe)) {
                Add-Step 'Removed the Frivo app'
            } else {
                Add-Step 'Remove the Frivo app (remove "Frivo App" in Apps & features)' $false
            }
        } catch {
            Add-Step 'Remove the Frivo app (remove "Frivo App" in Apps & features)' $false
        }
    }

    # --- the launcher window ---
    # A running launcher holds its working directory inside the install
    # folder and would block the removal below.
    try {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine -match 'Launcher\.ps1' -and
                $_.CommandLine -match [regex]::Escape($InstallDir) -and
                ($_.Name -ieq 'powershell.exe' -or $_.Name -ieq 'FrivoHost.exe')
            } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { } }
    } catch { }

    # --- NEW (1.8.0): starting Frivo before sign-in ---
    # First, so the task isn't left pointing at a removed Frivo. Only when
    # it runs this install's Frivo.
    try {
        if (Unregister-FrivoBootTask -InstallDir $InstallDir) { Add-Step 'Removed the "Frivo (at startup)" task' }
    } catch {
        Add-Step 'Remove the "Frivo (at startup)" task' $false
    }

    # --- running instances ---
    try {
        $killed = 0
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ExecutablePath -and
                (Test-PathWithinDirectory -Path $_.ExecutablePath -Directory $InstallDir)
            } |
            ForEach-Object {
                try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $killed++ } catch { }
            }
        # NEW (1.7.0): the built-in AI's engine runs from the data folder.
        $killed += Stop-FrivoBuiltinAI -Folders (Get-FrivoBuiltinAIFolders)
        if ($killed) {
            Add-Step ('Stopped {0} running instance(s)' -f $killed)
            # File handles are released asynchronously.
            Start-Sleep -Milliseconds 800
        }
    } catch {
        Add-Step 'Stop running instances' $false
    }

    # --- sign-in entry ---
    foreach ($runKey in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
    )) {
        try {
            $v = Get-ItemProperty -Path $runKey -Name $AppName -ErrorAction SilentlyContinue
            if ($v -and ([string] $v.$AppName) -match [regex]::Escape($InstallDir)) {
                Remove-ItemProperty -Path $runKey -Name $AppName -ErrorAction Stop
                Add-Step 'Removed the sign-in entry'
            }
        } catch {
            Add-Step 'Remove the sign-in entry' $false
        }
    }

    # --- startup task (older versions) ---
    foreach ($task in $TaskNames) {
        try {
            $q = Invoke-Tool -FilePath 'schtasks.exe' -Arguments @('/query', '/tn', $task, '/fo', 'LIST', '/v')
            if ($q.ExitCode -eq 0 -and $q.StdOut -match [regex]::Escape($InstallDir)) {
                $d = Invoke-Tool -FilePath 'schtasks.exe' -Arguments @('/delete', '/tn', $task, '/f')
                Add-Step ('Removed startup task "{0}"' -f $task) ($d.ExitCode -eq 0)
            }
        } catch {
            Add-Step ('Remove startup task "{0}"' -f $task) $false
        }
    }

    # --- shortcuts ---
    # Joined only after checking for empty: GetFolderPath can return '' for
    # a folder the OS doesn't have, and Join-Path refuses an empty path.
    $shortcutRoots = @()
    foreach ($base in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory'))) {
        if ($base) { $shortcutRoots += $base }
    }
    foreach ($base in @([Environment]::GetFolderPath('StartMenu'), [Environment]::GetFolderPath('CommonStartMenu'))) {
        if ($base) { $shortcutRoots += (Join-Path $base 'Programs') }
    }
    foreach ($root in $shortcutRoots) {
        foreach ($name in @('Frivo.lnk', 'Voice Console.lnk')) {
            $link = Join-Path $root $name
            if (Test-Path -LiteralPath $link) {
                try {
                    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
                    if (([string] $shortcut.TargetPath) -match [regex]::Escape($InstallDir) -or
                        ([string] $shortcut.Arguments) -match [regex]::Escape($InstallDir)) {
                        Remove-Item -LiteralPath $link -Force -ErrorAction Stop
                        Add-Step ('Removed shortcut {0}' -f $name)
                    }
                } catch {
                    Add-Step ('Remove shortcut {0}' -f $name) $false
                }
            }
        }
    }

    # --- firewall ---
    foreach ($rule in $RuleNames) {
        try {
            $show = Invoke-Tool -FilePath 'netsh.exe' -Arguments @('advfirewall','firewall','show','rule',('name=' + $rule), 'verbose')
            if ($show.StdOut -notmatch 'No rules match' -and $show.StdOut -match [regex]::Escape($InstallDir)) {
                $pythonw = Join-Path $InstallDir '.venv\Scripts\pythonw.exe'
                $del = Invoke-Tool -FilePath 'netsh.exe' -Arguments @('advfirewall','firewall','delete','rule',('name=' + $rule), ('program=' + $pythonw))
                Add-Step ('Removed firewall rule "{0}"' -f $rule) ($del.ExitCode -eq 0)
            }
        } catch {
            Add-Step ('Remove firewall rule "{0}"' -f $rule) $false
        }
    }

    $sharedInstall = Test-OtherFrivoInstall -InstallPath $InstallDir

    # --- NEW (updates): the updater task and its folder ---
    # The task is only removed when it runs this install's updater; the
    # shared folder in ProgramData only when no other Frivo is installed.
    if ($script:HasUpdateModule) {
        try {
            if (Unregister-FrivoUpdaterTask -InstallDir $InstallDir) {
                Add-Step ('Removed the "{0}" task' -f (Get-FrivoUpdaterTaskName))
            }
        } catch {
            Add-Step ('Remove the "{0}" task' -f (Get-FrivoUpdaterTaskName)) $false
        }
        if (-not $sharedInstall) {
            $updateFolder = Get-FrivoUpdateFolder
            $programDataFrivo = Split-Path -Parent $updateFolder
            try {
                if (Test-Path -LiteralPath $updateFolder) {
                    $item = Get-Item -LiteralPath $updateFolder -Force
                    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                        # Windows PowerShell's Remove-Item -Recurse follows a
                        # link into its target. Remove the link alone.
                        [System.IO.Directory]::Delete($updateFolder)
                    } else {
                        Remove-Item -LiteralPath $updateFolder -Recurse -Force -ErrorAction Stop
                    }
                    Add-Step 'Removed the update records'
                }
                if ((Test-Path -LiteralPath $programDataFrivo) -and
                    -not (Get-ChildItem -LiteralPath $programDataFrivo -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
                    Remove-Item -LiteralPath $programDataFrivo -Force -ErrorAction SilentlyContinue
                }
            } catch {
                Add-Step 'Remove the update records' $false
            }
        }
    }

    # --- frivo.local address ---
    try {
        if ($sharedInstall) {
            Add-Step 'Kept shared frivo.local address for another Frivo installation'
        } elseif (Remove-FrivoHostsEntry) {
            Add-Step 'Removed the frivo.local address'
        }
    } catch {
        Add-Step 'Remove the frivo.local address' $false
    }

    # --- trusted certificate ---
    # The CA that setup placed in Trusted Root Certification Authorities.
    # Removing it is part of leaving the machine exactly as it was found.
    try {
        $removedCerts = if ($sharedInstall) { 0 } else { Remove-FrivoRootCertificate -CertificatePath (Join-Path $DataDir 'ca.crt') }
        if ($sharedInstall) {
            Add-Step 'Kept shared trusted certificate for another Frivo installation'
        } elseif ($removedCerts -gt 0) {
            Add-Step 'Removed the trusted certificate'
        }
    } catch {
        Add-Step 'Remove the trusted certificate' $false
    }

    # --- registry ---
    foreach ($key in $RegKeys) {
        if (Test-Path $key) {
            try {
                $location = [string] (Get-ItemProperty -Path $key -ErrorAction Stop).InstallLocation
                if ($location -and [System.IO.Path]::GetFullPath($location).TrimEnd('\', '/').Equals(
                        [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\', '/'),
                        [System.StringComparison]::OrdinalIgnoreCase)) {
                    Remove-Item -Path $key -Recurse -Force -ErrorAction Stop
                    Add-Step 'Removed Apps & features entry'
                }
            } catch {
                Add-Step 'Remove Apps & features entry' $false
            }
        }
    }

    # --- NEW (1.7.0): the built-in AI ---
    # Gigabytes of engine and models, not settings: always removed, even
    # when settings are kept. Setting it up again is one click.
    # CHANGED (1.7.0): including a folder picked in Settings > Storage. Only
    # its builtin_ai subfolder: never anything else in the folder you picked.
    foreach ($folder in @(Get-FrivoBuiltinAIFolders | ForEach-Object { Join-Path $_ 'builtin_ai' })) {
        if (Test-Path -LiteralPath $folder) {
            try {
                Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction Stop
                Add-Step 'Removed the built-in AI'
            } catch {
                Add-Step ('Remove the built-in AI ({0})' -f $folder) $false
            }
        }
    }

    # --- settings ---
    if ($PreserveSettings) {
        if (Test-Path -LiteralPath $DataDir) { Add-Step ('Kept settings in {0}' -f $DataDir) }
    } elseif (Test-Path -LiteralPath $DataDir) {
        # NEW (1.7.0): folders picked in Settings > Storage go too, but only
        # Frivo's own subfolder in each (voices, saved, audio_cache).
        try {
            $config = Join-Path $DataDir 'config.json'
            if (Test-Path -LiteralPath $config) {
                $cfg = Get-Content -LiteralPath $config -Raw -ErrorAction Stop | ConvertFrom-Json
                foreach ($pair in @(@('storage_voices', 'voices'), @('storage_saved', 'saved'), @('storage_audio', 'audio_cache'))) {
                    $picked = [string] $cfg.($pair[0])
                    if ($picked -and [System.IO.Path]::IsPathRooted($picked)) {
                        $folder = Join-Path $picked $pair[1]
                        if (Test-Path -LiteralPath $folder) {
                            try { Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction Stop } catch {
                                Add-Step ('Delete {0}' -f $folder) $false
                            }
                        }
                    }
                }
            }
        } catch { }
        try {
            Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction Stop
            Add-Step 'Deleted settings'
        } catch {
            Add-Step 'Delete settings' $false
        }
    }

    # --- program files ---
    # Remove files while the window is open so any failures can be reported.
    # Static assets remain locked until the dialog closes and are removed by
    # deferred cleanup.
    foreach ($item in @('.venv', 'templates', '__pycache__', 'audio_cache')) {
        $path = Join-Path $InstallDir $item
        if (Test-Path -LiteralPath $path) {
            try {
                Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
            } catch {
                Add-Step ('Remove {0}' -f $item) $false
            }
        }
    }
    Get-ChildItem -LiteralPath $InstallDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne 'Uninstall.cmd' } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

    # static and the uninstaller's icon can remain locked until this window
    # closes. A detached PowerShell process waits for this exact process ID,
    # then removes the folder. A fixed delay is not enough: the user can
    # keep the completion window open longer than the delay.
    $escapedInstallDir = $InstallDir.Replace("'", "''")
    $cleanupCommand = "Wait-Process -Id $PID; Remove-Item -LiteralPath '$escapedInstallDir' -Recurse -Force -ErrorAction SilentlyContinue"
    $cleanupArguments = ConvertTo-ArgumentString @('-NoProfile', '-WindowStyle', 'Hidden', '-Command', $cleanupCommand)
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $cleanupArguments `
                      -WorkingDirectory ([Environment]::GetFolderPath('Windows')) `
                      -WindowStyle Hidden | Out-Null
        Add-Step 'Finalizing program files'
    } catch {
        Add-Step 'Remove program files' $false
    }

    Write-SetupLog ('uninstall finished with {0} problem(s)' -f $problems.Count)
}

# ==================================================================
# Silent mode
# ==================================================================

if ($Silent) {
    Invoke-Removal -PreserveSettings (-not $RemoveSettings) -RemoveTheApp ([bool] $RemoveApp)
    $steps | ForEach-Object { Write-Host $_.Text }
    exit $(if ($problems.Count) { 1 } else { 0 })
}

# ==================================================================
# Window
# ==================================================================

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

Import-Module (Join-Path $ScriptDir 'Frivo.Ui.psm1') -Force
$Theme = Get-FrivoTheme

$form = New-FrivoForm -Theme $Theme -Title ('Uninstall {0}' -f $AppName) -Width 500 -Height 430 `
    -IconPath (Join-Path $InstallDir 'static\Frivo.ico')

$header = New-FrivoHeader -Theme $Theme -Form $form -Title ('Uninstall {0}' -f $AppName) `
    -Subtitle $InstallDir -LogoPngPath (Join-Path $InstallDir 'static\icon.png')

# ---------- confirm view ----------
$viewConfirm = New-Object System.Windows.Forms.Panel
$viewConfirm.Location = New-Object System.Drawing.Point(0, 76)
$viewConfirm.Size = New-Object System.Drawing.Size(500, 354)
$viewConfirm.BackColor = $Theme.Bg
$form.Controls.Add($viewConfirm)

[void] (New-FrivoLabel -Theme $Theme -Parent $viewConfirm -Text @"
This removes Frivo, its shortcuts, network access and local certificate.
"@ -X 28 -Y 10 -W 444 -H 42 -Font $Theme.FontUI -Color $Theme.Dim)

$cardSettings = New-FrivoCard -Theme $Theme -Parent $viewConfirm -X 24 -Y 64 -W 452 -H $(if ($script:AppPaths) { 108 } else { 70 })
$chkDelete = New-FrivoCheck -Theme $Theme -Parent $cardSettings -Text 'Also remove Frivo saved API keys and preferences' -X 18 -Y 18 -W 416
# NEW (1.8.0): ticked when setup installed the app with Frivo.
$chkApp = New-FrivoCheck -Theme $Theme -Parent $cardSettings -Text 'Also remove the Frivo app' -X 18 -Y 58 -W 416 -Checked $script:AppWithFrivo
$chkApp.Visible = [bool] $script:AppPaths

$btnRemove = New-FrivoButton -Theme $Theme -Parent $viewConfirm -Text ('Uninstall {0}' -f $AppName) -X 24 -Y 250 -W 452 -H 44 -Primary $true
$btnCancel = New-FrivoButton -Theme $Theme -Parent $viewConfirm -Text 'Cancel' -X 24 -Y 302 -W 452 -H 38

# ---------- progress view ----------
$viewRun = New-Object System.Windows.Forms.Panel
$viewRun.Location = New-Object System.Drawing.Point(0, 76)
$viewRun.Size = New-Object System.Drawing.Size(500, 354)
$viewRun.BackColor = $Theme.Bg
$viewRun.Visible = $false
$form.Controls.Add($viewRun)

$runLog = New-FrivoTextBox -Theme $Theme -Parent $viewRun -X 24 -Y 8 -W 452 -H 230 -Multiline
$summaryLbl = New-FrivoLabel -Theme $Theme -Parent $viewRun -Text '' -X 28 -Y 246 -W 444 -H 48 -Font $Theme.FontUI -Color $Theme.Ink
$btnClose = New-FrivoButton -Theme $Theme -Parent $viewRun -Text 'Close' -X 24 -Y 302 -W 452 -H 38 -Primary $true
$btnClose.Enabled = $false

# ---------- behaviour ----------
$btnCancel.Add_Click({
    Write-SetupLog 'uninstall: cancelled by user'
    $form.Close()
})

$btnRemove.Add_Click({
    # Read before the view is hidden: a control in a hidden panel reports
    # Visible = $false, which made this always "keep the app".
    $removeApp = [bool] $script:AppPaths -and $chkApp.Checked
    $viewConfirm.Visible = $false
    $viewRun.Visible = $true
    $header.Subtitle.Text = 'Removing…'
    [System.Windows.Forms.Application]::DoEvents()

    $script:StepSink = {
        param($Text, $Ok)
        $mark = if ($Ok) { '  ' } else { '! ' }
        $runLog.AppendText($mark + $Text + "`r`n")
        $runLog.SelectionStart = $runLog.TextLength
        $runLog.ScrollToCaret()
        [System.Windows.Forms.Application]::DoEvents()
    }

    Invoke-Removal -PreserveSettings (-not $chkDelete.Checked) -RemoveTheApp $removeApp

    if ($problems.Count -eq 0) {
        $header.Subtitle.Text = 'Finished'
        $done = ('{0} has been uninstalled. You can now close this window.' -f $AppName)
        if (-not $chkDelete.Checked -and (Test-Path -LiteralPath $DataDir)) {
            $done += ' Your settings were kept.'
        }
        $summaryLbl.Text = $done
    } else {
        $header.Subtitle.Text = 'Finished, with problems'
        $summaryLbl.ForeColor = $Theme.Warn
        $summaryLbl.Text = ('{0} step(s) did not complete. A log was saved to:{1}{2}' -f $problems.Count, "`r`n", $LogPath)
    }
    $btnClose.Enabled = $true
})

$btnClose.Add_Click({ $form.Close() })

[void] $form.ShowDialog()
