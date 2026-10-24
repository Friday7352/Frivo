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

function Sync-FrivoDictation {
    <#
        NEW (2.0.0): installs built-in dictation's package (moonshine-voice,
        from requirements-dictation.txt). Unlike requirements.txt, a failure
        here doesn't stop setup: Frivo works without it, and its Settings ›
        Dictation card says to run setup again. Returns $true when it's there.
        Quick when nothing changed (pip finds it already installed).
    #>
    param([string] $VenvPython, [string] $Target, [scriptblock] $Log)
    $req = Join-Path $Target 'requirements-dictation.txt'
    if (-not (Test-Path -LiteralPath $req -PathType Leaf)) { return $false }
    & $Log 'Installing built-in dictation...'
    try {
        $r = Invoke-Tool -FilePath $VenvPython -Arguments @(
            '-m', 'pip', 'install', '--no-input', '--disable-pip-version-check', '-r', $req
        )
    } catch {
        & $Log ('Built-in dictation could not be installed: {0}. Everything else works.' -f $_.Exception.Message)
        return $false
    }
    if ($r.ExitCode -ne 0) {
        & $Log ('Built-in dictation could not be installed. Everything else works.{0}{1}' -f "`r`n", (Get-LastLines ($r.StdErr + "`r`n" + $r.StdOut) 4))
        return $false
    }
    return $true
}

# CHANGED (1.5.0): the Kokoro install step (Sync-FreeVoiceDependencies) and
# the Visual C++ runtime it needed (Test-VCRuntimePresent, Install-VCRuntime)
# have been removed. Frivo's own voices (Piper) need neither: the speech
# library is in requirements.txt and carries its own runtime.

function Reset-FrivoVoicePermissions {
    <#
        NEW (1.6.1): makes the voices folder take its permissions from the
        Frivo folder again. Earlier setups unpacked the voices in a folder
        that newer Python makes readable by only the account running setup
        (an administrator), so Frivo, running as you, couldn't load them:
        "Load model ... failed: system error number 13". Every install,
        update and Repair puts that right. Never throws.
    #>
    param([string] $Target)
    try {
        $voices = Join-Path $Target 'voices'
        if (-not (Test-Path -LiteralPath $voices -PathType Container)) { return }
        $icacls = Join-Path $env:SystemRoot 'System32\icacls.exe'
        if (-not (Test-Path -LiteralPath $icacls -PathType Leaf)) { return }
        $r = Invoke-Tool -FilePath $icacls -Arguments @($voices, '/reset', '/T', '/C', '/Q')
        Write-SetupLog ('voices: permissions reset (icacls exit {0})' -f $r.ExitCode)
    } catch {
        Write-SetupLog ('voices: permissions not reset: {0}' -f $_.Exception.Message)
    }
}

function Stop-FrivoBuiltinAI {
    <#
        NEW (1.7.0): stops the built-in AI's engine (llama-server.exe) if it's
        running. It runs from Frivo's data folder, not the program folder, so
        stopping Frivo's Python alone could leave it behind, holding its
        files open: they then couldn't be deleted or downloaded again.
        Only an engine inside a Frivo builtin_ai folder is touched. Returns
        how many were stopped. Never throws.
    #>
    param([string[]] $Folders = @())
    $stopped = 0
    # CHANGED (1.7.0): and the folder picked in Settings > Storage, read from
    # config.json in any of these folders.
    foreach ($folder in @($Folders)) {
        try {
            $config = Join-Path $folder 'config.json'
            if ($folder -and (Test-Path -LiteralPath $config)) {
                $picked = [string] ((Get-Content -LiteralPath $config -Raw -ErrorAction Stop | ConvertFrom-Json).storage_builtin_ai)
                if ($picked -and [System.IO.Path]::IsPathRooted($picked)) { $Folders += $picked }
            }
        } catch { }
    }
    try {
        Get-CimInstance Win32_Process -Filter "Name = 'llama-server.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $path = [string] $_.ExecutablePath
                if (-not $path) { return $false }
                foreach ($folder in $Folders) {
                    if ($folder -and (Test-PathWithinDirectory -Path $path -Directory (Join-Path $folder 'builtin_ai'))) { return $true }
                }
                return ($path -match '\\Frivo\\builtin_ai\\engine-[^\\]+\\')
            } |
            ForEach-Object {
                try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $stopped++ } catch { }
            }
        if ($stopped) { Start-Sleep -Milliseconds 800 }   # Windows lets go of the files a moment later
    } catch { }
    return $stopped
}

function Sync-FrivoVoices {
    <#
        NEW (1.5.0): gets Frivo's free voices by running voice_pack.py with
        Frivo's own Python. The first install downloads them (about 215 MB);
        an update or Repair only fetches one that's missing or damaged.
        Never throws: if it fails, setup still finishes, and Frivo and the
        Windows voices still work.
    #>
    param([string] $VenvPython, [string] $Target, [scriptblock] $Log)
    try {
        $script = Join-Path $Target 'voice_pack.py'
        if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { return $false }
        & $Log 'Getting Frivo''s voices (a one-time download of about 215 MB)...'
        $r = Invoke-Tool -FilePath $VenvPython -Arguments @($script, 'install')
        foreach ($line in (($r.StdOut + "`n" + $r.StdErr) -split "`r?`n")) {
            if ($line.Trim()) { Write-SetupLog ('voices: ' + $line.Trim()) }
        }
        Reset-FrivoVoicePermissions -Target $Target
        if ($r.ExitCode -ne 0) {
            & $Log 'Some of Frivo''s voices could not be downloaded. Frivo still works, and so do the Windows voices. Run setup again (Repair) to try again.'
            return $false
        }
        & $Log 'Frivo''s voices are ready.'
        return $true
    } catch {
        Write-SetupLog ('voices: {0}' -f $_.Exception.Message)
        return $false
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

# ==================================================================
# NEW (2.0.0): the Frivo app (desktop\ in the repo)
# ==================================================================
# Setup can install the Frivo app with Frivo, or on its own. The app is a
# per-person install, in that person's own AppData, made by its own
# installer, which setup downloads from Frivo's releases on GitHub. These
# say where it ends up, run things as the person signed in at this PC
# (setup itself runs as administrator), and set the two settings Frivo and
# the app share.

# Where the app's installer puts it. From desktop\package.json: the folder
# is "name", the program "build.executableName", the uninstaller is named
# after "productName". Change them together.
$script:AppFolderName  = 'frivo-app'
$script:AppExeName     = 'FrivoApp.exe'
# CHANGED (2.0.0): the app is called just Frivo (productName), so its
# uninstaller is "Uninstall Frivo.exe". Apps from before were "Frivo App".
$script:AppUninstaller = 'Uninstall Frivo.exe'
$script:AppUninstallerOld = 'Uninstall Frivo App.exe'

function Get-FrivoDesktopUser {
    <#
        The person signed in at this PC's screen (DOMAIN\name), and their own
        Local and Roaming AppData. Usually the same person setup runs as, just
        without administrator rights; with "run as a different administrator"
        it's someone else, and their folders come from their profile.
    #>
    $user = $null
    try { $user = [string] (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName } catch { }
    # CHANGED: nobody at the console (Remote Desktop, say): whoever owns the
    # Explorer in setup's own session, the desktop setup was started from.
    if (-not $user) {
        try {
            $session = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
            foreach ($explorer in @(Get-CimInstance Win32_Process -Filter "Name = 'explorer.exe'" -ErrorAction Stop)) {
                if ($explorer.SessionId -ne $session) { continue }
                $owner = Invoke-CimMethod -InputObject $explorer -MethodName GetOwner -ErrorAction Stop
                if ($owner -and $owner.User) {
                    $user = if ($owner.Domain) { '{0}\{1}' -f $owner.Domain, $owner.User } else { [string] $owner.User }
                    break
                }
            }
        } catch { }
    }
    $local = $env:LOCALAPPDATA
    $roaming = $env:APPDATA
    $me = ''
    try { $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name } catch { }
    if ($user -and $user -ine $me) {
        try {
            $sid = (New-Object System.Security.Principal.NTAccount($user)).Translate(
                [System.Security.Principal.SecurityIdentifier]).Value
            $profileDir = [string] (Get-ItemProperty -LiteralPath (
                'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\' + $sid) -ErrorAction Stop).ProfileImagePath
            if ($profileDir) {
                $local = Join-Path $profileDir 'AppData\Local'
                $roaming = Join-Path $profileDir 'AppData\Roaming'
            }
        } catch { }
    }
    return [pscustomobject] @{ User = $user; LocalAppData = $local; RoamingAppData = $roaming }
}

function Get-FrivoAppPaths {
    param([Parameter(Mandatory)] [string] $LocalAppData)
    $folder = Join-Path $LocalAppData ('Programs\' + $script:AppFolderName)
    $uninstaller = Join-Path $folder $script:AppUninstaller
    $old = Join-Path $folder $script:AppUninstallerOld
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf) -and (Test-Path -LiteralPath $old -PathType Leaf)) { $uninstaller = $old }
    return [pscustomobject] @{
        Folder      = $folder
        Exe         = Join-Path $folder $script:AppExeName
        Uninstaller = $uninstaller
    }
}

function Set-FrivoAppListed {
    <#
        NEW (2.0.0): whether the Frivo app has its own entry in Apps &
        features for $User. With Frivo installed on the same PC it doesn't:
        there's one "Frivo" there, and uninstalling it offers to remove the
        app too. On its own, or once Frivo is uninstalled and the app kept,
        it does. (The app's installer hides it the same way when Frivo is
        here: desktop\build\installer.nsh.) Returns $true when it found
        the app's entry.
    #>
    param([Parameter(Mandatory)] [string] $User, [Parameter(Mandatory)] [bool] $Listed)
    $sid = (New-Object System.Security.Principal.NTAccount($User)).Translate(
        [System.Security.Principal.SecurityIdentifier]).Value
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $root = if ($sid -eq $me) { 'HKCU:' } else { 'Registry::HKEY_USERS\' + $sid }
    $uninstallKey = Join-Path $root 'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    if (-not (Test-Path -LiteralPath $uninstallKey)) { return $false }
    $found = $false
    foreach ($key in @(Get-ChildItem -LiteralPath $uninstallKey -ErrorAction SilentlyContinue)) {
        $values = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction SilentlyContinue
        if (-not $values) { continue }
        $command = [string] $values.UninstallString
        # The app's entry, and only it: its uninstaller in Programs\frivo-app.
        if ($command -notmatch ('\\Programs\\' + [regex]::Escape($script:AppFolderName) + '\\Uninstall Frivo( App)?\.exe')) { continue }
        if ($Listed) {
            Remove-ItemProperty -LiteralPath $key.PSPath -Name 'SystemComponent' -ErrorAction SilentlyContinue
        } else {
            New-ItemProperty -LiteralPath $key.PSPath -Name 'SystemComponent' -Value 1 -PropertyType DWord -Force | Out-Null
        }
        $found = $true
    }
    return $found
}

function Invoke-FrivoAsDesktopUser {
    <#
        Runs a program as the person signed in at this PC, in their own
        session and with their own rights, not setup's: a one-off scheduled
        task, the same way Frivo is started again after an update. With
        -Wait, waits for it to finish (up to -TimeoutSeconds) and returns
        $true when it did. Without, returns once it has been started.

        CHANGED: throws when there's nobody signed in to run it as, rather
        than running it with setup's administrator rights.
    #>
    param(
        [AllowEmptyString()] [string] $User,
        [Parameter(Mandatory)] [string] $FilePath,
        [string] $Arguments = '',
        [switch] $Wait,
        [int] $TimeoutSeconds = 600
    )
    if (-not $User) {
        throw 'Nobody is signed in to this PC to install the app for. Sign in, then run setup again.'
    }
    $taskName = 'Frivo Run ' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    try {
        $action = if ($Arguments) {
            New-ScheduledTaskAction -Execute $FilePath -Argument $Arguments
        } else {
            New-ScheduledTaskAction -Execute $FilePath
        }
        $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName
        if (-not $Wait) {
            Start-Sleep -Seconds 2   # deleting the task straight away can stop it starting
            return $true
        }
        # 267011: hasn't run yet. 267009: still running.
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $ui = 'System.Windows.Forms.Application' -as [type]
        while ((Get-Date) -lt $deadline) {
            # Short sleeps with the window kept alive, so setup doesn't show
            # "Not responding" while it waits.
            for ($i = 0; $i -lt 10; $i++) {
                Start-Sleep -Milliseconds 50
                if ($ui) { $ui::DoEvents() }
            }
            $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
            $state = [string] (Get-ScheduledTask -TaskName $taskName -ErrorAction Stop).State
            if ($state -ne 'Running' -and $info.LastTaskResult -notin @(267009, 267011)) { return $true }
        }
        return $false
    } finally {
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop } catch { }
    }
}

function Set-FrivoLauncherAppPath {
    <#
        App mode for Frivo's launcher (installer\Launcher.ps1): appPath in
        launcher.json is the app's .exe, or '' for none. Everything else in
        the file is the launcher's and is kept. UTF-8 with a BOM, the way
        Windows PowerShell writes it.
    #>
    param(
        [Parameter(Mandatory)] [string] $DataDir,
        [AllowEmptyString()] [string] $AppPath
    )
    $path = Join-Path $DataDir 'launcher.json'
    $settings = [ordered] @{}
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        try {
            $raw = Get-Content -LiteralPath $path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            foreach ($p in $raw.PSObject.Properties) { $settings[$p.Name] = $p.Value }
        } catch { }
    }
    if ($settings.Contains('appPath') -and [string] $settings['appPath'] -eq $AppPath) { return }
    $settings['appPath'] = $AppPath
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    [System.IO.File]::WriteAllText($path, ($settings | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($true)))
}

function Get-FrivoLauncherAppPath {
    param([Parameter(Mandatory)] [string] $DataDir)
    try {
        $raw = Get-Content -LiteralPath (Join-Path $DataDir 'launcher.json') -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($raw.PSObject.Properties['appPath']) { return [string] $raw.appPath }
    } catch { }
    return ''
}

function Set-FrivoAppMode {
    <#
        Where the Frivo app connects: 'local' (Frivo runs on this PC, so it
        opens straight to Frivo) or $null (it asks again next time it opens).
        Its own settings file, in the person's Roaming AppData under "Frivo
        App"; everything else in it is kept. UTF-8 without a BOM: the app
        reads it with JSON.parse.
    #>
    param(
        [Parameter(Mandatory)] [string] $RoamingAppData,
        [AllowNull()] [AllowEmptyString()] [string] $Mode
    )
    $dir = Join-Path $RoamingAppData 'Frivo App'
    $path = Join-Path $dir 'app-settings.json'
    $settings = [ordered] @{}
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        try {
            $raw = [System.IO.File]::ReadAllText($path) | ConvertFrom-Json -ErrorAction Stop
            foreach ($p in $raw.PSObject.Properties) { $settings[$p.Name] = $p.Value }
        } catch { }
    } elseif (-not $Mode) {
        return   # nothing to undo
    }
    $settings['mode'] = if ($Mode) { $Mode } else { $null }
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    [System.IO.File]::WriteAllText($path, ($settings | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
}

function Get-FrivoPairingCode {
    <#
        NEW (2.0.0): Frivo's pairing code, from its certificate authority
        (ca.crt in Frivo's data folder): the SHA-256, first 60 bits, as
        twelve characters of Crockford's base 32, XXXX-XXXX-XXXX. The Frivo app on
        another PC asks for it. Worked out the same way as pairing_code_for
        in app\app.py and desktop\src\pairing.js. $null without one.
    #>
    param([Parameter(Mandatory)] [string] $CertificatePath)
    try {
        $pem = [System.IO.File]::ReadAllText($CertificatePath)
        $m = [regex]::Match($pem, '-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----', 'Singleline')
        if (-not $m.Success) { return $null }
        $der = [Convert]::FromBase64String(($m.Groups[1].Value -replace '\s', ''))
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try { $digest = $sha.ComputeHash($der) } finally { $sha.Dispose() }
        $bits = -join ($digest[0..7] | ForEach-Object { [Convert]::ToString($_, 2).PadLeft(8, '0') })
        $alphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
        $text = -join (0..11 | ForEach-Object { $alphabet[[Convert]::ToInt32($bits.Substring($_ * 5, 5), 2)] })
        return $text.Substring(0, 4) + '-' + $text.Substring(4, 4) + '-' + $text.Substring(8)
    } catch {
        return $null
    }
}

# ------------------------------------------------------------------
# NEW (2.0.0): running Frivo before anyone signs in
# ------------------------------------------------------------------
# For a PC that's only a Frivo server: Frivo's server starts when Windows
# does, as the person who installed it, with nobody signed in. It's a
# scheduled task that runs "whether the user is signed in or not" without
# storing their password (S4U), so it has no window, no tray icon, and no
# access to network shares; it doesn't need any. Their Frivo launcher, when
# they do sign in, finds it running and takes it over like any other.
$script:BootTaskName = 'Frivo (at startup)'

function Get-FrivoBootTaskAction {
    <#
        What the task runs: Frivo's server from the install folder, with its
        data folder given on the command line (the task's environment might
        not be the person's own). pythonw.exe, the same program the
        firewall rule lets other devices reach, started directly: the task
        is running exactly as long as Frivo is.
    #>
    param([Parameter(Mandatory)] [string] $InstallDir, [Parameter(Mandatory)] [string] $DataDir)
    $target = $InstallDir.TrimEnd('\', '/')
    $data = $DataDir.TrimEnd('\', '/')
    if ($data.Contains('"')) { throw 'The data folder''s path has a quote in it.' }
    return [pscustomobject] @{
        Path      = $target + '\.venv\Scripts\pythonw.exe'
        Arguments = ('app.py --data-dir "{0}"' -f $data)
        WorkingDirectory = $target
    }
}

function Test-FrivoBootTask {
    try {
        $service = New-Object -ComObject 'Schedule.Service'
        $service.Connect()
        [void] $service.GetFolder('\').GetTask($script:BootTaskName)
        return $true
    } catch {
        return $false
    }
}

function Register-FrivoBootTask {
    param(
        [Parameter(Mandatory)] [string] $InstallDir,
        [Parameter(Mandatory)] [string] $DataDir,
        [Parameter(Mandatory)] [string] $User
    )
    $sid = (New-Object System.Security.Principal.NTAccount($User)).Translate(
        [System.Security.Principal.SecurityIdentifier]).Value
    $action = Get-FrivoBootTaskAction -InstallDir $InstallDir -DataDir $DataDir

    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $root = $service.GetFolder('\')
    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Author = 'Frivo setup'
    $definition.RegistrationInfo.Description =
        'Starts Frivo''s server when Windows starts, before anyone signs in. Turn it off by running Frivo''s setup again (Repair).'
    $definition.Principal.UserId = $sid
    $definition.Principal.LogonType = 2          # TASK_LOGON_S4U: no stored password
    $definition.Principal.RunLevel = 0           # TASK_RUNLEVEL_LUA: not as administrator
    $definition.Settings.Enabled = $true
    $definition.Settings.AllowDemandStart = $true
    $definition.Settings.StartWhenAvailable = $true
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.ExecutionTimeLimit = 'PT0S'   # runs for as long as Windows does
    $definition.Settings.MultipleInstances = 2         # TASK_INSTANCES_IGNORE_NEW
    $definition.Settings.Hidden = $false

    $trigger = $definition.Triggers.Create(8)    # TASK_TRIGGER_BOOT
    $trigger.Delay = 'PT30S'                     # once the network is up
    $exec = $definition.Actions.Create(0)        # TASK_ACTION_EXEC
    $exec.Path = $action.Path
    $exec.Arguments = $action.Arguments
    $exec.WorkingDirectory = $action.WorkingDirectory

    # Administrators manage it; the person it runs as can start and stop it.
    $sddl = 'D:(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;{0})' -f $sid
    # 6 = TASK_CREATE_OR_UPDATE, 2 = TASK_LOGON_S4U
    [void] $root.RegisterTaskDefinition($script:BootTaskName, $definition, 6, $sid, $null, 2, $sddl)
    return $true
}

function Unregister-FrivoBootTask {
    <#
        Removes the task, only when it runs Frivo from this install folder.
        Returns $true when something was removed.
    #>
    param([Parameter(Mandatory)] [string] $InstallDir)
    try {
        $service = New-Object -ComObject 'Schedule.Service'
        $service.Connect()
        $root = $service.GetFolder('\')
        $task = $root.GetTask($script:BootTaskName)
    } catch {
        return $false
    }
    # Ordinal comparison, not -like: [ and ] in a path are wildcards there.
    $pythonw = $InstallDir.TrimEnd('\', '/') + '\.venv\Scripts\pythonw.exe'
    foreach ($a in $task.Definition.Actions) {
        if (-not ([string] $a.Path).Equals($pythonw, [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
    }
    try { [void] $task.Stop(0) } catch { }
    $root.DeleteTask($script:BootTaskName, 0)
    return $true
}

# Whether the task is running Frivo right now (an update checks before it
# stops Frivo, so it can start it again after).
function Test-FrivoBootTaskRunning {
    try {
        $service = New-Object -ComObject 'Schedule.Service'
        $service.Connect()
        return ([int] $service.GetFolder('\').GetTask($script:BootTaskName).State -eq 4)   # TASK_STATE_RUNNING
    } catch {
        return $false
    }
}

function Start-FrivoBootTask {
    try {
        $service = New-Object -ComObject 'Schedule.Service'
        $service.Connect()
        [void] $service.GetFolder('\').GetTask($script:BootTaskName).Run($null)
        return $true
    } catch {
        return $false
    }
}

# ------------------------------------------------------------------
# NEW (2.0.0): a backup from setup or the uninstaller
# ------------------------------------------------------------------
# The same zip Frivo makes in Settings > Updates > Back up, so it restores
# there the same way (Restore adds it to what's there): settings, profiles,
# saved replies with their audio, tag taste, Hold the accent anchors, and
# optionally the voices you added. Made here in PowerShell, without Frivo's
# Python, so it works whatever version is installed and even when Frivo's
# own files are half gone. Saved replies and voices are found wherever
# Settings > Storage put them.

function Get-FrivoBackupFolder {
    <#
        Documents\Frivo backups for the person signed in at this PC (not the
        administrator setup may be running as).
    #>
    param([string] $RoamingAppData)
    $docs = [Environment]::GetFolderPath('MyDocuments')
    $me = $env:APPDATA
    if ($RoamingAppData -and $me -and -not $RoamingAppData.TrimEnd('\').Equals($me.TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase)) {
        # Someone else's profile: C:\Users\name\AppData\Roaming -> C:\Users\name\Documents
        $profileDir = Split-Path -Parent (Split-Path -Parent $RoamingAppData.TrimEnd('\'))
        if ($profileDir) { $docs = Join-Path $profileDir 'Documents' }
    }
    if (-not $docs) { $docs = [System.IO.Path]::GetTempPath() }
    return (Join-Path $docs 'Frivo backups')
}

function Test-FrivoHasData {
    param([Parameter(Mandatory)] [string] $DataDir)
    foreach ($name in @('config.json', 'profiles.json', 'saved')) {
        if (Test-Path -LiteralPath (Join-Path $DataDir $name)) { return $true }
    }
    return $false
}

function New-FrivoBackup {
    <#
        Writes "Frivo backup <date> <time>.zip" into $Destination and returns
        its path. API keys are left out unless -IncludeKeys (a backup is a
        file people copy around); voices you added only with -IncludeVoices
        (they're big). Throws with a reason when it can't.
    #>
    param(
        [Parameter(Mandatory)] [string] $DataDir,
        [Parameter(Mandatory)] [string] $Destination,
        [string] $Version = '',
        [switch] $IncludeKeys,
        [switch] $IncludeVoices
    )
    if (-not (Test-Path -LiteralPath $DataDir -PathType Container) -or -not (Test-FrivoHasData -DataDir $DataDir)) {
        throw ('There are no Frivo settings to back up in {0}.' -f $DataDir)
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $utf8 = New-Object System.Text.UTF8Encoding($false)

    $configText = $null
    $configPath = Join-Path $DataDir 'config.json'
    if (Test-Path -LiteralPath $configPath -PathType Leaf) { $configText = [System.IO.File]::ReadAllText($configPath) }
    # Where Settings > Storage keeps saved replies and voices.
    $picked = @{ saved = ''; voices = '' }
    if ($configText) {
        foreach ($kind in @('saved', 'voices')) {
            $m = [regex]::Match($configText, ('"storage_{0}"\s*:\s*"((?:[^"\\]|\\.)*)"' -f $kind))
            if ($m.Success) {
                try { $value = ('"{0}"' -f $m.Groups[1].Value) | ConvertFrom-Json } catch { $value = '' }
                if ($value -and [System.IO.Path]::IsPathRooted([string] $value) -and (Test-Path -LiteralPath ([string] $value))) {
                    $picked[$kind] = [string] $value
                }
            }
        }
    }
    $savedDir  = Join-Path $(if ($picked.saved)  { $picked.saved }  else { $DataDir }) 'saved'
    $voicesDir = Join-Path $(if ($picked.voices) { $picked.voices } else { $DataDir }) 'voices'

    if (-not $IncludeKeys -and $configText) {
        # Only the keys' values are blanked; everything else stays exactly
        # as written. Frivo's restore skips a blank key.
        $configText = [regex]::Replace($configText,
            '("(?:openai_api_key|elevenlabs_api_key)"\s*:\s*)"(?:[^"\\]|\\.)*"', '$1""')
    }

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $stamp = Get-Date -Format 'yyyy-MM-dd HHmm'
    $final = Join-Path $Destination ('Frivo backup {0}.zip' -f $stamp)
    for ($n = 2; Test-Path -LiteralPath $final; $n++) {
        $final = Join-Path $Destination ('Frivo backup {0} ({1}).zip' -f $stamp, $n)
    }
    $temp = $final + '.partial'
    $counts = [ordered] @{ profiles = 0; saved = 0; voices = 0 }

    try {
    $zip = [System.IO.Compression.ZipFile]::Open($temp, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $addText = {
            param([string] $Name, [string] $Text)
            $entry = $zip.CreateEntry($Name, [System.IO.Compression.CompressionLevel]::Optimal)
            $stream = $entry.Open()
            try { $bytes = $utf8.GetBytes($Text); $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
        }
        $addFile = {
            param([string] $Path, [string] $Name)
            [void] [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $Path, $Name, [System.IO.Compression.CompressionLevel]::Optimal)
        }
        $countIn = {
            param([string] $Path)
            try { return @((Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)).Count } catch { return 0 }
        }

        if ($null -ne $configText) { & $addText 'data/config.json' $configText }
        # CHANGED (2.0.0): browser_prefs.json, each browser's preferences
        # (favourite voices, audio devices, ...), which Frivo keeps a copy of.
        foreach ($name in @('profiles.json', 'tag_taste.json', 'voice_anchors.json', 'browser_prefs.json')) {
            $path = Join-Path $DataDir $name
            if (Test-Path -LiteralPath $path -PathType Leaf) { & $addFile $path ('data/' + $name) }
        }
        $profiles = Join-Path $DataDir 'profiles.json'
        if (Test-Path -LiteralPath $profiles -PathType Leaf) { $counts.profiles = & $countIn $profiles }
        $anchors = Join-Path $DataDir 'anchors'
        if (Test-Path -LiteralPath $anchors -PathType Container) {
            Get-ChildItem -LiteralPath $anchors -File | Where-Object { $_.Name -match '^[A-Za-z0-9_.\-]{1,120}\.(mp3|wav)$' } |
                ForEach-Object { & $addFile $_.FullName ('data/anchors/' + $_.Name) }
        }
        if (Test-Path -LiteralPath $savedDir -PathType Container) {
            Get-ChildItem -LiteralPath $savedDir -File | ForEach-Object { & $addFile $_.FullName ('data/saved/' + $_.Name) }
            $index = Join-Path $savedDir 'saved.json'
            if (Test-Path -LiteralPath $index -PathType Leaf) { $counts.saved = & $countIn $index }
        }
        if ($IncludeVoices -and (Test-Path -LiteralPath $voicesDir -PathType Container)) {
            $root = (Resolve-Path -LiteralPath $voicesDir).ProviderPath.TrimEnd('\', '/')
            Get-ChildItem -LiteralPath $voicesDir -File -Recurse | ForEach-Object {
                $rel = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
                & $addFile $_.FullName ('data/voices/' + $rel)
            }
            $index = Join-Path $voicesDir 'voices.json'
            if (Test-Path -LiteralPath $index -PathType Leaf) { $counts.voices = & $countIn $index }
        }
        # CHANGED (2.0.0): what the browser keeps, for Restore to put back in
        # whichever browser restores it: the most recently used one's copy.
        $browserText = '{}'
        $prefsPath = Join-Path $DataDir 'browser_prefs.json'
        if (Test-Path -LiteralPath $prefsPath -PathType Leaf) {
            try {
                $all = Get-Content -LiteralPath $prefsPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $newest = $null
                foreach ($p in $all.PSObject.Properties) {
                    if ($p.Value -and $p.Value.PSObject.Properties['prefs'] -and
                        (-not $newest -or [string] $p.Value.updated -gt [string] $newest.updated)) { $newest = $p.Value }
                }
                if ($newest) { $browserText = $newest.prefs | ConvertTo-Json -Depth 3 -Compress }
            } catch { $browserText = '{}' }
        }
        & $addText 'browser.json' $browserText
        $about = [ordered] @{
            format  = 1
            app     = 'Frivo'
            version = $Version
            made    = (Get-Date -Format 'yyyy-MM-dd HH:mm')
            keys    = [bool] $IncludeKeys
            voices  = [bool] $IncludeVoices
            counts  = $counts
            by      = 'setup'
        }
        & $addText 'frivo-backup.json' ($about | ConvertTo-Json -Depth 4)
    } finally {
        $zip.Dispose()
    }
    Move-Item -LiteralPath $temp -Destination $final -Force
    } catch {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        throw
    }
    return $final
}

function Get-SetupLogPath { return $script:SetupLogPath }

Export-ModuleMember -Function `
    Get-PythonVersionFromOutput, Test-PythonVersionOk, Get-PythonCandidates,
    New-FrivoDataFiles, Get-LauncherScript, Get-UninstallCommand,
    Get-UninstallLauncher, Get-DefaultInstallPath, Get-DataPath,
    Get-FrivoInstallMarkerPath, Test-FrivoInstallOwnership, Test-FrivoRecoverableResidue, Write-FrivoInstallMarker, Test-OtherFrivoInstall, Test-PathWithinDirectory,
    Test-IsAdministrator, Test-InstallPathUsable,
    Write-SetupLog, Invoke-Tool, ConvertTo-ArgumentString, Get-LastLines, Find-Python, Install-Python,
    Update-PathFromRegistry, New-Venv, Sync-VenvDependencies, Sync-FrivoDictation, Get-SetupLogPath,
    Sync-FrivoVoices,
    Reset-FrivoVoicePermissions,
    Stop-FrivoBuiltinAI,
    Get-LocalHostname, Get-HostsFilePath, Add-FrivoHostsEntry, Remove-FrivoHostsEntry,
    Install-FrivoRootCertificate, Remove-FrivoRootCertificate, Get-LauncherShim, Get-WScriptPath,
    Get-FrivoDesktopUser, Get-FrivoAppPaths, Invoke-FrivoAsDesktopUser,
    Set-FrivoLauncherAppPath, Get-FrivoLauncherAppPath, Set-FrivoAppMode, Get-FrivoPairingCode,
    Get-FrivoBackupFolder, Test-FrivoHasData, New-FrivoBackup, Set-FrivoAppListed,
    Get-FrivoBootTaskAction, Test-FrivoBootTask, Register-FrivoBootTask, Unregister-FrivoBootTask, Start-FrivoBootTask, Test-FrivoBootTaskRunning
