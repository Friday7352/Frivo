# The Frivo app

Windows lists it as just **Frivo**. On a PC where Frivo itself is installed,
it has no entry of its own in Apps & features: there's one Frivo, and
uninstalling it offers to remove the app too (`build/installer.nsh` and
`Set-FrivoAppListed` in `installer/Frivo.Setup.psm1`). Its settings stay in
`%APPDATA%\Frivo App`, apart from Frivo's.

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

NEW (Frivo 2.0.0). The app comes inside `FrivoSetup.exe` (`Build.bat` puts
it in `build\app\`, which `build\Frivo.iss` packs into setup's payload).
Setup asks what the PC is for: Frivo in the app (the default), Frivo without
the app, or just the app. For the app it runs the bundled
`FrivoApp-Setup.exe` silently as the person signed in at the PC
(`Install-FrivoApp` in `installer\Install.ps1`, through
`Invoke-FrivoAsDesktopUser` in `installer\Frivo.Setup.psm1`), unless a newer
app is already installed. For Frivo in the app it then sets app mode in
`launcher.json` and tells the app Frivo runs here (`mode: "local"` in its
`app-settings.json`), so the app opens straight to Frivo. The choice is kept
in Frivo's Apps & features entry (`FrivoRole`) for updates and Repair.
Uninstalling Frivo offers to remove the app too.

Setup also leaves a copy of the app's installer with Frivo
(`app-installer\FrivoApp-Setup.exe` and `app.json`), including on silent
updates. That's what Frivo hands out to other PCs.

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

The app updates from the Frivo it's connected to, not from GitHub. Frivo
answers `/api/app/latest` (`{version, name, size, sha256}`, from the copy
setup left in `app-installer\`) and `/api/app/installer` (the file). The app
looks 8 seconds after it connects and every six hours; if Frivo carries a
newer version, it downloads it, checks its SHA-256 as it arrives
(`downloadChecked` in `src/github.js`), and installs it when you choose
**Restart to update** (Settings › App or the tray menu). Frivo keeps running
through an app update. CHANGED (2.0.0): it also installs by itself, as soon
as the window is in the tray or minimized, or when the app next starts (the
download is remembered in `pendingUpdate`), and an update that installed
from the tray starts the app in the tray again.

Each build has an id (`src/build-id.json`, written by `Build.bat`, also in
`app.json` beside the installer). When Frivo carries a different build of
the same version, the app takes it too, so updating Frivo is all it ever
takes, even between builds that didn't change the version. On the PC Frivo runs on, setup has already updated the
app, so there's nothing to fetch. In a browser, Frivo's page offers the same
file as a download.

The app's version is Frivo's: keep `"version"` in `package.json` the same as
the `VERSION` file (`tests/test-version.py` checks). An app whose version
didn't change isn't offered to other PCs.

## Building

Run `Build.bat` in the repository root. It runs the app's tests, builds the
app, and puts it inside `dist\FrivoSetup.exe`, the only file to publish.
Nothing needs installing first: the first time, it downloads a copy of
Node.js (pinned in `build\Build-App.ps1`, checked against nodejs.org's
SHA-256) into `desktop\.tools`, and uses only that.

Run it without installing: `npm ci` then `npm start` in `desktop\`. Run the
unit tests with `npm test`.

Setup is not code-signed, so Windows SmartScreen warns the first time
someone runs it (*More info › Run anyway*).

## Files

| File | What it does |
| --- | --- |
| `src/main.js` | The window, tray, connecting, starting and stopping, updates |
| `src/frivo-local.js` | Frivo on this PC: finding it, its launcher, its sign-in entry |
| `src/trust.js` | Trusting Frivo's certificate on another PC |
| `src/pairing.js` | Pairing codes (the same as `app.py` and the launcher work out) |
| `src/discovery.js` | Finding Frivo on the network |
| `src/osc.js` | FrivOSC, built in: VRChat's chatbox and microphone (ported from the FrivOSC repository's `frivosc_service.py`) |
| `src/github.js` | Frivo's releases on GitHub, and downloads checked against their SHA-256 |
| `src/address.js` | Turning what's typed into Frivo's address |
| `src/settings.js` | The app's own settings, in `%APPDATA%\Frivo App` |
| `src/preload.js` | `window.frivoApp` and `window.frivoShell` |
| `src/ui/` | The app's own screens: where Frivo runs, starting, trusting, installing |
| `build/installer.nsh` | Uninstalling removes the app's sign-in entry |
| `test/units.test.js` | Unit tests (`npm test`) |
