# Frivo 1.8.0

## The Frivo app (new)

Frivo in its own window for Windows, with a tray icon and no browser tab.

**One setup for everything.** `FrivoSetup.exe` now asks what the PC is for:

- **Run Frivo here, in the Frivo app** (the default). Frivo runs in the background and the app is its window, so there's only one thing to open. Frivo's launcher stays out of sight: the Frivo shortcuts, starting with Windows, and Frivo coming back after an update all open the app.
- **Run Frivo here, without the app.** Frivo and its launcher, used in a browser, as before. For a PC that phones and other PCs connect to.
- **Just the Frivo app.** For a PC that connects to Frivo on another PC. Nothing else is installed: no Python, voices, certificate or firewall rule. The first time it opens, pick the other PC from the list of Frivo found on your network (or type its address) and type its pairing code; after that the app only accepts that Frivo at that address.

Setup downloads the app (about 100 MB) from the app's releases on GitHub and checks it against the fingerprint GitHub publishes before installing it, so `FrivoSetup.exe` and Frivo's own updates stay small. If the download fails, Frivo is still installed and works in your browser; run setup again to add the app. Updating an existing Frivo keeps what it was; choose the app on the "How you'll use Frivo" page to add it. The app is also a separate download (`FrivoApp-Setup-1.0.0.exe`, tagged `app-v1.0.0`) for anyone who wants just it.

What else it does:

- **Same Frivo.** The app shows Frivo's own pages, so every Frivo update shows up in it straight away. The app only updates itself when its own parts change, and asks before restarting to do it.
- **Settings › App** (only in the app): where Frivo runs, the network address for phones, Stop Frivo, Start with Windows, what closing the window does, and the app's own updates. The same things are on the tray icon's menu.
- **Closing the window** keeps Frivo running in the tray, so phones and other devices stay connected. **Quit** in the tray stops it. You can change this.
- **When Frivo drops out**, the app says so and reconnects by itself, including through an in-app Frivo update.
- **Nothing changes for browsers and phones.** In a browser on Windows, Settings › Updates offers the app, once, with a way to hide it.
- **Existing installs** just add the app. It finds the Frivo that's already here and uses it; settings, profiles, saved replies, voices and keys stay where they are.
- **Uninstalling Frivo** offers to remove the app too, ticked when setup installed them together.

**For the launcher:** a new *app mode*. When the app runs Frivo on this PC, the launcher has no window or tray icon, opens the app wherever it used to show itself, and stops Frivo when the app asks. Uninstall the app, or point it at another PC, and the launcher is back to its own window and tray icon.

**Launch Frivo now**, at the end of setup, starts Frivo as you rather than as administrator. Frivo started that way used to run as administrator until you signed out, and nothing else (a new launcher, or now the app) could stop it.

## Connecting other devices

- **Frivo is found on your network.** The app lists every Frivo on your network to pick from, by PC name, instead of asking for an address. Typing one still works.
- **Pairing codes.** Connecting the app to another PC asks for a short code, like `K7Q4-MD2X-9P3R`, shown in that PC's launcher and in Frivo under **Settings › Other devices**. It proves it's your Frivo, without reading through certificate fingerprints. Comparing the certificate is still there under "No code?".
- **Settings › Other devices** (new): this PC's network addresses with a **QR code** to scan with a phone, the pairing code, and Frivo's certificate to download, with steps for trusting it on an iPhone or Android phone so the browser stops warning. The launcher has a **QR code** button and shows the pairing code too.

## Shortcuts in the app

**Settings › App › Shortcuts**: keys that work anywhere, even with VRChat or a game in front. **Ctrl + Alt + D** starts and stops dictation; set one for **Send** too. They press Frivo's own buttons, so they do exactly what clicking them does, with the window hidden or in the tray.

## Starting with Windows

- **Start Frivo when I sign in** is now on by default in setup.
- **Also start Frivo before anyone signs in** (new, off by default): for a PC that only runs Frivo for others. Frivo starts with Windows as you, with no window and without storing your password, so phones and other PCs can connect after a restart or power cut without anyone signing in. When you do sign in, the launcher (or the app) takes it over. Run setup again and choose Repair to turn it off; uninstalling removes it.

## The launcher looks like Frivo

Frivo's launcher, setup and uninstaller use Frivo's current colours. The launcher has Frivo's "Running" pill in the top corner, both addresses on one card, and its settings are switches in rows like Frivo's Settings, instead of radio buttons and checkboxes. Setup's welcome page no longer says you need OpenAI and ElevenLabs keys: free voices and Clean up work without any.

## Fixes

- The volume chip in the message box keeps one width from 5% to 150%.
