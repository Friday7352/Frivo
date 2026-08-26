# Scans every PowerShell script in the repo for the "unparenthesised + inside an array
# literal" bug found in Set-FirewallRule.
#
# In PowerShell, comma binds tighter than +, so
#     @('a=', 'b=' + $x, 'c=')
# is ('a=','b=') + $x + ('c=') — five elements, with $x split out on its
# own. When that array is an argument list, the receiving program gets an
# empty "b=" and a stray token. It fails, and nothing crashes: the wrong
# command just quietly does nothing.
#
# AST-based rather than regex: it looks for a BinaryExpression whose parent
# is an ArrayLiteral, which is exactly the shape that misparses.

param([string] $RepoRoot)

Set-StrictMode -Version Latest

# param() rather than $args[0]: under StrictMode, indexing $args when no
# argument was passed throws "Index was outside the bounds of the array".

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

$found = 0
$scanned = 0

# Every PowerShell file in the repo, not just installer/. The build scripts
# assemble compiler and netsh-style argument arrays the same way, and this
# class of bug never throws — the wrong command just quietly does nothing —
# so it has to be searched for rather than waited for.
$scanRoots = @('installer', 'build', 'tests') |
    ForEach-Object { Join-Path $RepoRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ }

foreach ($file in (Get-ChildItem -Path $scanRoots -Include *.ps1,*.psm1 -Recurse)) {
    $scanned++
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$null, [ref]$errors)
    if ($errors -and @($errors).Count -gt 0) {
        Write-Host ("PARSE FAIL  " + $file.Name)
        $found++
        continue
    }

    $arrays = $ast.FindAll({
        param($n) $n -is [System.Management.Automation.Language.ArrayLiteralAst]
    }, $true)

    foreach ($arr in $arrays) {
        foreach ($el in $arr.Elements) {
            if ($el -is [System.Management.Automation.Language.BinaryExpressionAst] -and
                $el.Operator -eq [System.Management.Automation.Language.TokenKind]::Plus) {
                $line = $el.Extent.StartLineNumber
                $text = $el.Extent.Text
                Write-Host ("  BUG  {0}:{1}  {2}" -f $file.Name, $line, $text)
                $found++
            }
        }
    }
}

Write-Host ""
Write-Host ("Scanned {0} file(s); {1} unparenthesised concatenation(s) inside array literals." -f $scanned, $found)
if ($found -gt 0) {
    Write-Host "Wrap each in parentheses: ('name=' + `$value)"
    exit 1
}
Write-Host "Clean."
exit 0
