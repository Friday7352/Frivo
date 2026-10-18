# NEW (1.5.0): Frivo's speech helper for the voices built into Windows.
#
# Started once by app.py and kept running, so a reply doesn't wait for a
# new PowerShell (and the speech engine inside it) to start every time.
# It reads one JSON request per line on stdin and answers each with one
# line on stdout, starting "@@FRIVO " so nothing else PowerShell prints can
# be mistaken for an answer. It exits when stdin closes, which is when
# Frivo stops.
#
# Two kinds of Windows voice, both free, both on this PC, neither AI:
#   sapi     the desktop voices (System.Speech), what Frivo has always used.
#   onecore  the newer voices Windows installs with each language
#            (Windows.Media.SpeechSynthesis). Settings > Time & language >
#            Speech adds more. Desktop programs can't see these through
#            System.Speech, which is why Frivo didn't list them before.
#
# Requests:
#   {"op":"ping"}
#   {"op":"list"}
#   {"op":"speak","kind":"sapi"|"onecore","voice":"...","sapi_rate":0,
#    "speed":1.0,"pages":["..."],"outs":["C:\\...wav"]}
# Each page is spoken to its own wave file, so Frivo knows exactly where
# each chatbox page ends. A plain reply is one page.

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
Add-Type -AssemblyName System.Speech

$script:sapi = $null
$script:onecore = $null
$script:asTask = $null
$script:oneCoreError = ''

function Get-Sapi {
    if (-not $script:sapi) { $script:sapi = New-Object System.Speech.Synthesis.SpeechSynthesizer }
    return $script:sapi
}

function Initialize-OneCore {
    if ($script:asTask) { return $true }
    if ($script:oneCoreError) { return $false }
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
        $script:asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } | Select-Object -First 1
        if (-not $script:asTask) { throw 'This version of Windows has no way to wait for the newer voices.' }
        return $true
    } catch {
        $script:oneCoreError = $_.Exception.Message
        return $false
    }
}

function Wait-Operation($operation, [type] $resultType) {
    $task = $script:asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    if (-not $task.Wait(60000)) { throw 'Windows took too long to speak.' }
    return $task.Result
}

function Get-LanguageName([string] $tag) {
    try { return (New-Object System.Globalization.CultureInfo $tag).DisplayName } catch { return $tag }
}

function Get-Voices {
    foreach ($v in (Get-Sapi).GetInstalledVoices()) {
        if (-not $v.Enabled) { continue }
        $i = $v.VoiceInfo
        [ordered]@{
            kind = 'sapi'; id = $i.Name; name = $i.Name; gender = [string]$i.Gender
            culture = $i.Culture.Name; language = $i.Culture.DisplayName
        }
    }
    if (Initialize-OneCore) {
        foreach ($v in [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices) {
            [ordered]@{
                # The token's last part ("MSTTS_V110_enUS_DavidM"): unique and stable.
                kind = 'onecore'; id = ($v.Id -split '\\')[-1]; name = $v.DisplayName
                gender = [string]$v.Gender; culture = $v.Language; language = Get-LanguageName $v.Language
            }
        }
    }
}

function Invoke-SapiSpeak($request) {
    $s = Get-Sapi
    $s.SelectVoice([string]$request.voice)
    $s.Rate = [int]$request.sapi_rate
    $pages = @($request.pages); $outs = @($request.outs)
    try {
        for ($i = 0; $i -lt $pages.Count; $i++) {
            $s.SetOutputToWaveFile([string]$outs[$i])
            $s.Speak([string]$pages[$i])
        }
    } finally {
        # Lets go of the last file, so Frivo can read it.
        $s.SetOutputToNull()
    }
}

function Invoke-OneCoreSpeak($request) {
    if (-not (Initialize-OneCore)) { throw "The newer Windows voices aren't available: $($script:oneCoreError)" }
    if (-not $script:onecore) { $script:onecore = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer }
    $s = $script:onecore
    $wanted = [string]$request.voice
    $voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
        Where-Object { ($_.Id -split '\\')[-1] -eq $wanted } | Select-Object -First 1
    if (-not $voice) { throw "That Windows voice isn't installed anymore: $wanted" }
    $s.Voice = $voice
    # SpeakingRate came with Windows 10 1709. Without it the voice keeps its
    # normal pace rather than failing.
    try { $s.Options.SpeakingRate = [double]$request.speed } catch { }
    $pages = @($request.pages); $outs = @($request.outs)
    for ($i = 0; $i -lt $pages.Count; $i++) {
        $stream = Wait-Operation ($s.SynthesizeTextToStreamAsync([string]$pages[$i])) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
        $in = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
        $out = [System.IO.File]::Create([string]$outs[$i])
        try { $in.CopyTo($out) } finally { $out.Dispose(); $in.Dispose(); $stream.Dispose() }
    }
}

function Send-Answer($answer) {
    [Console]::Out.WriteLine('@@FRIVO ' + (ConvertTo-Json -InputObject $answer -Compress -Depth 5))
    [Console]::Out.Flush()
}

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    if (-not $line.Trim()) { continue }
    try {
        $request = ConvertFrom-Json -InputObject $line
        switch ([string]$request.op) {
            'ping'  { Send-Answer @{ ok = $true } }
            'list'  {
                $voices = @(Get-Voices)
                Send-Answer @{ ok = $true; voices = $voices; onecore_error = $script:oneCoreError }
            }
            'speak' {
                if ([string]$request.kind -eq 'onecore') { Invoke-OneCoreSpeak $request } else { Invoke-SapiSpeak $request }
                Send-Answer @{ ok = $true }
            }
            default { Send-Answer @{ ok = $false; error = "Unknown request: $($request.op)" } }
        }
    } catch {
        Send-Answer @{ ok = $false; error = $_.Exception.Message }
    }
}

# Frivo has stopped (stdin closed). Exit outright: the speech engines leave
# threads running that would otherwise keep this process alive in the
# background after Frivo is gone.
foreach ($engine in @($script:sapi, $script:onecore)) {
    if ($engine) { try { $engine.Dispose() } catch { } }
}
[Environment]::Exit(0)
