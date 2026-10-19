<#
    NEW (1.5.0): checks app\windows_speech.ps1 on a real Windows PC.

    Starts the helper exactly the way Frivo does, asks it for the voices,
    and has the first desktop voice and the first newer (OneCore) voice each
    speak a one-page and a three-page reply. Times every step and writes
    everything to tests\windows-voice-check\ (report.txt plus the wave
    files), which can be deleted afterwards.

    Also checks that the setup scripts parse. Run it by double-clicking
    check-windows-voices.bat.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$helper = Join-Path $root 'app\windows_speech.ps1'
$outDir = Join-Path $PSScriptRoot 'windows-voice-check'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$report = Join-Path $outDir 'report.txt'
$lines = New-Object System.Collections.Generic.List[string]
function Note([string] $text) { $lines.Add($text); Write-Host $text }

Note ("Windows: " + [Environment]::OSVersion.VersionString + "  PowerShell " + $PSVersionTable.PSVersion)

# The setup scripts and the helper must at least parse.
foreach ($script in @(Get-ChildItem (Join-Path $root 'installer') -Include *.ps1, *.psm1 -Recurse) + @(Get-Item $helper)) {
    $tokens = $null; $errors = $null
    [void] [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref] $tokens, [ref] $errors)
    if ($errors) { Note ("PARSE ERROR in {0}: {1}" -f $script.Name, ($errors | ForEach-Object { "line $($_.Extent.StartLineNumber): $($_.Message)" }) -join '; ') }
}
Note 'parse check done'
$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$literal = "'" + $helper.Replace("'", "''") + "'"
$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName = $psExe
$info.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText(' + $literal + ', [Text.Encoding]::UTF8)))"'
$info.UseShellExecute = $false
$info.RedirectStandardInput = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
$info.CreateNoWindow = $true

$clock = [System.Diagnostics.Stopwatch]::StartNew()
$proc = [System.Diagnostics.Process]::Start($info)
$errTask = $proc.StandardError.ReadToEndAsync()

function Ask($request, [string] $label) {
    $t = [System.Diagnostics.Stopwatch]::StartNew()
    $proc.StandardInput.WriteLine((ConvertTo-Json -InputObject $request -Compress -Depth 5))
    $proc.StandardInput.Flush()
    $other = @()
    while ($true) {
        $line = $proc.StandardOutput.ReadLine()
        if ($null -eq $line) { throw "The helper stopped. Other output: $($other -join ' | ')" }
        if ($line.StartsWith('@@FRIVO ')) { break }
        $other += $line
    }
    $t.Stop()
    $answer = ConvertFrom-Json -InputObject $line.Substring(8)
    Note ("{0,-34} {1,6:N0} ms  ok={2} {3}" -f $label, $t.Elapsed.TotalMilliseconds, $answer.ok, $answer.error)
    if ($other) { Note ("   (other output: " + ($other -join ' | ') + ")") }
    return $answer
}

try {
    $null = Ask @{ op = 'ping' } 'start + first answer'
    Note ("   helper started and answered after {0:N0} ms" -f $clock.Elapsed.TotalMilliseconds)
    $null = Ask @{ op = 'ping' } 'second answer (already running)'
    $list = Ask @{ op = 'list' } 'list voices'
    if ($list.onecore_error) { Note ("   newer voices error: " + $list.onecore_error) }
    foreach ($v in @($list.voices)) { Note ("   {0,-8} {1,-45} {2,-7} {3,-6} id={4}" -f $v.kind, $v.name, $v.gender, $v.culture, $v.id) }

    $pages = @('Okay so here is the thing about the backrooms world. The lights hum all the time.',
               'If you stand still long enough, you start to hear footsteps that are not yours.',
               "Come by tonight and I'll show you around, but bring a flashlight.")
    foreach ($kind in 'sapi', 'onecore') {
        $voice = @($list.voices) | Where-Object { $_.kind -eq $kind } | Select-Object -First 1
        if (-not $voice) { Note "   no $kind voice to try"; continue }
        foreach ($speed in 1.0, 1.5) {
            $one = Join-Path $outDir "$kind-one-$speed.wav"
            $null = Ask @{ op = 'speak'; kind = $kind; voice = $voice.id; sapi_rate = [int](($speed - 1) * 10); speed = $speed
                           pages = @('Hi there! This is how I sound. Nice to meet you.'); outs = @($one) } "$kind one page, speed $speed"
        }
        $outs = @(0, 1, 2 | ForEach-Object { Join-Path $outDir "$kind-page-$_.wav" })
        $three = Ask @{ op = 'speak'; kind = $kind; voice = $voice.id; sapi_rate = 0; speed = 1.0; pages = $pages; outs = $outs } "$kind three pages"
        # NEW (1.5.0): the word boundaries the reply highlight uses.
        if ($null -eq $three.words) { Note "   $kind words: none reported (no highlight for this voice)" }
        else {
            $counts = @($three.words | ForEach-Object { @($_).Count }) -join ', '
            $first = @(@($three.words)[0])[0..2] | ForEach-Object { '[' + ($_ -join ', ') + ']' }
            Note ("   $kind words per page: $counts   first: " + ($first -join ' '))
        }
        $null = Ask @{ op = 'speak'; kind = $kind; voice = $voice.id; sapi_rate = 0; speed = 1.0
                       pages = @('Ünïcödé: café, naïve, 日本語.'); outs = @(Join-Path $outDir "$kind-unicode.wav") } "$kind non-English text"
    }
    $null = Ask @{ op = 'speak'; kind = 'onecore'; voice = 'NoSuchVoice'; speed = 1.0; pages = @('x'); outs = @(Join-Path $outDir 'none.wav') } 'missing voice (should fail)'
    $null = Ask @{ op = 'ping' } 'still alive after a failure'
} catch {
    Note ("FAILED: " + $_.Exception.Message)
} finally {
    $proc.StandardInput.Close()
    if (-not $proc.WaitForExit(5000)) { Note 'helper did not exit when stdin closed'; $proc.Kill() } else { Note 'helper exited when stdin closed' }
    $stderr = $errTask.Result
    if ($stderr) { Note ("stderr: " + $stderr.Trim()) }
    [System.IO.File]::WriteAllLines($report, $lines, (New-Object System.Text.UTF8Encoding $false))
    Note "Report written to $report"
}
