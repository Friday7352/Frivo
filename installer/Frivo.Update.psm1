<#
    Frivo.Update.psm1
    ------------------------------------------------------------------
    NEW (updates): the half of in-app updating that isn't running anything.

    Frivo updates itself the way Clearspace does: it reads the releases on
    GitHub, downloads FrivoSetup.exe from the one it wants, checks the file
    against the size and SHA-256 fingerprint GitHub publishes for it, and
    runs it silently. The difference is where that happens. Clearspace
    installs per user, so it can run its own installer. Frivo lives in
    Program Files, so the installer needs administrator rights — and the
    person clicking "Update now" is usually in a browser on another
    machine, nowhere near a UAC prompt. So the work is done by the
    "Frivo Updater" scheduled task (Update-Frivo.ps1, running as SYSTEM),
    which setup registers and anyone signed in to the PC may start.

    That task trusts nothing it is handed. It is told only a version
    number; it asks GitHub itself which file that is, and installs only an
    installer from this repository's releases whose fingerprint matches.
    Everything that decides "is this a release we may install" is in here,
    and app.py makes the same decisions for what the browser offers. Both
    read installer\update-policy.json, so the repository, the asset name
    and the oldest version you can go back to are written down once.

    Pure functions, apart from the last section (folder permissions and
    the scheduled task), which is marked as Windows-only. Everything above
    it runs anywhere, which is what tests\test-update-logic.ps1 relies on.

    -- What makes going back safe --
    An older Frivo reading what a newer one wrote:
      config.json    load_config() merges the file over its defaults, so a
                     key it does not know is kept, and written back on save.
      profiles.json  a list of objects; unknown fields are carried along.
      usage.json     a dated ledger, same shape since it existed.
    oldest_rollback is 1.4.0 because that is the first release that can
    update itself: going further back would leave no way back up from
    inside Frivo. Whoever changes the shape of a data file must raise
    oldest_rollback to the release that ships the change.
#>

Set-StrictMode -Version Latest

# ------------------------------------------------------------------
# Policy
# ------------------------------------------------------------------

function ConvertTo-FrivoVersion {
    <#
        "v1.4.0", "1.4" and "V2.0.1" are versions; "nightly" is not.
        Always three parts, so 1.4 and 1.4.0 compare equal — the same rule
        as parse_version() in app.py.
    #>
    param([AllowNull()] [AllowEmptyString()] [string] $Text)

    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $match = [regex]::Match($Text.Trim(), '^[vV]?(\d{1,5})(?:\.(\d{1,5}))?(?:\.(\d{1,5}))?$')
    if (-not $match.Success) { return $null }
    $minor = if ($match.Groups[2].Success) { [int] $match.Groups[2].Value } else { 0 }
    $patch = if ($match.Groups[3].Success) { [int] $match.Groups[3].Value } else { 0 }
    return [version]::new([int] $match.Groups[1].Value, $minor, $patch)
}

function Get-FrivoVersionText {
    param([Parameter(Mandatory)] [version] $Version)
    return ('{0}.{1}.{2}' -f $Version.Major, $Version.Minor, [Math]::Max($Version.Build, 0))
}

function Get-FrivoUpdatePolicy {
    <#
        Reads update-policy.json. Throws when it is missing or does not
        look right: an updater that cannot say where updates come from must
        not guess.
    #>
    param([Parameter(Mandatory)] [string] $Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw ('The update policy is missing: {0}' -f $Path)
    }
    $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop

    $repository = [string] $raw.repository
    if ($repository -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$') {
        throw ('update-policy.json names no usable repository: "{0}"' -f $repository)
    }
    $asset = [string] $raw.asset
    if ($asset -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*\.exe$') {
        throw ('update-policy.json names no usable installer: "{0}"' -f $asset)
    }
    $oldest = ConvertTo-FrivoVersion ([string] $raw.oldest_rollback)
    if (-not $oldest) {
        throw ('update-policy.json has no usable oldest_rollback: "{0}"' -f [string] $raw.oldest_rollback)
    }

    return [pscustomobject] @{
        Repository     = $repository
        Asset          = $asset
        OldestRollback = $oldest
        ReleasesApi    = ('https://api.github.com/repos/{0}/releases?per_page=50' -f $repository)
        ReleasesPage   = ('https://github.com/{0}/releases' -f $repository)
        # Only an installer from this repository's own releases is ever
        # downloaded. Checked on the URL GitHub hands back, not assumed.
        DownloadPrefix = ('https://github.com/{0}/releases/download/' -f $repository)
    }
}

# ------------------------------------------------------------------
# Releases
# ------------------------------------------------------------------

function Get-JsonField {
    param($Object, [string] $Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}

function ConvertFrom-FrivoRelease {
    <#
        Reads one release as GitHub describes it. $null when it is not
        something Frivo can install: a draft or pre-release, a tag that is
        not a version number, or no installer from this repository.
    #>
    param(
        $Release,
        [Parameter(Mandatory)] $Policy
    )

    if ($null -eq $Release -or $Release -is [string] -or $Release -is [array]) { return $null }
    if ((Get-JsonField $Release 'draft') -eq $true) { return $null }
    if ((Get-JsonField $Release 'prerelease') -eq $true) { return $null }

    $tag = [string] (Get-JsonField $Release 'tag_name')
    $version = ConvertTo-FrivoVersion $tag
    if (-not $version) { return $null }

    foreach ($asset in @(Get-JsonField $Release 'assets')) {
        if ($null -eq $asset) { continue }
        if (-not ([string] (Get-JsonField $asset 'name')).Equals($Policy.Asset, [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $url = [string] (Get-JsonField $asset 'browser_download_url')
        if (-not $url.StartsWith($Policy.DownloadPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $null
        }

        $size = 0L
        $rawSize = Get-JsonField $asset 'size'
        if ($null -ne $rawSize) { try { $size = [long] $rawSize } catch { $size = 0L } }

        # "sha256:<64 hex digits>". Anything else is treated as absent.
        $sha256 = $null
        $digest = [string] (Get-JsonField $asset 'digest')
        $digestMatch = [regex]::Match($digest, '^sha256:([0-9a-fA-F]{64})$')
        if ($digestMatch.Success) { $sha256 = $digestMatch.Groups[1].Value.ToLowerInvariant() }

        # Opened in a browser on request, so it must be a github.com page too.
        $page = [string] (Get-JsonField $Release 'html_url')
        if (-not $page.StartsWith($Policy.ReleasesPage, [System.StringComparison]::OrdinalIgnoreCase)) {
            $page = $Policy.ReleasesPage
        }

        return [pscustomobject] @{
            Version     = $version
            VersionText = Get-FrivoVersionText $version
            Tag         = $tag
            Notes       = [string] (Get-JsonField $Release 'body')
            PageUrl     = $page
            DownloadUrl = $url
            Size        = $size
            Sha256      = $sha256
            Published   = [string] (Get-JsonField $Release 'published_at')
        }
    }
    return $null
}

function ConvertFrom-FrivoReleaseList {
    <#
        GitHub's list of releases, keeping the installable ones: newest
        first, each version once (the first GitHub lists wins).

        Takes the JSON text rather than an object. Windows PowerShell's
        ConvertFrom-Json emits a top-level array as ONE object, so
        @(... | ConvertFrom-Json) is a one-element array holding the real
        one. A foreach over the parsed value enumerates it correctly on
        both 5.1 and 7.
    #>
    param(
        [Parameter(Mandatory)] [AllowEmptyString()] [string] $Json,
        [Parameter(Mandatory)] $Policy
    )

    $found = New-Object System.Collections.ArrayList
    if ([string]::IsNullOrWhiteSpace($Json)) { return ,@() }
    $parsed = ConvertFrom-Json -InputObject $Json -ErrorAction Stop
    $seen = @{}
    foreach ($release in $parsed) {
        $info = ConvertFrom-FrivoRelease -Release $release -Policy $Policy
        if (-not $info) { continue }
        if ($seen.ContainsKey($info.VersionText)) { continue }
        $seen[$info.VersionText] = $true
        [void] $found.Add($info)
    }
    $sorted = @($found | Sort-Object -Property Version -Descending)
    return ,$sorted
}

function Select-FrivoUpdateTarget {
    <#
        Which release to install, given the version that was asked for.
        Throws with a reason the person can act on when it is not allowed:

          not a release      only versions GitHub lists as installable
          the same version   nothing to do
          too old            below oldest_rollback (see the header)

        Newer than the installed version is an update; older but not below
        the floor is going back. Both are allowed.
    #>
    param(
        [Parameter(Mandatory)] [AllowEmptyCollection()] [object[]] $Releases,
        [Parameter(Mandatory)] [string] $Version,
        [Parameter(Mandatory)] [version] $Current,
        [Parameter(Mandatory)] $Policy,
        # The task installs only what GitHub has fingerprinted. app.py may
        # still list a release without one, but the updater will not run it.
        [switch] $RequireFingerprint
    )

    $wanted = ConvertTo-FrivoVersion $Version
    if (-not $wanted) { throw ('"{0}" is not a version number.' -f $Version) }
    $wantedText = Get-FrivoVersionText $wanted

    $match = $null
    foreach ($release in $Releases) {
        if ($release.VersionText -eq $wantedText) { $match = $release; break }
    }
    if (-not $match) {
        throw ('Frivo {0} is not a release on GitHub that has {1} attached.' -f $wantedText, $Policy.Asset)
    }
    if ($wanted -eq $Current) {
        throw ('Frivo {0} is already installed.' -f $wantedText)
    }
    if ($wanted -lt $Policy.OldestRollback) {
        throw ('Frivo {0} is older than {1}, the oldest version that can update itself, so it cannot be installed from here.' -f
            $wantedText, (Get-FrivoVersionText $Policy.OldestRollback))
    }
    if ($RequireFingerprint -and -not $match.Sha256) {
        throw ('GitHub publishes no SHA-256 fingerprint for {0} in Frivo {1}, so it cannot be checked and will not be installed.' -f
            $Policy.Asset, $wantedText)
    }
    return $match
}

# ------------------------------------------------------------------
# Downloads
# ------------------------------------------------------------------

function Get-FrivoFileSha256 {
    param([Parameter(Mandatory)] [string] $Path)
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([System.BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
        } finally { $sha.Dispose() }
    } finally { $stream.Dispose() }
}

function Test-FrivoDownloadedFile {
    <#
        The downloaded installer must be exactly what GitHub published.
        Throws (and the caller deletes the file) when it is not.
    #>
    param(
        [Parameter(Mandatory)] [string] $Path,
        [long] $Size,
        [AllowNull()] [AllowEmptyString()] [string] $Sha256
    )

    $actualSize = (Get-Item -LiteralPath $Path -ErrorAction Stop).Length
    if ($Size -gt 0 -and $actualSize -lt $Size) {
        throw ('The download was cut short ({0:N0} of {1:N0} bytes). Try again.' -f $actualSize, $Size)
    }
    if ($Size -gt 0 -and $actualSize -ne $Size) {
        throw 'The downloaded installer does not match the one published on GitHub, so it was deleted.'
    }
    if ([string]::IsNullOrWhiteSpace($Sha256)) {
        throw 'There is no published fingerprint to check the download against.'
    }
    $actual = Get-FrivoFileSha256 -Path $Path
    if ($actual -ne $Sha256.ToLowerInvariant()) {
        throw 'The downloaded installer does not match the one published on GitHub, so it was deleted.'
    }
    return $true
}

# ------------------------------------------------------------------
# The request and the status
# ------------------------------------------------------------------
# Both live in %ProgramData%\Frivo\Updates. The app (running as you) writes
# request.json; the task (running as SYSTEM) reads it, then reports progress
# in status.json, which the app and the relaunch watcher read.

function Get-FrivoUpdateFolder {
    param([string] $ProgramData)
    if ([string]::IsNullOrWhiteSpace($ProgramData)) { $ProgramData = $env:ProgramData }
    if ([string]::IsNullOrWhiteSpace($ProgramData)) { $ProgramData = 'C:\ProgramData' }
    return [System.IO.Path]::Combine($ProgramData, 'Frivo', 'Updates')
}

function Read-FrivoUpdateRequest {
    <#
        Reads what the app asked for. Only two fields are believed, and
        both are checked for shape: the request id (echoed back so the
        browser knows the status is about its own request) and the version
        (looked up on GitHub, never used as a path or URL).
    #>
    param([Parameter(Mandatory)] [string] $Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'No update was requested.' }
    $info = Get-Item -LiteralPath $Path -Force
    if ($info.Length -gt 4096) { throw 'The update request is not valid.' }
    try {
        $raw = [System.IO.File]::ReadAllText($Path) | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw 'The update request is not valid.'
    }
    $id = [string] (Get-JsonField $raw 'id')
    if ($id -notmatch '^[A-Za-z0-9-]{8,64}$') { throw 'The update request is not valid.' }
    $version = ConvertTo-FrivoVersion ([string] (Get-JsonField $raw 'version'))
    if (-not $version) { throw 'The update request names no version.' }
    return [pscustomobject] @{ Id = $id; Version = (Get-FrivoVersionText $version) }
}

function Write-FrivoUpdateStatus {
    <#
        Replaces status.json in one step: written to a new file beside it,
        then moved over the old one. A reader never sees half a file, and
        the result is always a file this process created.
    #>
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [hashtable] $Status
    )

    $Status['updated_utc'] = [DateTime]::UtcNow.ToString('o')
    $json = $Status | ConvertTo-Json -Depth 4
    $folder = Split-Path -Parent $Path
    $temp = Join-Path $folder ('.status-{0}.tmp' -f [guid]::NewGuid().ToString('N'))
    [System.IO.File]::WriteAllText($temp, $json, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Get-FrivoSetupFailure {
    <#
        The reason setup gave, from the part of its log written during this
        update. Install.ps1 logs "FAILED: <message>" before it gives up.
    #>
    param([AllowNull()] [AllowEmptyString()] [string] $LogText)

    if ([string]::IsNullOrWhiteSpace($LogText)) { return '' }
    $last = ''
    foreach ($line in ($LogText -split "`r?`n")) {
        $m = [regex]::Match($line, 'FAILED:\s*(.+)$')
        if ($m.Success) { $last = $m.Groups[1].Value.Trim() }
    }
    return $last
}

# ==================================================================
# Windows only: the folder's permissions and the scheduled task
# ==================================================================
# Everything above runs anywhere. These two need Windows, and live here so
# that setup, the updater itself and the uninstaller share one copy.

$script:UpdaterTaskName = 'Frivo Updater'

function Get-FrivoUpdaterTaskName { return $script:UpdaterTaskName }

function Initialize-FrivoUpdateFolder {
    <#
        Creates %ProgramData%\Frivo\Updates and sets exactly who may do
        what in it, every time, rather than trusting what is there:

          SYSTEM, Administrators   everything
          Users                    read; create files in Updates (request.json)
          whoever created a file   that file (CREATOR OWNER)

        Users may create files but not folders, so nobody can plant a link
        there. A folder that is itself a link — someone created
        ProgramData\Frivo before setup did and pointed it elsewhere — is
        removed and made again, because SYSTEM writes into it.
    #>
    param([string] $ProgramData)

    $updates = Get-FrivoUpdateFolder -ProgramData $ProgramData
    $parent  = Split-Path -Parent $updates

    $system   = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $admins   = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $users    = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-545')
    $creator  = New-Object System.Security.Principal.SecurityIdentifier('S-1-3-0')
    $both     = [System.Security.AccessControl.InheritanceFlags] 'ContainerInherit, ObjectInherit'
    $none     = [System.Security.AccessControl.InheritanceFlags]::None
    $noProp   = [System.Security.AccessControl.PropagationFlags]::None
    $inhOnly  = [System.Security.AccessControl.PropagationFlags]::InheritOnly
    $allow    = [System.Security.AccessControl.AccessControlType]::Allow
    $full     = [System.Security.AccessControl.FileSystemRights]::FullControl
    $read     = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
    $create   = [System.Security.AccessControl.FileSystemRights]::CreateFiles

    foreach ($dir in @($parent, $updates)) {
        if (Test-Path -LiteralPath $dir) {
            $item = Get-Item -LiteralPath $dir -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                # Removes the link, never what it points at.
                [System.IO.Directory]::Delete($dir)
            }
        }
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }

        $acl = New-Object System.Security.AccessControl.DirectorySecurity
        $acl.SetOwner($admins)
        $acl.SetAccessRuleProtection($true, $false)
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($system, $full, $both, $noProp, $allow)))
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($admins, $full, $both, $noProp, $allow)))
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($users, $read, $both, $noProp, $allow)))
        if ($dir -eq $updates) {
            $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($users, $create, $none, $noProp, $allow)))
            $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($creator, $full, $both, $inhOnly, $allow)))
        }
        (Get-Item -LiteralPath $dir -Force).SetAccessControl($acl)
    }
    return $updates
}

function Get-FrivoUpdaterTaskAction {
    param([Parameter(Mandatory)] [string] $InstallDir)
    $root = if ($env:SystemRoot) { $env:SystemRoot } else { 'C:\Windows' }
    return [pscustomobject] @{
        Path      = ($root.TrimEnd('\') + '\System32\WindowsPowerShell\v1.0\powershell.exe')
        Arguments = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f
                     ($InstallDir.TrimEnd('\', '/') + '\installer\Update-Frivo.ps1'))
    }
}

function Register-FrivoUpdaterTask {
    <#
        The "Frivo Updater" task: no schedule, runs only when started,
        as SYSTEM. Its security descriptor lets any signed-in user start
        it (GRGX for Authenticated Users) — that is the whole point, Frivo
        runs as you — while only administrators can change it.

        Left alone when it already says the right thing. The updater runs
        setup from inside this task, and setup calls this: rewriting the
        definition of the task that is running it is a risk with no gain.

        Returns 'registered' or 'unchanged'.
    #>
    param([Parameter(Mandatory)] [string] $InstallDir)

    $action = Get-FrivoUpdaterTaskAction -InstallDir $InstallDir
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $root = $service.GetFolder('\')

    $existing = $null
    try { $existing = $root.GetTask($script:UpdaterTaskName) } catch { $existing = $null }
    if ($existing) {
        try {
            $current = $null
            foreach ($a in $existing.Definition.Actions) { $current = $a; break }
            $sd = [string] $existing.GetSecurityDescriptor(4)   # DACL only
            $principal = [string] $existing.Definition.Principal.UserId
            if ($current -and
                [string] $current.Path -eq $action.Path -and
                [string] $current.Arguments -eq $action.Arguments -and
                $principal -match '(?i)SYSTEM|S-1-5-18' -and
                $sd -match '\(A;;GRGX;;;AU\)') {
                return 'unchanged'
            }
        } catch { }
    }

    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Author = 'Frivo setup'
    $definition.RegistrationInfo.Description =
        'Installs a Frivo update when Frivo asks for one. Only installs FrivoSetup.exe from the GitHub releases named in update-policy.json, after checking its SHA-256 fingerprint.'
    $definition.Principal.UserId = 'S-1-5-18'
    $definition.Principal.LogonType = 5         # TASK_LOGON_SERVICE_ACCOUNT
    $definition.Principal.RunLevel = 1          # TASK_RUNLEVEL_HIGHEST
    $definition.Settings.Enabled = $true
    $definition.Settings.AllowDemandStart = $true
    $definition.Settings.StartWhenAvailable = $false
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.ExecutionTimeLimit = 'PT1H'
    $definition.Settings.MultipleInstances = 2  # TASK_INSTANCES_IGNORE_NEW
    $definition.Settings.Hidden = $false

    $exec = $definition.Actions.Create(0)       # TASK_ACTION_EXEC
    $exec.Path = $action.Path
    $exec.Arguments = $action.Arguments
    $exec.WorkingDirectory = ($InstallDir.TrimEnd('\', '/') + '\installer')

    $sddl = 'D:(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;AU)'
    # 6 = TASK_CREATE_OR_UPDATE
    [void] $root.RegisterTaskDefinition($script:UpdaterTaskName, $definition, 6, 'SYSTEM', $null, 5, $sddl)
    return 'registered'
}

function Unregister-FrivoUpdaterTask {
    <#
        Removes the task — only when it belongs to this install. Returns
        $true when something was removed.
    #>
    param([Parameter(Mandatory)] [string] $InstallDir)

    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $root = $service.GetFolder('\')
    try { $task = $root.GetTask($script:UpdaterTaskName) } catch { return $false }
    $expected = (Get-FrivoUpdaterTaskAction -InstallDir $InstallDir).Arguments
    foreach ($a in $task.Definition.Actions) {
        if ([string] $a.Arguments -ne $expected) { return $false }
    }
    $root.DeleteTask($script:UpdaterTaskName, 0)
    return $true
}

Export-ModuleMember -Function `
    ConvertTo-FrivoVersion, Get-FrivoVersionText, Get-FrivoUpdatePolicy,
    ConvertFrom-FrivoRelease, ConvertFrom-FrivoReleaseList, Select-FrivoUpdateTarget,
    Get-FrivoFileSha256, Test-FrivoDownloadedFile,
    Get-FrivoUpdateFolder, Read-FrivoUpdateRequest, Write-FrivoUpdateStatus, Get-FrivoSetupFailure,
    Get-FrivoUpdaterTaskName, Initialize-FrivoUpdateFolder, Get-FrivoUpdaterTaskAction,
    Register-FrivoUpdaterTask, Unregister-FrivoUpdaterTask
