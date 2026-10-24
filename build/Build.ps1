<#
    Frivo — the one build
    ------------------------------------------------------------------
    NEW (2.0.0): run through Build.bat at the repo root. Makes
    dist\FrivoSetup.exe, the one installer, with the Frivo app inside it.
    That's the one file to publish: setup installs the app from inside
    itself, and the app updates itself from the Frivo it's connected to,
    which keeps the app's installer beside it.

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

# ---- 2. FrivoSetup.exe, with the app inside ----
# build\app\ is what Frivo.iss packs into the setup (installer\app\ in its
# payload): the app's installer under one fixed name, and its version.
$payload = Join-Path $here 'app'
if (Test-Path -LiteralPath $payload) { Remove-Item -LiteralPath $payload -Recurse -Force }
New-Item -ItemType Directory -Path $payload -Force | Out-Null
Copy-Item -LiteralPath $appBuilt -Destination (Join-Path $payload 'FrivoApp-Setup.exe') -Force
[System.IO.File]::WriteAllText((Join-Path $payload 'app.json'), (@{ version = $appVersion } | ConvertTo-Json),
    (New-Object System.Text.UTF8Encoding($false)))
# Left over from builds that put the app beside setup instead.
foreach ($old in @((Join-Path $root 'installer\bundled-app.json'))) {
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force }
}
if (Test-Path -LiteralPath $dist) {
    Get-ChildItem -LiteralPath $dist -Filter 'FrivoApp-Setup-*.exe' -File | Remove-Item -Force
}

Write-Host ''
Write-Host '=== FrivoSetup.exe ==='
& (Join-Path $here 'Build-Installer.ps1')

$frivoVersion = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
$size = (Get-Item -LiteralPath (Join-Path $dist 'FrivoSetup.exe')).Length / 1MB
Write-Host ''
Write-Host '=================================================================='
Write-Host (' Done: dist\FrivoSetup.exe ({0:N0} MB), with the Frivo app {1} inside.' -f $size, $appVersion)
Write-Host ''
Write-Host ' Run it to install or update Frivo, the app, or both.'
Write-Host (' To publish: a GitHub release v{0} with FrivoSetup.exe. That''s all.' -f $frivoVersion)
Write-Host '=================================================================='
