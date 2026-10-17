<#
    Frivo — updater
    ------------------------------------------------------------------
    NEW (updates): what the "Frivo Updater" scheduled task runs, as SYSTEM.

    Frivo (running as you) writes %ProgramData%\Frivo\Updates\request.json
    with the version it wants, then starts this task. This script:

      1. reads the version from the request — and nothing else from it
      2. asks GitHub for Frivo's releases and finds that version itself
      3. refuses anything Select-FrivoUpdateTarget refuses (not a release,
         already installed, older than the oldest version that can update
         itself, no fingerprint to check against)
      4. downloads FrivoSetup.exe into the program folder's own updates\
         folder (Program Files permissions: nobody else can swap it)
      5. checks it against the size and SHA-256 GitHub published
      6. runs it with /VERYSILENT, which updates without a window — see
         build\Frivo.iss and Install.ps1's silent mode
      7. confirms Windows now lists the version it asked for

    Every step is reported in status.json, which the browser and the
    relaunch watcher (Update-Watch.ps1) read. "restart": true in that file
    means setup has started and has stopped Frivo, so whatever happens next,
    Frivo needs starting again.

    Can also be run elevated by hand (or by Frivo, when the task is missing
    and Windows asks for permission instead); it behaves the same.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Split-Path -Parent $ScriptDir

# Loaded once, now. Setup replaces these files while this script is still
# running; PowerShell has already read them, so that is harmless.
Import-Module (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Force
Import-Module (Join-Path $ScriptDir 'Frivo.Update.psm1') -Force

$UpdateFolder = Get-FrivoUpdateFolder
$RequestPath  = [System.IO.Path]::Combine($UpdateFolder, 'request.json')
$StatusPath   = [System.IO.Path]::Combine($UpdateFolder, 'status.json')
$UpdaterLog   = [System.IO.Path]::Combine($UpdateFolder, 'updater.log')
$Downloads    = [System.IO.Path]::Combine($InstallDir, 'updates')

$InstallerArguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL'
$DownloadLimit      = [TimeSpan]::FromMinutes(20)
$InstallLimit       = [TimeSpan]::FromMinutes(25)

function Write-UpdaterLog {
    param([string] $Message)
    try {
        Add-Content -LiteralPath $UpdaterLog -Encoding UTF8 -Value (
            '[{0}] {1}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Message)
    } catch { }
}

# One at a time, machine-wide. A second start of the task is ignored by the
# task's own settings; this also covers the elevated-by-hand route.
$createdMutex = $false
$mutex = New-Object System.Threading.Mutex($true, 'Global\FrivoUpdater', [ref] $createdMutex)
if (-not $createdMutex) {
    try {
        if (-not $mutex.WaitOne(0)) { exit 0 }
    } catch [System.Threading.AbandonedMutexException] { }
}

$requestOwner = ''   # NEW (restart)
$status = @{
    id       = ''
    state    = 'starting'
    version  = ''
    from     = ''
    kind     = ''
    message  = ''
    received = 0
    total    = 0
    restart  = $false
    started_utc = [DateTime]::UtcNow.ToString('o')
}

function Set-UpdateState {
    param([string] $State, [string] $Message = '')
    $status.state = $State
    $status.message = $Message
    try { Write-FrivoUpdateStatus -Path $StatusPath -Status $status } catch {
        Write-UpdaterLog ('could not write status: ' + $_.Exception.Message)
    }
    Write-UpdaterLog ('{0}: {1} {2}' -f $status.id, $State, $Message)
}

function Get-InstalledFrivoVersion {
    <# What Windows says is installed — the registry entry setup writes. #>
    foreach ($key in @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    )) {
        try {
            $value = [string] (Get-ItemProperty -Path $key -ErrorAction Stop).DisplayVersion
            if ($value) { return $value }
        } catch { }
    }
    return ''
}

function Get-RunningFrivoVersion {
    <# The VERSION file setup writes beside app.py. #>
    $path = Join-Path $InstallDir 'VERSION'
    try { return (Get-Content -LiteralPath $path -Raw -ErrorAction Stop).Trim() } catch { return '' }
}

function Get-Releases {
    param($Policy)
    $previous = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        # -UserAgent, not a User-Agent entry in -Headers: Windows
        # PowerShell 5.1 refuses to set that header any other way.
        $response = Invoke-WebRequest -Uri $Policy.ReleasesApi -UseBasicParsing -TimeoutSec 30 `
            -UserAgent ('Frivo-Updater/' + (Get-RunningFrivoVersion))
    } catch {
        throw ('GitHub could not be reached to look up the release: ' + $_.Exception.Message)
    } finally {
        $ProgressPreference = $previous
    }
    # .Content is a string on 5.1 and 7 alike when the response is JSON.
    return ConvertFrom-FrivoReleaseList -Json ([string] $response.Content) -Policy $Policy
}

function Save-Installer {
    <#
        Streams the installer to disk, reporting progress about four times
        a second. HttpWebRequest rather than Invoke-WebRequest, whose
        progress bar costs more than the download on Windows PowerShell and
        which cannot report how far it has got.
    #>
    param($Release, $Policy, [string] $Target)

    if (-not $Release.DownloadUrl.StartsWith($Policy.DownloadPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'The update is not from Frivo''s releases.'
    }
    $partial = $Target + '.part'
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $request = [System.Net.HttpWebRequest]::Create($Release.DownloadUrl)
    $request.UserAgent = 'Frivo-Updater/' + (Get-RunningFrivoVersion)
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 60000
    $request.AllowAutoRedirect = $true

    $response = $request.GetResponse()
    try {
        $total = if ($Release.Size -gt 0) { $Release.Size } else { [long] $response.ContentLength }
        $status.total = [long] [Math]::Max($total, 0)
        $source = $response.GetResponseStream()
        $file = [System.IO.File]::Create($partial)
        try {
            $buffer = New-Object byte[] 65536
            $done = 0L
            $lastReport = 0L
            while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $file.Write($buffer, 0, $read)
                $done += $read
                if ($clock.Elapsed -gt $DownloadLimit) { throw 'The download took too long.' }
                if ($clock.ElapsedMilliseconds - $lastReport -ge 250) {
                    $lastReport = $clock.ElapsedMilliseconds
                    $status.received = $done
                    try { Write-FrivoUpdateStatus -Path $StatusPath -Status $status } catch { }
                }
            }
            $status.received = $done
        } finally {
            $file.Dispose()
            $source.Dispose()
        }
    } finally {
        $response.Dispose()
    }
    Move-Item -LiteralPath $partial -Destination $Target -Force
}

# NEW (restart): who asked for this update. request.json is created by the
# Frivo server process, which runs as the signed-in user, so the file's owner
# is that user. It is the account Frivo has to be started again as.
function Get-RequestOwner {
    param([string] $Path)
    try { return [string] (Get-Acl -LiteralPath $Path).Owner } catch { return '' }
}

function Test-FrivoRunning {
    <# Any Frivo server or launcher running from this install. #>
    try {
        $found = @(Get-CimInstance Win32_Process `
            -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'FrivoHost.exe'" `
            -ErrorAction Stop |
            Where-Object { $_.ExecutablePath -and (Test-PathWithinDirectory -Path $_.ExecutablePath -Directory $InstallDir) })
        return $found.Count -gt 0
    } catch {
        return $false
    }
}

function Restart-FrivoIfNeeded {
    <#
        NEW (restart): the backup for Update-Watch.ps1.

        Starting Frivo again is the watcher's job, because anything this
        script starts would run as SYSTEM, invisibly, in the wrong account.
        But when the watcher did not do it, nothing did, and Frivo stayed
        stopped until someone went to that PC. So: give the watcher time,
        then look. If nothing from this install is running, start Frivo
        the way Windows sign-in does (Frivo.vbs -Tray), as the person who
        asked for the update, in their own session, through a one-off
        scheduled task. An Interactive task needs no password: it only runs
        in a session that user already has open.

        Only checks for a process, never for the port: a launcher that is
        still starting would otherwise be started a second time, and a
        second launcher opens the first one's window.
    #>
    param([string] $Owner)

    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        if (Test-FrivoRunning) {
            Write-UpdaterLog 'Frivo is running again.'
            return
        }
        Start-Sleep -Seconds 1
    }

    if (-not $Owner -or $Owner -match '^(NT AUTHORITY|BUILTIN)\\') {
        Write-UpdaterLog ('Frivo did not start again, and the request has no user to start it as ({0}).' -f $Owner)
        return
    }
    $shim = Join-Path $InstallDir 'Frivo.vbs'
    if (-not (Test-Path -LiteralPath $shim -PathType Leaf)) {
        Write-UpdaterLog ('Frivo did not start again, and {0} is missing.' -f $shim)
        return
    }

    Write-UpdaterLog ('Frivo did not start again; starting it as {0}.' -f $Owner)
    $taskName = 'Frivo Restart'
    try {
        $root = if ($env:SystemRoot) { $env:SystemRoot } else { 'C:\Windows' }
        $action = New-ScheduledTaskAction -Execute ($root.TrimEnd('\') + '\System32\wscript.exe') `
            -Argument ('"{0}" -Tray' -f $shim) -WorkingDirectory $InstallDir
        $principal = New-ScheduledTaskPrincipal -UserId $Owner -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline -and -not (Test-FrivoRunning)) { Start-Sleep -Seconds 1 }
        if (Test-FrivoRunning) {
            Write-UpdaterLog 'Started Frivo again.'
        } else {
            Write-UpdaterLog 'Asked Windows to start Frivo, but it is still not running. Is that user signed in?'
        }
    } catch {
        Write-UpdaterLog ('Could not start Frivo again: ' + $_.Exception.Message)
    } finally {
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop } catch { }
    }
}

function Clear-Downloads {
    if (-not (Test-Path -LiteralPath $Downloads)) { return }
    Get-ChildItem -LiteralPath $Downloads -Force -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -Recurse -ErrorAction SilentlyContinue }
}

try {
    $who = 'unknown'
    try { $who = [Security.Principal.WindowsIdentity]::GetCurrent().Name } catch { }
    Write-UpdaterLog ('--- updater started as {0} ---' -f $who)

    # The folder SYSTEM writes into is put right before anything is written.
    try { [void] (Initialize-FrivoUpdateFolder) } catch {
        Write-UpdaterLog ('could not secure the update folder: ' + $_.Exception.Message)
        throw 'The update folder could not be prepared.'
    }

    $request = Read-FrivoUpdateRequest -Path $RequestPath
    $requestOwner = Get-RequestOwner -Path $RequestPath   # NEW (restart)
    Write-UpdaterLog ('requested by ' + $requestOwner)
    Remove-Item -LiteralPath $RequestPath -Force -ErrorAction SilentlyContinue
    $status.id = $request.Id
    $status.version = $request.Version

    $currentText = Get-RunningFrivoVersion
    $current = ConvertTo-FrivoVersion $currentText
    if (-not $current) { throw 'The installed Frivo has no version number, so it cannot be updated from here. Run FrivoSetup.exe once.' }
    $status.from = Get-FrivoVersionText $current

    Set-UpdateState 'checking' 'Looking up the release on GitHub.'
    # Windows PowerShell 5.1 does not offer TLS 1.2 by default; GitHub
    # requires it.
    try {
        [System.Net.ServicePointManager]::SecurityProtocol =
            [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
    } catch { }

    $policy = Get-FrivoUpdatePolicy -Path (Join-Path $ScriptDir 'update-policy.json')
    $releases = Get-Releases -Policy $policy
    $target = Select-FrivoUpdateTarget -Releases $releases -Version $request.Version -Current $current `
        -Policy $policy -RequireFingerprint
    $status.kind = if ($target.Version -gt $current) { 'update' } else { 'rollback' }

    if (-not (Test-Path -LiteralPath $Downloads)) {
        New-Item -ItemType Directory -Path $Downloads -Force | Out-Null
    }
    Clear-Downloads
    $setup = Join-Path $Downloads ('FrivoSetup-{0}.exe' -f $target.VersionText)

    Set-UpdateState 'downloading' ('Downloading Frivo {0}.' -f $target.VersionText)
    try {
        Save-Installer -Release $target -Policy $policy -Target $setup
    } catch {
        throw ('The download failed: ' + $_.Exception.Message)
    }

    Set-UpdateState 'verifying' 'Checking the download against GitHub''s fingerprint.'
    try {
        [void] (Test-FrivoDownloadedFile -Path $setup -Size $target.Size -Sha256 $target.Sha256)
    } catch {
        Remove-Item -LiteralPath $setup -Force -ErrorAction SilentlyContinue
        throw
    }

    # From here on Frivo is stopped by setup, so it has to be started again
    # whatever the outcome.
    $status.restart = $true
    Set-UpdateState 'installing' ('Installing Frivo {0}. Frivo restarts when it is done.' -f $target.VersionText)

    $setupLog = Get-SetupLogPath
    Write-UpdaterLog ('setup log: ' + $setupLog)
    $logStart = 0L
    try { if (Test-Path -LiteralPath $setupLog) { $logStart = (Get-Item -LiteralPath $setupLog).Length } } catch { }

    $process = Start-Process -FilePath $setup -ArgumentList $InstallerArguments -WindowStyle Hidden -PassThru
    # Touching Handle keeps the process object able to report ExitCode
    # after it has exited — without it, Windows PowerShell returns $null.
    $null = $process.Handle
    if (-not $process.WaitForExit([int] $InstallLimit.TotalMilliseconds)) {
        try { $process.Kill() } catch { }
        throw 'Setup did not finish in time and was stopped.'
    }
    $exitCode = $process.ExitCode

    $installed = Get-InstalledFrivoVersion
    if ($exitCode -ne 0 -or (ConvertTo-FrivoVersion $installed) -ne $target.Version) {
        $reason = ''
        try {
            if (Test-Path -LiteralPath $setupLog) {
                $stream = [System.IO.File]::Open($setupLog, 'Open', 'Read', 'ReadWrite')
                try {
                    if ($logStart -le $stream.Length) { [void] $stream.Seek($logStart, 'Begin') }
                    $reader = New-Object System.IO.StreamReader($stream)
                    $reason = Get-FrivoSetupFailure -LogText $reader.ReadToEnd()
                } finally { $stream.Dispose() }
            }
        } catch { }
        if (-not $reason) {
            $reason = ('Setup stopped with code {0}, and Windows lists version {1}.' -f $exitCode,
                $(if ($installed) { $installed } else { 'none' }))
        }
        throw $reason
    }

    $verb = if ($status.kind -eq 'rollback') { 'went back to' } else { 'updated to' }
    Set-UpdateState 'done' ('Frivo {0} {1}.' -f $verb, $target.VersionText)
} catch {
    $message = $_.Exception.Message
    Write-UpdaterLog ('FAILED: ' + $message)
    Set-UpdateState 'failed' $message
} finally {
    Clear-Downloads
    # NEW (restart): setup stopped Frivo, so make sure something starts it.
    # Run as SYSTEM only: run elevated by hand, the watcher and the person
    # running it are the same account, and there is nobody else to start.
    $isSystem = $false
    try { $isSystem = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value -eq 'S-1-5-18' } catch { }
    if ($status.restart -and $isSystem) {
        try { Restart-FrivoIfNeeded -Owner $requestOwner } catch {
            Write-UpdaterLog ('restart check failed: ' + $_.Exception.Message)
        }
    }
    try { $mutex.ReleaseMutex() } catch { }
}
