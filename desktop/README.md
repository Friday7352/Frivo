# Frivo App

Frivo in its own window, for Windows. It's an [Electron](https://www.electronjs.org)
app that shows Frivo's own pages from Frivo's server, the way a browser tab
does, and adds what a tab can't: a window and tray icon of its own, starting
with Windows, and running Frivo on this PC with nothing else to open.

## Where Frivo runs

The app asks the first time, and **Change where Frivo runs** (tray menu, or
Settings › App) asks again.

**On this PC.** The app doesn't run Frivo's server itself. It starts Frivo's
launcher, which starts the server, follows in-app updates, and starts Frivo
again after one. The app puts the launcher in *app mode* by writing its own
path to `appPath` in `%APPDATA%\Frivo\launcher.json`. In app mode the
launcher (`installer\Launcher.ps1`):

- has no window and no tray icon
- opens the app wherever it used to show itself: the Frivo shortcuts, signing
  in to Windows, and after an update
- stops the server and closes when the app sets `Local\FrivoLauncherStop`
  (Stop Frivo, and Quit)
- goes back to its own window and tray icon if the app is set to another PC,
  or uninstalled (`appPath` then points at nothing)
- never goes into app mode when it's running as administrator (an older
  setup's "Launch Frivo now" did that): the app couldn't stop it, so it keeps
  its own tray icon, and the app's Stop says to use it
- a second launcher started in the background (`-Tray`: the app's Start, or
  signing in) only makes sure the server runs, through
  `Local\FrivoLauncherStart`; one started from a shortcut brings the app up

Starting with Windows is Frivo's own sign-in entry (`HKCU\...\Run\Frivo`, the
same as the launcher's checkbox), which starts the launcher, which opens the
app in the tray. If Frivo isn't installed, the app downloads `FrivoSetup.exe`
from Frivo's newest release, checks it against the SHA-256 GitHub publishes,
and runs it.

**On another PC.** The app connects to Frivo's address there, like a phone
does. Frivo serves HTTPS with a certificate from its own small certificate
authority, made when it was installed, which another PC doesn't know. The
welcome screen lists Frivo found on the network (`src/discovery.js` asks every
address on this PC's private networks for `/api/hello` on port 5000). The
first time, the app asks for that Frivo's pairing code (`src/pairing.js`: the
first 60 bits of the SHA-256 of its authority, as `XXXX-XXXX-XXXX`, accepted
only from a real self-signed authority) and checks it
against the authority the server sent; comparing the full fingerprint is
still offered. Once paired, that authority's certificate is kept for that address, and a server
there is only accepted when its certificate is really signed by it and in
date. (Frivo sends its authority's certificate to anyone who connects, so
just matching it would prove nothing.) (`src/trust.js` says why the
certificate is read before Chromium connects.) Starting with Windows is the
app's own sign-in entry (`HKCU\...\Run\Frivo App`).

**Shortcuts.** Global hotkeys (Electron's `globalShortcut`) set in Settings ›
App › Shortcuts, kept in the app's settings: Ctrl+Alt+D for dictation by
default, and one for Send. The app sends `app:hotkey` to Frivo's page, which
presses its own button (`initDesktopApp` in `app/static/app.js`). The window
isn't throttled in the background, so dictation keeps going behind a game.

## Installed by Frivo's setup

NEW (Frivo 1.8.0). `FrivoSetup.exe` asks what the PC is for: Frivo in the
app (the default), Frivo without the app, or just the app. For the app it
looks up the newest `app-v…` release, downloads `FrivoApp-Setup-<version>.exe`,
checks it against GitHub's SHA-256 (`Select-FrivoAppRelease` and
`Save-FrivoDownload` in `installer\Frivo.Update.psm1`), and runs it silently
as the person signed in at the PC (`Invoke-FrivoAsDesktopUser` in
`installer\Frivo.Setup.psm1`). For Frivo in the app it then sets app mode in
`launcher.json` and tells the app Frivo runs here (`mode: "local"` in its
`app-settings.json`), so the app opens straight to Frivo. The choice is kept
in Frivo's Apps & features entry (`FrivoRole`) for updates and Repair; a
silent in-app update never downloads the app. Uninstalling Frivo offers to
remove the app too.

**So publish an app release before (or with) a Frivo release that should
install it**: setup can only download an app release that exists. Without
one, setup still installs Frivo and says the app couldn't be installed.

The folder, program and uninstaller names setup looks for come from
`package.json` (`name`, `build.executableName`, `productName`);
`tests/test-app-setup.ps1` checks they still agree.

## Frivo's pages and the app

Frivo's pages load in the app with `window.frivoApp` (`src/preload.js`), and
`static/app.js` shows **Settings › App** when it's there. The main process
checks every request against the page it came from, so only Frivo's own pages
at the chosen address can use it. Pages have no Node access and run
sandboxed. The app adds `FrivoApp/<version>` to the user agent.

Because the pages come from Frivo's server, changes to Frivo's UI ship with
Frivo and show up in the app with no app update.

## Updates

The app's releases live in the Frivo repository too, tagged `app-v1.0.0` and
so on, with `FrivoApp-Setup-1.0.0.exe` attached. Frivo's own updater ignores
those tags (they aren't plain versions), and the app ignores Frivo's. The app
checks 20 seconds after starting and every six hours, downloads a newer
version, checks its SHA-256 against the one GitHub publishes, and installs it
when you choose **Restart to update** (Settings › App or the tray menu).
Frivo keeps running through an app update.

## Building and publishing

1. Change `"version"` in `package.json` (the app's own version, separate from
   Frivo's `VERSION` file).
2. Run `Build-App.bat` in the repository root. It runs the tests and writes
   `desktop\dist\FrivoApp-Setup-<version>.exe`. Nothing needs installing
   first: the first time, it downloads a copy of Node.js (pinned in
   `build\Build-App.ps1`, checked against nodejs.org's SHA-256) into
   `desktop\.tools`, and uses only that.
3. Make a GitHub release tagged `app-v<version>` (for example `app-v1.0.1`),
   not a pre-release or a draft, and attach that file with its name unchanged.
4. **Untick "Set as the latest release".** GitHub's "latest release" link is
   what Frivo's README and download links point at, and it should stay on
   Frivo's newest release, not the app's.

Run it without installing: `npm ci` then `npm start` in `desktop\`. Run the
unit tests with `npm test`.

The installer is not code-signed, so Windows SmartScreen warns the first time
someone runs it (*More info › Run anyway*), the same as `FrivoSetup.exe`.

## Files

| File | What it does |
| --- | --- |
| `src/main.js` | The window, tray, connecting, starting and stopping, updates |
| `src/frivo-local.js` | Frivo on this PC: finding it, its launcher, its sign-in entry |
| `src/trust.js` | Trusting Frivo's certificate on another PC |
| `src/pairing.js` | Pairing codes (the same as `app.py` and the launcher work out) |
| `src/discovery.js` | Finding Frivo on the network |
| `src/github.js` | Releases on GitHub, and downloads checked against their SHA-256 |
| `src/address.js` | Turning what's typed into Frivo's address |
| `src/settings.js` | The app's own settings, in `%APPDATA%\Frivo App` |
| `src/preload.js` | `window.frivoApp` and `window.frivoShell` |
| `src/ui/` | The app's own screens: where Frivo runs, starting, trusting, installing |
| `build/installer.nsh` | Uninstalling removes the app's sign-in entry |
| `test/units.test.js` | Unit tests (`npm test`) |
