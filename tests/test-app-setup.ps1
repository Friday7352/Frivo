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

# CHANGED (2.0.0): the app is inside FrivoSetup.exe now, not on GitHub, so
# there are no app releases to pick or download.
$work = Join-Path ([System.IO.Path]::GetTempPath()) ('frivo-app-setup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null

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
Check 'setup says when Frivo is here without the app, and that nothing needs uninstalling' ($install -match 'Installed here now: Frivo without the app, so that' -and $install -match 'To add the app, choose the first option: nothing needs uninstalling')
# CHANGED (2.0.0): what's installed is picked to start with.
Check 'with just the app here, "Just the app" is picked, so an update keeps it that way' ($install -match '(?s)installedRole -eq ''App''\) \{.{0,80}\$radioApp\.Checked = \$true')
Check 'with Frivo without the app, "without the app" is picked' ($install -match "Role -eq 'Server'\) \{ \`$radioServer\.Checked = \`$true \}")
Check 'an install whose app was removed says setup puts it back' ($install -match 'but the app itself is missing')
Check 'the existing-install page says which kind it is' ($install -match "' \(without the app\)'" -and $install -match "' \(in the Frivo app\)'")
Check 'setup offers a backup before an update or repair' ($install -match '\$chkSetupBackup = New-FrivoCheck' -and $install -match '\$script:wantBackup = \$chkSetupBackup\.Visible -and \$chkSetupBackup\.Checked')
Check 'and makes it before Install-Frivo stops or changes anything' ($install -match '(?s)if \(\$script:wantBackup\).{0,3000}\$script:launcherPath = Install-Frivo')
Check 'a failed backup stops setup unless you say to go on' ($install -match 'Setup stopped before changing anything, since the backup could not be made')
Check 'uninstalling asks keep or delete, keep by default' ($uninstall -match '\$radioKeep = New-FrivoRadio .*-Checked \$true' -and $uninstall -match '\$radioDelete = New-FrivoRadio')
Check 'with a backup first' ($uninstall -match '\$chkBackup = New-FrivoCheck' -and $uninstall -match 'New-FrivoBackup -DataDir \$DataDir')
Check 'and settings are kept if the backup fails' ($uninstall -match 'Kept your settings and saves, since the backup could not be made')
Check 'a silent uninstall can make one too, and -RemoveApp survives elevation' ($uninstall -match "if \(\`$Backup\)\s+\{ \`$relaunch \+= '-Backup' \}" -and $uninstall -match "if \(\`$RemoveApp\)\s+\{ \`$relaunch \+= '-RemoveApp' \}")
$folder = Get-FrivoBackupFolder -RoamingAppData $env:APPDATA
Check 'backups go to Documents\Frivo backups' ($folder -match 'Frivo backups$') $folder


# CHANGED (2.0.0): the app is inside FrivoSetup.exe (installer\app\ in its payload)
$src = Get-Content -LiteralPath (Join-Path $root 'installer/Install.ps1') -Raw
$ast = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref] $null, [ref] $null)
$fn = $ast.Find({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $args[0].Name -eq 'Get-FrivoBundledApp' }, $true)
. ([scriptblock]::Create($fn.Extent.Text))
$pkg = Join-Path $work 'pkg'
$ScriptDir = Join-Path $pkg 'installer'
$PackageDir = $pkg
New-Item -ItemType Directory -Path (Join-Path $ScriptDir 'app'), (Join-Path $pkg 'desktop/dist') -Force | Out-Null
Check 'no app in the setup or the source tree: none' ($null -eq (Get-FrivoBundledApp))
foreach ($v in @('1.0.0', '1.2.0', '1.10.0')) { [System.IO.File]::WriteAllText((Join-Path $pkg "desktop/dist/FrivoApp-Setup-$v.exe"), 'x') }
$found = Get-FrivoBundledApp
Check 'run from the source tree, the newest built app is used' ($found -and $found.Version -eq [version] '1.10.0') $found.Version
[System.IO.File]::WriteAllText((Join-Path $ScriptDir 'app/FrivoApp-Setup.exe'), 'the app inside the setup')
[System.IO.File]::WriteAllText((Join-Path $ScriptDir 'app/app.json'), '{"version":"1.3.0"}')
$found = Get-FrivoBundledApp
Check 'the app inside the setup comes first, with its version' ($found -and $found.Path -like '*installer*app*FrivoApp-Setup.exe' -and $found.Version -eq [version] '1.3.0') $found
$build = Get-Content -LiteralPath (Join-Path $root 'build/Build.ps1') -Raw
Check 'Build.bat puts the app into the setup' ($build -match "Copy-Item -LiteralPath \`$appBuilt -Destination \(Join-Path \`$payload 'FrivoApp-Setup.exe'\)")
$iss = Get-Content -LiteralPath (Join-Path $root 'build/Frivo.iss') -Raw
Check 'and Frivo.iss packs it' ($iss -match 'Source: "app\\\*";\s+DestDir: "\{tmp\}\\FrivoSetupPayload\\installer\\app"')
Check 'setup keeps the app installer beside Frivo for the app to update from' ($install -match 'Copy-FrivoAppInstaller -Target \$Target -Log \$Log')
Check 'and nothing about the app is downloaded from GitHub any more' ($install -notmatch 'Get-FrivoAppReleasesApi|Select-FrivoAppRelease')


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


# NEW (2.0.0): FrivOSC built into the app
Check 'setup offers to remove the separate FrivOSC when the app is installed' ($install -match '\$chkRemoveOSC = New-FrivoCheck' -and $install -match 'Remove-FrivoStandaloneOSC -Log \$Log')
Check 'only by its own uninstaller, silently, told its folder (1.2.0 can''t work it out)' ($install -match "FrivOSC-Uninstall\.ps1" -and $install -match "'-Silent',\s+'-InstallPath', \('`"\{0\}`"' -f \`$folder\)")
Check 'not when choosing Frivo without the app' ($install -match '\$chkRemoveOSC\.Enabled = -not \$radioServer\.Checked')

Check 'an installed app reported as 1.0.0.0 counts as 1.0.0, so the same version is reinstalled' ($install -match '\$installed = \[version\]::new\(\$v\.Major, \$v\.Minor, \[Math\]::Max\(\$v\.Build, 0\)\)')

Remove-Item -LiteralPath $work -Recurse -Force
Write-Host ''
if ($failures) { Write-Host "$failures failed"; exit 1 } else { Write-Host 'All app setup checks passed.' }
