# Tests

PowerShell checks for the installer and launcher. They run on Linux or
Windows — nothing here touches the real registry, filesystem, or firewall.

    pwsh -NoProfile -File tests/test-firewall.ps1
    pwsh -NoProfile -File tests/test-arraysplat.ps1

Both exit non-zero on failure, so they can be chained.

## test-firewall.ps1

Extracts `Set-FirewallRule` from `installer/Install.ps1` and runs it for
real against a mocked `Invoke-Tool`, asserting the exact netsh argument
list rather than eyeballing it. Also statically checks
`Enable-FrivoFirewallRule` in `Launcher.ps1` and that `Uninstall.ps1` still
removes what the installer now creates.

It covers two bugs worth not reintroducing:

**The rule is program-scoped, with no `protocol=`/`localport=` pin.** Frivo
listens on TCP 5000 (dashboard) and UDP 9001 (VRChat OSC, when mute-synced
dictation is on). netsh takes one protocol per rule, so pinning ports would
mean two rules here and two elevated calls in the launcher — two UAC
prompts behind one button. The single rule is still scoped to this
install's own `pythonw.exe`, the private profile, and the local subnet.

**`('program=' + $pythonw)` keeps its parentheses.** Inside an array literal
the comma binds tighter than `+`, so

    @('action=allow', 'program=' + $pythonw, 'profile=private')

parses as `('action=allow', 'program=') + $pythonw + ('profile=private')`.
The path becomes its own element, netsh receives an empty `program=`
followed by a stray argument, rejects the command, and the failure is only
logged — so the firewall rule silently never exists. This shipped, and is
why the launcher's "open port" button was doing the work the installer was
supposed to have already done.

## test-arraysplat.ps1

Walks the AST of every `.ps1`/`.psm1` under `installer/`, `build/` and
`tests/` looking for that same shape anywhere else: a `+` expression sitting directly inside an array
literal. This class of bug never throws — the wrong command just quietly
does nothing — so it needs to be searched for rather than waited for.

## test-inno-discovery.ps1

    pwsh -NoProfile -File tests/test-inno-discovery.ps1

The build script installs Inno Setup itself when it is missing — winget
first, then the current release straight from jrsoftware.org's GitHub. The
discovery half of that is pure logic, so it is tested: an existing install
must be found (machine-wide, per-user, version 6 or 7, or via the registry)
and must never be installed over, and when both install routes fail the
error has to say where to get it by hand and that a new window is needed.

The functions are extracted from the build script at run time rather than
copied, so this fails if the real ones change shape. It caught a real bug
immediately: `Join-Path` throws on an empty base, and the candidate paths
were being built inside an array literal — evaluated before the guard that
was supposed to skip them. Same shape as the `Find-InstalledPython` bug in
FrivOSC.

## test-frivosc-bridge.py

    python3 tests/test-frivosc-bridge.py

Frivo's half of the FrivOSC bridge, driven through Flask's test client
against the real `app.py`: the outbox queue and its bound, the
acknowledgements, the connected/not-connected rule, the settings switch,
and the entry FrivOSC gets in the header status chip beside Evora.

Two assertions are there because of bugs that shipped. `osc_enabled` was
read on the way out of the settings endpoint but never written on the way
in, so the switch flipped itself back off on every save — and the first
version of this test passed anyway, because an earlier assertion had set
the value directly in `CFG` and left it there. Every case now starts from
`reset()`. The other is that FrivOSC must be marked as having no OpenAI
fallback: it is not a provider, and a chatbox that cannot reach VRChat
does not quietly start costing credits.

## Not covered here

`app.js`, `index.html`, and `style.css` have no automated suite.
They are checked per change with `python -m py_compile`, `node --check`, an
HTML tag-balance parse, a cross-check that every `$("id")` in the JS exists
in the template, and Playwright renders for anything visual.

The larger WinForms dry-run harness (13 scenarios against stubbed
System.Windows.Forms) lives outside this repo.
