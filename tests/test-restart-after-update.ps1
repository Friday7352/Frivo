<#
    NEW (restart): Frivo is started again after an in-app update.

        pwsh -NoProfile -File tests/test-restart-after-update.ps1

    Frivo usually runs on a PC nobody is sitting at, and is updated from a
    browser somewhere else. When an update stopped it and nothing started
    it again, it stayed down until someone walked over to that PC.

    The restart is done by setup (Install.ps1's silent update), not by the
    updater: during an update the updater that runs is the OLD version's,
    while setup is always the NEW one — so a fix here works on the very next
    update. Setup notes who Frivo is running as before stopping it, and
    afterwards starts it again as them, through a one-off Interactive
    scheduled task (SYSTEM cannot start it directly without it running as
    SYSTEM, invisibly, with the wrong settings).

    The functions are lifted out of Install.ps1 and run for real under
    StrictMode, with Windows' process list and Task Scheduler replaced.
    Exits non-zero on failure.
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Import-Module (Join-Path $Root 'installer/Frivo.Setup.psm1') -Force

$script:failures = 0
function Check {
    param([string] $Name, [bool] $Condition, $Got = $null)
    if ($Condition) { Write-Host ('  PASS  ' + $Name) }
    else { Write-Host ('  FAIL  ' + $Name + '   got=' + [string] $Got); $script:failures++ }
}

$installPath = Join-Path $Root 'installer/Install.ps1'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($installPath, [ref] $null, [ref] $null)
foreach ($name in @('Get-FrivoRunningUsers', 'Test-FrivoRunningFrom', 'Start-FrivoAsUser')) {
    $fn = $ast.Find({
        param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name
    }, $true)
    if (-not $fn) { Write-Host ('Missing function: ' + $name); exit 1 }
    Invoke-Expression $fn.Extent.Text
}

# --- a pretend machine -------------------------------------------------------
$target = Join-Path ([IO.Path]::GetTempPath()) ('frivo-restart-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $target | Out-Null
Set-Content -LiteralPath (Join-Path $target 'Frivo.vbs') -Value "' shim"
$elsewhere = Join-Path ([IO.Path]::GetTempPath()) 'SomeOtherApp'

function Fake([int] $Id, [string] $Name, [string] $Path, [string] $Domain, [string] $User) {
    [pscustomobject] @{ ProcessId = $Id; Name = $Name; ExecutablePath = $Path; Domain = $Domain; User = $User }
}
$script:processes = @()
$script:cimFails = $false
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($script:cimFails) { throw 'WMI is unavailable' }
    $script:processes
}
function Invoke-CimMethod {
    param($InputObject, $MethodName, $ErrorAction)
    [pscustomobject] @{ ReturnValue = 0; Domain = $InputObject.Domain; User = $InputObject.User }
}
$script:log = @()
function Write-SetupLog { param($Message) $script:log += , $Message }
function Start-Sleep { param([int] $Milliseconds, [int] $Seconds) }

# Task Scheduler, recorded.
$script:tasks = @()
$script:started = @()
$script:removed = @()
$script:onStart = { }
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory) [pscustomobject] @{ Execute = $Execute; Argument = $Argument } }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) [pscustomobject] @{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel } }
function New-ScheduledTaskSettingsSet { param([switch] $AllowStartIfOnBatteries, [switch] $DontStopIfGoingOnBatteries, $ExecutionTimeLimit) [pscustomobject] @{ ExecutionTimeLimit = $ExecutionTimeLimit } }
function Register-ScheduledTask { param($TaskName, $Action, $Principal, $Settings, [switch] $Force) $script:tasks += , [pscustomobject] @{ Name = $TaskName; Action = $Action; Principal = $Principal; Settings = $Settings } }
function Start-ScheduledTask { param($TaskName) $script:started += $TaskName; & $script:onStart }
function Unregister-ScheduledTask { param($TaskName, [switch] $Confirm, $ErrorAction) $script:removed += $TaskName }

$server   = Fake 11 'pythonw.exe'   (Join-Path $target '.venv/Scripts/pythonw.exe') 'FRIVOBOX' 'Payton'
$launcher = Fake 12 'FrivoHost.exe' (Join-Path $target 'installer/FrivoHost.exe')    'FRIVOBOX' 'Payton'
$system   = Fake 13 'pythonw.exe'   (Join-Path $target '.venv/Scripts/pythonw.exe') 'NT AUTHORITY' 'SYSTEM'
$other    = Fake 14 'python.exe'    (Join-Path $elsewhere 'python.exe')             'FRIVOBOX' 'Someone'

try {
    Write-Host '--- who Frivo is running as ---'
    $script:processes = @($server, $launcher, $other)
    $users = Get-FrivoRunningUsers -Target $target
    Check 'the account running Frivo, once (server and launcher are the same person)' (($users -join ',') -eq 'FRIVOBOX\Payton') ($users -join ',')
    Check 'not someone else''s Python from another folder' (-not ($users -contains 'FRIVOBOX\Someone'))

    $script:processes = @($system)
    $users = Get-FrivoRunningUsers -Target $target
    Check 'never SYSTEM: Frivo started as it would run invisibly with the wrong settings' ($users.Count -eq 0) ($users -join ',')

    $script:processes = @()
    $users = Get-FrivoRunningUsers -Target $target
    Check 'Frivo not running: nobody to restart (an empty list, not $null)' ($null -ne $users -and $users.Count -eq 0)

    $script:cimFails = $true
    $users = Get-FrivoRunningUsers -Target $target
    Check 'Windows'' process list unavailable: nobody, and no error' ($null -ne $users -and $users.Count -eq 0)
    $script:cimFails = $false

    Write-Host ''
    Write-Host '--- starting it again ---'
    $script:processes = @()
    $script:onStart = { $script:processes = @($server, $launcher) }   # Windows starts it
    $ok = Start-FrivoAsUser -Target $target -User 'FRIVOBOX\Payton'
    $task = $script:tasks[-1]
    Check 'Frivo is started again' ($ok -eq $true)
    Check 'as that user' ($task.Principal.UserId -eq 'FRIVOBOX\Payton') $task.Principal.UserId
    Check 'in their own session, no password (Interactive)' ([string] $task.Principal.LogonType -eq 'Interactive') $task.Principal.LogonType
    Check 'without administrator rights' ([string] $task.Principal.RunLevel -eq 'Limited') $task.Principal.RunLevel
    Check 'the way sign-in does: Frivo.vbs -Tray, through wscript' ($task.Action.Execute -match 'wscript\.exe$' -and $task.Action.Argument -match 'Frivo\.vbs" -Tray$') ($task.Action.Execute + ' ' + $task.Action.Argument)
    Check 'with no time limit (the default ends it after three days)' ($task.Settings.ExecutionTimeLimit -eq [TimeSpan]::Zero) $task.Settings.ExecutionTimeLimit
    Check 'and the one-off task is removed afterwards' ($script:removed -contains 'Frivo Restart')

    $script:removed = @()
    $script:processes = @()
    $script:onStart = { }   # the user is not signed in: nothing comes up
    $ok = Start-FrivoAsUser -Target $target -User 'FRIVOBOX\Payton'
    Check 'when nothing comes up, it says so instead of claiming success' ($ok -eq $false)
    Check 'and still removes the task' ($script:removed -contains 'Frivo Restart')

    Remove-Item -LiteralPath (Join-Path $target 'Frivo.vbs')
    $count = $script:tasks.Count
    $ok = Start-FrivoAsUser -Target $target -User 'FRIVOBOX\Payton'
    Check 'no launcher script: nothing is registered' ($ok -eq $false -and $script:tasks.Count -eq $count)

    Write-Host ''
    Write-Host '--- wired into the silent update ---'
    $text = [System.IO.File]::ReadAllText($installPath)
    $silent = $text.Substring($text.IndexOf('if ($Silent) {'))
    $capture = $silent.IndexOf('$restartUsers = Get-FrivoRunningUsers -Target $target')
    $install = $silent.IndexOf('Install-Frivo -Target $target')
    Check 'who Frivo runs as is noted before setup stops it' ($capture -gt 0 -and $capture -lt $install) "$capture / $install"
    Check 'the restart runs in finally: after a failed update too' ($silent -match '(?s)\} finally \{.*foreach \(\$user in \$restartUsers\).*Start-FrivoAsUser')
    Check 'and not when Frivo is already back (a second launcher pops the first open)' ($silent -match 'if \(Test-FrivoRunningFrom \$restartTarget\) \{ break \}')
    Check 'the caller does not wrap the ,@() result in @() again' ($silent -notmatch '@\(Get-FrivoRunningUsers')

    $watch = [System.IO.File]::ReadAllText((Join-Path $Root 'installer/Update-Watch.ps1'))
    Check 'the watcher does not start a second Frivo when setup already did' ($watch -match '(?s)function Start-Frivo \{.*if \(Test-FrivoRunning\) \{')
} finally {
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
if ($script:failures) { Write-Host ('{0} restart check(s) failed.' -f $script:failures); exit 1 }
Write-Host 'All restart checks passed.'
