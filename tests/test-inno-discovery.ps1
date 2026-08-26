<#
    Inno Setup discovery, lifted out of the real build script.

    The build script must never tell someone to go install Inno Setup when
    they already have it, and must never fail at the "install it" step in a
    way that leaves them nothing to act on. Both of those are pure logic, so
    both are tested here — the actual install is not run.

    The functions are extracted from build/Build-Installer.ps1 at run time rather than
    copied, so this fails if the real ones change shape.

    Usage:  pwsh -NoProfile -File tests/test-inno-discovery.ps1
    Runs on Linux or Windows. Nothing is installed and nothing outside a
    temporary folder is touched.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $PSCommandPath
$buildScript = Join-Path (Split-Path -Parent $here) 'build/Build-Installer.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw ("The build script was not found at {0}." -f $buildScript)
}

# From the first Inno function to the closing brace of Get-InnoSetupCompiler,
# whose body ends with a here-string. Anchored on that rather than on the
# next function, because the build scripts do not all order their functions
# the same way.
$source = Get-Content -LiteralPath $buildScript -Raw
$start = $source.IndexOf('function Find-InnoSetupCompiler {')
$hereEnd = if ($start -ge 0) { $source.IndexOf("'@", $source.IndexOf('function Get-InnoSetupCompiler {', $start)) } else { -1 }
$end = if ($hereEnd -ge 0) { $source.IndexOf('}', $hereEnd) + 1 } else { -1 }
if ($start -lt 0 -or $end -le $start) {
    throw 'The Inno Setup functions could not be located in the build script.'
}
. ([scriptblock]::Create($source.Substring($start, $end - $start)))

$fails = @()
function Check([string] $Name, [bool] $Condition, $Got) {
    if ($Condition) { Write-Host "  PASS  $Name" }
    else { Write-Host "  FAIL  $Name   got=$Got"; $script:fails += $Name }
}

$sandbox = Join-Path ([IO.Path]::GetTempPath()) ('inno-' + [Guid]::NewGuid().ToString('N'))
$savedProgramFiles = $env:ProgramFiles
$savedProgramFilesX86 = ${env:ProgramFiles(x86)}
$savedLocalAppData = $env:LOCALAPPDATA

try {
    Write-Host '--- nothing installed ---'
    $env:ProgramFiles = Join-Path $sandbox 'pf'
    ${env:ProgramFiles(x86)} = Join-Path $sandbox 'pf86'
    $env:LOCALAPPDATA = Join-Path $sandbox 'lad'
    Check 'returns nothing rather than throwing when Inno is absent' `
        ($null -eq (Find-InnoSetupCompiler)) 'found something'

    Write-Host ''
    Write-Host '--- an ordinary machine-wide install ---'
    $dir = Join-Path $env:ProgramFiles 'Inno Setup 6'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $dir 'ISCC.exe') -Value 'stub'
    $found = Find-InnoSetupCompiler
    Check 'finds Inno Setup 6' ($found -and $found.Contains('Inno Setup 6')) $found

    Write-Host ''
    Write-Host '--- Inno Setup 7 counts too ---'
    # 7 is current and 6 is what most machines have. Either compiles these
    # scripts, so neither may be treated as "not installed".
    $dir7 = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7'
    New-Item -ItemType Directory -Path $dir7 -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $dir7 'ISCC.exe') -Value 'stub'
    $env:ProgramFiles = Join-Path $sandbox 'empty-pf'
    $found = Find-InnoSetupCompiler
    Check 'finds Inno Setup 7' ($found -and $found.Contains('Inno Setup 7')) $found

    Write-Host ''
    Write-Host '--- a per-user install ---'
    ${env:ProgramFiles(x86)} = Join-Path $sandbox 'empty-pf86'
    $dirUser = Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') 'Inno Setup 6'
    New-Item -ItemType Directory -Path $dirUser -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $dirUser 'ISCC.exe') -Value 'stub'
    $found = Find-InnoSetupCompiler
    Check 'finds an install under LocalAppData' ($found -and $found.Contains('Inno Setup 6')) $found

    Write-Host ''
    Write-Host '--- empty environment variables ---'
    # Join-Path throws rather than returning anything when its base is empty,
    # and these can all be empty in a service or scheduled-task context. This
    # already shipped once as a bug in FrivOSC's Find-InstalledPython, and it
    # caught a second one here.
    $env:ProgramFiles = ''
    ${env:ProgramFiles(x86)} = ''
    $env:LOCALAPPDATA = ''
    $threw = $false; $message = ''
    try { [void](Find-InnoSetupCompiler) } catch { $threw = $true; $message = $_.Exception.Message }
    Check 'survives empty ProgramFiles / LocalAppData' (-not $threw) $message

    Write-Host ''
    Write-Host '--- Get-InnoSetupCompiler leaves an existing install alone ---'
    $env:ProgramFiles = Join-Path $sandbox 'pf'
    $script:installAttempted = $false
    function Install-InnoSetupWithWinget { $script:installAttempted = $true; return $false }
    function Install-InnoSetupFromJrsoftware { $script:installAttempted = $true; return $false }
    $result = Get-InnoSetupCompiler
    Check 'returns what is already installed' ($result -and $result.Contains('Inno Setup 6')) $result
    Check 'and does not install over it' (-not $script:installAttempted) 'it tried'

    Write-Host ''
    Write-Host '--- when both install routes fail ---'
    $env:ProgramFiles = Join-Path $sandbox 'still-empty'
    $threw = $false; $message = ''
    try { [void](Get-InnoSetupCompiler) } catch { $threw = $true; $message = $_.Exception.Message }
    Check 'throws rather than returning nothing' $threw 'returned quietly'
    Check 'and says where to get it by hand' `
        ($threw -and $message.Contains('jrsoftware.org/isdl.php')) $message
    Check 'and warns that a fresh install needs a new window' `
        ($threw -and $message.Contains('close this window')) $message
} finally {
    $env:ProgramFiles = $savedProgramFiles
    ${env:ProgramFiles(x86)} = $savedProgramFilesX86
    $env:LOCALAPPDATA = $savedLocalAppData
    Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
if ($fails.Count) {
    Write-Host ("{0} failed: {1}" -f $fails.Count, ($fails -join ', '))
    exit 1
}
Write-Host ("{0} passed, 0 failed" -f 11)
