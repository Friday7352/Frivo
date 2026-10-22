# Frivo 1.8.0

## The Frivo app (new)

Frivo in its own window for Windows, with a tray icon and no browser tab. It's a separate download, `FrivoApp-Setup-1.0.0.exe`, from the app's releases (tagged `app-v1.0.0`). The first time it opens, it asks where Frivo runs:

- **On this PC.** Frivo runs in the background and the app is its window, so there's only one thing to open. Frivo's launcher stays out of sight: the Frivo shortcuts, starting with Windows, and Frivo coming back after an update all open the app instead. If Frivo isn't installed yet, the app downloads its setup from GitHub, checks it, and runs it.
- **On another PC.** Type the address shown in Frivo's launcher on that PC. The first time, the app shows Frivo's certificate and asks you to trust it, then only accepts that one at that address.

What else it does:

- **Same Frivo.** The app shows Frivo's own pages, so every Frivo update shows up in it straight away. The app only updates itself when its own parts change, and asks before restarting to do it.
- **Settings › App** (only in the app): where Frivo runs, the network address for phones, Stop Frivo, Start with Windows, what closing the window does, and the app's own updates. The same things are on the tray icon's menu.
- **Closing the window** keeps Frivo running in the tray, so phones and other devices stay connected. **Quit** in the tray stops it. You can change this.
- **When Frivo drops out**, the app says so and reconnects by itself, including through an in-app Frivo update.
- **Nothing changes for browsers and phones.** In a browser on Windows, Settings › Updates offers the app, once, with a way to hide it.
- **Existing installs** just add the app. It finds the Frivo that's already here and uses it; settings, profiles, saved replies, voices and keys stay where they are.

**For the launcher:** a new *app mode*. When the app runs Frivo on this PC, the launcher has no window or tray icon, opens the app wherever it used to show itself, and stops Frivo when the app asks. Uninstall the app, or point it at another PC, and the launcher is back to its own window and tray icon.

**Launch Frivo now**, at the end of setup, starts Frivo as you rather than as administrator. Frivo started that way used to run as administrator until you signed out, and nothing else (a new launcher, or now the app) could stop it.
