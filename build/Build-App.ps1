<#
    Frivo App — build
    ------------------------------------------------------------------
    NEW (2.0.0): builds desktop\dist\FrivoApp-Setup-<version>.exe, the Frivo
    app's installer. Run by build\Build.ps1 (Build.bat at the repo root),
    which also builds FrivoSetup.exe and puts the two together in dist\.

    Nothing needs installing first. The app is built with Node.js, so this
    downloads a private copy of it the first time into desktop\.tools (not
    installed, not on PATH, ignored by git), checks it against the SHA-256
    nodejs.org publishes, and uses it from there. Delete desktop\.tools to
    get rid of it.

    People who install the app don't need any of this: the installer it
    makes has everything the app needs inside it.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Windows PowerShell's progress bar makes downloads crawl

# Node.js LTS used to build the app. Any 22.x works; pinned so every build
# uses the same one.
$NodeVersion = '22.22.0'

$Root    = Split-Path -Parent $PSScriptRoot
$Desktop = Join-Path $Root 'desktop'
$Tools   = Join-Path $Desktop '.tools'
$NodeDir = Join-Path $Tools ('node-v{0}-win-x64' -f $NodeVersion)
$Npm     = Join-Path $NodeDir 'npm.cmd'

function Get-Node {
    if (Test-Path -LiteralPath (Join-Path $NodeDir 'node.exe') -PathType Leaf) { return }

    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $zipName = 'node-v{0}-win-x64.zip' -f $NodeVersion
    $base    = 'https://nodejs.org/dist/v{0}' -f $NodeVersion
    $zip     = Join-Path $Tools $zipName
    $sums    = Join-Path $Tools 'SHASUMS256.txt'
    New-Item -ItemType Directory -Path $Tools -Force | Out-Null

    Write-Host ('Downloading Node.js {0}, used only to build the app (nothing is installed)...' -f $NodeVersion)
    Invoke-WebRequest -Uri ('{0}/{1}' -f $base, $zipName) -OutFile $zip -UseBasicParsing
    Invoke-WebRequest -Uri ('{0}/SHASUMS256.txt' -f $base) -OutFile $sums -UseBasicParsing

    # "<sha256>  node-v22.22.0-win-x64.zip"
    $expected = $null
    foreach ($line in [System.IO.File]::ReadAllLines($sums)) {
        $parts = $line.Trim() -split '\s+'
        if ($parts.Count -eq 2 -and $parts[1] -eq $zipName) { $expected = $parts[0].ToLowerInvariant() }
    }
    $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    Remove-Item -LiteralPath $sums -Force
    if (-not $expected -or $actual -ne $expected) {
        Remove-Item -LiteralPath $zip -Force
        throw "The Node.js download doesn't match the checksum nodejs.org publishes for it, so it was deleted. Try again."
    }

    Write-Host 'Unpacking Node.js...'
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path -LiteralPath $tar -PathType Leaf) {
        & $tar -xf $zip -C $Tools
        if ($LASTEXITCODE) { throw 'Node.js could not be unpacked.' }
    } else {
        Expand-Archive -LiteralPath $zip -DestinationPath $Tools -Force
    }
    Remove-Item -LiteralPath $zip -Force
    if (-not (Test-Path -LiteralPath (Join-Path $NodeDir 'node.exe') -PathType Leaf)) {
        throw ('Node.js was unpacked, but {0} is missing.' -f (Join-Path $NodeDir 'node.exe'))
    }
}

function Invoke-Npm {
    param([string[]] $Arguments, [string] $What)
    Write-Host ''
    Write-Host ('{0}...' -f $What)
    & $Npm @Arguments
    if ($LASTEXITCODE) { throw ('{0} failed (npm {1}).' -f $What, ($Arguments -join ' ')) }
}

Get-Node
# This build only: the downloaded Node first on PATH, so npm and the tools
# it runs use it rather than any other Node on the PC.
$env:PATH = $NodeDir + ';' + $env:PATH

Push-Location -LiteralPath $Desktop
try {
    Invoke-Npm -Arguments @('ci', '--no-audit', '--no-fund') -What 'Getting the app''s build tools'
    Invoke-Npm -Arguments @('test') -What 'Testing'
    Invoke-Npm -Arguments @('run', 'dist') -What 'Building the installer'
} finally {
    Pop-Location
}

$version = (Get-Content -LiteralPath (Join-Path $Desktop 'package.json') -Raw | ConvertFrom-Json).version
$built = Join-Path $Desktop ('dist\FrivoApp-Setup-{0}.exe' -f $version)
if (-not (Test-Path -LiteralPath $built -PathType Leaf)) { throw ('The build finished, but {0} is missing.' -f $built) }
Write-Host ''
Write-Host ('Built {0}' -f $built)
