# Frivo 1.2.0

VRChat support has been rebuilt around a new companion app, the service
indicators have moved into the sidebar and now open to their own settings,
and a firewall bug that quietly broke network access has been fixed.

## VRChat now works through FrivOSC

VRChat only speaks OSC to `127.0.0.1`. It will not send to another computer
and will not listen to one — so Frivo could never reach it across a network,
and the old settings asked you to configure something that could not work
unless Frivo and VRChat were on the same PC.

[FrivOSC](https://github.com/Friday7352/FrivOSC) is a small companion that
runs on the PC you play VRChat on, where that traffic already is, and talks
to Frivo over your network instead. No ports to forward, no firewall rule,
no VRChat launch options.

Install FrivOSC on your VRChat PC, then turn on **VRChat OSC** in
**Settings → VRChat**. Three switches:

* **VRChat OSC** — the master switch.
* **Follow VRChat mute** — unmuting in VRChat starts dictation, muting stops
  it. The microphone button still overrides it at any time.
* **Unmute when I send** — opens your VRChat microphone if it is muted, so a
  spoken reply is not delivered into a closed mic. It never mutes you.

Frivo shows FrivOSC's connection state and your VRChat microphone state live.

**Needs FrivOSC 1.1.0 or newer.**

## Service status moved to the sidebar

Evora and FrivOSC each get their own indicator now, instead of sharing one.
They go down independently and for unrelated reasons, and "2 services
offline" made you hover to find out which.

Click one to expand it into that service's settings — Evora's address and
model, or the VRChat switches — without opening the Settings sheet. The
same controls are still in Settings; it is one set of settings shown in two
places, not two copies.

## Listening panel

Clicking a heard message still loads it into the reply box. **Ctrl-click**
(Cmd on a Mac) now adds it to what is already there, so several things
people said can be gathered into one reply.

## Fixes

**Network access from other devices never worked.** The installer's firewall
rule was silently never created, because of a PowerShell parsing bug in how
its arguments were built — the command was rejected and the failure only
logged. If you could not reach Frivo from a phone or another PC, or you had
been using the launcher's "open port" button to make it work, a reinstall
fixes it properly.

**Uninstalling could leave files behind.** The launcher held the `static`
folder open for as long as its window existed, so the uninstaller could not
remove it.

**Settings changes needed a restart.** Edits to the page were compiled once
per run and then never re-read, so a new option could be present in the
files and absent from the page. Static files are also stamped so a browser
cannot serve an old copy.

Long text no longer overflows in the settings rows or the credits card.

## New icons

Frivo, Evora and FrivOSC now share one icon family. Installing updates the
desktop, taskbar and Start Menu icons; Windows caches these aggressively, so
setup now clears that cache as well.

## Removed

* **The old VRChat chatbox settings** (host address and port). FrivOSC
  handles this now — see above.
* **Evora's "Start command"** and the "click to start" prompt on its status
  indicator. It ran a shell command on the Frivo server and only ever worked
  if you had separately set up a scheduled task and remote-management
  firewall rules on the Evora machine, which nothing in either installer
  does. It read as a button that starts Evora; it was a text box for your own
  remote-admin command.

## Upgrading

Your settings are kept. Two things need attention:

1. If you used the VRChat chatbox, install FrivOSC on your VRChat PC. The old
   address and port settings are gone.
2. If you set an Evora start command, it is no longer used.

## Caveats

The microphone options press VRChat's mute key rather than setting a state,
because VRChat exposes no way to set one. They depend on **Options → Voice →
Toggle Voice** being on, which is VRChat's default; with it off, VRChat
treats the key as push-to-talk and FrivOSC will say so in its log rather than
silently doing nothing.

VRChat has an [open bug](https://github.com/vrchat-community/osc/issues/108)
where OSC input can disturb keyboard and controller bindings. It is reported
against a message format FrivOSC does not use, but if you use **Unmute when
I send**, try it at your desk before you try it in a headset.

## For anyone building from source

The version number now lives in a single `VERSION` file at the repository
root. Everything reads it: the Apps & features entry, the setup wizard, the
installer container and the compiled host. They had previously drifted apart.
