<#
    Builds FrivoSetup.exe from this source tree.
    Run on Windows. Installs Inno Setup first if it is missing.
#>

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Build-FrivoHost {
    # Native host used for Frivo's WinForms scripts.
    $source = Join-Path $here 'FrivoHost.cs'
    $output = Join-Path $here 'FrivoHost.exe'
    $windows = [Environment]::GetFolderPath('Windows')
    $compiler = Join-Path $windows 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
        throw 'The Windows .NET compiler needed to build FrivoHost.exe was not found.'
    }

    # Resolve the PowerShell automation assembly used by the native host.
    $windowsPowerShell = Join-Path $windows 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $automation = @(& $windowsPowerShell -NoProfile -Command '[System.Management.Automation.PSObject].Assembly.Location') |
        Select-Object -First 1
    if (-not (Test-Path -LiteralPath $automation -PathType Leaf)) {
        throw 'Windows PowerShell automation support was not found.'
    }

    $icon = Join-Path (Split-Path -Parent $here) 'app\static\Frivo.ico'
    $arguments = @(
        '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        ('/out:{0}' -f $output),
        ('/win32icon:{0}' -f $icon),
        ('/reference:{0}' -f $automation),
        '/reference:System.Windows.Forms.dll',
        $source
    )
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
        throw 'Could not build FrivoHost.exe.'
    }
}

function Find-InnoSetupCompiler {
    # Check both per-user and machine-wide Inno Setup locations.
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return Get-Item -LiteralPath $candidate
        }
    }

    $command = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
        return Get-Item -LiteralPath $command.Source
    }
    return $null
}

Build-FrivoHost

$iscc = Find-InnoSetupCompiler

if (-not $iscc) {
    Write-Host 'Inno Setup not found. Installing via winget...'
    winget install --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
    $iscc = Find-InnoSetupCompiler
}
if (-not $iscc) { throw 'Inno Setup was installed, but ISCC.exe could not be found. Close and reopen PowerShell, then run this script again.' }

& $iscc.FullName (Join-Path $here 'Frivo.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup reported an error.' }

$out = Join-Path (Split-Path -Parent $here) 'dist\FrivoSetup.exe'
Write-Host ''
Write-Host ('Built: {0}' -f $out)
Write-Host 'This single file is what you distribute.'
