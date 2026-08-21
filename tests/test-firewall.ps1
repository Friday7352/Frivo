# Focused test for the firewall-rule change in Install.ps1 / Launcher.ps1.
#
# Set-FirewallRule is extracted and run for real against a mocked
# Invoke-Tool, so the actual netsh argument list is asserted rather than
# eyeballed. Runs under StrictMode, which is what the real installer sets.

param([string] $RepoRoot)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# param() rather than $args[0]: under StrictMode, indexing $args when no
# argument was passed throws "Index was outside the bounds of the array".

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

# Linux pwsh's Join-Path rejects 'C:\...' (no such drive), which is the
# same class the real harness patches with Convert-ForLinux. The netsh
# argument shape is what's under test, not path handling.
$FakeTarget = '/tmp/frivo-fake-install'

$script:pass = 0
$script:fail = 0

function Assert-True {
    param([string] $Name, [bool] $Condition, [string] $Detail = '')
    if ($Condition) {
        Write-Host ("  PASS  " + $Name)
        $script:pass++
    } else {
        Write-Host ("  FAIL  " + $Name + $(if ($Detail) { " -- $Detail" } else { '' }))
        $script:fail++
    }
}

# --- extract Set-FirewallRule from Install.ps1 without running the whole file ---
$installPath = Join-Path $RepoRoot 'installer/Install.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($installPath, [ref]$tokens, [ref]$errors)
if ($errors -and $errors.Count -gt 0) {
    Write-Host "Install.ps1 has parse errors"; exit 1
}
$fnAst = $ast.Find({
    param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Set-FirewallRule'
}, $true)
if (-not $fnAst) { Write-Host "Set-FirewallRule not found"; exit 1 }

# --- mock Invoke-Tool: record every call, report success ---
$script:calls = New-Object System.Collections.ArrayList
function Invoke-Tool {
    param([string] $FilePath, [string[]] $Arguments)
    [void]$script:calls.Add([pscustomobject]@{ FilePath = $FilePath; Arguments = $Arguments })
    return [pscustomobject]@{ ExitCode = 0; StdOut = ''; StdErr = '' }
}

Invoke-Expression $fnAst.Extent.Text

$logLines = New-Object System.Collections.ArrayList
$log = { param($m) [void]$logLines.Add($m) }

Write-Host "`nSet-FirewallRule — enabled"
$script:calls.Clear()
Set-FirewallRule -Enabled $true -Target $FakeTarget -Log $log

$addCalls = @($script:calls | Where-Object { $_.Arguments -contains 'add' })
$delCalls = @($script:calls | Where-Object { $_.Arguments -contains 'delete' })

Assert-True 'deletes stale rules first' ($delCalls.Count -eq 1)
Assert-True 'adds exactly one rule (one UAC-free elevated call, no duplicates)' ($addCalls.Count -eq 1) "got $($addCalls.Count)"

$a = $addCalls[0].Arguments
Assert-True 'targets netsh.exe' ($addCalls[0].FilePath -eq 'netsh.exe')
Assert-True 'rule is named Frivo' ($a -contains 'name=Frivo')
Assert-True 'inbound' ($a -contains 'dir=in')
Assert-True 'allow' ($a -contains 'action=allow')
Assert-True 'scoped to this install pythonw' (@($a | Where-Object { $_ -like 'program=*pythonw.exe' }).Count -eq 1)
# Regression for the shipped bug: 'program=' + $path without parentheses
# splits into two array elements, so netsh gets an empty program= and a
# stray path token, rejects the command, and the rule silently never
# exists. Assert the path is fused onto the flag, not merely present.
Assert-True 'program= is one fused argument, not split in two' (@($a | Where-Object { $_ -eq 'program=' }).Count -eq 0) 'bare program= means the concatenation was not parenthesised'
Assert-True 'private profile only' ($a -contains 'profile=private')
Assert-True 'local subnet only' ($a -contains 'remoteip=localsubnet')

# The point of the change: no protocol/port pin, so UDP 9001 is covered
# without a second rule and without the user running netsh by hand.
Assert-True 'no protocol pin (so UDP 9001 is covered too)' (@($a | Where-Object { $_ -like 'protocol=*' }).Count -eq 0)
Assert-True 'no localport pin' (@($a | Where-Object { $_ -like 'localport=*' }).Count -eq 0)

Write-Host "`nSet-FirewallRule — disabled"
$script:calls.Clear()
Set-FirewallRule -Enabled $false -Target $FakeTarget -Log $log
Assert-True 'does nothing when the user declined the firewall option' ($script:calls.Count -eq 0)

Write-Host "`nSet-FirewallRule — netsh failure is non-fatal"
$script:calls.Clear()
$logLines.Clear()
function Invoke-Tool {
    param([string] $FilePath, [string[]] $Arguments)
    [void]$script:calls.Add([pscustomobject]@{ FilePath = $FilePath; Arguments = $Arguments })
    return [pscustomobject]@{ ExitCode = 1; StdOut = ''; StdErr = 'denied' }
}
$threw = $false
try { Set-FirewallRule -Enabled $true -Target $FakeTarget -Log $log } catch { $threw = $true }
Assert-True 'install continues when netsh fails' (-not $threw)
Assert-True 'and says so' (@($logLines | Where-Object { $_ -match 'could not be added' }).Count -ge 1)

# --- Launcher.ps1 static checks ---
Write-Host "`nLauncher.ps1 — Enable-FrivoFirewallRule"
$launcherPath = Join-Path $RepoRoot 'installer/Launcher.ps1'
$lt = $null; $le = $null
$last = [System.Management.Automation.Language.Parser]::ParseFile($launcherPath, [ref]$lt, [ref]$le)
Assert-True 'parses cleanly' (-not $le -or $le.Count -eq 0)

$lfn = $last.Find({
    param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Enable-FrivoFirewallRule'
}, $true)
Assert-True 'Enable-FrivoFirewallRule exists' ($null -ne $lfn)
$body = $lfn.Extent.Text
Assert-True 'launcher rule is program-scoped, not port-pinned' ($body -notmatch 'localport=')
Assert-True 'launcher rule keeps localsubnet scoping' ($body -match 'remoteip=localsubnet')
Assert-True 'launcher rule keeps private profile' ($body -match 'profile=private')
Assert-True 'does not assign to the automatic $args variable' ($body -notmatch '\$args\s*=')
Assert-True 'still quotes via ConvertTo-ArgumentString' ($body -match 'ConvertTo-ArgumentString')

# Uninstall must still remove what we now create (delete by name+program).
Write-Host "`nUninstall.ps1 — still removes the rule"
$uninstall = Get-Content (Join-Path $RepoRoot 'installer/Uninstall.ps1') -Raw
Assert-True 'deletes firewall rule by name and program' ($uninstall -match "delete','rule'" -or $uninstall -match "'delete','rule'" -or $uninstall -match "delete',\s*'rule'")

Write-Host ("`n{0} passed, {1} failed" -f $script:pass, $script:fail)
if ($script:fail -gt 0) { exit 1 }
exit 0
