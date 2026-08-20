<#
    Frivo.Setup.psm1
    ------------------------------------------------------------------
    Everything the installer does that isn't drawing a window.

    Kept apart from Install.ps1 on purpose: the wizard needs Windows to
    run at all, but this half is ordinary file and string work, so it can
    be imported and tested anywhere. Nothing in here touches WinForms.
#>

Set-StrictMode -Version Latest

# ------------------------------------------------------------------
# Python discovery
# ------------------------------------------------------------------

function Get-PythonVersionFromOutput {
    <#
        Turns "Python 3.12.1" into a [version]. Returns $null for anything
        that isn't a version line, which is what a missing interpreter, a
        Microsoft Store stub, or an error message all look like.
    #>
    param([string] $Output)

    if ([string]::IsNullOrWhiteSpace($Output)) { return $null }
    $match = [regex]::Match($Output, 'Python\s+(\d+)\.(\d+)(?:\.(\d+))?')
    if (-not $match.Success) { return $null }

    $major = [int] $match.Groups[1].Value
    $minor = [int] $match.Groups[2].Value
    $patch = if ($match.Groups[3].Success) { [int] $match.Groups[3].Value } else { 0 }
    return [version]::new($major, $minor, $patch)
}

function Test-PythonVersionOk {
    <#
        3.9 is the floor. Below that the standard library calls this app
        makes are missing, and 3.13 is the newest it has been run on.
    #>
    param([version] $Version)

    if ($null -eq $Version) { return $false }
    if ($Version.Major -ne 3) { return $false }
    return $Version.Minor -ge 9
}

function Get-PythonCandidates {
    <#
        In preference order. The launcher (py.exe) comes first because it
        finds real installs even when PATH points at the Store stub, which
        exits silently and installs nothing.
    #>
    return @(
        @{ Command = 'py';     Arguments = @('-3', '--version') }
        @{ Command = 'python'; Arguments = @('--version') }
        @{ Command = 'python3'; Arguments = @('--version') }
    )
}

# ------------------------------------------------------------------
# Data files
# ------------------------------------------------------------------

function New-FrivoDataFiles {
    <#
        Writes the three files the app keeps its state in. Existing files
        are never overwritten — reinstalling over the top must not cost
        someone their API keys or their profiles.

        Returns the list of paths actually created.
    #>
    param(
        [Parameter(Mandatory)] [string] $Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }

    # Keep the installed configuration aligned with app.py defaults.
    $config = [ordered] @{
        openai_api_key             = ''
        elevenlabs_api_key         = ''
        voice_id                   = '21m00Tcm4TlvDq8ikWAM'
        voice_name                 = 'Rachel'
        model                      = 'gpt-4o-mini'
        translation_model          = 'gpt-4.1-nano'
        system_prompt              = ''
        response_style             = 'flair'
        personality_preset         = 'neutral'
        max_words                  = 80
        language                   = 'English'
        speaking_speed             = 1.0
        temperature                = 0.7
        max_tokens                 = 0
        chat_provider              = 'openai'
        translation_provider       = 'openai'
        transcription_provider     = 'openai'
        ollama_url                 = 'http://127.0.0.1:11434'
        ollama_model               = 'llama3.1:8b'
        ollama_translation_model   = ''
        whisper_url                = 'http://127.0.0.1:9000'
        whisper_start_command      = ''
        allow_openai_fallback      = $false
        osc_host                   = ''
        osc_port                   = 9000
        osc_page_seconds_speaking  = 1.6
        osc_page_seconds_silent    = 4.0
        osc_sfx                    = $true
    }

    $created = @()
    $files = @{
        'config.json'   = ($config | ConvertTo-Json -Depth 4)
        'profiles.json' = '[]'
        'usage.json'    = '{}'
    }

    foreach ($name in $files.Keys) {
        $target = [System.IO.Path]::Combine($Path, $name)
        if (Test-Path -LiteralPath $target) { continue }
        # UTF-8 without a BOM: Python's json module chokes on a BOM, and
        # PowerShell 5.1 adds one unless told otherwise.
        $encoding = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($target, $files[$name], $encoding)
        $created += $target
    }

    return $created
}

# ------------------------------------------------------------------
# Launchers
# ------------------------------------------------------------------

function Get-LauncherScript {
    <#
        The .cmd that actually starts the app.

        -Hidden picks pythonw.exe, which has no console window — right for
        the startup task, wrong for the shortcut, where seeing the URL and
        any error it prints is most of the value.
    #>
    param(
        [switch] $Hidden
    )

    $exe = if ($Hidden) { 'pythonw.exe' } else { 'python.exe' }
    $lines = @(
        '@echo off'
        'rem Generated by the Frivo installer.'
        'rem Runs the app from its own private virtual environment, so it'
        'rem cannot be broken by anything else installed on this machine.'
        'cd /d "%~dp0"'
        ('".venv\Scripts\' + $exe + '" "app.py" %*')
    )
    if (-not $Hidden) {
        $lines += 'if errorlevel 1 pause'
    }
    return ($lines -join "`r`n") + "`r`n"
}

function Get-UninstallCommand {
    param([Parameter(Mandatory)] [string] $InstallPath)
    # Apps & features requires a quoted Windows command path.
    return ('"{0}\Uninstall.cmd"' -f $InstallPath.TrimEnd('\', '/'))
}

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------

# A marker is written before any application files are copied.  It makes
# cleanup prove that a directory belongs to Frivo instead of treating an
# arbitrary folder selected in the destination picker as disposable.
$script:InstallMarkerName = '.frivo-install.json'
$script:InstallMarkerId   = 'com.frivo.desktop'

function Get-FrivoInstallMarkerPath {
    param([Parameter(Mandatory)] [string] $Path)
    return (Join-Path $Path $script:InstallMarkerName)
}

function Test-PathWithinDirectory {
    <# True only when Path is inside Directory, not merely a text prefix. #>
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $Directory
    )
    try {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
        $fullDir  = [System.IO.Path]::GetFullPath($Directory).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
        return $fullPath.StartsWith($fullDir, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Test-FrivoInstallOwnership {
    param([Parameter(Mandatory)] [string] $Path)

    try {
        $markerPath = Get-FrivoInstallMarkerPath $Path
        if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { return $false }
        $marker = Get-Content -LiteralPath $markerPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ([string] $marker.Id -ne $script:InstallMarkerId) { return $false }
        $actual = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
        $recorded = [System.IO.Path]::GetFullPath([string] $marker.InstallPath).TrimEnd('\', '/')
        return $actual.Equals($recorded, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Test-FrivoRecoverableResidue {
    <#
        Recognizes the icon-only folder left by the pre-1.1.0 uninstaller.
        Restrict recovery to the default Frivo location to avoid cleaning an
        unrelated non-empty folder.
    #>
    param([Parameter(Mandatory)] [string] $Path)

    try {
        $actual = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
        $default = [System.IO.Path]::GetFullPath((Get-DefaultInstallPath)).TrimEnd('\', '/')
        if (-not $actual.Equals($default, [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
        if (-not (Test-Path -LiteralPath $actual -PathType Container)) { return $false }
        $files = @(Get-ChildItem -LiteralPath $actual -File -Recurse -Force -ErrorAction Stop)
        if ($files.Count -eq 0) { return $false }
        foreach ($file in $files) {
            $relative = $file.FullName.Substring($actual.Length).TrimStart('\', '/')
            if ($relative -notin @('static\icon.png', 'static\Frivo.ico')) { return $false }
        }
        $dirs = @(Get-ChildItem -LiteralPath $actual -Directory -Recurse -Force -ErrorAction Stop)
        return $dirs.Count -eq 1 -and $dirs[0].Name -eq 'static'
    } catch {
        return $false
    }
}

function Write-FrivoInstallMarker {
    param([Parameter(Mandatory)] [string] $Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $marker = [ordered] @{
        Id          = $script:InstallMarkerId
        InstallPath = $fullPath
        CreatedUtc  = [DateTime]::UtcNow.ToString('o')
    }
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText((Get-FrivoInstallMarkerPath $fullPath), ($marker | ConvertTo-Json), $encoding)
}

function Test-OtherFrivoInstall {
    <# True when another registered Frivo install still uses machine-wide resources. #>
    param([Parameter(Mandatory)] [string] $InstallPath)

    try { $current = [System.IO.Path]::GetFullPath($InstallPath).TrimEnd('\', '/') } catch { return $false }
    foreach ($key in @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Frivo',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo',
        'HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Frivo'
    )) {
        try {
            if (-not (Test-Path $key)) { continue }
            $other = [string] (Get-ItemProperty -Path $key -ErrorAction Stop).InstallLocation
            if ($other -and -not [System.IO.Path]::GetFullPath($other).TrimEnd('\', '/').Equals($current, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        } catch { }
    }
    return $false
}

function Get-DefaultInstallPath {
    <#
        Program Files, like any other installed Windows application.

        The app itself never writes here: settings, profiles, the usage
        ledger, the certificate and the audio cache all go to
        %APPDATA%\Frivo instead. That split is what makes a
        Program Files install work at all without the app needing admin
        every time it runs.
    #>
    param([string] $Root)

    if ([string]::IsNullOrWhiteSpace($Root)) {
        $Root = [Environment]::GetFolderPath('ProgramFiles')
    }
    if ([string]::IsNullOrWhiteSpace($Root)) { $Root = 'C:\Program Files' }
    return ($Root.TrimEnd('\', '/') + '\Frivo')
}

function Get-DataPath {
    <#
        Where the app keeps everything it writes. Must agree with
        _resolve_data_dir() in app.py — if these two disagree, the
        uninstaller offers to delete settings that aren't there.
    #>
    param([string] $Root)

    if ([string]::IsNullOrWhiteSpace($Root)) {
        $Root = [Environment]::GetFolderPath('ApplicationData')
    }
    if ([string]::IsNullOrWhiteSpace($Root)) { $Root = $HOME }
    return ($Root.TrimEnd('\', '/') + '\Frivo')
}

function Test-IsAdministrator {
    <#
        Program Files, HKLM, and firewall changes require elevation.
    #>
    if ($env:OS -ne 'Windows_NT') { return $false }
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-InstallPathUsable {
    <#
        Validates that the destination is a usable folder on an available drive.
    #>
    param(
        [string] $Path,
        # Permits a pre-marker install only when the caller has already
        # identified it as this application's registered legacy install.
        [switch] $AllowKnownExistingInstall
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return @{ Ok = $false; Reason = 'Choose a folder to install into.' }
    }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return @{ Ok = $false; Reason = 'That path is a file, not a folder.' }
    }
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
    } catch {
        return @{ Ok = $false; Reason = 'That does not look like a valid path.' }
    }
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($root -and -not (Test-Path -LiteralPath $root)) {
        return @{ Ok = $false; Reason = ('Drive {0} is not available.' -f $root) }
    }

    if (-not $root -or $full.TrimEnd('\', '/').Equals($root.TrimEnd('\', '/'), [System.StringComparison]::OrdinalIgnoreCase)) {
        return @{ Ok = $false; Reason = 'Choose a dedicated folder for Frivo, not the root of a drive.' }
    }

    if (Test-Path -LiteralPath $full) {
        try {
            $hasContents = $null -ne (Get-ChildItem -LiteralPath $full -Force -ErrorAction Stop | Select-Object -First 1)
        } catch {
            return @{ Ok = $false; Reason = 'Setup cannot inspect that destination folder.' }
        }
        if ($hasContents -and -not $AllowKnownExistingInstall -and -not (Test-FrivoInstallOwnership $full) -and -not (Test-FrivoRecoverableResidue $full)) {
            return @{ Ok = $false; Reason = 'Choose a new empty folder. Setup will only update a folder it previously created.' }
        }
    }
    return @{ Ok = $true; Reason = ''; Path = $full }
}

function Get-UninstallLauncher {
    <#
        Creates the command used by Apps & features to start the uninstaller.
    #>
    # Do not use the install folder as the working directory: it is removed
    # during uninstall. The VBScript shim suppresses a console window; -STA
    # is required by the uninstaller's dialogs.
    $q = [char]34
    $lines = @(
        '@echo off'
        'rem Uninstalls Frivo. Generated by the installer.'
        'setlocal'
        'set "FRIVO_UNINST=%~dp0installer\Uninstall.ps1"'
        'cd /d "%SystemRoot%"'
        'set "SHIM=%TEMP%\frivo-uninstall.vbs"'
        ('> "%SHIM%" echo Set s = CreateObject(' + $q + 'WScript.Shell' + $q + ')')
        ('>>"%SHIM%" echo s.Run ' + $q + 'powershell -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File ' + $q + $q + '%FRIVO_UNINST%' + $q + $q + $q + ', 0, False')
        'cscript //nologo "%SHIM%" >nul 2>&1'
        'del "%SHIM%" >nul 2>&1'
        'endlocal'
    )
    return ($lines -join "`r`n") + "`r`n"
}


# ==================================================================
# Shared runtime setup
# ==================================================================
# Used by both the wizard and any other front end (a compiled
# installer, or an unattended run). None of it draws a window.

# Use the system temp path so logging does not depend on an environment variable.
$script:SetupLogPath = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'Frivo-Setup.log')

function Write-SetupLog {
    <#
        Everything goes to a file as well as the window. When setup fails
        on someone else's machine, this file is the only evidence.
    #>
    param([string] $Message)
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    try {
        Add-Content -LiteralPath $script:SetupLogPath -Value ('[{0}] {1}' -f $stamp, $Message) -Encoding UTF8
    } catch { }
}


function ConvertTo-ArgumentString {
    <#
        Quotes an argument list the way Windows expects.

        Start-Process -ArgumentList joins an array with single spaces and
        quotes nothing. Any argument containing a space is therefore split
        into several by the receiving program. That is not theoretical:
        "py -3 -m venv C:\Program Files\Frivo\.venv" was read by
        Python as three separate directories, so it created three venvs in
        the wrong places and exited 0, and setup then failed with no
        explanation because nothing had actually gone wrong from Python's
        point of view.

        Backslashes immediately before a quote must be doubled, per the
        rules CommandLineToArgvW uses to parse the string back.
    #>
    param([string[]] $Arguments)

    # $null -eq, not -not: a single-element array unwraps to its element,
    # so @('') is falsy and would return early instead of quoting.
    if ($null -eq $Arguments -or $Arguments.Count -eq 0) { return '' }

    $parts = foreach ($arg in $Arguments) {
        $text = [string] $arg
        if ($text -eq '') {
            '""'
        } elseif ($text -match '[\s"]') {
            # Double any run of backslashes that precedes a quote, escape
            # the quotes, then double a trailing run before the closing one.
            $escaped = [regex]::Replace($text, '(\\*)"', '$1$1\"')
            $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
            '"' + $escaped + '"'
        } else {
            $text
        }
    }
    return ($parts -join ' ')
}

function Invoke-Tool {
    <#
        Runs a program hidden, waits, and returns its exit code and output.

        Uses Start-Process to hide the child window and capture output.
    #>
    param(
        [Parameter(Mandatory)] [string]   $FilePath,
        [string[]] $Arguments = @(),
        [string]   $WorkingDirectory
    )

    if (-not (Test-Path -LiteralPath $FilePath)) {
        # Not necessarily fatal: it may be on PATH rather than a full path.
        $resolved = Get-Command $FilePath -ErrorAction SilentlyContinue
        if (-not $resolved) {
            throw ("Required program not found: {0}" -f $FilePath)
        }
    }

    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $params = @{
            FilePath               = $FilePath
            Wait                   = $true
            PassThru               = $true
            RedirectStandardOutput = $outFile
            RedirectStandardError  = $errFile
        }
        # WindowStyle is only supported on Windows.
        if ($env:OS -eq 'Windows_NT') { $params['WindowStyle'] = 'Hidden' }
        # One pre-quoted string, not the array: see ConvertTo-ArgumentString.
        $argString = ConvertTo-ArgumentString $Arguments
        if ($argString) { $params['ArgumentList'] = $argString }
        if ($WorkingDirectory)                { $params['WorkingDirectory'] = $WorkingDirectory }

        $proc = Start-Process @params
        $stdout = ''
        $stderr = ''
        if (Test-Path $outFile) { $stdout = (Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue) }
        if (Test-Path $errFile) { $stderr = (Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue) }

        Write-SetupLog ('RUN {0} {1}' -f $FilePath, $argString)
        Write-SetupLog ('    exit={0}' -f $proc.ExitCode)
        if ($stdout) { Write-SetupLog ('    out: ' + $stdout.Trim()) }
        if ($stderr) { Write-SetupLog ('    err: ' + $stderr.Trim()) }

        return [pscustomobject] @{
            ExitCode = $proc.ExitCode
            StdOut   = [string] $stdout
            StdErr   = [string] $stderr
        }
    } catch {
        throw ("Could not run {0}`r`n{1}" -f $FilePath, $_.Exception.Message)
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-LastLines {
    <#
        The tail of a tool's output, for putting a real reason in front of
        the user instead of a generic failure.
    #>
    param([string] $Text, [int] $Count = 6)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $lines = $Text -split "`r?`n" | Where-Object { $_.Trim() }
    if ($lines.Count -le $Count) { return ($lines -join "`r`n") }
    return (($lines | Select-Object -Last $Count) -join "`r`n")
}


function Find-Python {
    foreach ($candidate in Get-PythonCandidates) {
        $exe = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        try {
            $result = Invoke-Tool -FilePath $exe.Source -Arguments $candidate.Arguments
        } catch {
            continue
        }
        $version = Get-PythonVersionFromOutput (($result.StdOut + ' ' + $result.StdErr))
        if (Test-PythonVersionOk $version) {
            return [pscustomobject] @{
                Path      = $exe.Source
                Arguments = @($candidate.Arguments | Where-Object { $_ -ne '--version' })
                Version   = $version
            }
        }
    }
    return $null
}

function Install-Python {
    param([scriptblock] $Log)

    & $Log 'Python was not found. Installing Python 3.12...'

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & $Log 'Downloading Python via Windows Package Manager...'
        try {
            $r = Invoke-Tool -FilePath $winget.Source -Arguments @(
                'install', '--id', 'Python.Python.3.12',
                '--source', 'winget', '--silent',
                '--accept-package-agreements', '--accept-source-agreements',
                '--scope', 'machine'
            )
            if ($r.ExitCode -eq 0) {
                Update-PathFromRegistry
                return
            }
            Write-SetupLog ('winget exit {0}; using direct download' -f $r.ExitCode)
        } catch {
            Write-SetupLog ('winget failed: {0}' -f $_.Exception.Message)
        }
        & $Log 'Package manager unavailable. Downloading from python.org...'
    } else {
        & $Log 'Downloading Python from python.org...'
    }

    $url = 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe'
    $exe = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'python-3.12.8-amd64.exe')
    try {
        $previous = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
        $ProgressPreference = $previous
    } catch {
        throw ("Could not download Python.`r`n{0}`r`n`r`nCheck the internet connection, or install Python 3.12 manually and run setup again." -f $_.Exception.Message)
    }

    & $Log 'Installing Python...'
    $r = Invoke-Tool -FilePath $exe -Arguments @(
        '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0'
    )
    Remove-Item -LiteralPath $exe -Force -ErrorAction SilentlyContinue
    if ($r.ExitCode -ne 0) {
        throw ('The Python installer reported error {0}. Setup cannot continue.' -f $r.ExitCode)
    }
    Update-PathFromRegistry
}

function Update-PathFromRegistry {
    # A newly installed program's PATH entry does not reach a process that
    # was already running, so it is read back from the registry by hand.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}


function Sync-VenvDependencies {
    <# Installs the packages required by the app into an existing venv. #>
    param([string] $VenvPython, [string] $Target, [scriptblock] $Log)

    # A venv can legitimately come up without pip — some Python builds ship
    # no ensurepip, and pip is what everything after this depends on.
    $pipCheck = Invoke-Tool -FilePath $VenvPython -Arguments @('-m', 'pip', '--version')
    if ($pipCheck.ExitCode -ne 0) {
        & $Log 'Bootstrapping the package installer...'
        $boot = Invoke-Tool -FilePath $VenvPython -Arguments @('-m', 'ensurepip', '--upgrade', '--default-pip')
        if ($boot.ExitCode -ne 0) {
            throw ("The Python environment has no package installer and it could not be repaired.`r`n`r`n{0}" -f (Get-LastLines $boot.StdErr))
        }
    }

    & $Log 'Installing dependencies. This may take a few minutes...'
    $req = Join-Path $Target 'requirements.txt'
    $r = Invoke-Tool -FilePath $VenvPython -Arguments @(
        '-m', 'pip', 'install', '--no-input', '--disable-pip-version-check', '-r', $req
    )
    if ($r.ExitCode -ne 0) {
        $detail = Get-LastLines ($r.StdErr + "`r`n" + $r.StdOut) 8
        throw ("Installing the Python dependencies failed.`r`n`r`n{0}" -f $detail)
    }
}

function New-Venv {
    param([string] $Target, $Python, [scriptblock] $Log)

    $venv       = Join-Path $Target '.venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'

    & $Log 'Creating isolated Python environment...'
    $venvArgs = @($Python.Arguments) + @('-m', 'venv', $venv)
    $r = Invoke-Tool -FilePath $Python.Path -Arguments $venvArgs
    if ($r.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        $detail = Get-LastLines ($r.StdErr + "`r`n" + $r.StdOut)
        if (-not $detail) {
            # Exit code 0 with nothing at the expected path means the tool
            # believed it succeeded, so say what was expected and missing
            # rather than repeating that something went wrong.
            $detail = ("Python reported success but no interpreter was created at:`r`n{0}" -f $venvPython)
        }
        throw ("Could not create the Python environment.`r`n`r`n{0}" -f $detail)
    }

    Sync-VenvDependencies -VenvPython $venvPython -Target $Target -Log $Log

    return $venvPython
}


# ------------------------------------------------------------------
# Local address (frivo.local) and certificate trust
# ------------------------------------------------------------------

# Must agree with LOCAL_HOSTNAME / CERT_HOSTNAMES in app.py — the hosts
# entry written here is only useful if the server certificate carries the
# same name.
$script:LocalHostname = 'frivo.local'

function Get-LocalHostname { return $script:LocalHostname }

function Get-HostsFilePath {
    if ($env:OS -eq 'Windows_NT') {
        $root = if ($env:SystemRoot) { $env:SystemRoot } else { 'C:\Windows' }
        return ($root.TrimEnd('\') + '\System32\drivers\etc\hosts')
    }
    # Only reached by the test suite; the installer itself is Windows-only.
    return '/etc/hosts'
}

function Add-FrivoHostsEntry {
    <#
        Points frivo.local at this machine, so the friendly address works
        in a browser on the PC Frivo is installed on. Hosts files are
        per-machine, which is exactly why other devices on the network
        still need the IP address instead.

        Idempotent: an existing frivo.local line, whoever wrote it, is
        left alone. Returns $true when a line was added.
    #>
    param([string] $HostsPath)

    if (-not $HostsPath) { $HostsPath = Get-HostsFilePath }
    $existing = @()
    if (Test-Path -LiteralPath $HostsPath) {
        $existing = @([System.IO.File]::ReadAllLines($HostsPath))
    }
    foreach ($line in $existing) {
        # An uncommented line that already maps the name, whatever the IP.
        if ($line -match ('(?i)^\s*[0-9a-fA-F:\.]+\s+.*\b' + [regex]::Escape($script:LocalHostname) + '\b')) {
            return $false
        }
    }
    $entry = "127.0.0.1`t{0}`t# Frivo - added by setup, removed on uninstall" -f $script:LocalHostname
    # Preserve the file exactly and append; hosts files are fussy about
    # encodings, and plain ASCII lines with CRLF endings are the one safe
    # form on Windows.
    $updated = $existing + @($entry)
    [System.IO.File]::WriteAllLines($HostsPath, $updated)
    return $true
}

function Remove-FrivoHostsEntry {
    <#
    Removes only the exact, tagged line added by Frivo. An existing
    frivo.local mapping is intentionally left alone: setup did not create
    it, so uninstall must not remove it.
    #>
    param([string] $HostsPath)

    if (-not $HostsPath) { $HostsPath = Get-HostsFilePath }
    if (-not (Test-Path -LiteralPath $HostsPath)) { return $false }
    $existing = @([System.IO.File]::ReadAllLines($HostsPath))
    $tag = '# Frivo - added by setup, removed on uninstall'
    $kept = @($existing | Where-Object { $_ -notmatch ('(?i)^\s*127\.0\.0\.1\s+' + [regex]::Escape($script:LocalHostname) + '\s+' + [regex]::Escape($tag) + '\s*$') })
    if ($kept.Count -eq $existing.Count) { return $false }
    [System.IO.File]::WriteAllLines($HostsPath, [string[]] $kept)
    return $true
}

# The CA certificate's subject, exactly as app.py issues it. Removal
# matches on this, so it must not drift from ensure_self_signed_cert().
$script:CaSubjectMatch = 'CN=Frivo Local CA'

function Install-FrivoRootCertificate {
    <#
        Imports Frivo's local certificate authority into this machine's
        Trusted Root store, which is what makes the browser padlock appear
        instead of a warning page — on this PC. Other devices have their
        own stores and still see the warning until ca.crt is installed on
        them or Proceed is clicked once.

        Reinstalls reuse the same certificate authority. Returns its thumbprint.
    #>
    param([Parameter(Mandatory)] [string] $CertificatePath)

    if (-not (Test-Path -LiteralPath $CertificatePath)) {
        throw ('Certificate file not found: {0}' -f $CertificatePath)
    }
    $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($CertificatePath)
    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
        [System.Security.Cryptography.X509Certificates.StoreName]::Root,
        [System.Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine)
    try {
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        # Do not remove another user's Frivo CA. The root store is shared by
        # the machine while each signed-in user has their own data folder.
        $present = @($store.Certificates | Where-Object { $_.Thumbprint -eq $cert.Thumbprint })
        if ($present.Count -eq 0) { $store.Add($cert) }
    } finally {
        $store.Close()
    }
    return $cert.Thumbprint
}

function Remove-FrivoRootCertificate {
    <#
    Removes the CA represented by CertificatePath. The machine-wide store is
    matched by thumbprint so another Frivo user's CA is preserved.
    #>
    param([Parameter(Mandatory)] [string] $CertificatePath)

    if (-not (Test-Path -LiteralPath $CertificatePath)) { return 0 }
    $thumbprint = ([System.Security.Cryptography.X509Certificates.X509Certificate2]::new($CertificatePath)).Thumbprint
    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
        [System.Security.Cryptography.X509Certificates.StoreName]::Root,
        [System.Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine)
    $removed = 0
    try {
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        $found = @($store.Certificates | Where-Object { $_.Thumbprint -eq $thumbprint })
        foreach ($cert in $found) {
            $store.Remove($cert)
            $removed++
        }
    } finally {
        $store.Close()
    }
    return $removed
}

function Get-WScriptPath {
    <#
        The full path to wscript.exe. Shortcuts and Run-key entries must
        carry an absolute path — a bare "wscript.exe" in a .lnk depends on
        PATH resolution at click time and can quietly do nothing.
    #>
    if ($env:SystemRoot) { return ($env:SystemRoot.TrimEnd('\') + '\System32\wscript.exe') }
    return 'C:\Windows\System32\wscript.exe'
}

function Get-LauncherShim {
    <#
        Frivo.vbs — what the shortcuts and the sign-in entry actually run.

        A VBScript shim starts the native Frivo host with no console flash.
        The host keeps Frivo—not Windows PowerShell—as the visible process
        in Task Manager. A PowerShell fallback keeps source-only installs
        working when the optional host was not bundled.
    #>
    $lines = @(
        "' Starts Frivo. Generated by the installer."
        'Set fso = CreateObject("Scripting.FileSystemObject")'
        'Set shell = CreateObject("WScript.Shell")'
        'base = fso.GetParentFolderName(WScript.ScriptFullName)'
        'target = base & "\installer\Launcher.ps1"'
        'host = base & "\installer\FrivoHost.exe"'
        'If Not fso.FileExists(target) Then'
        '    MsgBox "Frivo''s launcher is missing:" & vbCrLf & target & vbCrLf & vbCrLf & "Run the installer again to repair the installation.", vbCritical, "Frivo"'
        '    WScript.Quit 1'
        'End If'
        'tray = ""'
        'For Each a In WScript.Arguments'
        '    If LCase(a) = "-tray" Then tray = " --tray"'
        'Next'
        'dataPath = shell.ExpandEnvironmentStrings("%APPDATA%\Frivo")'
        'If fso.FileExists(host) Then'
        '    cmd = """" & host & """ --script """ & target & """ --data """ & dataPath & """" & tray'
        'Else'
        '    cmd = "powershell -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File """ & target & """" & tray'
        'End If'
        'shell.Run cmd, 0, False'
    )
    return ($lines -join "`r`n") + "`r`n"
}

function Get-SetupLogPath { return $script:SetupLogPath }

Export-ModuleMember -Function `
    Get-PythonVersionFromOutput, Test-PythonVersionOk, Get-PythonCandidates,
    New-FrivoDataFiles, Get-LauncherScript, Get-UninstallCommand,
    Get-UninstallLauncher, Get-DefaultInstallPath, Get-DataPath,
    Get-FrivoInstallMarkerPath, Test-FrivoInstallOwnership, Test-FrivoRecoverableResidue, Write-FrivoInstallMarker, Test-OtherFrivoInstall, Test-PathWithinDirectory,
    Test-IsAdministrator, Test-InstallPathUsable,
    Write-SetupLog, Invoke-Tool, ConvertTo-ArgumentString, Get-LastLines, Find-Python, Install-Python,
    Update-PathFromRegistry, New-Venv, Sync-VenvDependencies, Get-SetupLogPath,
    Get-LocalHostname, Get-HostsFilePath, Add-FrivoHostsEntry, Remove-FrivoHostsEntry,
    Install-FrivoRootCertificate, Remove-FrivoRootCertificate, Get-LauncherShim, Get-WScriptPath
