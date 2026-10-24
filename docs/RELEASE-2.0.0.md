# Frivo 2.0.0

## Updating from 1.x

- **Frivo 1.4.0 or newer updates itself**, like any other update: the *Update* chip in the top bar, or Settings › Updates. Everything is kept: settings, keys, profiles, saved replies, voices.
- **An update keeps Frivo as it was**, in your browser with its launcher. To add the new **Frivo app**, run `FrivoSetup.exe` from this release once, choose **Update**, and pick *Run Frivo here, in the Frivo app*. Nothing needs uninstalling.
- **Older than 1.4.0:** download `FrivoSetup.exe` from this release and run it. It updates in place.
- On a PC that only needs the app (Frivo runs on another PC), run `FrivoSetup.exe` and choose *Just the Frivo app*.

## The Frivo app (new)

Frivo in its own window for Windows, with a tray icon and no browser tab.

**One setup for everything.** `FrivoSetup.exe` now asks what the PC is for:

- **Run Frivo here, in the Frivo app** (the default). Frivo runs in the background and the app is its window, so there's only one thing to open. Frivo's launcher stays out of sight: the Frivo shortcuts, starting with Windows, and Frivo coming back after an update all open the app.
- **Run Frivo here, without the app.** Frivo and its launcher, used in a browser, as before. For a PC that phones and other PCs connect to.
- **Just the Frivo app.** For a PC that connects to Frivo on another PC. Nothing else is installed: no Python, voices, certificate or firewall rule. The first time it opens, pick the other PC from the list of Frivo found on your network (or type its address) and type its pairing code; after that the app only accepts that Frivo at that address.

The app comes inside `FrivoSetup.exe`, so there's one file to download whichever you pick, and nothing to fetch during setup. That makes setup bigger (about 125 MB) and every update the same size. Updating an existing Frivo keeps what it was; choose the app on the "How you'll use Frivo" page to add it.

What else it does:

- **Same Frivo, same version.** The app shows Frivo's own pages, so every Frivo update shows up in it straight away. Updating Frivo updates the app on the same PC. An app on another PC gets its update from the Frivo it's connected to (not from GitHub), and asks before restarting to install it.
- **Settings › App** (only in the app): where Frivo runs, the network address for phones, Stop Frivo, Start with Windows, what closing the window does, and the app's own updates. The same things are on the tray icon's menu.
- **Closing the window** keeps Frivo running in the tray, so phones and other devices stay connected. **Quit** in the tray stops it. You can change this.
- **When Frivo drops out**, the app says so and reconnects by itself, including through an in-app Frivo update.
- **Nothing changes for browsers and phones.** In a browser on Windows, Settings › Updates offers the app, once, with a way to hide it. The download comes from that Frivo.
- **Existing installs** just add the app. It finds the Frivo that's already here and uses it; settings, profiles, saved replies, voices and keys stay where they are.
- **Uninstalling Frivo** offers to remove the app too, ticked when setup installed them together.

**For the launcher:** a new *app mode*. When the app runs Frivo on this PC, the launcher has no window or tray icon, opens the app wherever it used to show itself, and stops Frivo when the app asks. Uninstall the app, or point it at another PC, and the launcher is back to its own window and tray icon.

**Launch Frivo now**, at the end of setup, starts Frivo as you rather than as administrator. Frivo started that way used to run as administrator until you signed out, and nothing else (a new launcher, or now the app) could stop it.

## One Frivo in Apps & features

The app is called just **Frivo**. With Frivo installed on the same PC, Apps & features shows one **Frivo**, at Frivo's version; uninstalling it offers to remove the app too. The app only gets an entry of its own on a PC where it's installed by itself (or kept when Frivo is uninstalled).

## One build

`Build.bat` builds everything into one file, `dist\FrivoSetup.exe`, with the app inside. That's the only file a release needs; there are no separate app releases. The separate `Build-App.bat` and `Build-Installer.bat` are gone.

## Adding the app later, backups, and uninstalling

- **Adding the app to Frivo, or Frivo to the app, later.** Run `FrivoSetup.exe` again: it sees what's already installed and says so on the "How you'll use Frivo" page. Choosing *in the Frivo app* adds what's missing in place. Nothing has to be uninstalled first, and your settings, profiles and saved replies stay.
- **A backup before updating or repairing.** Setup offers to save one to *Documents\Frivo backups* first (ticked for Repair). It's the same zip as Settings › Updates › Back up, so Restore there brings it back. API keys are left out. If it can't be made, setup asks before changing anything.
- **Uninstalling** asks what to do with your settings and saves: **keep them for next time** (the default; installing Frivo again picks them up) or **delete them**. Deleting ticks *Save a backup first*, and nothing is deleted if that backup can't be made.

## Connecting other devices

- **Frivo is found on your network.** The app lists every Frivo on your network to pick from, by PC name, instead of asking for an address. Typing one still works.
- **Pairing codes.** Connecting the app to another PC asks for a short code, like `K7Q4-MD2X-9P3R`, shown in that PC's launcher and in Frivo under **Settings › Other devices**. It proves it's your Frivo, without reading through certificate fingerprints. Comparing the certificate is still there under "No code?".
- **Settings › Other devices** (new): this PC's network addresses with a **QR code** to scan with a phone, the pairing code, and Frivo's certificate to download, with steps for trusting it on an iPhone or Android phone so the browser stops warning. The launcher has a **QR code** button and shows the pairing code too.

## The Server page

For a PC that runs Frivo for other devices. On a PC set up as Frivo without the app, the Frivo shortcut opens it in your browser and the launcher stays in the tray (its window is under **Show launcher**, and comes up by itself if Frivo won't start). The chat is one click away, and on the tray menu. Anyone can also open it from **Settings › Other devices › Server page**, or at `/server`.

- **Connect a phone or PC:** the address with its QR code, and the pairing code.
- **Health:** whether other devices can reach it (and the firewall port), HTTPS and when its certificate runs out, whether it starts before anyone signs in, and whether an update is waiting.
- **Connected now:** each phone, PC and Frivo app using it, by name where the network knows one, and what it's doing right now (dictating, speaking, writing a reply), or when it was last seen.
- **Graphics card:** its memory over the last ten minutes when Ollama or Evora is in use, and how each service Frivo depends on is doing.
- **Recent activity:** the last things Frivo logged, with warnings and errors marked.
- **Restart** and **Stop**, which only work on the PC Frivo runs on. Stop leaves the launcher open, so Start is right there.

## Settings › Audio

A new **Audio** section in Settings, laid out like Discord's Voice & Video:

- **Input device** (the microphone you dictate with) and **Output device** side by side. The output device is new: replies, voice previews and everything else Frivo plays go there, so Frivo can play in your headphones, or into a virtual cable, while everything else stays on your speakers. It works in the Frivo app, Chrome and Edge; other browsers play through the system default.
- **Output volume**, moved here from Voices.
- **Mic test**: press *Let's check*, say something, and watch the level and hear yourself back through your output device. **Test sound** plays a short chime on the output device.
- **Listening input**: the Listening panel's audio source, with **Check** to see its level against the loudness gate before you start listening.
- Device names show once Frivo is allowed to use the microphone, and the lists update by themselves when you plug something in, so there are no more Reload buttons. Dictation and Listening show the chosen device and lead here.

## FrivOSC is built into the app

The Frivo app now does FrivOSC's job itself: VRChat's chatbox, microphone sync, the typing dots and unmute-when-I-send. Run the app on the PC you play VRChat on and it connects VRChat to Frivo whenever VRChat is running, whether Frivo runs on that PC or another. Nothing else to install, no Python on the VRChat PC, and it talks to Frivo over the app's own trusted connection.

- It only runs while VRChat is running, so the app on a PC without VRChat never picks up chatbox messages meant for the VRChat PC.
- It can be turned off in Settings › App › **VRChat on this PC**, which also shows whether VRChat is connected and your mic state.
- If the separate FrivOSC is installed, setup offers to remove it (ticked) when it installs the app. While the separate one is running, the app stands aside rather than both fighting over VRChat's port.
- The separate FrivOSC keeps working for anyone using Frivo in a browser, without the app.

## Shortcuts in the app

**Settings › App › Shortcuts**: keys that work anywhere, even with VRChat or a game in front. **Ctrl + Alt + D** starts and stops dictation; set one for **Send** too. They press Frivo's own buttons, so they do exactly what clicking them does, with the window hidden or in the tray.

## Starting with Windows

- **Start Frivo when I sign in** is now on by default in setup.
- **Also start Frivo before anyone signs in** (new, off by default): for a PC that only runs Frivo for others. Frivo starts with Windows as you, with no window and without storing your password, so phones and other PCs can connect after a restart or power cut without anyone signing in. When you do sign in, the launcher (or the app) takes it over. Run setup again and choose Repair to turn it off; uninstalling removes it.

## The launcher looks like Frivo

Frivo's launcher, setup and uninstaller use Frivo's current colours. The launcher has Frivo's "Running" pill in the top corner, both addresses on one card, and its settings are switches in rows like Frivo's Settings, instead of radio buttons and checkboxes. Setup's welcome page no longer says you need OpenAI and ElevenLabs keys: free voices and Clean up work without any.

## Fixes

- **Frivo no longer freezes for minutes at a time.** One connection that opened and then said nothing (a browser's speculative connection, a phone that dozed off) held up everyone else for up to three minutes: Frivo was running but answered nobody, and the app said it had stopped responding. Now such a connection waits on its own.
- The app waits a little longer before deciding Frivo has stopped responding, so a busy moment isn't mistaken for it.
- Frivo's server log no longer fills with a line every second from the launcher checking that Frivo is up.
- The volume chip in the message box keeps one width from 5% to 150%.
