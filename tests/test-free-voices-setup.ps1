<#
    NEW (1.5.0): setup installs the free voices, and can never be broken by them.

        pwsh -NoProfile -File tests/test-free-voices-setup.ps1

    The free voices (Kokoro) are optional: requirements-voices.txt is
    installed after requirements.txt, best effort. Checked here:

      * installed once per version of requirements-voices.txt (a marker in
        the venv remembers it), and retried next time if it failed
      * a failure is logged and reported, and never stops setup
      * the Visual C++ runtime Kokoro needs is installed only when missing,
        and its "already newer" / "restart pending" answers count as fine
      * the file is copied with the app, and both install and update run it
      * requirements-voices.txt only asks for Kokoro on Python 3.10–3.13

    The functions are lifted out of Frivo.Setup.psm1 and run for real under
    StrictMode with pip, downloads and the installer replaced.
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script:failures = 0
function Check {
    param([string] $Name, [bool] $Condition, $Got = $null)
    if ($Condition) { Write-Host ('  PASS  ' + $Name) }
    else { Write-Host ('  FAIL  ' + $Name + '   got=' + [string] $Got); $script:failures++ }
}

$modulePath = Join-Path $Root 'installer/Frivo.Setup.psm1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($modulePath, [ref] $null, [ref] $null)
foreach ($name in @('Test-VCRuntimePresent', 'Install-VCRuntime', 'Sync-FreeVoiceDependencies')) {
    $fn = $ast.Find({
        param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name
    }, $true)
    if (-not $fn) { Write-Host ('Missing function: ' + $name); exit 1 }
    Invoke-Expression $fn.Extent.Text
}

# --- a pretend machine -----------------------------------------------------------
$script:setupLines = @()
$script:messages = @()
function Write-SetupLog { param($Message) $script:setupLines += , [string] $Message }
function Get-LastLines { param($Text, $Count) [string] $Text }
$script:pipRuns = 0
$script:pipExit = 0
$script:redistRuns = 0
$script:redistExit = 0
$script:downloads = 0
function Invoke-Tool {
    param([string] $FilePath, [string[]] $Arguments, [string] $WorkingDirectory)
    if ($Arguments -contains 'pip') {
        $script:pipRuns++
        $script:lastPip = $Arguments
        return [pscustomobject] @{ ExitCode = $script:pipExit; StdOut = 'out'; StdErr = 'pip said no' }
    }
    $script:redistRuns++
    $script:lastRedist = $Arguments
    return [pscustomobject] @{ ExitCode = $script:redistExit; StdOut = ''; StdErr = '' }
}
function Invoke-WebRequest { param($Uri, $OutFile, [switch] $UseBasicParsing, $UserAgent, $TimeoutSec) $script:downloads++; $script:lastUrl = $Uri; Set-Content -LiteralPath $OutFile -Value 'exe' }
$Log = { param($m) $script:messages += , [string] $m }

$target = Join-Path ([IO.Path]::GetTempPath()) ('frivo-voices-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$venvPython = Join-Path $target '.venv/Scripts/python.exe'
New-Item -ItemType Directory -Path (Split-Path -Parent $venvPython) -Force | Out-Null
Copy-Item (Join-Path $Root 'app/requirements-voices.txt') -Destination $target
$marker = Join-Path $target '.venv/frivo-voices.ok'

try {
    Write-Host '--- requirements-voices.txt ---'
    $req = [IO.File]::ReadAllText((Join-Path $Root 'app/requirements-voices.txt'))
    Check 'asks for Kokoro only on Python 3.10–3.13' ($req -match 'kokoro-onnx[^\r\n;]*;\s*python_version >= "3\.10" and python_version < "3\.14"')
    $main = [IO.File]::ReadAllText((Join-Path $Root 'app/requirements.txt'))
    Check 'and is not in requirements.txt (whose failure stops setup)' ($main -notmatch 'kokoro')

    Write-Host ''
    Write-Host '--- installing ---'
    # The runtime check reads System32; point it at a folder we control.
    $sys = Join-Path $target 'System32'
    New-Item -ItemType Directory -Path $sys | Out-Null
    $env:SystemRoot = $target
    Set-Content -LiteralPath (Join-Path $sys 'msvcp140.dll') -Value 'x'
    Set-Content -LiteralPath (Join-Path $sys 'msvcp140_1.dll') -Value 'x'

    $ok = Sync-FreeVoiceDependencies -VenvPython $venvPython -Target $target -Log $Log
    Check 'installs requirements-voices.txt into the venv' ($ok -eq $true -and $script:pipRuns -eq 1 -and ($script:lastPip -join ' ') -match 'requirements-voices\.txt') ($script:lastPip -join ' ')
    Check 'remembers it did' (Test-Path -LiteralPath $marker)
    Check 'runtime present: not installed again' ($script:redistRuns -eq 0 -and $script:downloads -eq 0)

    $ok = Sync-FreeVoiceDependencies -VenvPython $venvPython -Target $target -Log $Log
    Check 'the next update: nothing to do' ($ok -eq $true -and $script:pipRuns -eq 1) $script:pipRuns

    Add-Content -LiteralPath (Join-Path $target 'requirements-voices.txt') -Value '# changed'
    [void] (Sync-FreeVoiceDependencies -VenvPython $venvPython -Target $target -Log $Log)
    Check 'requirements-voices.txt changed: installed again' ($script:pipRuns -eq 2) $script:pipRuns

    Write-Host ''
    Write-Host '--- when it fails ---'
    Remove-Item -LiteralPath $marker
    $script:pipExit = 1
    $threw = $false
    try { $ok = Sync-FreeVoiceDependencies -VenvPython $venvPython -Target $target -Log $Log } catch { $threw = $true }
    Check 'pip failing never stops setup' (-not $threw -and $ok -eq $false)
    Check 'it says the rest still works' (($script:messages -join "`n") -match 'ElevenLabs and Windows voices still work')
    Check 'and logs why' (($script:setupLines -join "`n") -match 'pip said no')
    Check 'and tries again next time (nothing remembered)' (-not (Test-Path -LiteralPath $marker))
    $script:pipExit = 0

    Remove-Item -LiteralPath (Join-Path $target 'requirements-voices.txt')
    $ok = Sync-FreeVoiceDependencies -VenvPython $venvPython -Target $target -Log $Log
    Check 'no requirements-voices.txt (an older payload): skipped quietly' ($ok -eq $false)
    Copy-Item (Join-Path $Root 'app/requirements-voices.txt') -Destination $target

    Write-Host ''
    Write-Host '--- the Visual C++ runtime ---'
    Remove-Item -LiteralPath (Join-Path $sys 'msvcp140_1.dll')
    Check 'missing msvcp140_1.dll means missing' (-not (Test-VCRuntimePresent))
    $script:redistExit = 3010
    Check 'installed when missing; "restart pending" is fine' ((Install-VCRuntime -Log $Log) -eq $true -and $script:downloads -eq 1)
    Check 'quietly, without restarting the PC' (($script:lastRedist -join ' ') -eq '/install /quiet /norestart') ($script:lastRedist -join ' ')
    Check 'from Microsoft' ($script:lastUrl -eq 'https://aka.ms/vs/17/release/vc_redist.x64.exe') $script:lastUrl
    $script:redistExit = 1638
    Check '"a newer one is installed" is fine' ((Install-VCRuntime -Log $Log) -eq $true)
    $script:redistExit = 1603
    Check 'a real failure is reported, not thrown' ((Install-VCRuntime -Log $Log) -eq $false)

    Write-Host ''
    Write-Host '--- wired into setup ---'
    $install = [IO.File]::ReadAllText((Join-Path $Root 'installer/Install.ps1'))
    Check 'copied with the app' ($install -match "requirements-voices\.txt")
    $after = $install.Substring($install.IndexOf('$venvPython = New-Venv -Target $Target'))
    Check 'installed after the venv is ready, on install and update alike' ($after -match '^(?s).{0,200}Sync-FreeVoiceDependencies -VenvPython \$venvPython')
    Check 'and its result never stops setup' ($install -match '\[void\] \(Sync-FreeVoiceDependencies')
    $module = [IO.File]::ReadAllText($modulePath)
    Check 'exported from the setup module' ($module -match 'Export-ModuleMember(?s).*Sync-FreeVoiceDependencies')
} finally {
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
if ($script:failures) { Write-Host ('{0} free-voice setup check(s) failed.' -f $script:failures); exit 1 }
Write-Host 'All free-voice setup checks passed.'
