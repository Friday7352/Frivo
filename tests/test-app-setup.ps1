<#
    NEW (2.0.0): setup's part in the Frivo app. Runs on Linux or Windows;
    nothing here touches the registry, the network or scheduled tasks.

      - picking the app's newest release from GitHub's list, and only one
        that's checkable and from this repository
      - the checked download: a wrong file is refused and deleted
      - launcher.json's appPath (app mode), keeping the launcher's own settings
      - the app's own settings: "Frivo runs here", readable by the app

    pwsh -NoProfile -File tests/test-app-setup.ps1
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'installer/Frivo.Setup.psm1') -Force
Import-Module (Join-Path $root 'installer/Frivo.Update.psm1') -Force

$failures = 0
function Check([string] $Name, [bool] $Ok, $Got = $null) {
    if ($Ok) { Write-Host "  PASS  $Name" } else { Write-Host "  FAIL  $Name   got=$Got"; $script:failures++ }
}

$policy = Get-FrivoUpdatePolicy -Path (Join-Path $root 'installer/update-policy.json')
$prefix = $policy.DownloadPrefix
$sha = 'a' * 64
function Asset($name, $tag, $digest = "sha256:$sha", $repoPrefix = $prefix) {
    [ordered] @{ name = $name; size = 10; digest = $digest; browser_download_url = "$repoPrefix$tag/$name" }
}
$releases = @(
    [ordered] @{ tag_name = 'v2.0.0'; assets = @(Asset 'FrivoSetup.exe' 'v2.0.0') }
    [ordered] @{ tag_name = 'app-v1.0.0'; assets = @(Asset 'FrivoApp-Setup-1.0.0.exe' 'app-v1.0.0') }
    [ordered] @{ tag_name = 'app-v1.2.0'; prerelease = $true; assets = @(Asset 'FrivoApp-Setup-1.2.0.exe' 'app-v1.2.0') }
    [ordered] @{ tag_name = 'app-v1.1.0'; assets = @(Asset 'FrivoApp-Setup-1.1.0.exe' 'app-v1.1.0') }
    [ordered] @{ tag_name = 'app-v1.3.0'; assets = @(Asset 'FrivoApp-Setup-1.3.0.exe' 'app-v1.3.0' $null) }
    [ordered] @{ tag_name = 'app-v1.4.0'; assets = @(Asset 'FrivoApp-Setup-1.4.0.exe' 'app-v1.4.0' "sha256:$sha" 'https://github.com/someone/else/releases/download/') }
)
$json = $releases | ConvertTo-Json -Depth 6
$pick = Select-FrivoAppRelease -Json $json -Policy $policy
Check 'the newest checkable app release is picked' ($pick -and $pick.VersionText -eq '1.1.0') $pick.VersionText
Check 'with its file and fingerprint' ($pick.Name -eq 'FrivoApp-Setup-1.1.0.exe' -and $pick.Sha256 -eq $sha)
Check "Frivo's own releases aren't the app" ($null -eq (ConvertFrom-FrivoAppRelease -Release $releases[0] -Policy $policy))
Check "and the app's aren't Frivo's (Frivo's updater skips app-v tags)" ($null -eq (ConvertFrom-FrivoRelease -Release $releases[1] -Policy $policy))
Check 'no releases, no pick' ($null -eq (Select-FrivoAppRelease -Json '[]' -Policy $policy))

# ---- the checked download, from a local file:// stand-in for GitHub
$work = Join-Path ([System.IO.Path]::GetTempPath()) ('frivo-app-setup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$src = Join-Path $work 'source.exe'
[System.IO.File]::WriteAllText($src, 'the frivo app')
$good = Get-FrivoFileSha256 -Path $src
$fakePolicy = [pscustomobject] @{ DownloadPrefix = (New-Object System.Uri($work)).AbsoluteUri.TrimEnd('/') + '/' }
$url = (New-Object System.Uri($src)).AbsoluteUri
$seen = New-Object System.Collections.ArrayList
$target = Join-Path $work 'FrivoApp-Setup.exe'
$out = Save-FrivoDownload -Url $url -Policy $fakePolicy -Target $target -Size 13 -Sha256 $good -OnProgress { param($d, $t) [void] $seen.Add($d) }
Check 'a matching download is kept' ((Test-Path -LiteralPath $target) -and ([System.IO.File]::ReadAllText($target) -eq 'the frivo app'))
Check 'with progress reported' ($seen.Count -ge 1 -and $seen[-1] -eq 13) ($seen -join ',')
$bad = Join-Path $work 'Bad.exe'
$refused = $false
try { Save-FrivoDownload -Url $url -Policy $fakePolicy -Target $bad -Size 13 -Sha256 ('b' * 64) | Out-Null } catch { $refused = $_.Exception.Message -match 'does not match' }
Check 'a download that does not match is refused' $refused
Check 'and nothing is left behind' (-not (Test-Path -LiteralPath $bad) -and -not (Test-Path -LiteralPath ($bad + '.part')))
$refused = $false
try { Save-FrivoDownload -Url 'https://example.com/x.exe' -Policy $fakePolicy -Target $bad -Sha256 $good | Out-Null } catch { $refused = $true }
Check 'a file from anywhere else is refused' $refused

# ---- launcher.json: app mode
$data = Join-Path $work 'Frivo'
New-Item -ItemType Directory -Path $data | Out-Null
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText((Join-Path $data 'launcher.json'), '{"closeAction":"stop","openBrowser":true,"lastUpdateNotice":"u1"}', $utf8Bom)
Set-FrivoLauncherAppPath -DataDir $data -AppPath 'C:\Users\x\AppData\Local\Programs\frivo-app\FrivoApp.exe'
$l = Get-Content -LiteralPath (Join-Path $data 'launcher.json') -Raw | ConvertFrom-Json
Check 'app mode is set in launcher.json' ($l.appPath -like '*FrivoApp.exe')
Check "and the launcher's own settings are kept" ($l.closeAction -eq 'stop' -and $l.openBrowser -eq $true -and $l.lastUpdateNotice -eq 'u1')
Check 'read back' ((Get-FrivoLauncherAppPath -DataDir $data) -like '*FrivoApp.exe')
Set-FrivoLauncherAppPath -DataDir $data -AppPath ''
Check 'and cleared' ((Get-FrivoLauncherAppPath -DataDir $data) -eq '')
$fresh = Join-Path $work 'Fresh'
Set-FrivoLauncherAppPath -DataDir $fresh -AppPath 'C:\a\FrivoApp.exe'
Check 'made when Frivo has no launcher.json yet' ((Get-FrivoLauncherAppPath -DataDir $fresh) -eq 'C:\a\FrivoApp.exe')

# ---- the app's own settings
$roaming = Join-Path $work 'Roaming'
New-Item -ItemType Directory -Path (Join-Path $roaming 'Frivo App') -Force | Out-Null
$appSettings = Join-Path $roaming 'Frivo App/app-settings.json'
[System.IO.File]::WriteAllText($appSettings, '{"mode":"remote","remoteUrl":"https://box:5000","trusted":{"box":{"fingerprint":"ab","pem":"x"}},"closeAction":"quit"}')
Set-FrivoAppMode -RoamingAppData $roaming -Mode 'local'
$bytes = [System.IO.File]::ReadAllBytes($appSettings)
Check 'the app settings are written without a BOM (the app reads them with JSON.parse)' (-not ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB))
$a = [System.IO.File]::ReadAllText($appSettings) | ConvertFrom-Json
Check 'the app is told Frivo runs here' ($a.mode -eq 'local')
Check 'and keeps everything else, trusted certificates too' ($a.closeAction -eq 'quit' -and $a.trusted.box.fingerprint -eq 'ab')
Set-FrivoAppMode -RoamingAppData $roaming -Mode $null
$b = [System.IO.File]::ReadAllText($appSettings) | ConvertFrom-Json
Check 'and told to ask again (Both changed to Server)' ($null -eq $b.mode -and $b.closeAction -eq 'quit')
Set-FrivoAppMode -RoamingAppData $roaming -Mode 'local'
$emptyRoaming = Join-Path $work 'NoApp'
Set-FrivoAppMode -RoamingAppData $emptyRoaming -Mode $null
Check 'asking again writes nothing when the app was never set up' (-not (Test-Path -LiteralPath (Join-Path $emptyRoaming 'Frivo App')))
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $settingsJs = (Join-Path $root 'desktop/src/settings.js') -replace '\\', '/'
    $file = $appSettings -replace '\\', '/'
    $mode = & node -e "const {Settings}=require('$settingsJs'); console.log(new Settings('$file').get('mode'))"
    Check 'and the app reads it' ($mode -eq 'local') $mode
} else {
    Write-Host '  SKIP  the app reading it (no node)'
}

# ---- where the app installs (desktop\package.json must agree)
$pkg = Get-Content -LiteralPath (Join-Path $root 'desktop/package.json') -Raw | ConvertFrom-Json
$paths = Get-FrivoAppPaths -LocalAppData (Join-Path $work 'Local')
$norm = { param($p) ([string] $p) -replace '\\', '/' }
Check "the app's folder matches package.json's name" ((& $norm $paths.Folder) -like ('*/Programs/' + $pkg.name)) $paths.Folder
Check "its program matches executableName" ((& $norm $paths.Exe) -like ('*/' + $pkg.build.executableName + '.exe')) $paths.Exe
Check "its uninstaller matches productName" ((& $norm $paths.Uninstaller) -like ('*/Uninstall ' + $pkg.productName + '.exe')) $paths.Uninstaller

# ---- setup's rules, from its source (the wizard needs Windows to run)
$install = Get-Content -LiteralPath (Join-Path $root 'installer/Install.ps1') -Raw
Check 'a silent update never downloads the app' ($install -match '-InstallApp \$false -SaveRole')
Check 'and never touches the app''s settings or app mode' ($install -match "if \(\`$Role -eq 'Both' -and \(\`$Action -ne 'Update' -or \`$InstallApp\)\)")
Check 'a guessed role is not saved' ($install -match 'if \(\$Role\) \{ Set-ItemProperty -Path \$RegKey -Name ''FrivoRole''')
Check 'just the app is never installed silently' ($install -match 'Just the Frivo app cannot be installed silently')
Check 'and keeps the role it was given' ($install -match '-Role \$\(if \(\$savedSettings\) \{ \$savedSettings\.Role \}')
Check 'the role is remembered for updates and Repair' ($install -match '-Name ''FrivoRole'' -Value \$Role')
Check '"Just the app" is not offered over an existing Frivo' ($install -match '\$radioApp\.Visible = \$false')
Check 'a problem with the app never undoes installing Frivo' ($install -match '\$script:appProblem = \$_\.Exception\.Message')
Check 'the app is installed as the person signed in, not as administrator' ($install -match 'Invoke-FrivoAsDesktopUser -User \$person\.User -FilePath \$file -Arguments ''/S'' -Wait')
$uninstall = Get-Content -LiteralPath (Join-Path $root 'installer/Uninstall.ps1') -Raw
Check 'uninstalling offers to remove the app, ticked when setup installed it' ($uninstall -match 'Also remove the Frivo app' -and $uninstall -match '-Checked \$script:AppWithFrivo')
Check 'and reads that box before hiding it' ($uninstall -match '\$removeApp = \[bool\] \$script:AppPaths -and \$chkApp\.Checked')
Check 'and waits for the app to be gone' ($uninstall -match 'wait for the app itself to be gone')
$setupModule = Get-Content -LiteralPath (Join-Path $root 'installer/Frivo.Setup.psm1') -Raw
Check 'the app is never run as administrator when nobody is signed in' ($setupModule -match 'Nobody is signed in to this PC')


# NEW (2.0.0): starting with Windows, and before anyone signs in
$boot = Get-FrivoBootTaskAction -InstallDir 'C:\Program Files\Frivo\' -DataDir 'C:\Users\Sam Lee\AppData\Roaming\Frivo'
Check "the at-startup task runs Frivo's own pythonw.exe (the firewall rule's program)" ($boot.Path -eq 'C:\Program Files\Frivo\.venv\Scripts\pythonw.exe') $boot.Path
Check "with Frivo's data folder given, quoted" ($boot.Arguments -eq 'app.py --data-dir "C:\Users\Sam Lee\AppData\Roaming\Frivo"') $boot.Arguments
Check 'in the install folder' ($boot.WorkingDirectory -eq 'C:\Program Files\Frivo') $boot.WorkingDirectory
Check 'outside Windows, there is no at-startup task' (-not (Test-FrivoBootTask) -and -not (Test-FrivoBootTaskRunning))
Check 'the task stores no password (S4U) and never runs as administrator' ($setupModule -match 'LogonType = 2 ' -and $setupModule -match 'RunLevel = 0 ')
Check 'and has no time limit' ($setupModule -match "ExecutionTimeLimit = 'PT0S'")
Check 'it is only removed when it runs this install' ($setupModule -match '\(\[string\] \$a\.Path\)\.Equals\(\$pythonw, \[System\.StringComparison\]::OrdinalIgnoreCase\)')
Check 'Repair notices the task was running before it stops Frivo' ($install -match '(?s)\$script:bootTaskWasRunning = Test-FrivoBootTaskRunning.{0,200}if \(\$CleanFirst\)')
Check '"Start when I sign in" is on for a new install' ($install -match "-Text \('Start \{0\} automatically when I sign in' -f \`$AppName\) -X 18 -Y 12 -W 536 -Checked \`$true")
Check 'starting before sign-in is a choice in setup' ($install -match '\$chkBoot = New-FrivoCheck')
Check 'which an update leaves as it is' ($install -match "-BootStart \`$\(if \(\`$script:installAction -eq 'Update'\) \{ \`$null \}")
Check 'an update starts Frivo again the way it was started' ($install -match 'Resume-FrivoBootTask -Target \$restartTarget' -and $install -match 'Resume-FrivoBootTask -Target \$txtPath\.Text')
Check 'uninstalling removes the task' ($uninstall -match 'Unregister-FrivoBootTask -InstallDir \$InstallDir')
$launcher = Get-Content -LiteralPath (Join-Path $root 'installer/Launcher.ps1') -Raw
Check "stopping Frivo in the launcher ends the task's copy too" ($launcher -match "GetTask\('Frivo \(at startup\)'\)\.Stop\(0\)")
Check 'the launcher shows the pairing code' ($launcher -match 'Get-FrivoPairingCode -CertificatePath \$CaCertPath')
Check 'and makes the QR code offline, with Frivo''s Python' ($launcher -match 'segno\.make\(sys\.argv\[1\]')


# NEW (2.0.0): adding the app (or Frivo) later, backups, keeping your data
Check 'setup says when Frivo is here without the app, and that nothing needs uninstalling' ($install -match 'Frivo is installed here without the app\. To add it, choose the first option: nothing needs uninstalling')
Check 'and when the app is here without Frivo' ($install -match 'The Frivo app is already installed here\. Choose the first option to add Frivo itself')
Check 'setup offers a backup before an update or repair' ($install -match '\$chkSetupBackup = New-FrivoCheck' -and $install -match '\$script:wantBackup = \$chkSetupBackup\.Visible -and \$chkSetupBackup\.Checked')
Check 'and makes it before Install-Frivo stops or changes anything' ($install -match '(?s)if \(\$script:wantBackup\).{0,3000}\$script:launcherPath = Install-Frivo')
Check 'a failed backup stops setup unless you say to go on' ($install -match 'Setup stopped before changing anything, since the backup could not be made')
Check 'uninstalling asks keep or delete, keep by default' ($uninstall -match '\$radioKeep = New-FrivoRadio .*-Checked \$true' -and $uninstall -match '\$radioDelete = New-FrivoRadio')
Check 'with a backup first' ($uninstall -match '\$chkBackup = New-FrivoCheck' -and $uninstall -match 'New-FrivoBackup -DataDir \$DataDir')
Check 'and settings are kept if the backup fails' ($uninstall -match 'Kept your settings and saves, since the backup could not be made')
Check 'a silent uninstall can make one too, and -RemoveApp survives elevation' ($uninstall -match "if \(\`$Backup\)\s+\{ \`$relaunch \+= '-Backup' \}" -and $uninstall -match "if \(\`$RemoveApp\)\s+\{ \`$relaunch \+= '-RemoveApp' \}")
$folder = Get-FrivoBackupFolder -RoamingAppData $env:APPDATA
Check 'backups go to Documents\Frivo backups' ($folder -match 'Frivo backups$') $folder


# NEW (2.0.0): the app built with this setup (Build.bat), used from beside it
$src = Get-Content -LiteralPath (Join-Path $root 'installer/Install.ps1') -Raw
$ast = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref] $null, [ref] $null)
$fn = $ast.Find({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $args[0].Name -eq 'Find-FrivoLocalAppInstaller' }, $true)
. ([scriptblock]::Create($fn.Extent.Text))
$pkg = Join-Path $work 'pkg'
$ScriptDir = Join-Path $pkg 'installer'
$PackageDir = $pkg
$beside = Join-Path $work 'Downloads'
New-Item -ItemType Directory -Path $ScriptDir, $beside -Force | Out-Null
$appFile = Join-Path $beside 'FrivoApp-Setup-1.2.0.exe'
[System.IO.File]::WriteAllText($appFile, 'the app built with this setup')
Check 'without bundled-app.json, nothing local is used' ($null -eq (Find-FrivoLocalAppInstaller))
[System.IO.File]::WriteAllText((Join-Path $pkg 'setup-folder.txt'), $beside)
$good = (Get-FileHash -LiteralPath $appFile -Algorithm SHA256).Hash
[System.IO.File]::WriteAllText((Join-Path $ScriptDir 'bundled-app.json'), (@{ name = 'FrivoApp-Setup-1.2.0.exe'; sha256 = $good } | ConvertTo-Json))
$found = Find-FrivoLocalAppInstaller
Check 'the app built with this setup is found beside FrivoSetup.exe' ($found -and $found.Path -eq $appFile -and $found.Version -eq [version] '1.2.0') $found
[System.IO.File]::WriteAllText($appFile, 'something else with the same name')
Check 'a file with the right name but other contents is never used' ($null -eq (Find-FrivoLocalAppInstaller))
[System.IO.File]::WriteAllText((Join-Path $beside 'FrivoApp-Setup-9.9.9.exe'), 'x')
Check 'nor any other FrivoApp-Setup file in that folder' ($null -eq (Find-FrivoLocalAppInstaller))
$build = Get-Content -LiteralPath (Join-Path $root 'build/Build.ps1') -Raw
Check 'Build.bat writes the app''s fingerprint into the setup it builds' ($build -match 'installer\\bundled-app\.json' -and $build -match "Get-FileHash -LiteralPath \`$appBuilt -Algorithm SHA256")
Check 'and puts the app beside FrivoSetup.exe' ($build -match 'Copy-Item -LiteralPath \$appBuilt -Destination \(Join-Path \$dist \$appName\)')
$iss = Get-Content -LiteralPath (Join-Path $root 'build/Frivo.iss') -Raw
Check 'setup tells Install.ps1 the folder it was run from' ($iss -match "setup-folder\.txt'\), ExpandConstant\('\{src\}'\)")


# NEW (2.0.0): one "Frivo" in Apps & features
$appPkg = Get-Content -LiteralPath (Join-Path $root 'desktop/package.json') -Raw | ConvertFrom-Json
Check 'the app is called Frivo' ($appPkg.productName -eq 'Frivo' -and $appPkg.build.productName -eq 'Frivo' -and $appPkg.build.nsis.uninstallDisplayName -eq 'Frivo')
Check 'but keeps its own settings folder, not Frivo''s' ((Get-Content -LiteralPath (Join-Path $root 'desktop/src/main.js') -Raw) -match "path\.join\(app\.getPath\('appData'\), 'Frivo App'\)")
$oldDir = Join-Path $work 'oldapp'
New-Item -ItemType Directory -Path (Join-Path $oldDir 'Programs/frivo-app') -Force | Out-Null
[System.IO.File]::WriteAllText((Join-Path $oldDir 'Programs/frivo-app/Uninstall Frivo App.exe'), 'x')
$oldPaths = Get-FrivoAppPaths -LocalAppData $oldDir
Check 'an app from before the rename is still found and removed by its old uninstaller' ((& $norm $oldPaths.Uninstaller) -like '*/Uninstall Frivo App.exe') $oldPaths.Uninstaller
$nsh = Get-Content -LiteralPath (Join-Path $root 'desktop/build/installer.nsh') -Raw
Check 'with Frivo installed, the app''s installer hides its own entry' ($nsh -match 'Uninstall\\Frivo" "DisplayName"' -and $nsh -match 'WriteRegDWORD SHELL_CONTEXT "\$\{UNINSTALL_REGISTRY_KEY\}" "SystemComponent" 1')
Check 'and setup does too' ($install -match 'Set-FrivoAppListed -User \$person\.User -Listed \$false')
$uninstall = Get-Content -LiteralPath (Join-Path $root 'installer/Uninstall.ps1') -Raw
Check 'uninstalling Frivo but keeping the app lists the app again' ($uninstall -match 'Set-FrivoAppListed -User \(Get-FrivoDesktopUser\)\.User -Listed \$true')

Remove-Item -LiteralPath $work -Recurse -Force
Write-Host ''
if ($failures) { Write-Host "$failures failed"; exit 1 } else { Write-Host 'All app setup checks passed.' }
