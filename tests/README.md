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

## test-update-logic.ps1

    pwsh -NoProfile -File tests/test-update-logic.ps1

NEW (updates). Covers the decisions the **Frivo Updater** task makes on
its own as SYSTEM, run for real against `tests/fixtures/github-releases.json`.
That sample was built to include every kind of release that must not be
installed: a pre-release, a draft, a `nightly` tag, an installer hosted
by another repository, a release with no installer, a version listed
twice, a release with no fingerprint, and one with an `md5:` digest.

It checks which releases count, and which ones a request may install. It
refuses the installed version, anything below `oldest_rollback`, and
anything without a fingerprint. It checks that a downloaded file has to be
byte-for-byte the published one, that a request file can't smuggle in a
path, that `status.json` is replaced whole, and that setup's `FAILED:` line
is the reason the dialog shows. It also reads the files around the
updater: setup ships it and registers the task, `Frivo.iss` never opens
the wizard on a silent run, `FrivoHost.exe --silent` never shows a message
box (as SYSTEM, nobody could close one), the launcher listens for the
watcher, and uninstall removes the task.

Every check was confirmed to fail on purpose. Removing `-RequireFingerprint`
from the task fails it, and so do dropping `Check: not WizardSilent` and
unguarding a `MessageBox.Show`.

## test-updates.py

    python3 tests/test-updates.py

NEW (updates). Frivo's own half, through Flask's test client against the
real `app.py` with GitHub swapped for the same fixture. It covers the chip
and "Skip this version", the automatic-check switch (it saves itself and
reaches config.json), Earlier versions (never below the floor), every way
an install can be refused, `request.json`, and following an install from
queued through the task's own status to a failure. A request nobody picks
up gets reported instead of waited on forever.

**The cross-check.** It also asks `Frivo.Update.psm1` to parse the same
fixture and requires both lists to match release for release, comparing
version, fingerprint, size and both URLs. The page offers releases, the task
decides what it will install, and the two must never disagree in front of
anyone. Letting the PowerShell side accept a pre-release makes this check
fail.

## test-update-ui.py

    python3 tests/test-update-ui.py

NEW (updates). The update dialog in a real browser against the real server,
with the task replaced by a stand-in that writes `status.json` the way
`Update-Frivo.ps1` does. It includes the part where setup stops Frivo, so
the server answers nothing for a few seconds and then comes back as the new
version. The run covers the chip, the tidied notes, download progress in MB,
the restart shown as a restart rather than an error, and the page reloading
into the new version. It also covers a failure with the task's reason and
Try again, Settings > About, Earlier versions and its going-back wording,
Escape, the switch surviving a reload, Skip, and no page errors. Screenshots
go to `tests/screenshots/`, which is git-ignored.

The end-to-end run of `Update-Frivo.ps1` itself was done by hand on Linux.
A copy of the script was pointed at a local web server, with the
Windows-only calls stubbed out, and it worked through download,
fingerprint, "setup", registry check and cleanup. Setup failing, a tampered
download, and a version that isn't a release each ended in the right
state. That run isn't kept as a test because it rewrites the script to run
it, so the real thing still needs a first run on Windows.

## test-dictation-speed.py

    python3 tests/test-dictation-speed.py

Live (Evora) dictation took about ten seconds from the end of a sentence
to the send. Three delays added up: Evora's speaker analysis ran on every
clip, the final transcription waited for silence and then queued behind a
live preview, and auto-send waited another 1.4s after the text came back.
The test drives the real page against the real server with a deliberately
slow fake Evora (0.6s per clip) and a microphone level the test controls:

- The sentence is sent about 1.5s after you stop talking.
- A pause that turns out not to be the end gives one message, not two.
- A breath mid-sentence discards the early final, so no words are lost.

On the server side it checks that Frivo asks Evora for words only
(`speaker=0`), retries a busy Evora a bounded number of times, and leaves
the listening panel's speaker requests alone.

Run against the old dictation code, it fails. The send comes 2.9s after
speech ends even with the fast fake Evora, and pausing then carrying on
sent the first half of the sentence on its own. That second bug is fixed
too.

## test-typing-indicator.py

    python3 tests/test-typing-indicator.py

Covers VRChat's typing dots while you respond. Frivo decides whether you're
replying and adds a `typing` flag to the outbox reply FrivOSC already
polls. FrivOSC 1.2.0 turns that flag into `/chatbox/typing`. FrivOSC's own
`test-end-to-end.py` checks the VRChat side.

Server side: the flag is only set with VRChat OSC on and the switch on. A
`typing` that nobody refreshes expires after 4 seconds, so a page closed
mid-sentence can't leave the dots up. The switch saves itself.

In a real browser:
- Typing puts the dots up, and a draft left sitting takes them down.
- Clearing or sending the box takes them down.
- Talking with Live (Evora) puts them up before any text arrives, and they
  stay up while you keep talking.
- With the Chatbox switch off, or the Settings switch off, the dots never
  appear, and the Settings switch stays off after a reload.

## test-restart-after-update.ps1

    pwsh -NoProfile -File tests/test-restart-after-update.ps1

Frivo usually runs on a PC nobody is sitting at, and gets updated from a
browser somewhere else. When an update stopped Frivo and nothing started
it again, it stayed down until someone walked over to that PC.

The restart now lives in setup (`Install.ps1`'s silent update), not in the
updater. During an update, the updater that runs belongs to the old
version, but setup always belongs to the new one. Two restart fixes were
put in the updater first, and both had to wait a release before they could
run at all.

Before stopping Frivo, setup notes which Windows account Frivo is running
as. Afterwards it starts Frivo again as that account through a one-off
Interactive scheduled task. Setup runs as SYSTEM, so anything it started
directly would also run as SYSTEM: invisible, and with the wrong settings.

The test runs the real functions under StrictMode, with Windows' process
list and Task Scheduler replaced:

- It restarts the right account once, never SYSTEM, and never someone else's
  Python from another folder.
- The restart goes through `Frivo.vbs -Tray`, in the user's session, without
  admin rights, and with no time limit (Task Scheduler's default stops a
  task after three days).
- The one-off task is always removed afterwards.
- It reports failure honestly instead of claiming success.
- Who Frivo runs as is noted before setup stops it.
- The restart also happens after a failed update.
- It doesn't start a second launcher when Frivo is already back, and neither
  does the watcher.

## test-reply-flow.py

    python3 tests/test-reply-flow.py

New in 1.5.0. Covers two things that used to go wrong between hitting send
and the reply landing.

**Typing dots through the reply.** The dots stay up while a slow reply is
being written, even though the message box is already empty. They come
down when the reply is handed to the chatbox. A failed reply takes them
down at once, including a server error, which returns early rather than
throwing.

**Auto-send is for speech.** Dictating hands-free still sends by itself.
Typing into a dictated message cancels its pending auto-send. The Auto
switch shows it's paused and the status line says so. Speaking more into
that message doesn't re-arm the send. Enter sends it, after which the next
dictated message auto-sends again. Typed text on its own never
auto-sends, and emptying the box clears the pause.

Run against the 1.4.x code, seven of these checks fail.

## test-response-styles.py (1.5.0)

`python3 tests/test-response-styles.py` checks that Response, Echo and Mimic behave as described in `docs/RELEASE-1.5.0.md`. A script stands in for the model, so nothing goes over the network.

- **Mimic:** in English, sends exactly what was typed, makes no model call, and needs no key. In another language, it makes one literal translation at temperature 0, with no personality or earlier turns sent.
- **Echo's word check** (`echo_keeps_words`): spelling, grammar, shorthand and emphasis are allowed. Added words, removed words and synonyms are caught.
- **Echo when the model rewords:** it retries once without the personality, then falls back to the text as typed. The reply is flagged either way.
- **Length:** Echo and Mimic are never shortened.
- **Old settings:** profiles and settings saved as "flair" read as Echo.

To mutation-check it, break the word check, the Mimic shortcut, the no-history rule or the "flair" alias in app.py. Each one makes the test fail.

`test-response-styles.py` also checks **Follow reply length**. Long Echo and Mimic messages stop at the last whole sentence that fits, and a too-long first sentence is cut cleanly with a full stop. With the switch off, nothing is shortened. Profiles saved before the switch existed behave as they used to. New and edited profiles save the switch.

## test-dictation-typing.py (1.5.0)

`python3 tests/test-dictation-typing.py` drives the page in a real browser with Live (Evora) dictation, under the test's control. It checks that:

- text typed while the mic is on isn't erased, and what you say afterwards goes after it;
- typing over a preview means the finished words replace the preview, not add it twice;
- a space you typed isn't doubled.

Removing the `takeTypedText()` call, or the preview replacement in `commitDictated()`, makes it fail.

## test-microphone-setting.py (1.5.0)

`python3 tests/test-microphone-setting.py` runs the Settings microphone list in a real browser with fake microphones. It checks that:

- a microphone you picked is still shown after a reload;
- before the mic is allowed, while names are hidden, your saved choice is shown and can't be overwritten with a blank;
- the list fills in by itself once the mic is allowed, and when Settings is opened;
- a saved microphone that's gone is labelled as not connected, and dictation falls back to the default one.

The test simulates hidden names by blanking what `enumerateDevices` returns, because headless Chromium's fake devices always show their names.

`test-response-styles.py` now tests Clean up (`cleanup_stays_on_message`). Fixes and clarifications pass. Filler, pet names, new content and answers are caught.

## test-free-voices.py (1.5.0)

`python3 tests/test-free-voices.py` covers the free voices, which are the ones built into Windows. The speech helper (`app/windows_speech.ps1`) is replaced by a stand-in that answers the same way, so it runs anywhere. It checks:

- the engine is chosen from the voice id (`windows:`, `onecore:`, the removed `kokoro:`, or ElevenLabs);
- the newer and older Windows voices are listed once each, and an older one that's in use stays listed;
- the voice list works without an ElevenLabs key;
- free voices speak without a key, record no credits, and get the speaking speed;
- non-English text reaches the helper as plain ASCII escapes and arrives intact;
- one helper serves every reply, and one that stops or hangs is replaced;
- a long reply gets exact chatbox page times;
- anything set to a Kokoro voice moves to a Windows voice of the same gender, and the old Kokoro download is deleted;
- previews are made once, in the voice's language, and kept.

## test-frivo-voices.py (1.5.0)

`python3 tests/test-frivo-voices.py` covers Frivo's own free voices (Piper). The first half tests `app/voice_pack.py` against a stand-in download server, so it runs anywhere. It checks that only shareable voices are listed with sizes and SHA-256s, that a bad download is retried, that nothing in an archive escapes the voices folder, that the pronunciation data is shared, that a damaged model is found and replaced, and that one voice failing doesn't stop the others.

The second half runs the real voices through Frivo when sherpa-onnx is installed and `app/voices` holds them (`python app/voice_pack.py install` gets them). It checks that every voice loads and speaks on one thread, the speed, exact chatbox page times, that at most two voices stay loaded, the messages for another language and for a missing voice, the move off Kokoro, and previews.

## test-ollama-models.py (1.5.0)

`python3 tests/test-ollama-models.py` runs Frivo against a stand-in Ollama server. It checks the Fast / Balanced / Best slots (defaults, saving, the one in use writing replies), that switching unloads the others and loads the new one, the status the AI chip shows (downloaded, loaded, share on the graphics card, Ollama unreachable), that requests ask for no thinking and to stay loaded (and retry without `think` if refused), that a stray `<think>` block is removed, the `ollama pull` message for a missing model, the engine name on replies, and that no OpenAI key is needed with Ollama.

## check-windows-voices.bat (1.5.0)

Double-click `tests/check-windows-voices.bat` on a Windows PC. It runs the real `app/windows_speech.ps1` the way Frivo does: it lists the voices, speaks with one older and one newer voice (one page, three pages, two speeds, non-English text), and checks that a missing voice fails cleanly and that the helper exits when Frivo would close it. It also checks that the setup scripts parse. Everything is timed and written to `tests/windows-voice-check/` (ignored by git).

## test-ui-shell.py (2.0 interface)

`python3 tests/test-ui-shell.py` drives the redesigned page in a real browser: the rail (Chat / Listening / Voices / Settings, active state, the listening dot), the drawer, the chips and their popovers, the status pill, the voice sheet's engine groups and cost tags, Settings' one-section-at-a-time navigation and search, autosave with the *Saved* mark, the Save key button, and the light theme. Two older tests were updated for the new layout: `test-listen-click.py` opens the drawer first, and `test-update-ui.py` opens Settings from the rail and the Updates page.

## test-gpu-graph.py (1.5.0)

`python3 tests/test-gpu-graph.py` runs Frivo against stand-in Evora and Ollama servers and checks the graphics-card graph in the status popover: it's off with no local service chosen; with Evora it reports the card and its Ollama / Evora / Other split; when Windows doesn't say who uses the card, Ollama's own figure splits it; Ollama on another PC isn't stacked onto Evora's card; an Evora too old for `/gpu`, an unreachable Evora, a PC with no NVIDIA card and a down Ollama each say what's wrong; history keeps ten minutes; and the page has the graph.

## test-word-highlight.py (1.5.0)

`python3 tests/test-word-highlight.py` checks the timings behind the glowing word: ElevenLabs' per-character timings become one start and end per word (and timings that don't match the text give none), a Windows voice's word boundaries do the same across pages (punctuation-only words share the previous word's time; a missing word gives none), and `/api/chat` sends `word_times` for ElevenLabs (one page or many) and none for Frivo's own voices.

`check-windows-voices.bat` now also reports how many word boundaries each Windows voice gave for the three-page reply, which is what the glow needs on a real Windows PC.

## test-saved-replies.py (1.5.0)

`python3 tests/test-saved-replies.py` checks saved replies: saving copies the reply's audio with its text, chatbox pages and word timings (and saving twice keeps one); only replies in the audio cache can be saved, safely; the list is newest first and its audio is served; playing one adds it to the conversation the AI remembers, without generating anything; deleting removes its audio; and the 7-day audio clean-up leaves saved replies alone.

## test-conversation-kept.py (1.5.0)

`python3 tests/test-conversation-kept.py` checks, in a real browser, that messages (with their times, word timings and Save state) and dividers come back after a refresh, in order, without playing; that a restored reply loads its audio on a click and plays with its words glowing; that one whose audio was cleaned up says so; that Clear forgets the conversation; and that the volume chip neither moves nor changes width while its slider is dragged.

- `test-custom-voices.py`: downloads a small Piper voice once, then adds it as plain files, a zip, a tar.gz and a sherpa-onnx archive; checks that programs, broken files and duplicates are refused with nothing left behind, and that rename, remove and the language check work.

- `test-voice-tags.py`: voice tags and Delivery. What ElevenLabs is sent for each setting, that the chatbox, word count and free voices never get tags, that Expressive voice tells the AI about them, that Suggest keeps every word, and that a refused v3 still speaks.

- `test-personality-maker.py`: the personality maker. What the AI is asked for Create, Ideas to add and Add all; that answers are cleaned up and checked; that turned-down and already-written ideas aren't offered; that the conversation is used; and that a merge that loses your text falls back to adding at the end.

- `test-voice-remove.py`: removing a voice from your ElevenLabs voices. Refused while a profile uses it, refused for free voices and bad ids, its anchors go with it, and ElevenLabs refusing is reported.

## The Frivo app (desktop\)

NEW (1.8.0). The app has its own tests, run from `desktop\` after `npm ci`:

    npm test             unit tests: addresses, GitHub releases and checked
                         downloads, certificate pinning, settings, and what
                         the app writes to Frivo's launcher.json
    npm run test:e2e     the app itself against a real Frivo (started from
                         ../app by desktop/test/serve-frivo.py, which needs
                         Frivo's Python packages). On Linux, under a display:
                         xvfb-run -a npm run test:e2e

The end-to-end test covers the first run, trusting Frivo's certificate on
another PC, Frivo's page with the app bridge and Settings › App, losing and
getting back the connection, the trusted certificate remembered and a changed
one caught, an address with nothing there, and "this PC" with a stand-in
address. The Windows-only parts (the launcher's app mode, the registry, the
shortcuts, installing Frivo) are checked from source by
`test-update-logic.ps1`, and need trying on Windows.
