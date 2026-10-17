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

## test-mute-sync.py

    python3 tests/test-mute-sync.py

Drives the real page in a real browser, with a fake microphone, against the
real server, and watches the record button. Everything worth getting right
about mute sync is a rule about *not* acting, and none of it is checkable by
reading the code:

**Unknown is not unmuted.** Before VRChat has sent a `MuteSelf`, the mute
state is `null`. Treating that as unmuted would start recording for someone
who is muted and does not know it.

**It acts on changes, never on the level.** That is the whole mechanism
behind "the mic button still overrides it" — stop dictation by hand while
still unmuted and it stays stopped, because nothing changed. Delete the
one-line guard that implements this and the override assertion fails; that
was checked by doing it.

**A companion that disappears does not stop you.** Losing the mute state
takes it back to unknown, and unknown must not yank a running dictation out
from under anyone.

**Switching it on while already unmuted starts dictation.** This was
reported as "microphone is detected as live in VRC but it's not turning on
the dictation". Turning the switch on used to record the current state as
already handled — defensible in the abstract, and in practice it meant the
feature did nothing until a mute/unmute cycle that nobody thought to
perform.

**The switch saves itself.** It lives in the sidebar status panel, and Save
belongs to the Settings sheet, so there is no Save button within reach of
it. Without `POST /api/frivosc/settings` it flipped, was never written down,
and the next status poll read the unchanged value off the server and
silently flipped it back. The test waits two polls to catch exactly that.

## test-hot-reload.py

    python3 tests/test-hot-reload.py

Editing a file must actually reach the browser. This exists because of a
real report: a switch was added to `index.html`, the file on disk plainly
had it, and it was not on the page. Nothing was wrong with the code — Jinja
compiles a template once per process and, with debug off (which is how Frivo
always runs), never looks at the file again. The running server was serving
HTML it had compiled before the edit.

That failure mode is silent. No error, no warning, just a feature that looks
like it was never built — and the obvious next move is to go re-check code
that was already correct. `TEMPLATES_AUTO_RELOAD` fixes it; this test holds
it fixed, and also checks that the `?v=` stamp on the static URLs moves when
`app.js` or `style.css` changes so the browser cannot serve an old copy.

Setting `TEMPLATES_AUTO_RELOAD` back to `False` makes the middle assertion
fail — that was checked by doing it.

## test-listen-click.py

    python3 tests/test-listen-click.py

Clicking a message in the listening panel loads it into the reply box;
Ctrl (Cmd on a Mac) adds it to whatever is already there, so several things
people said can be gathered into one reply.

Every interesting case is about not destroying text: appending into an
empty box must not leave a leading space, a trailing space someone typed is
theirs rather than something to double, text already typed has to survive,
and the caret must land at the end or the next thing typed appears in the
middle of the sentence you just built. Two more are about not copying at
all — a message still being transcribed shows an ellipsis placeholder, and
the speaker name renames rather than copies.

None of that is visible by reading the code, so this drives the real page
in a real browser. Removing the append branch fails four assertions;
checked by doing it.

## test-version.py

    python3 tests/test-version.py

One version number, read by everything. Before this it was written down in
three places and they had already drifted: the installer said 1.1.2, the
Inno container said 1.1.2, and `FrivoHost.cs` still said 1.1.1 — so the Apps
& features entry and the exe's own file properties disagreed about what was
installed. Nothing catches that. It is three literals that have to be edited
together and silently do not have to match.

`VERSION` at the repo root is now the only copy. This checks that all four
consumers — `Install.ps1`, `Frivo.iss`, `Build-Installer.ps1` and `app.py` —
resolve to the same string, that each finds it in both the repo layout and
the installed one, that a missing file degrades to "unknown" rather than
failing an install, and that a malformed one is rejected at build time
rather than by csc with an error that mentions nothing useful.

It also scans for a literal creeping back in. That scan is per-language on
purpose: `#` starts a comment in PowerShell but starts the *preprocessor*
in an `.iss` file, which is exactly where a version literal lives. Treating
them the same made the scan walk straight past a reintroduced literal —
found by putting one back and watching it pass.

## Not covered here

`app.js`, `index.html`, and `style.css` have no full suite — `test-mute-sync.py`
covers one feature end to end, and the expanding status chips are checked
the same way ad hoc.
They are checked per change with `python -m py_compile`, `node --check`, an
HTML tag-balance parse, a cross-check that every `$("id")` in the JS exists
in the template, and Playwright renders for anything visual.

The larger WinForms dry-run harness (13 scenarios against stubbed
System.Windows.Forms) lives outside this repo.
