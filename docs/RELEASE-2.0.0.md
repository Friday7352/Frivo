# Frivo 2.0.0

## Updating from 1.x

- **Frivo 1.4.0 or newer updates itself**, like any other update: the *Update* chip in the top bar, or Settings › Updates & backup. Everything is kept: settings, keys, profiles, saved replies, voices.
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

- **Same Frivo, same version.** The app shows Frivo's own pages, so every Frivo update shows up in it straight away. Updating Frivo updates the app on the same PC. An app on another PC gets its update from the Frivo it's connected to (not from GitHub) and installs it by itself while it's in the tray or minimized, or the next time it starts. You only ever update Frivo.
- **Settings › Frivo app** (only in the app): where Frivo runs, the network address for phones, Stop Frivo, Start with Windows, what closing the window does, and the app's own updates. The same things are on the tray icon's menu.
- **Closing the window** keeps Frivo running in the tray, so phones and other devices stay connected. **Quit** in the tray stops it. You can change this.
- **When Frivo drops out**, the app says so and reconnects by itself, including through an in-app Frivo update.
- **Nothing changes for browsers and phones.** In a browser on Windows, Settings › Updates & backup offers the app, once, with a way to hide it. The download comes from that Frivo.
- **Existing installs** just add the app. It finds the Frivo that's already here and uses it; settings, profiles, saved replies, voices and keys stay where they are.
- **Uninstalling Frivo** offers to remove the app too, ticked when setup installed them together.

**For the launcher:** a new *app mode*. When the app runs Frivo on this PC, the launcher has no window or tray icon, opens the app wherever it used to show itself, and stops Frivo when the app asks. Uninstall the app, or point it at another PC, and the launcher is back to its own window and tray icon.

**Launch Frivo now**, at the end of setup, starts Frivo as you rather than as administrator. Frivo started that way used to run as administrator until you signed out, and nothing else (a new launcher, or now the app) could stop it.

## One Frivo in Apps & features

The app is called just **Frivo**. With Frivo installed on the same PC, Apps & features shows one **Frivo**, at Frivo's version; uninstalling it offers to remove the app too. The app only gets an entry of its own on a PC where it's installed by itself (or kept when Frivo is uninstalled).

## One build

`Build.bat` builds everything into one file, `dist\FrivoSetup.exe`, with the app inside. That's the only file a release needs; there are no separate app releases. The separate `Build-App.bat` and `Build-Installer.bat` are gone.

## Adding the app later, backups, and uninstalling

- **Setup knows what's installed.** Running `FrivoSetup.exe` again picks what this PC already has (just the app, Frivo without the app, or Frivo in the app) and says so, so an update keeps it as it is. If Frivo was set up with the app and the app has since been uninstalled, it says so and puts it back.
- **Adding the app to Frivo, or Frivo to the app, later.** Run `FrivoSetup.exe` again: it sees what's already installed and says so on the "How you'll use Frivo" page. Choosing *in the Frivo app* adds what's missing in place. Nothing has to be uninstalled first, and your settings, profiles and saved replies stay.
- **A backup before updating or repairing.** Setup offers to save one to *Documents\Frivo backups* first (ticked for Repair). It's the same zip as Settings › Updates & backup › Back up, so Restore there brings it back. API keys are left out unless you tick *Include my API keys in it*, which the uninstaller offers too. If it can't be made, setup asks before changing anything.
- **Uninstalling** asks what to do with your settings and saves: **keep them for next time** (the default; installing Frivo again picks them up) or **delete them**. Deleting ticks *Save a backup first*, and nothing is deleted if that backup can't be made.
- **Restoring a backup made with its API keys** puts those keys back, replacing the ones there. A backup made without them never clears a key.
- **Favourite voices, audio devices and other browser preferences survive.** They live in the browser (or the Frivo app), so uninstalling the app or clearing a browser used to lose them even with *keep them for next time*. Frivo now keeps a copy of each device's and browser's preferences in its own settings folder, which setup's backups include. A browser or a reinstalled app that starts with none takes them back by itself. Saved microphones, the listening input and the output device are found again by name when the browser gives them new ids.

## Connecting other devices

- **Frivo is found on your network.** The app lists every Frivo on your network to pick from, by PC name, instead of asking for an address. Typing one still works.
- **Pairing codes.** Connecting the app to another PC asks for a short code, like `K7Q4-MD2X-9P3R`, shown in that PC's launcher and in Frivo under **Settings › Other devices**. It proves it's your Frivo, without reading through certificate fingerprints. Comparing the certificate is still there under "No code?".
- **Settings › Other devices** (new): this PC's network addresses with a **QR code** to scan with a phone, the pairing code, and Frivo's certificate to download, with steps for trusting it on an iPhone or Android phone so the browser stops warning. The launcher has a **QR code** button and shows the pairing code too.

## Settings, reorganised

Settings is grouped now, and every setting has one home:

- **General:** Accounts & keys, Appearance (its own page now), Audio.
- **Features:** Replies, Voices, Dictation, Listening. Each keeps only its own options, with a **Uses** section that says what it runs on and leads to where that's chosen.
- **Engines:** **Providers** says which engine does each job: chat replies, transcription, listening and translation. **Models & downloads** holds everything Frivo downloads (the built-in AI, the dictation models and NVIDIA's libraries) and where it's all kept (what was Storage).
- **Add-ons:** **FrivOSC** (what was VRChat, plus the app's VRChat on this PC switch), **Evora** (address, model, idle timers, Speaker setup and Voice matching) and **Ollama** (address, models and the models on the Ollama PC), each with a dot for whether it's working.
- **This PC:** Frivo app, Other devices, and Updates & backup, with a badge when an update is waiting.

Old links to Settings › VRChat or Storage open the new pages.


Fast, live dictation that runs inside Frivo, with nothing else to install. In **Settings › Models & downloads**, pick a model and click **Download and use**:

- **Small:** NVIDIA Nemotron 3.5 ASR Streaming, about 680 MB, on the processor. Truly streaming: words appear as you say them. About 40 languages.
- **Medium:** NVIDIA Parakeet TDT v3, about 670 MB, on the processor. Re-reads each sentence as you speak, more accurate. 25 European languages.
- **Large:** Whisper large-v3-turbo (the model Evora uses), about 1.6 GB plus about 1 GB of NVIDIA's libraries the first time. Needs an NVIDIA graphics card. The most accurate, about 100 languages. Its memory shows on the GPU graph as **Built-in dictation**.

All three run on the PC Frivo runs on: no OpenAI, no Evora, and nothing leaves that PC. They're multilingual: the dictation language you pick is passed to the model, or it works it out. The download always happens on the PC Frivo runs on, even when you click the button from a phone or another PC, and each file is checked against its size and checksum before it's kept.

The mic button then uses the new **Live (Frivo)** mode. Your microphone streams to Frivo a few times a second, and words appear as you speak. Each sentence finishes itself when you pause, and Auto-send works as it does with Evora. **Test with my voice** records four seconds from your microphone and shows what the model heard and how long it took. The model loads when you start dictating and frees its memory after 15 minutes without dictation (you can change that), and **Remove** deletes it.

## Listening with the built-in model

Once a dictation model is downloaded, the **Listening** panel uses it too: no Evora, no OpenAI for the words, and nothing leaves the PC Frivo runs on. The audio source streams to Frivo a few times a second, and each person's words appear as they talk, with the language they're speaking. Every finished line is translated into the language picked under **Show me in**, with what was said underneath; with **Live updates** on, the line still being said is translated as it goes too. Nothing is translated when they already speak your language (Small and Large say which language they heard; with Medium, the translation provider decides).

- Translation still uses the provider in **Settings › Providers › Translation** (OpenAI, Ollama or the built-in AI).
- The loudness gate still decides what counts: anything quieter is sent to Frivo as silence, so music or game sound under the gate is never transcribed.
- **Commit every** finishes a line that goes on without a pause.
- Telling voices apart is Evora's, so the speaker controls step aside while the built-in model is listening. **Settings › Providers › Listening** switches back to Evora or OpenAI.

## The Server page

For a PC that runs Frivo for other devices. On a PC set up as Frivo without the app, the Frivo shortcut opens it in your browser and the launcher stays in the tray (its window is under **Show launcher**, and comes up by itself if Frivo won't start). The chat is one click away, and on the tray menu. Anyone can also open it from **Settings › Other devices › Server page**, or at `/server`.

- **Connect a phone or PC:** the address with its QR code, and the pairing code.
- **Health:** whether other devices can reach it (and the firewall port), HTTPS and when its certificate runs out, whether it starts before anyone signs in, and whether an update is waiting.
- **Connected now:** each phone, PC and Frivo app using it, by name where the network knows one, and what it's doing right now (dictating, speaking, writing a reply), or when it was last seen.
- **Graphics card:** its memory over the last ten minutes when Ollama, Evora or built-in dictation's Large model is in use, and how each service Frivo depends on is doing.
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
- It can be turned off in Settings › FrivOSC › **VRChat on this PC**, which also shows whether VRChat is connected and your mic state.
- If the separate FrivOSC is installed, setup offers to remove it (ticked) when it installs the app. While the separate one is running, the app stands aside rather than both fighting over VRChat's port.
- The separate FrivOSC keeps working for anyone using Frivo in a browser, without the app.

## Shortcuts in the app

**Settings › Frivo app › Shortcuts**: keys that work anywhere, even with VRChat or a game in front. **Ctrl + Alt + D** starts and stops dictation; set one for **Send** too. They press Frivo's own buttons, so they do exactly what clicking them does, with the window hidden or in the tray.

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
