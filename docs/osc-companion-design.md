# FrivOSC — design

A companion process that owns every OSC conversation with VRChat, so
Frivo itself never speaks the protocol.

Status: **proposal, not built.** Written to be argued with before any code
moves.

## Name

**FrivOSC** — Frivo and OSC overlapping on the shared O.

Chosen over family-style names (Orvo, Osca, Corva) deliberately. Those
suit something a user picks up and looks at; this autostarts, hides, and
should be instantly identifiable when it turns up in Task Manager or a
support thread. It also matches how the VRChat OSC ecosystem already names
itself — VRCOSC, VOR, VRCFaceTracking — so it slots in where its users
already are.

Conventions, since the mixed caps need a ruling:

- **In prose:** FrivOSC.
- **On disk / in Task Manager:** `FrivOSC.exe`.
- **Said aloud:** "friv-oh-ess-see". Worth writing down once so support
  conversations do not have to relitigate it.
- Not "FrivOCS" — the protocol is O-S-C, Open Sound Control. Easy
  transposition to make and it reads as a typo to anyone who knows OSC.

## Why

Frivo speaks OSC directly today, and OSC does not want to leave the
machine it started on. VRChat sends its output to `127.0.0.1` and listens
on `127.0.0.1`; everything else is worked around. Every rough edge in the
current OSC features traces back to that single fact:

| Symptom | Cause |
| --- | --- |
| Chatbox needs the VRChat PC's IP typed in | Frivo sends UDP across the network |
| That PC needs an inbound UDP 9000 rule | same |
| Mute sync needs a `--osc=` launch option | VRChat won't send off-box on its own |
| That launch option breaks VRCFaceTracking etc. | VRChat has one output destination |
| A relay script exists at all | to work around the above |
| OSCQuery can't help | it doesn't work cross-machine on Windows |

None of these are Frivo bugs. They are what happens when a LAN service
tries to speak a loopback protocol.

FrivOSC removes the premise. OSC stays on loopback where it belongs, and the network hop becomes HTTP — which
crosses machines happily, over a port that is already open because the
dashboard uses it.

```
BEFORE
  Frivo server ──── UDP 9000 ───────────────▶ VRChat PC     (chatbox)
  Frivo server ◀─── UDP 9001 ──────────────── VRChat PC     (mute, needs launch option)
     requires: typed IP, inbound rules on both boxes, launch option

AFTER
  Frivo server ◀══ HTTPS 5000 ══▶ FrivOSC ──▶ 127.0.0.1  VRChat
                  (already open)   (same PC as VRChat, loopback only)
     requires: FrivOSC knows Frivo's address
```

The prize is not just tidiness. On the VRChat PC the companion is
same-machine with VRChat, which is precisely the case where **OSCQuery
works**. It can register with VRChat properly: no fixed port, no launch
option, and it coexists with other OSC apps instead of stealing VRChat's
single output destination.

Same-PC installs are not a special case. The companion talks to
`localhost:5000`; one code path, not two.

### Does a same-PC install still need FrivOSC?

Yes — and it should not be optional, but it also should not be visible.

The tempting shortcut is to let Frivo listen on UDP 9001 directly when it
shares a machine with VRChat, and skip the companion. Two reasons not to:

1. **Two code paths means two answers.** "Does OSC work?" would depend on
   a topology detail, with separate bugs, separate docs, and a support
   burden that never shrinks.
2. **Binding 9001 directly squats on VRChat's default output port** — the
   same port every other non-OSCQuery app wants. Frivo would be competing
   with VRCFaceTracking rather than coexisting with it. Registering
   through OSCQuery is what avoids that, and OSCQuery belongs in the
   companion because it only works same-machine.

The answer to "but that's a second install for someone with one PC" is
packaging, not architecture: the Frivo installer asks whether this PC also
runs VRChat, and installs and autostarts the companion if so. One
installer, one click, and the companion stays an implementation detail
that a single-PC user never has to think about.

## Scope: both directions, not just mute

The mute feature prompted this, but the chatbox has the same disease and
the same cure. If the companion exists, it should own **all** OSC, and
Frivo should not import `socket` for OSC purposes at all.

That means the companion also fixes things that are already shipped and
already annoy people:

- Chatbox no longer needs the VRChat PC's address typed into Settings.
- Chatbox no longer needs an inbound UDP rule on the VRChat PC.
- `osc_host` / `osc_port` stop being user-facing concepts.

Frivo becomes: *here is some text, show it.* The companion becomes: *I
know how VRChat wants to be talked to.*

## Responsibilities

**FrivOSC (runs on the VRChat PC)**

- Register with VRChat over OSCQuery; fall back to plain UDP 9001 if
  OSCQuery is unavailable.
- Watch `/avatar/parameters/MuteSelf`; report changes to Frivo.
- Accept chatbox text from Frivo; do the 144-character paging, the
  page-counter suffixes, and the rate-limit pacing; send to VRChat on
  loopback.
- Hold the Frivo server address, and survive it being unreachable.
- Report its own liveness.

**Frivo (unchanged machine, smaller job)**

- Accept mute state over HTTP; expose it to the browser as it does now.
- Send chatbox text over HTTP instead of UDP.
- Show whether FrivOSC is connected.
- Keep working with no companion at all — the whole feature set stays
  optional.

Notably FrivOSC holds **no** API keys, no config, no history. If it
is lost, nothing is lost.

## HTTP contract

FrivOSC → Frivo, and Frivo → FrivOSC, both over the existing HTTPS
port. Two shapes to decide between:

**A. FrivOSC polls and pushes (recommended).** The companion is the only
one who initiates. It POSTs mute changes as they happen, and long-polls
or short-polls for pending chatbox messages. Frivo needs no route to the
companion, no idea of its address, and nothing has to be open on the
VRChat PC at all. It also means the companion works from anywhere it can
reach Frivo, including across a VPN.

**B. Frivo pushes to FrivOSC.** Lower latency for chatbox, but the
companion needs a listening port, an inbound firewall rule, and a
discoverable address — reintroducing exactly what this design deletes.

Recommend A. Chatbox latency is already governed by VRChat's ~1.5s
rate limit, so a 500ms poll costs nothing perceptible.

### Sketch

```
POST /api/frivosc/hello
  { "version": "1.0.0", "hostname": "PAYTON-PC", "oscquery": true }
  → { "ok": true, "server_version": "1.2.0", "poll_ms": 500 }

POST /api/frivosc/state
  { "muted": true }
  → { "ok": true }
  Sent on change, and as a heartbeat every N seconds.

GET  /api/frivosc/outbox
  → { "messages": [ { "id": "…", "text": "…", "speaking": true } ] }
  Long-poll. Frivo queues chatbox sends here instead of sending UDP.

POST /api/frivosc/ack
  { "id": "…", "pages": 3 }
  → { "ok": true }
```

### Firewall: nothing to open, on either machine

Worth stating plainly, because it is the main thing this design buys and
it is easy to assume otherwise.

- The companion never listens for network traffic. It only makes outbound
  HTTPS calls. Windows Firewall allows outbound by default, so the VRChat
  PC needs no rule — and therefore the companion's installer needs no
  elevation for firewall purposes, and its uninstaller has nothing to
  clean up.
- The companion listens on `127.0.0.1:9001` for VRChat. Loopback is never
  firewalled.
- On the Frivo server it connects to port 5000, which is already open
  because the dashboard uses it.

So there is no "enable OSC support → add firewall rules" step to build.
An OSC toggle in Frivo should govern *behaviour* — whether mute drives
dictation — not plumbing.

Consequence: the UDP 9001 allowance recently added to the installer's
rule becomes unnecessary under this design. Harmless, but it should be
reverted rather than left as a rule nobody can explain later.

This holds only for design A. Design B needs the companion to listen,
which puts every one of those rules back.

### LAN, not the internet

Frivo has no authentication; `app.py`'s own header says as much. Anything
that can reach port 5000 can spend the API keys. The installer's rule is
scoped `remoteip=localsubnet`, which is what keeps that honest today.

The companion does not change this and must not quietly widen it. It works
across a LAN, and across a VPN that makes the two machines look local —
both fine. Genuine internet exposure is a separate piece of work
(authentication, a real certificate, rate limiting) and should not arrive
as a side effect of an OSC feature.

### Liveness matters more than it looks

A dead companion and an unmuted mic look identical if the only signal is
"no mute message." Dictation would sit enabled forever after a crash.

So: the companion heartbeats, and Frivo treats mute state as **stale**
after a timeout (~15s). Stale is a third state alongside muted/unmuted,
and it means *stop driving dictation and say so* — not *assume unmuted*.
The existing three-state UI (`null` / true / false) already has the right
shape for this; `null` becomes "no companion" rather than "nothing heard
yet."

## Authentication

Frivo has no auth today, by design, and its own header says so. The
companion adds a new inbound endpoint that changes behaviour, so it is
worth a decision rather than a default.

- **Do nothing.** Consistent with the rest of the app. Worst case: someone
  on your LAN toggles your dictation or writes to your chatbox. The
  chatbox one is the real annoyance — it is visible to other players.
- **Shared token.** Frivo generates one, shows it in Settings, the
  companion is given it once. Roughly ten lines. Blocks casual mischief,
  not a determined attacker on your LAN.

Recommend the token, only because the chatbox path can put text in front
of other people. Cheap enough that the argument for skipping it is weak.

## Pairing

The companion needs Frivo's address once. In order of preference:

1. Typed in on first run, remembered. Same act as today's chatbox setup,
   and it replaces that setup rather than adding to it.
2. mDNS: Frivo advertises, the companion finds it. Nice, not v1.

## What this does to the current code

Roughly half of what exists moves rather than dies.

| Now | After |
| --- | --- |
| `osc_string` / `osc_message` encoders | move to companion |
| `osc_read_string` / `osc_parse_message` | move to companion |
| `osc_listener_loop` + start/stop | move to companion |
| `chatbox_pages` (144-char paging, counters) | move to companion |
| `OSC_QUEUE` worker + pacing | move to companion |
| `osc_relay.py` | delete — FrivOSC supersedes it |
| `Start-OSC-Relay.bat` | delete |
| `--osc=` launch option docs | delete |
| `osc_host` / `osc_port` settings | deprecate |
| `/api/osc/chatbox` | keep, but queues instead of sending |
| `/api/osc/mute-status` | keep as-is for the browser |
| firewall rule covering UDP 9001 | revert — nothing needs it |
| the in-app launch-option hint | replaced by "no companion connected" |

`chatbox_pages` is the one piece worth pausing on: it has real logic in it
(sentence-aware breaking, the repack-for-counter-width loop) and it works.
Porting it is mechanical but it should be ported, not rewritten — and its
behaviour should be pinned with tests before it moves.

An alternative is leaving paging in Frivo and making the companion dumb.
That is less porting, but it leaves VRChat's 144-character limit encoded
in the server, which is exactly the knowledge this split is trying to
move. Recommend porting.

## Migration

Existing installs have `osc_host` set and working. The rule should be:
**if a companion is connected, use it; otherwise fall back to direct UDP
using the old settings.** Nobody's setup breaks on upgrade, the old path
quietly stops being used once a companion appears, and it can be deleted a
release or two later.

## Implementation language

- **Python.** `osc_relay.py` is already most of the OSC plumbing, and
  `chatbox_pages` ports as-is. Requires Python on the VRChat PC.
- **C# / .NET.** Self-contained `.exe`, real tray icon, and VRChat's own
  OSCQuery library is C# — meaningful, since OSCQuery is the part with the
  least margin for a hand-rolled implementation. The repo already builds
  `FrivoHost.cs` with Inno Setup, so the tooling exists.

Recommend prototyping in Python to prove the mechanism end-to-end, then
deciding. The HTTP contract above is language-agnostic, so a rewrite later
costs nothing on Frivo's side.

## Install story

The honest cost of this design is a second thing to install. It is paid
for by asking one question during setup and doing the right thing with
the answer.

### The installer question

A wizard page with two radio options, not a checkbox. A checkbox has a
default, and a default here is a silent guess about the user's hardware
that determines whether the feature works at all. Two explicit options
make the user state the fact, and neither reads as the "advanced" one.

> **Will you play VRChat on this computer?**
>
> ( ) **VRChat will be played on this computer**
>     Frivo will set up everything it needs. Nothing else to install.
>
> ( ) **VRChat will be played on a different computer**
>     You'll install a small Frivo helper on that computer. Frivo will
>     give you the download and set it up for you.

Deliberately phrased around where VRChat *is*, not around what to
install. The user knows which computer they play on; they should not have
to know what a companion process is, or infer from "recommended" which
one applies to them.

### What each answer does

**This computer** — installs the companion alongside Frivo, sets it to
autostart, points it at `localhost`. The user does nothing further and
never needs to know it exists. Same click count as today.

**A different computer** — installs nothing extra here. The final wizard
page, and Frivo's Settings, both offer the companion as a download with
this server's address already baked in, so setting it up on the VRChat PC
is: download, run, done. No address typed, no command run, no firewall
prompt (see above — it needs none).

Either answer must be changeable afterwards from Frivo's Settings, since
people move machines around and some will answer wrong. That is the same
two options, worded the same way, in a settings row rather than a wizard
page.

### Edge case worth a decision

Frivo is useful without VRChat — voice replies, profiles, transcription.
Someone installing it purely for that has to answer a VRChat question that
does not apply to them.

Two options still handles it correctly: "a different computer" installs
nothing and does nothing, so a non-VRChat user picking it is harmless. But
it reads oddly. A third option ("I don't play VRChat") would be honest at
the cost of making the page busier. Leaning toward two, on the grounds
that the wrong answer costs nothing.

Since the companion needs no firewall rule and writes nothing outside its
own folder, its installer can be far lighter than Frivo's — no elevation,
no certificate work, no registry beyond an autostart entry. Uninstalling
is deleting a folder and that entry.

That is also why baking the server address into the download works: the
companion has no config to speak of, so "configured" means one address in
one file next to the executable.

## Settled

- **No firewall rules, either side.** Outbound-only companion, loopback
  OSC, and port 5000 already open. Any "enable OSC → open ports" flow is
  solving a problem this design deletes.
- **Same-PC installs run the companion too** — bundled and autostarted, so
  it stays invisible. No second code path in Frivo.
- **LAN scope stays LAN scope.** The companion must not become the reason
  an unauthenticated Frivo ends up reachable from the internet.
- **Setup asks one question**: will you play VRChat on this computer, or a
  different one. Two radio options, no default, phrased around the user's
  hardware rather than around what gets installed. Changeable later from
  Settings.
- **It is called FrivOSC.** `FrivOSC.exe` on disk, "friv-oh-ess-see" out
  loud, and never FrivOCS.

## Open questions

1. Token auth, or match the app's existing no-auth posture?
2. Port `chatbox_pages`, or keep paging server-side?
3. Python prototype first, or straight to a compiled companion?
4. Does the companion get a tray UI, or run silently with a log?
5. How aggressively to deprecate `osc_host` — one release, or leave it?
6. Two options on the setup page, or a third for "I don't play VRChat"?

## Unverified assumption

All of this rests on VRChat actually emitting `MuteSelf` the way we
believe. That has never been tested on real hardware — not with the
current in-Frivo version either. It is worth ten minutes with the existing
build before committing to any of this, because if the parameter behaves
differently the companion's whole reason for existing changes shape.
