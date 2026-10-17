<#
    Frivo — update watcher
    ------------------------------------------------------------------
    NEW (updates): starts Frivo again after an update. Clearspace's setup
    does this itself with /relaunch=1; Frivo's cannot, because it runs as
    SYSTEM and anything it started would run as SYSTEM too, invisible, in
    the wrong account. So Frivo starts this little watcher as you, just
    before it asks for the update, and it waits:

      installing   setup is about to stop Frivo. The launcher is asked to
                   close itself (Local\FrivoLauncherQuit) so its tray icon
                   goes away cleanly instead of being killed and left
                   behind as a ghost until the taskbar repaints.
      done/failed  if setup got as far as stopping Frivo ("restart": true),
                   start it again the way Windows sign-in does: Frivo.vbs
                   -Tray, which starts the server and the tray icon.

    A failure before setup started (no network, a fingerprint mismatch)
    leaves Frivo running, so there is nothing to start and the watcher just
    leaves. So does a request the updater never picks up.

    Runs from the program folder and is replaced by the update it is
    watching — harmless, PowerShell read it before that happened.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RequestId
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Split-Path -Parent $ScriptDir
Import-Module (Join-Path $ScriptDir 'Frivo.Update.psm1') -Force

$StatusPath = [System.IO.Path]::Combine((Get-FrivoUpdateFolder), 'status.json')
$Shim       = [System.IO.Path]::Combine($InstallDir, 'Frivo.vbs')
$WatchLog   = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'Frivo-Update.log')

# Long enough for a slow download plus a dependency refresh; short enough
# that a watcher whose update vanished does not linger for the day.
$GiveUpAt   = (Get-Date).AddMinutes(50)
# The updater writes its first status within seconds of starting. Nothing
# for this long means the task never ran (or Windows is still asking for
# permission and nobody is there to answer).
$NoSignAt   = (Get-Date).AddMinutes(10)

function Write-WatchLog {
    param([string] $Message)
    try {
        Add-Content -LiteralPath $WatchLog -Encoding UTF8 -Value (
            '[{0}] {1}: {2}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $RequestId, $Message)
    } catch { }
}

function Read-Status {
    try {
        if (-not (Test-Path -LiteralPath $StatusPath -PathType Leaf)) { return $null }
        return ([System.IO.File]::ReadAllText($StatusPath) | ConvertFrom-Json)
    } catch {
        return $null   # mid-replace; the next look will find it
    }
}

function Close-Launcher {
    try {
        $quit = [System.Threading.EventWaitHandle]::OpenExisting('Local\FrivoLauncherQuit')
        [void] $quit.Set()
        $quit.Dispose()
        Write-WatchLog 'asked the launcher to close'
    } catch {
        # No launcher running, or one from before 1.4.0 that does not
        # listen. Setup stops it either way.
    }
}

function Test-FrivoRunning {
    <# NEW (restart): our own Frivo processes from this install. #>
    foreach ($name in @('pythonw', 'python', 'FrivoHost')) {
        foreach ($process in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            try {
                if ($process.Path -and $process.Path.StartsWith($InstallDir.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
                    return $true
                }
            } catch { }
        }
    }
    return $false
}

function Start-Frivo {
    # NEW (restart): setup now starts Frivo again itself. Starting a second
    # launcher on top would pop the first one's window open.
    if (Test-FrivoRunning) {
        Write-WatchLog 'Frivo is already running again; nothing to start'
        return
    }
    if (-not (Test-Path -LiteralPath $Shim -PathType Leaf)) {
        Write-WatchLog ('cannot restart: {0} is missing' -f $Shim)
        return
    }
    $root = if ($env:SystemRoot) { $env:SystemRoot } else { 'C:\Windows' }
    $wscript = $root.TrimEnd('\') + '\System32\wscript.exe'
    Start-Process -FilePath $wscript -ArgumentList ('"{0}" -Tray' -f $Shim) -WorkingDirectory $InstallDir
    Write-WatchLog 'started Frivo again'
}

Write-WatchLog 'watching'
$closed = $false
$seen = $false
while ((Get-Date) -lt $GiveUpAt) {
    Start-Sleep -Milliseconds 800
    $s = Read-Status
    if (-not $s -or [string] $s.id -ne $RequestId) {
        if (-not $seen -and (Get-Date) -gt $NoSignAt) {
            Write-WatchLog 'the updater never reported on this request; leaving'
            exit 0
        }
        continue
    }
    $seen = $true
    $state = [string] $s.state

    if ($state -eq 'installing' -and -not $closed) {
        $closed = $true
        Close-Launcher
    }
    if ($state -in @('done', 'failed')) {
        Write-WatchLog ('update finished: {0} {1}' -f $state, [string] $s.message)
        if ($s.restart -eq $true) {
            # Setup has exited by now; give Windows a moment to let go of
            # the files it replaced before the new launcher opens them.
            Start-Sleep -Seconds 2
            Start-Frivo
        }
        exit 0
    }
}
Write-WatchLog 'gave up waiting'
