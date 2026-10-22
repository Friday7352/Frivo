<#
    NEW (updates): the updater's decisions, run for real against a sample of
    GitHub's release list (tests/fixtures/github-releases.json).

        pwsh -NoProfile -File tests/test-update-logic.ps1

    Covers what the SYSTEM task decides on its own: which releases count,
    which one a request may install, whether a download is the published
    file, what a request file may say, and the shape of the files around it
    (Install.ps1 ships the updater, Frivo.iss never opens the wizard on a
    silent run, FrivoHost never shows a box nobody can see). The same
    fixture is parsed by app.py in test-updates.py, which also checks both
    sides reach the same list.

    Exits non-zero on failure.
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Import-Module (Join-Path $Root 'installer/Frivo.Update.psm1') -Force

$script:failures = 0
function Check {
    param([string] $Name, [bool] $Condition, $Got = $null)
    if ($Condition) {
        Write-Host ('  PASS  ' + $Name)
    } else {
        Write-Host ('  FAIL  ' + $Name + '   got=' + [string] $Got)
        $script:failures++
    }
}
function Throws {
    param([string] $Name, [scriptblock] $Block, [string] $Pattern)
    try {
        & $Block | Out-Null
        Check $Name $false 'no error'
    } catch {
        Check $Name ($_.Exception.Message -match $Pattern) $_.Exception.Message
    }
}

$policy = Get-FrivoUpdatePolicy -Path (Join-Path $Root 'installer/update-policy.json')
$json = Get-Content -LiteralPath (Join-Path $Root 'tests/fixtures/github-releases.json') -Raw

Write-Host '--- policy ---'
Check 'repository is read' ($policy.Repository -eq 'Friday7352/Frivo') $policy.Repository
Check 'only this repository''s downloads are trusted' ($policy.DownloadPrefix -eq 'https://github.com/Friday7352/Frivo/releases/download/') $policy.DownloadPrefix
Check 'oldest version to go back to is the first that can update itself' ($policy.OldestRollback -eq [version] '1.4.0') $policy.OldestRollback

$bad = Join-Path ([System.IO.Path]::GetTempPath()) ('policy-{0}.json' -f [guid]::NewGuid())
Set-Content -LiteralPath $bad -Value '{"repository":"../evil","asset":"FrivoSetup.exe","oldest_rollback":"1.4.0"}'
Throws 'a repository that is not owner/name is refused' { Get-FrivoUpdatePolicy -Path $bad } 'repository'
Set-Content -LiteralPath $bad -Value '{"repository":"a/b","asset":"..\\x.exe","oldest_rollback":"1.4.0"}'
Throws 'an asset name with a path in it is refused' { Get-FrivoUpdatePolicy -Path $bad } 'installer'
Remove-Item -LiteralPath $bad -Force
Throws 'a missing policy file is refused' { Get-FrivoUpdatePolicy -Path (Join-Path $Root 'nope.json') } 'missing'

Write-Host ''
Write-Host '--- versions ---'
Check '"v1.4.0" is 1.4.0' ((ConvertTo-FrivoVersion 'v1.4.0') -eq [version] '1.4.0')
Check '"1.4" is 1.4.0' ((ConvertTo-FrivoVersion '1.4') -eq [version] '1.4.0')
Check '"V2" is 2.0.0' ((ConvertTo-FrivoVersion 'V2') -eq [version] '2.0.0')
Check '"nightly" is not a version' ($null -eq (ConvertTo-FrivoVersion 'nightly'))
Check '"1.4.0.1" is not a version (three parts, like app.py)' ($null -eq (ConvertTo-FrivoVersion '1.4.0.1'))
Check '"../1.4.0" is not a version' ($null -eq (ConvertTo-FrivoVersion '../1.4.0'))
Check 'empty is not a version' ($null -eq (ConvertTo-FrivoVersion ''))

Write-Host ''
Write-Host '--- the release list ---'
$releases = ConvertFrom-FrivoReleaseList -Json $json -Policy $policy
$versions = @($releases | ForEach-Object { $_.VersionText }) -join ','
Check 'installable releases, newest first, each once' ($versions -eq '1.5.0,1.4.5,1.4.0,1.3.0,1.1.0') $versions
$v150 = $releases | Where-Object { $_.VersionText -eq '1.5.0' }
Check 'a version listed twice keeps the first GitHub lists' ($v150.Sha256 -eq ('b' * 64)) $v150.Sha256
Check 'the fingerprint is read from "sha256:<hex>" and lowercased' ($v150.Sha256 -eq ('b' * 64))
Check 'the size is read' ($v150.Size -eq 2275000) $v150.Size
$v145 = $releases | Where-Object { $_.VersionText -eq '1.4.5' }
Check 'a release with no digest is listed without a fingerprint' ($null -eq $v145.Sha256)
Check 'a release page that is not on github.com is replaced' ($v145.PageUrl -eq $policy.ReleasesPage) $v145.PageUrl
$v110 = $releases | Where-Object { $_.VersionText -eq '1.1.0' }
Check 'a digest that is not sha256 counts as none' ($null -eq $v110.Sha256)
Check 'asset names match without regard to case' (($releases | Where-Object { $_.VersionText -eq '1.4.0' }).Tag -eq 'V1.4')
Check 'pre-releases, drafts, non-version tags, other repositories and releases without the installer are left out' (
    -not ($releases | Where-Object { $_.VersionText -in @('1.4.1', '1.6.0', '1.4.2', '1.2.0') }))
$single = ConvertFrom-FrivoReleaseList -Json '[]' -Policy $policy
Check 'an empty list is an empty array, not $null' ($null -ne $single -and $single.Count -eq 0)

Write-Host ''
Write-Host '--- what a request may install ---'
$current = [version] '1.4.0'
$t = Select-FrivoUpdateTarget -Releases $releases -Version '1.5.0' -Current $current -Policy $policy -RequireFingerprint
Check 'a newer release is an update' ($t.VersionText -eq '1.5.0')
$t = Select-FrivoUpdateTarget -Releases $releases -Version 'v1.4.0' -Current ([version] '1.5.0') -Policy $policy -RequireFingerprint
Check 'an older release, not below the floor, is going back' ($t.VersionText -eq '1.4.0')
Throws 'the installed version is refused' {
    Select-FrivoUpdateTarget -Releases $releases -Version '1.4.0' -Current $current -Policy $policy -RequireFingerprint } 'already installed'
Throws 'below the floor is refused, and says why' {
    Select-FrivoUpdateTarget -Releases $releases -Version '1.3.0' -Current $current -Policy $policy -RequireFingerprint } 'oldest version that can update itself'
Throws 'no fingerprint is refused when one is required' {
    Select-FrivoUpdateTarget -Releases $releases -Version '1.4.5' -Current $current -Policy $policy -RequireFingerprint } 'fingerprint'
Throws 'a version that is not a release is refused' {
    Select-FrivoUpdateTarget -Releases $releases -Version '9.9.9' -Current $current -Policy $policy -RequireFingerprint } 'not a release'
Throws 'a pre-release cannot be asked for by name' {
    Select-FrivoUpdateTarget -Releases $releases -Version '1.4.1' -Current $current -Policy $policy -RequireFingerprint } 'not a release'
Throws 'nonsense is refused' {
    Select-FrivoUpdateTarget -Releases $releases -Version 'latest' -Current $current -Policy $policy } 'not a version'

Write-Host ''
Write-Host '--- the download ---'
$file = Join-Path ([System.IO.Path]::GetTempPath()) ('frivo-setup-{0}.exe' -f [guid]::NewGuid())
[System.IO.File]::WriteAllBytes($file, [byte[]] (1..200))
$hash = Get-FrivoFileSha256 -Path $file
Check 'the matching file passes' (Test-FrivoDownloadedFile -Path $file -Size 200 -Sha256 $hash.ToUpperInvariant())
Throws 'a short file is refused' { Test-FrivoDownloadedFile -Path $file -Size 201 -Sha256 $hash } 'cut short'
Throws 'a different file is refused' { Test-FrivoDownloadedFile -Path $file -Size 200 -Sha256 ('0' * 64) } 'does not match'
Throws 'no fingerprint means no install' { Test-FrivoDownloadedFile -Path $file -Size 200 -Sha256 '' } 'no published fingerprint'
Remove-Item -LiteralPath $file -Force

Write-Host ''
Write-Host '--- the request file ---'
$dir = Join-Path ([System.IO.Path]::GetTempPath()) ('frivo-upd-{0}' -f [guid]::NewGuid())
New-Item -ItemType Directory -Path $dir | Out-Null
$req = Join-Path $dir 'request.json'
Set-Content -LiteralPath $req -Value '{"id":"0123456789abcdef","version":"v1.5"}'
$r = Read-FrivoUpdateRequest -Path $req
Check 'a good request is read, version normalised' ($r.Id -eq '0123456789abcdef' -and $r.Version -eq '1.5.0') ($r | ConvertTo-Json -Compress)
Set-Content -LiteralPath $req -Value '{"id":"..\\..\\x","version":"1.5.0"}'
Throws 'an id that is not an id is refused' { Read-FrivoUpdateRequest -Path $req } 'not valid'
Set-Content -LiteralPath $req -Value '{"id":"0123456789abcdef","version":"C:\\evil.exe"}'
Throws 'a version that is a path is refused' { Read-FrivoUpdateRequest -Path $req } 'no version'
Set-Content -LiteralPath $req -Value ('{"id":"0123456789abcdef","version":"1.5.0","pad":"' + ('x' * 5000) + '"}')
Throws 'an oversized request is refused' { Read-FrivoUpdateRequest -Path $req } 'not valid'
Set-Content -LiteralPath $req -Value 'not json'
Throws 'a request that is not JSON is refused' { Read-FrivoUpdateRequest -Path $req } 'not valid'
Remove-Item -LiteralPath $req -Force
Throws 'no request at all is reported as such' { Read-FrivoUpdateRequest -Path $req } 'No update was requested'

Write-Host ''
Write-Host '--- the status file ---'
$statusPath = Join-Path $dir 'status.json'
Write-FrivoUpdateStatus -Path $statusPath -Status @{ id = 'abc12345'; state = 'downloading'; received = 10; total = 20; restart = $false }
Write-FrivoUpdateStatus -Path $statusPath -Status @{ id = 'abc12345'; state = 'installing'; received = 20; total = 20; restart = $true }
$s = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
Check 'status.json holds the latest state' ($s.state -eq 'installing' -and $s.restart -eq $true) ($s | ConvertTo-Json -Compress)
Check 'and when it was written' ([bool] $s.updated_utc)
Check 'no temporary files are left behind' (@(Get-ChildItem -LiteralPath $dir -Force).Count -eq 1)
Remove-Item -LiteralPath $dir -Recurse -Force

Write-Host ''
Write-Host '--- setup''s reason ---'
$log = "[x] Silent Update`r`n[x] FAILED: first`r`n[x] silent: Copying`r`n[x] FAILED: The existing Python environment is incomplete."
Check 'the last FAILED line is the reason' ((Get-FrivoSetupFailure -LogText $log) -eq 'The existing Python environment is incomplete.')
Check 'no FAILED line, no reason' ((Get-FrivoSetupFailure -LogText 'all good') -eq '')

Write-Host ''
Write-Host '--- the files around it ---'
function Read-Source([string] $Relative) { return [System.IO.File]::ReadAllText((Join-Path $Root $Relative)) }
function Strip-PsComments([string] $Text) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($Text, [ref] $tokens, [ref] $errors)
    $out = $Text
    foreach ($tok in ($tokens | Where-Object { $_.Kind -eq 'Comment' } | Sort-Object { $_.Extent.StartOffset } -Descending)) {
        $out = $out.Remove($tok.Extent.StartOffset, $tok.Extent.EndOffset - $tok.Extent.StartOffset)
    }
    return $out
}
$worker = Strip-PsComments (Read-Source 'installer/Update-Frivo.ps1')
Check 'the task demands a fingerprint' ($worker -match 'Select-FrivoUpdateTarget[^\r\n]*`?\s*[\s\S]{0,120}-RequireFingerprint')
Check 'the task checks the download before running it' ($worker.IndexOf('Test-FrivoDownloadedFile') -lt $worker.IndexOf('Start-Process -FilePath $setup'))
Check 'the task runs setup silently' ($worker -match '/VERYSILENT')
Check 'the task downloads into the program folder, not a shared one' ($worker.Contains('[System.IO.Path]::Combine($InstallDir, ''updates'')'))
Check 'the task resets its folder''s permissions before using it' ($worker.IndexOf('Initialize-FrivoUpdateFolder') -lt $worker.IndexOf('Read-FrivoUpdateRequest -Path'))

# NEW (restart): when the watcher does not start Frivo again, the task does.
Check 'the task makes sure Frivo is started again after setup stopped it' ($worker -match 'if \(\$status\.restart -and \$isSystem\)\s*\{\s*try \{ Restart-FrivoIfNeeded')
Check 'as the person who asked, read from who owns the request file' ($worker.IndexOf('Get-RequestOwner -Path $RequestPath') -lt $worker.IndexOf('Remove-Item -LiteralPath $RequestPath'))
Check 'in their own session, without a password (Interactive)' ($worker -match '-LogonType Interactive')
Check 'and only when nothing from this install is running (not a port check)' ($worker -match 'function Restart-FrivoIfNeeded[\s\S]*Test-FrivoRunning' -and $worker -notmatch 'TcpClient')
Check 'the one-off task is always removed' ($worker -match 'finally \{\s*try \{ Unregister-ScheduledTask -TaskName \$taskName')

$install = Strip-PsComments (Read-Source 'installer/Install.ps1')
foreach ($name in @('Frivo.Update.psm1', 'Update-Frivo.ps1', 'Update-Watch.ps1', 'update-policy.json')) {
    Check ('setup installs {0}' -f $name) ($install -match [regex]::Escape("'$name'"))
}
Check 'setup registers the updater on every action' ($install -match 'Register-FrivoUpdater -Target \$Target')
Check 'a silent update refuses a half-installed Frivo' ($install -match "Action -eq 'Update' -and \`$existing\.State -ne 'Installed'")
Check 'silent mode logs FAILED: before giving up' ($install -match "Write-SetupLog \('FAILED: '")
Check 'silent mode never writes to a host that is not there' (-not ($install -match '(?s)if \(\$Silent\).{0,4000}Write-Host'))

$iss = Read-Source 'build/Frivo.iss'
Check 'the wizard never opens on a silent run' ($iss -match 'Check: not WizardSilent')
Check 'a silent run updates through FrivoHost --silent' ($iss -match '--silent --action Update')
Check 'and reports failure as the exit code' ($iss -match 'function GetCustomSetupExitCode')

$hostCs = Read-Source 'build/FrivoHost.cs'
$boxes = [regex]::Matches($hostCs, 'MessageBox\.Show').Count
$guarded = [regex]::Matches($hostCs, 'if \(!silent\)[^\n]*\r?\n\s*MessageBox\.Show').Count
Check 'FrivoHost shows no message box when silent' ($boxes -gt 0 -and $boxes -eq $guarded) ('{0} boxes, {1} guarded' -f $boxes, $guarded)

$launcher = Strip-PsComments (Read-Source 'installer/Launcher.ps1')
Check 'the launcher closes when the watcher asks' ($launcher -match 'Local\\FrivoLauncherQuit' -and $launcher -match 'quitSignal\.WaitOne\(0\)')
$watch = Read-Source 'installer/Update-Watch.ps1'
Check 'the watcher asks with the same name' ($watch -match "OpenExisting\('Local\\FrivoLauncherQuit'\)")

# NEW (1.8.0): the Frivo app (desktop\) and the launcher's app mode agree.
$appLocal = Read-Source 'desktop/src/frivo-local.js'
Check 'the launcher stops Frivo when the app asks' ($launcher -match 'Local\\FrivoLauncherStop' -and $launcher -match 'stopSignal\.WaitOne\(0\)')
Check 'the app asks with the same name' ($appLocal -match "OpenExisting\('Local\\\\FrivoLauncherStop'\)")
Check 'the app writes appPath, which the launcher reads' ($appLocal -match 'settings\.appPath = want' -and $launcher -match "raw\.PSObject\.Properties\['appPath'\]")
Check 'no tray icon in app mode' ($launcher -match '\$notify\.Visible = -not \$script:appMode')
Check 'app mode never opens the browser' ($launcher -match 'openBrowser -and -not \$script:appMode')
Check 'never app mode as administrator: nobody could stop it' ($launcher -match 'if \(\$script:elevated\) \{ return \$false \}')
Check 'a second launcher in the background starts the server without showing anything' ($launcher -match 'if \(\$Tray\) \{ \[void\] \$startSignal\.Set\(\) \} else \{ \[void\] \$showSignal\.Set\(\) \}')
Check 'old show and start requests are cleared' ($launcher -match '\[void\] \$showSignal\.Reset\(\)\s+\[void\] \$startSignal\.Reset\(\)')
$install = Strip-PsComments (Read-Source 'installer/Install.ps1')
Check 'Launch Frivo now starts it as the signed-in person' ($install -match 'Start-FrivoAsUser -Target \$txtPath\.Text -User \$desktopUser -Window')
Check 'the app waits for a stop to finish' ($appLocal -match 'Mutex\]::TryOpenExisting' -and $appLocal -match 'Test-Port')

$uninstall = Strip-PsComments (Read-Source 'installer/Uninstall.ps1')
Check 'uninstall removes the updater task' ($uninstall -match 'Unregister-FrivoUpdaterTask -InstallDir \$InstallDir')

$module = Strip-PsComments (Read-Source 'installer/Frivo.Update.psm1')
Check 'only Authenticated Users may start the task, and only admins change it' ($module -match "D:\(A;;FA;;;SY\)\(A;;FA;;;BA\)\(A;;GRGX;;;AU\)")
Check 'the task runs as SYSTEM' ($module -match "Principal\.UserId = 'S-1-5-18'")

Write-Host ''
if ($script:failures) {
    Write-Host ('{0} update check(s) failed.' -f $script:failures)
    exit 1
}
Write-Host 'All update checks passed.'
