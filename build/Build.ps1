<#
    Frivo — the one build
    ------------------------------------------------------------------
    NEW (2.0.0): run through Build.bat at the repo root. Makes everything,
    into dist\:

      dist\FrivoSetup.exe                 the installer. The one people run.
      dist\FrivoApp-Setup-<version>.exe   the Frivo app, which FrivoSetup.exe
                                          installs. Not run by hand: it's
                                          uploaded to GitHub for setup to
                                          download, and setup uses it from
                                          here when you test a build on
                                          this PC.

    The app is only rebuilt when something in desktop\ changed since the
    last build (it takes a few minutes); -RebuildApp forces it. Its steps
    are build\Build-App.ps1, and the installer's build\Build-Installer.ps1.
#>

[CmdletBinding()]
param([switch] $RebuildApp)

$ErrorActionPreference = 'Stop'
$here    = $PSScriptRoot
$root    = Split-Path -Parent $here
$desktop = Join-Path $root 'desktop'
$dist    = Join-Path $root 'dist'

function Get-AppSourceHash {
    <#
        One fingerprint of the app's own files (not node_modules, its build
        output, or the Node.js the build downloads), to tell whether the app
        needs building again.
    #>
    $skip = @('node_modules', 'dist', '.tools', 'screenshots')
    $files = New-Object System.Collections.Generic.List[string]
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($desktop)
    while ($pending.Count) {
        $folder = $pending.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $folder -Force) {
            if ($item.PSIsContainer) {
                if ($skip -notcontains $item.Name) { $pending.Push($item.FullName) }
            } else {
                $files.Add($item.FullName)
            }
        }
    }
    $files.Sort([System.StringComparer]::OrdinalIgnoreCase)
    $all = foreach ($file in $files) {
        $file.Substring($desktop.Length) + '=' + (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($all -join "`n"))
        return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '')
    } finally { $sha.Dispose() }
}

# ---- 1. the Frivo app ----
$appVersion = (Get-Content -LiteralPath (Join-Path $desktop 'package.json') -Raw | ConvertFrom-Json).version
$appName  = 'FrivoApp-Setup-{0}.exe' -f $appVersion
$appBuilt = Join-Path $desktop ('dist\' + $appName)
$stampPath = Join-Path $desktop 'dist\.built-from'
$hash = Get-AppSourceHash
$stamp = if (Test-Path -LiteralPath $stampPath -PathType Leaf) { (Get-Content -LiteralPath $stampPath -Raw).Trim() } else { '' }

Write-Host ''
if ($RebuildApp -or -not (Test-Path -LiteralPath $appBuilt -PathType Leaf) -or $stamp -ne $hash) {
    Write-Host ('=== The Frivo app {0} ===' -f $appVersion)
    & (Join-Path $here 'Build-App.ps1')
    Set-Content -LiteralPath $stampPath -Value $hash -Encoding ASCII
} else {
    Write-Host ('=== The Frivo app {0}: unchanged since its last build, so that one is used ===' -f $appVersion)
}

# ---- 2. FrivoSetup.exe ----
# It carries the app file's name and SHA-256, so it installs that exact
# file when it's beside it, and never any other.
$bundled = [ordered] @{ name = $appName; sha256 = (Get-FileHash -LiteralPath $appBuilt -Algorithm SHA256).Hash; version = $appVersion }
$bundledPath = Join-Path $root 'installer\bundled-app.json'
[System.IO.File]::WriteAllText($bundledPath, ($bundled | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
Write-Host ''
Write-Host '=== FrivoSetup.exe ==='
& (Join-Path $here 'Build-Installer.ps1')

# ---- 3. the app beside it ----
New-Item -ItemType Directory -Path $dist -Force | Out-Null
Get-ChildItem -LiteralPath $dist -Filter 'FrivoApp-Setup-*.exe' -File |
    Where-Object { $_.Name -ne $appName } | Remove-Item -Force
Copy-Item -LiteralPath $appBuilt -Destination (Join-Path $dist $appName) -Force

$frivoVersion = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
Write-Host ''
Write-Host '=================================================================='
Write-Host ' Done. In dist\:'
Write-Host ''
Write-Host '   FrivoSetup.exe          Run this. It installs Frivo, the app, or both.'
Write-Host ('   {0}  Leave it beside FrivoSetup.exe: setup' -f $appName)
Write-Host '                           installs the app from it on this PC.'
Write-Host ''
Write-Host ' To publish:'
Write-Host ('   1. GitHub release app-v{0} with {1}' -f $appVersion, $appName)
Write-Host '      ("Set as the latest release" unticked). Only when the app changed.'
Write-Host ('   2. GitHub release v{0} with FrivoSetup.exe.' -f $frivoVersion)
Write-Host '=================================================================='
