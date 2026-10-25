'use strict';
/*
  Frivo App: Frivo in its own window.

  Frivo itself is a web app served by Frivo's server (Python, app\app.py).
  This app shows it, the way a browser tab does, and adds what a tab can't:
  a window and a tray icon of its own, starting with Windows, and running
  Frivo on this PC without a separate launcher window.

    On this PC       Frivo's launcher runs Frivo's server in the background
                     (app mode, see frivo-local.js); this app is the window.
    On another PC    connects to Frivo's address there, like a phone does.

  Frivo's pages come from Frivo's server, so a Frivo update changes what's
  shown here with no update to this app. This app updates itself only when
  its own parts change (updater below), from its own releases on GitHub.
*/

const {
  app, BrowserWindow, Tray, Menu, ipcMain, session, shell, net, nativeImage,
  clipboard, Notification, dialog, screen, globalShortcut,
} = require('electron');
const path = require('path');
const fs = require('fs');
const { pathToFileURL } = require('url');
const { spawn } = require('child_process');

const pkg = require('../package.json');
const { Settings } = require('./settings');
const { normalizeAddress } = require('./address');
const trust = require('./trust');
const gh = require('./github');
const { FrivoLocal, lanAddress } = require('./frivo-local');
const pairing = require('./pairing');       // NEW: pairing codes
const discovery = require('./discovery');   // NEW: finding Frivo on the network
const { FrivOSC } = require('./osc');       // NEW (2.0.0): FrivOSC, built in
// NEW (2.0.0): which build this is (Build.bat writes it). Frivo may carry a
// newer build of the same version, and the app follows the Frivo it uses.
let BUILD_ID = '';
try { BUILD_ID = String(require('./build-id.json').build || ''); } catch { BUILD_ID = ''; }
const os = require('os');
const { execFile } = require('child_process');

const REPOSITORY = pkg.frivo.repository;
const PORT = pkg.frivo.port;
const MINIMUM_FRIVO = gh.parseVersion(pkg.frivo.minimumFrivo);
// FIXED: from "frivo", not "build": electron-builder takes the "build"
// section out of package.json when it packages the app, so reading it there
// crashed the installed app at start. Must match build.appId (the unit
// tests check).
const APP_ID = pkg.frivo.appId;
const IS_WINDOWS = process.platform === 'win32';
const UPDATE_EVERY_MS = 6 * 60 * 60 * 1000;
const PROBE_EVERY_MS = 4000;

// For tests and for working on the app away from Windows: "Frivo on this
// PC" is this address, with none of the Windows parts (launcher, registry).
const TEST_LOCAL_ORIGIN = process.env.FRIVO_APP_LOCAL_ORIGIN || '';

// The app's own folder. Never %APPDATA%\Frivo, which is Frivo's: Electron
// would otherwise pick a folder named after the app, right next to it.
app.setPath('userData', process.env.FRIVO_APP_USER_DATA || path.join(app.getPath('appData'), 'Frivo App'));
if (IS_WINDOWS) app.setAppUserModelId(APP_ID);

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  start();
}

function start() {
  const settings = new Settings(path.join(app.getPath('userData'), 'app-settings.json'));
  const local = new FrivoLocal({ appData: app.getPath('appData'), execPath: process.execPath });
  // CHANGED (2.0.0): also after an update that installed itself while the
  // app was in the tray.
  const hiddenStart = process.argv.includes('--hidden') || settings.get('startHiddenOnce') === true;
  if (settings.get('startHiddenOnce')) settings.update({ startHiddenOnce: false });

  // ---------------------------------------------------------------- FrivOSC (NEW, 2.0.0)
  // VRChat's chatbox and microphone, done by the app on the PC that plays
  // VRChat (osc.js says how). Talks to whichever Frivo the app is connected
  // to, through the app's own trusted connection.
  const OSC_LOG = path.join(app.getPath('userData'), 'frivosc.log');
  const [oscListen, oscSend] = (process.env.FRIVO_APP_OSC_PORTS || '9001,9000').split(',').map(Number);
  const vrchatOverride = process.env.FRIVO_APP_VRCHAT || '';   // 'always' / 'never', for tests
  const oscBridge = new FrivOSC({
    listenPort: oscListen || 9001,
    sendPort: oscSend || 9000,
    version: app.getVersion(),
    hostname: os.hostname(),
    request: async (method, urlPath, body) => {
      const origin = oscBridge.connectedTo;
      if (!origin) throw new Error('not connected');
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await net.fetch(`${origin}${urlPath}`, {
          method,
          headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
          body: body ? JSON.stringify(body) : undefined,
          cache: 'no-store',
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Frivo answered ${response.status}`);
        return await response.json().catch(() => ({}));
      } finally {
        clearTimeout(timer);
      }
    },
    // Only while VRChat runs here: the app on the PC Frivo runs on mustn't
    // take the chatbox messages meant for the app on the VRChat PC.
    vrchatRunning: () => new Promise((resolve) => {
      if (vrchatOverride) { resolve(vrchatOverride === 'always'); return; }
      if (!IS_WINDOWS) { resolve(false); return; }
      execFile('tasklist.exe', ['/FI', 'IMAGENAME eq VRChat.exe', '/FO', 'CSV', '/NH'], { windowsHide: true, timeout: 4000 },
        (err, stdout) => resolve(!err && /"VRChat\.exe"/i.test(String(stdout))));
    }),
    // The separate FrivOSC, if it's installed and at work: its status file
    // is rewritten every couple of seconds while it runs.
    standaloneRunning: () => {
      if (!IS_WINDOWS || vrchatOverride) return false;
      try {
        const file = path.join(process.env.ProgramData || 'C:\\ProgramData', 'FrivOSC', 'status.json');
        const status = JSON.parse(fs.readFileSync(file, 'utf8'));
        return Boolean(status.running) && Date.now() / 1000 - Number(status.updated_at || 0) < 15;
      } catch {
        return false;
      }
    },
    log: (text) => {
      try {
        if (fs.existsSync(OSC_LOG) && fs.statSync(OSC_LOG).size > 1000000) fs.renameSync(OSC_LOG, `${OSC_LOG}.old`);
        fs.appendFileSync(OSC_LOG, `[${new Date().toISOString().replace('T', ' ').slice(0, 19)}] ${text}\n`);
      } catch { /* logging never stops the bridge */ }
    },
    // pushState is declared further down; before the window exists it has
    // nothing to tell anyway.
    onChange: () => { pushState().catch(() => {}); },
  });
  oscBridge.setEnabled(settings.get('vrchatBridge'));

  const state = {
    win: null,
    tray: null,
    // What's in the window: 'shell' (the app's own screens) or 'frivo'.
    showing: null,
    view: null,             // the shell screen showing, or to show
    origin: null,           // the Frivo being shown, once it answers
    pendingLoad: false,     // started hidden: Frivo's page loads on first show
    everShown: false,
    connected: false,
    misses: 0,
    probeTimer: null,
    install: null,          // Frivo on this PC, as found
    lanUrl: null,
    userStopped: false,
    quitting: false,
    localPins: {},          // hostname -> { fingerprint, pem }, for Frivo on this PC
    pendingTrust: null,     // the certificate the trust screen is asking about
    connectSeq: 0,          // a newer connect makes older ones give up
    update: { state: 'idle', version: '', error: '', file: '', percent: 0 },
    busy: false,            // install or start in progress: no double clicks
    discovery: { searching: false, servers: [] },   // NEW: Frivo found on the network
    discoverySeq: 0,
    hotkeyErrors: {},       // NEW: shortcuts that couldn't be registered, and why
    queuedHotkey: '',       // NEW: pressed before Frivo's page was loaded
  };

  const iconPath = path.join(__dirname, '..', 'build', IS_WINDOWS ? 'icon.ico' : 'icon.png');

  // ---------------------------------------------------------------- helpers

  function originOf(url) {
    try { return new URL(url).origin; } catch { return null; }
  }

  function hostOf(url) {
    try { return new URL(url).host; } catch { return url; }
  }

  // Exactly the app's own screens, nothing else that happens to be a file.
  const SHELL_URL = pathToFileURL(path.join(__dirname, 'ui', 'shell.html')).href;
  function isShellUrl(url) {
    return String(url || '').split(/[?#]/)[0] === SHELL_URL;
  }

  function fromShell(event) {
    return isShellUrl(event.senderFrame && event.senderFrame.url);
  }

  function fromFrivo(event) {
    return Boolean(state.origin) && originOf(event.senderFrame && event.senderFrame.url) === state.origin;
  }

  function notify(title, body) {
    try {
      if (Notification.isSupported()) new Notification({ title, body, icon: iconPath, silent: true }).show();
    } catch { /* no notifications: nothing lost */ }
  }

  async function probe(origin, timeoutMs = 3500) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await net.fetch(`${origin}/static/icon.png`, {
        method: 'HEAD', cache: 'no-store', signal: controller.signal, bypassCustomProtocolHandlers: true,
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function frivoOutdated() {
    if (!state.install || !state.install.version) return false;
    const v = gh.parseVersion(state.install.version);
    return Boolean(v && gh.compareVersions(v, MINIMUM_FRIVO) < 0);
  }

  // ---------------------------------------------------------------- window

  function restoreBounds() {
    const b = settings.get('bounds');
    if (!b || typeof b.width !== 'number') return { width: 1280, height: 860 };
    const area = screen.getDisplayMatching(b).workArea;
    const visible = b.x < area.x + area.width - 80 && b.x + b.width > area.x + 80 &&
                    b.y < area.y + area.height - 80 && b.y + b.height > area.y;
    return visible ? b : { width: b.width, height: b.height };
  }

  function createWindow() {
    const bounds = restoreBounds();
    const win = new BrowserWindow({
      ...bounds,
      minWidth: 380,
      minHeight: 520,
      show: false,
      title: 'Frivo',
      icon: iconPath,
      backgroundColor: '#0f1013',
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        spellcheck: true,
        // NEW: dictation started by a hotkey keeps going with the window
        // hidden or behind VRChat.
        backgroundThrottling: false,
      },
    });
    win.setMenuBarVisibility(false);
    if (settings.get('bounds') && settings.get('bounds').maximized) win.maximize();

    // The page's own <title> would replace "Frivo" with whatever it says.
    win.on('page-title-updated', (e) => e.preventDefault());

    let saveTimer = null;
    const saveBounds = () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        if (win.isDestroyed()) return;
        settings.set('bounds', { ...win.getNormalBounds(), maximized: win.isMaximized() });
      }, 400);
    };
    win.on('resize', saveBounds);
    win.on('move', saveBounds);
    // NEW (2.0.0): put away with an update waiting: it installs now.
    win.on('hide', () => setTimeout(autoInstallWhenAway, 1500));
    win.on('minimize', () => setTimeout(autoInstallWhenAway, 1500));

    win.on('close', (e) => {
      if (state.quitting) return;
      e.preventDefault();
      if (settings.get('closeAction') === 'quit') {
        quitApp();
        return;
      }
      win.hide();
      if (!settings.get('trayNoticeShown')) {
        settings.set('trayNoticeShown', true);
        notify('Frivo is still running', 'Frivo keeps running in the tray. Right-click its icon to quit.');
      }
    });

    win.on('show', () => {
      state.everShown = true;
      if (state.pendingLoad && state.origin) {
        state.pendingLoad = false;
        loadFrivoPage(state.origin);
      }
    });

    const wc = win.webContents;

    // Keys a browser would have: reload, zoom, and the developer tools for
    // looking into a problem.
    wc.on('before-input-event', (event, input) => {
      if (input.type !== 'keyDown') return;
      const ctrl = input.control || input.meta;
      const key = String(input.key || '').toLowerCase();
      if (key === 'f5' || (ctrl && key === 'r')) { event.preventDefault(); reload(); }
      else if (ctrl && (key === '=' || key === '+')) { event.preventDefault(); wc.setZoomLevel(Math.min(wc.getZoomLevel() + 0.5, 4)); }
      else if (ctrl && key === '-') { event.preventDefault(); wc.setZoomLevel(Math.max(wc.getZoomLevel() - 0.5, -3)); }
      else if (ctrl && key === '0') { event.preventDefault(); wc.setZoomLevel(0); }
      else if (key === 'f12' || (ctrl && input.shift && key === 'i')) { event.preventDefault(); wc.toggleDevTools(); }
    });

    // Links to anywhere but Frivo open in the browser.
    wc.on('will-navigate', (event, url) => {
      if (isShellUrl(url)) return;
      if (state.origin && originOf(url) === state.origin) return;
      event.preventDefault();
      if (/^https?:/i.test(url)) shell.openExternal(url);
    });
    wc.setWindowOpenHandler(({ url }) => {
      if (state.origin && originOf(url) === state.origin) {
        return {
          action: 'allow',
          overrideBrowserWindowOptions: { icon: iconPath, autoHideMenuBar: true, backgroundColor: '#0f1013' },
        };
      }
      if (/^https?:/i.test(url)) shell.openExternal(url);
      return { action: 'deny' };
    });

    // Frivo's page failed to load (it went away between the check and the
    // load): treat it like losing the connection.
    wc.on('did-fail-load', (event, code, description, url, isMainFrame) => {
      if (!isMainFrame || code === -3 /* aborted: a newer load */) return;
      if (state.showing === 'frivo') connectionLost();
    });

    wc.on('render-process-gone', () => {
      if (!state.quitting) setTimeout(reload, 500);
    });

    return win;
  }

  function showWindow() {
    const win = state.win;
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  }

  function reload() {
    if (state.showing === 'frivo' && state.origin) loadFrivoPage(state.origin);
    else if (state.showing === 'shell') sendView();
  }

  // ---------------------------------------------------------------- shell screens

  function showView(view) {
    state.view = { ...view, appVersion: app.getVersion() };
    if (state.showing !== 'shell') {
      state.showing = 'shell';
      state.win.loadFile(path.join(__dirname, 'ui', 'shell.html')).catch(() => {});
      // The page asks for the view once it's ready (shell:ready).
    } else {
      sendView();
    }
    rebuildTray();
  }

  function sendView() {
    if (state.win && !state.win.isDestroyed() && state.showing === 'shell') {
      state.win.webContents.send('shell:view', state.view);
    }
  }

  function busyView(title, detail, actions = [], extra = {}) {
    showView({ name: 'status', spinner: true, title, detail, actions, ...extra });
  }

  function errorView(title, detail, actions = [], extra = {}) {
    showView({ name: 'status', spinner: false, tone: 'error', title, detail, actions, ...extra });
  }

  // NEW: looks for Frivo on the network while the welcome screen is up, and
  // fills the list in as each one answers.
  function startDiscovery() {
    const run = ++state.discoverySeq;
    state.discovery = { searching: true, servers: [] };
    const push = () => {
      if (run !== state.discoverySeq || !state.view || state.view.name !== 'welcome') return;
      state.view = { ...state.view, discovery: { ...state.discovery, servers: [...state.discovery.servers] } };
      sendView();
    };
    discovery.findFrivo({
      port: PORT,
      cancelled: () => run !== state.discoverySeq,
      onFound: (server) => {
        if (run !== state.discoverySeq) return;
        state.discovery.servers.push(server);
        state.discovery.servers.sort((a, b) => a.name.localeCompare(b.name));
        push();
      },
    }).catch(() => {}).finally(() => {
      if (run !== state.discoverySeq) return;
      state.discovery.searching = false;
      push();
    });
  }

  async function welcomeView(extra = {}) {
    // Whatever was connecting or being watched stops: the choice is open again.
    ++state.connectSeq;
    stopProbing();
    startDiscovery();
    const install = IS_WINDOWS ? await local.findInstall() : null;
    state.install = install || state.install;
    showView({
      name: 'welcome',
      local: {
        supported: IS_WINDOWS || Boolean(TEST_LOCAL_ORIGIN),
        installed: Boolean(install) || Boolean(TEST_LOCAL_ORIGIN),
        version: install ? install.version : '',
      },
      remoteUrl: settings.get('remoteUrl') || '',
      discovery: state.discovery,
      current: settings.get('mode'),
      canGoBack: Boolean(settings.get('mode')),
      ...extra,
    });
  }

  // ---------------------------------------------------------------- connecting

  async function connect() {
    const mode = settings.get('mode');
    if (mode === 'local') return connectLocal();
    if (mode === 'remote') return connectRemote();
    return welcomeView();
  }

  function stopProbing() {
    oscBridge.setConnection(null);   // NEW (2.0.0)
    clearInterval(state.probeTimer);
    state.probeTimer = null;
    state.connected = false;
    state.misses = 0;
    state.pendingLoad = false;
  }

  // Frivo answers at `origin`: show it, and keep checking it's still there.
  function frivoReady(origin) {
    state.origin = origin;
    oscBridge.setConnection(origin);   // NEW (2.0.0)
    // NEW (2.0.0): the app's update comes from Frivo, so look once it answers.
    if (state.update.state === 'idle' || state.update.state === 'error') setTimeout(() => checkForAppUpdate(), 8000);
    state.connected = true;
    state.userStopped = false;   // it's running, whoever started it
    state.misses = 0;
    clearInterval(state.probeTimer);
    state.probeTimer = setInterval(async () => {
      if (!state.connected || !state.origin) return;
      // CHANGED (2.0.0): more patient. Frivo busy (starting a voice, a long
      // reply) isn't Frivo gone: three misses in a row, each given 6 seconds.
      if (await probe(state.origin, 6000)) { state.misses = 0; return; }
      state.misses += 1;
      if (state.misses >= 3) connectionLost();
    }, PROBE_EVERY_MS);

    if (!state.everShown && !state.win.isVisible()) {
      // Started at sign-in, in the tray: Frivo's page waits until the window
      // is first opened, so nothing in it (listening, say) runs unseen.
      state.pendingLoad = true;
      state.showing = null;
    } else {
      loadFrivoPage(origin);
    }
    rebuildTray();
    pushState();
  }

  function loadFrivoPage(origin) {
    state.showing = 'frivo';
    state.win.loadURL(`${origin}/`).catch(() => {});
  }

  async function waitForFrivo(origins, { seq, timeoutMs, onWait } = {}) {
    const until = Date.now() + (timeoutMs || 120000);
    while (Date.now() < until) {
      if (seq !== undefined && seq !== state.connectSeq) return null;
      for (const origin of origins) {
        if (await probe(origin)) return origin;
      }
      if (onWait) onWait();
      await sleep(1500);
    }
    return null;
  }

  async function connectLocal() {
    const seq = ++state.connectSeq;
    stopProbing();
    state.origin = null;
    state.queuedHotkey = '';   // NEW: not for another page

    if (TEST_LOCAL_ORIGIN) {
      busyView('Starting Frivo…', '');
      const origin = await waitForFrivo([TEST_LOCAL_ORIGIN], { seq, timeoutMs: 60000 });
      if (seq !== state.connectSeq) return;
      if (origin) frivoReady(origin);
      else errorView("Frivo didn't start", '', [{ id: 'retry', label: 'Try again', primary: true }, { id: 'change', label: 'Change where Frivo runs' }]);
      return;
    }

    const install = await local.findInstall();
    if (seq !== state.connectSeq) return;
    state.install = install;
    if (!install) {
      local.setAppMode(false);
      await syncShortcuts();
      welcomeView({ notice: "Frivo isn't installed on this PC. Install it, or connect to Frivo on another PC." });
      return;
    }

    // From here the launcher keeps to the background and opens this app. A
    // Frivo too old to have app mode keeps its launcher as it was, and the
    // app keeps its own shortcuts.
    const outdated = frivoOutdated();
    if (!local.setAppMode(!outdated)) {
      notify("Frivo's settings couldn't be updated", "The launcher may still show its own window. Try again from the tray icon.");
    }
    await syncShortcuts();

    // Frivo's own certificate authority, from its data folder: trusted for
    // this PC's own addresses even if setup couldn't add it to Windows.
    const pin = trust.localAuthorityPin(local.authorityCert);
    state.localPins = pin ? { localhost: pin, '127.0.0.1': pin } : {};

    lanAddress().then((ip) => { state.lanUrl = ip ? `https://${ip}:${PORT}` : null; rebuildTray(); pushState(); });

    if (outdated) {
      notify('Update Frivo', `Frivo ${install.version} runs fine here, but update it to ${pkg.frivo.minimumFrivo} or newer so its launcher stays in the background.`);
    }

    const origins = [`https://localhost:${PORT}`, `http://localhost:${PORT}`];
    for (const origin of origins) {
      if (await probe(origin)) {
        if (seq === state.connectSeq) frivoReady(origin);
        return;
      }
    }
    if (seq !== state.connectSeq) return;

    state.userStopped = false;
    local.startLauncher(install);
    busyView('Starting Frivo…', 'The first start after installing or updating can take a little longer.');
    const origin = await waitForFrivo(origins, {
      seq,
      timeoutMs: 150000,
      onWait: () => {
        const update = local.updateStatus();
        if (update && /install|download|queue|stopp/i.test(update.state)) {
          busyView('Updating Frivo…', update.message || 'Frivo starts again when the update finishes.');
        }
      },
    });
    if (seq !== state.connectSeq) return;
    if (origin) {
      frivoReady(origin);
    } else {
      errorView("Frivo didn't start", 'The server log usually says why.', [
        { id: 'retry', label: 'Try again', primary: true },
        { id: 'log', label: 'View server log' },
        { id: 'change', label: 'Change where Frivo runs' },
      ]);
    }
  }

  /*
    Whether Frivo at `url` can be shown: 'up', 'down' (nothing answers), or
    { trust: info } when it answers with a certificate not trusted yet.

    The certificate is read here first, outside Chromium, and Chromium only
    connects once it's one that will be accepted. Chromium remembers a
    certificate it turned down (for half an hour), so letting it try one
    before the person had trusted it would keep the address failing after
    they did.
  */
  async function remoteCheck(url, timeoutMs = 6000) {
    const u = new URL(url);
    if (u.protocol === 'https:') {
      let info = null;
      try { info = await trust.inspectServer(url, timeoutMs); } catch { info = null; }
      if (!info) return 'down';
      if (!info.trustedBySystem) {
        const pin = settings.get('trusted')[trust.pinKey(u.hostname)];
        const pinOk = pin && typeof pin === 'object' && trust.leafTrustedBy(info.leafRaw, pin);
        if (!pinOk) return { trust: info, pinned: pin && pin.fingerprint };
      }
    }
    return (await probe(url, timeoutMs)) ? 'up' : 'down';
  }

  function trustView(url, info, pinned) {
    // The same authority as before, but it didn't sign what was sent (or
    // what it signed is out of date): not something to offer to trust.
    if (pinned && pinned === info.fingerprint) {
      state.pendingTrust = null;
      errorView(`Frivo at ${hostOf(url)} didn't prove who it is`,
        "It sent the certificate you trusted, but not one signed by it, or one that's out of date. That isn't what Frivo does, so the app won't connect. If you just reinstalled Frivo on that PC, restart it there and try again.",
        [{ id: 'retry', label: 'Try again', primary: true }, { id: 'change', label: 'Change where Frivo runs' }]);
      return;
    }
    // A chain that doesn't hold together can't be trusted at all.
    const pin = { fingerprint: info.fingerprint, pem: info.authorityPem };
    if (!trust.leafTrustedBy(info.leafRaw, pin)) {
      state.pendingTrust = null;
      errorView(`Frivo at ${hostOf(url)} sent a certificate that doesn't check out`,
        "Its certificate isn't signed by the authority it came with, or it's out of date, so the app won't connect.",
        [{ id: 'retry', label: 'Try again', primary: true }, { id: 'change', label: 'Change where Frivo runs' }]);
      return;
    }
    // CHANGED: asks for the pairing code shown on that PC; comparing the
    // certificate's fingerprint is still there as "No code?".
    state.pendingTrust = { key: trust.pinKey(new URL(url).hostname), pin, code: info.pairingCode, url, info, changed: Boolean(pinned) };
    pairView();
  }

  function pairView(error = '') {
    const p = state.pendingTrust;
    if (!p) return;
    showView({
      name: 'pair',
      host: hostOf(p.url),
      serverName: settings.get('remoteName') || '',
      changed: p.changed,
      error,
    });
  }

  function fingerprintView() {
    const p = state.pendingTrust;
    if (!p) return;
    showView({
      name: 'trust',
      host: hostOf(p.url),
      changed: p.changed,
      authority: p.info.authority,
      server: p.info.server,
      names: p.info.names,
      fingerprint: trust.formatFingerprint(p.info.fingerprint),
      fullFingerprint: p.info.fingerprint,
    });
  }

  // Keeps checking until Frivo at `url` is back (resolves 'up'), needs its
  // certificate trusted ({ trust }), or a newer connect takes over (null).
  async function waitForRemote(url, seq) {
    for (;;) {
      if (seq !== state.connectSeq) return null;
      const result = await remoteCheck(url, 4000);
      if (seq !== state.connectSeq) return null;
      if (result !== 'down') return result;
      await sleep(2500);
    }
  }

  async function connectRemote() {
    const seq = ++state.connectSeq;
    stopProbing();
    state.origin = null;
    state.queuedHotkey = '';   // NEW: not for another page
    const url = settings.get('remoteUrl');
    if (!url) { welcomeView(); return; }
    const host = hostOf(url);

    busyView(`Connecting to ${host}…`, '');
    let result = await remoteCheck(url);
    if (seq !== state.connectSeq) return;
    if (result === 'down') {
      errorView(`Can't reach Frivo at ${host}`,
        'Check that Frivo is running on that PC and that this PC is on the same network. Trying again every few seconds.',
        [{ id: 'retry', label: 'Try again', primary: true }, { id: 'change', label: 'Change where Frivo runs' }],
        { waiting: true });
      result = await waitForRemote(url, seq);
      if (!result) return;
    }
    if (result === 'up') frivoReady(url);
    else trustView(url, result.trust, result.pinned);
  }

  // Frivo stopped answering while it was shown.
  async function connectionLost() {
    if (!state.connected) return;
    stopProbing();
    const seq = ++state.connectSeq;
    const origin = state.origin;
    const mode = settings.get('mode');

    if (mode === 'local' && state.userStopped) {
      stoppedView();
      return;
    }
    if (mode === 'local') {
      const update = local.updateStatus();
      if (update && /install|download|queue|stopp|done/i.test(update.state)) {
        busyView('Updating Frivo…', update.message || 'Frivo starts again when the update finishes.');
      } else {
        busyView('Frivo stopped responding', 'Waiting for it to come back…', [
          { id: 'retry', label: 'Start Frivo', primary: true },
          { id: 'log', label: 'View server log' },
        ]);
      }
      const back = await waitForFrivo([origin], {
        seq,
        timeoutMs: 10 * 60 * 1000,
        onWait: () => {
          const u = local.updateStatus();
          if (u && /install|download|queue|stopp/i.test(u.state) && state.view && state.view.title !== 'Updating Frivo…') {
            busyView('Updating Frivo…', u.message || 'Frivo starts again when the update finishes.');
          }
        },
      });
      if (seq !== state.connectSeq) return;
      if (back) frivoReady(back);
      else connectLocal();
      return;
    }

    busyView(`Reconnecting to ${hostOf(origin)}…`, 'Frivo on that PC stopped answering. This reconnects as soon as it\'s back.', [
      { id: 'change', label: 'Change where Frivo runs' },
    ]);
    const result = await waitForRemote(origin, seq);
    if (!result || seq !== state.connectSeq) return;
    if (result === 'up') frivoReady(origin);
    else trustView(origin, result.trust, result.pinned);
  }

  function stoppedView() {
    showView({
      name: 'status',
      spinner: false,
      title: 'Frivo is stopped',
      detail: "Phones and other devices can't reach it until it's started again.",
      actions: [{ id: 'start', label: 'Start Frivo', primary: true }, { id: 'change', label: 'Change where Frivo runs' }],
    });
  }

  // ---------------------------------------------------------------- choosing

  async function chooseLocal() {
    const previous = settings.get('mode');
    settings.update({ mode: 'local' });
    if (previous === 'remote') applyRemoteLoginItem(false);
    await connectLocal();
  }

  async function chooseRemote(text, name = '') {
    const parsed = normalizeAddress(text, PORT);
    if (!parsed.ok) return parsed;
    ++state.discoverySeq;   // the list is done with
    const previous = settings.get('mode');
    if (previous === 'local' && IS_WINDOWS && state.install) {
      const { response } = await dialog.showMessageBox(state.win, {
        type: 'question',
        title: 'Frivo',
        message: 'Keep Frivo running on this PC?',
        detail: "This PC's Frivo goes back to its own launcher, in the tray. Stop it if you only use Frivo on the other PC; it then also stops starting with Windows here.",
        buttons: ['Stop it', 'Keep it running'],
        defaultId: 0,
        cancelId: 1,
        noLink: true,
      });
      if (response === 0) {
        local.setAppMode(false);
        const result = await local.stopFrivo(state.install);
        await local.setStartAtLogin(false, state.install);
        if (result === 'running') await explainCantStop();
      }
    }
    if (IS_WINDOWS) local.setAppMode(false);
    settings.update({ mode: 'remote', remoteUrl: parsed.url, remoteName: String(name || '').slice(0, 64) });
    await syncShortcuts();
    applyRemoteLoginItem(settings.get('remoteStartAtLogin'));
    connectRemote();
    return { ok: true };
  }

  // ---------------------------------------------------------------- start / stop / quit

  // Frivo started by its setup, as administrator, can't be stopped from an
  // ordinary app. Its launcher keeps its own window and tray icon then (it
  // won't go into app mode as administrator), so that's where to stop it.
  async function explainCantStop() {
    await dialog.showMessageBox(state.win, {
      type: 'warning',
      title: 'Frivo',
      message: "Frivo couldn't be stopped from here",
      detail: "It was started as administrator, most likely by its setup. Stop it from its own launcher (the Frivo icon in the tray), then start it again from this app.",
      noLink: true,
    });
  }

  async function stopFrivo() {
    if (settings.get('mode') !== 'local') return;
    state.userStopped = true;
    stopProbing();
    const seq = ++state.connectSeq;
    busyView('Stopping Frivo…', '');
    const result = state.install ? await local.stopFrivo(state.install) : 'stopped';
    if (seq !== state.connectSeq) return;
    if (result === 'running') {
      state.userStopped = false;
      await explainCantStop();
      connectLocal();
      return;
    }
    stoppedView();
    pushState();
  }

  async function startFrivo() {
    state.userStopped = false;
    await connectLocal();
  }

  let quittingPromise = null;
  function quitApp({ keepFrivo = false } = {}) {
    if (quittingPromise) return quittingPromise;
    quittingPromise = (async () => {
      state.quitting = true;
      stopProbing();
      if (!keepFrivo && settings.get('mode') === 'local' && state.install) {
        try { await local.stopFrivo(state.install); } catch { /* quitting anyway */ }
      }
      if (state.tray) state.tray.destroy();
      app.exit(0);
    })();
    return quittingPromise;
  }

  // ---------------------------------------------------------------- start with Windows

  function applyRemoteLoginItem(on) {
    if (!IS_WINDOWS) return;
    app.setLoginItemSettings({ openAtLogin: Boolean(on), path: process.execPath, args: ['--hidden'], name: 'Frivo App' });
  }

  async function getStartAtLogin() {
    if (!IS_WINDOWS) return false;
    if (settings.get('mode') === 'local') return local.getStartAtLogin();
    return Boolean(settings.get('remoteStartAtLogin'));
  }

  async function setStartAtLogin(on) {
    if (!IS_WINDOWS) return false;
    if (settings.get('mode') === 'local') {
      if (!state.install) return false;
      return local.setStartAtLogin(Boolean(on), state.install);
    }
    settings.set('remoteStartAtLogin', Boolean(on));
    applyRemoteLoginItem(on);
    return true;
  }

  // ---------------------------------------------------------------- shortcuts

  /*
    Frivo's setup makes "Frivo" shortcuts for everyone on the PC, and in app
    mode they open this app. This app's installer makes its own "Frivo"
    shortcuts too, for people who connect to another PC. Both on one desktop
    would be two identical icons, so this app's own step aside while
    Frivo's do the job, and come back if that stops being true.
  */
  async function syncShortcuts() {
    if (!IS_WINDOWS || !app.isPackaged) return;
    const mine = [
      path.join(app.getPath('desktop'), 'Frivo.lnk'),
      path.join(app.getPath('appData'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Frivo.lnk'),
    ];
    const isMine = (p) => {
      try { return shell.readShortcutLink(p).target.toLowerCase() === process.execPath.toLowerCase(); } catch { return false; }
    };
    const removed = new Set(settings.get('removedShortcuts'));
    const frivosDoIt = settings.get('mode') === 'local' && local.isAppMode() && local.frivoShortcutsExist();
    for (const p of mine) {
      if (frivosDoIt) {
        if (fs.existsSync(p) && isMine(p)) {
          try { fs.unlinkSync(p); removed.add(p); } catch { /* in use: leave it */ }
        }
      } else if (removed.has(p)) {
        if (!fs.existsSync(p)) {
          shell.writeShortcutLink(p, 'create', {
            target: process.execPath, icon: process.execPath, iconIndex: 0, appUserModelId: APP_ID, description: 'Frivo',
          });
        }
        removed.delete(p);
      }
    }
    settings.set('removedShortcuts', [...removed]);
  }

  // ---------------------------------------------------------------- installing Frivo here

  async function installFrivo() {
    if (state.busy || !IS_WINDOWS) return;
    state.busy = true;
    const seq = ++state.connectSeq;
    try {
      showView({ name: 'install', stage: 'download', percent: 0 });
      const releases = await gh.listReleases(net.fetch, REPOSITORY, `FrivoApp/${app.getVersion()}`);
      const setup = gh.latestFrivo(releases, REPOSITORY);
      if (!setup) throw new Error("No Frivo release with a checkable setup file was found on GitHub.");
      const file = path.join(app.getPath('temp'), 'FrivoApp', gh.FRIVO_ASSET);
      let last = 0;
      await gh.downloadVerified(net.fetch, setup, file, REPOSITORY, (received, total) => {
        const percent = total ? Math.floor((received / total) * 100) : 0;
        if (percent !== last) { last = percent; showView({ name: 'install', stage: 'download', percent, version: setup.version }); }
      });
      if (seq !== state.connectSeq) return;
      showView({ name: 'install', stage: 'setup', version: setup.version });
      const code = await local.runSetup(file);
      try { fs.unlinkSync(file); } catch { /* temp folder: Windows tidies it */ }
      if (code === 1223) throw new Error('Setup needs administrator approval to install Frivo. Try again and choose Yes.');
      if (code !== 0) throw new Error(`Setup didn't finish (code ${code}).`);
      state.busy = false;
      await chooseLocal();
    } catch (err) {
      errorView("Frivo couldn't be installed", err.message || String(err), [
        { id: 'install', label: 'Try again', primary: true },
        { id: 'change', label: 'Back' },
      ]);
    } finally {
      state.busy = false;
    }
  }

  // ---------------------------------------------------------------- the app's own updates

  /*
    CHANGED (2.0.0): the app updates from the Frivo it's connected to, not
    from GitHub. FrivoSetup.exe carries the app and leaves a copy with
    Frivo (app-installer\), which Frivo hands out at /api/app/latest and
    /api/app/installer. So updating Frivo on any PC brings its apps along.
  */
  async function checkForAppUpdate({ manual = false } = {}) {
    if (!app.isPackaged && !process.env.FRIVO_APP_UPDATE_TEST) {
      if (manual) { state.update = { ...state.update, state: 'error', error: 'Updates work in the installed app.' }; pushState(); rebuildTray(); }
      return;
    }
    if (['checking', 'downloading', 'ready'].includes(state.update.state)) return;
    const origin = state.connected ? state.origin : null;
    if (!origin) {
      if (manual) { state.update = { ...state.update, state: 'error', error: 'Connect to Frivo to check: the app updates from it.' }; pushState(); rebuildTray(); }
      return;
    }
    state.update = { ...state.update, state: 'checking', error: '' };
    pushState();
    try {
      const response = await net.fetch(`${origin}/api/app/latest`, { cache: 'no-store', bypassCustomProtocolHandlers: true });
      const info = response.ok ? await response.json() : null;
      const offered = info && gh.parseVersion(info.version);
      const mine = gh.parseVersion(app.getVersion());
      const cmp = offered && mine ? gh.compareVersions(offered, mine) : -1;
      // NEW (2.0.0): or the same version, built again (Build.bat): the app
      // takes the build its Frivo carries, so updating Frivo is enough.
      const rebuilt = cmp === 0 && info.build && BUILD_ID && info.build !== BUILD_ID;
      if (!offered || !mine || !info.sha256 || !(cmp > 0 || rebuilt)) {
        state.update = { state: manual ? 'current' : 'idle', version: '', error: '', file: '', percent: 0 };
        pushState();
        rebuildTray();
        return;
      }
      const version = offered.join('.');
      state.update = { state: 'downloading', version, error: '', file: '', percent: 0 };
      pushState();
      const file = path.join(app.getPath('userData'), 'updates', `FrivoApp-Setup-${version}${info.build ? `-${info.build}` : ''}.exe`);
      await gh.downloadChecked(net.fetch, `${origin}/api/app/installer`, info.sha256, info.size, file, (received, total) => {
        state.update.percent = total ? Math.floor((received / total) * 100) : 0;
      });
      state.update = { state: 'ready', version, error: '', file, percent: 100 };
      // CHANGED (2.0.0): it installs by itself: now if the app is in the
      // tray, otherwise when it's next put away or started.
      settings.update({ pendingUpdate: { file, version, build: info.build || '' } });
      notify('Frivo app update', `The app updates to Frivo's ${version} by itself, the next time it's in the tray or starts. Or restart it from the tray menu now.`);
      setTimeout(autoInstallWhenAway, 1000);
    } catch (err) {
      state.update = { state: 'error', version: '', error: err.message || String(err), file: '', percent: 0 };
    }
    pushState();
    rebuildTray();
  }

  function installAppUpdate({ quiet = false } = {}) {
    if (state.update.state !== 'ready' || !fs.existsSync(state.update.file)) return;
    // Silent install of the new version, which starts the app again. Frivo
    // itself keeps running: this updates the app, not Frivo.
    settings.update({ pendingUpdate: null, startHiddenOnce: Boolean(quiet) });
    const child = spawn(state.update.file, ['/S', '--updated', '--force-run'], { detached: true, stdio: 'ignore' });
    child.on('error', () => {});
    child.unref();
    quitApp({ keepFrivo: true });
  }

  // NEW (2.0.0): an update installs by itself while the window is put away
  // (in the tray or minimized), so nothing is interrupted. Otherwise it
  // waits, checking again every minute.
  function autoInstallWhenAway() {
    clearTimeout(state.autoInstallTimer);
    if (state.update.state !== 'ready' || !app.isPackaged) return;   // never from the tests
    const win = state.win;
    const away = !win || win.isDestroyed() || !win.isVisible() || win.isMinimized();
    if (away) { installAppUpdate({ quiet: true }); return; }
    state.autoInstallTimer = setTimeout(autoInstallWhenAway, 60000);
  }

  // NEW (2.0.0): one downloaded before the app was closed installs as it starts.
  function installPendingUpdate() {
    const pending = settings.get('pendingUpdate');
    if (!pending || !pending.file) return false;
    settings.update({ pendingUpdate: null });
    const mine = gh.parseVersion(app.getVersion());
    const theirs = gh.parseVersion(pending.version);
    const newer = mine && theirs && (gh.compareVersions(theirs, mine) > 0
      || (gh.compareVersions(theirs, mine) === 0 && pending.build && BUILD_ID && pending.build !== BUILD_ID));
    if (!newer || !fs.existsSync(pending.file)) return false;
    try {
      const child = spawn(pending.file, ['/S', '--updated', '--force-run'], { detached: true, stdio: 'ignore' });
      child.on('error', () => {});
      child.unref();
      return true;
    } catch {
      return false;
    }
  }

  // ---------------------------------------------------------------- hotkeys

  /*
    NEW: keys that work anywhere, even with VRChat in front: start or stop
    dictation, and send what's in the box. They press Frivo's own buttons in
    its page (static/app.js listens through window.frivoApp.onHotkey).
  */
  const HOTKEY_ACTIONS = ['dictate', 'send'];

  function registerHotkeys() {
    globalShortcut.unregisterAll();
    state.hotkeyErrors = {};
    const keys = settings.get('hotkeys');
    for (const action of HOTKEY_ACTIONS) {
      const accel = keys[action];
      if (!accel) continue;
      let ok = false;
      try { ok = globalShortcut.register(accel, () => fireHotkey(action)); } catch { ok = false; }
      if (!ok) state.hotkeyErrors[action] = `${accel} is taken by another program, or isn't a key the app can use.`;
    }
  }

  function fireHotkey(action) {
    if (!state.connected || !state.origin) return;
    const wc = state.win.webContents;
    if (state.pendingLoad) {
      // Started in the tray and never opened: load Frivo's page now, unseen.
      // The key waits until the page says it's listening (app:hotkey-ready).
      state.pendingLoad = false;
      state.queuedHotkey = action;
      loadFrivoPage(state.origin);
      return;
    }
    if (state.showing === 'frivo') wc.send('app:hotkey', action);
  }

  // CHANGED: Ctrl, Alt or Win with a key, or an F key. Not Shift alone (it
  // would stop capitals being typed anywhere), and not the combinations
  // everything else relies on.
  const RESERVED_HOTKEYS = new Set(['C', 'V', 'X', 'A', 'Z', 'Y'].map((k) => `CommandOrControl+${k}`)
    .concat(['Alt+F4', 'Alt+Tab', 'CommandOrControl+Alt+Delete']));
  function validAccelerator(accel) {
    if (accel === '') return true;
    if (typeof accel !== 'string' || accel.length > 60) return false;
    const m = /^((?:(?:CommandOrControl|Alt|Shift|Super)\+)*)([A-Z0-9]|F(?:[1-9]|1\d|2[0-4])|Space|Enter|Tab|Backspace|Insert|Home|End|PageUp|PageDown|Up|Down|Left|Right|[`\-=\[\];',./\\])$/.exec(accel);
    if (!m) return false;
    const mods = m[1] ? m[1].slice(0, -1).split('+') : [];
    if (new Set(mods).size !== mods.length) return false;
    if (RESERVED_HOTKEYS.has(accel)) return false;
    const fKey = /^F\d+$/.test(m[2]);
    return fKey || mods.some((mod) => mod !== 'Shift');
  }

  // ---------------------------------------------------------------- tray

  function rebuildTray() {
    if (!state.tray) return;
    const mode = settings.get('mode');
    const items = [{ label: 'Open Frivo', click: showWindow }];

    if (mode === 'local') {
      const running = state.connected;
      items.push({ type: 'separator' });
      items.push({ label: running ? 'Frivo is running on this PC' : 'Frivo is stopped', enabled: false });
      if (running) items.push({ label: 'Stop Frivo', click: stopFrivo });
      else items.push({ label: 'Start Frivo', click: () => { showWindow(); startFrivo(); } });
      if (state.lanUrl) {
        items.push({ label: `Copy network address (${state.lanUrl})`, click: () => clipboard.writeText(state.lanUrl) });
      }
    } else if (mode === 'remote') {
      items.push({ type: 'separator' });
      items.push({ label: `Connected to ${hostOf(settings.get('remoteUrl'))}`, enabled: false });
    }

    items.push({ type: 'separator' });
    items.push({
      label: 'When I close the window',
      submenu: [
        { label: 'Keep Frivo running in the tray', type: 'radio', checked: settings.get('closeAction') === 'tray', click: () => setCloseAction('tray') },
        { label: mode === 'local' ? 'Stop Frivo and quit' : 'Quit', type: 'radio', checked: settings.get('closeAction') === 'quit', click: () => setCloseAction('quit') },
      ],
    });
    if (IS_WINDOWS && mode) {
      items.push({
        label: 'Start with Windows',
        type: 'checkbox',
        checked: Boolean(state.startAtLoginCache),
        click: async (item) => { await setStartAtLogin(item.checked); await refreshStartAtLogin(); },
      });
    }
    items.push({ label: 'Change where Frivo runs…', click: () => { showWindow(); welcomeView(); } });
    if (state.update.state === 'ready') {
      items.push({ type: 'separator' });
      items.push({ label: `Restart to update the app (${state.update.version})`, click: installAppUpdate });
    }
    items.push({ type: 'separator' });
    items.push({ label: mode === 'local' ? 'Stop Frivo and quit' : 'Quit Frivo', click: () => quitApp() });

    state.tray.setContextMenu(Menu.buildFromTemplate(items));
    state.tray.setToolTip(mode === 'local' ? (state.connected ? 'Frivo: running' : 'Frivo: stopped') : 'Frivo');
  }

  async function refreshStartAtLogin() {
    state.startAtLoginCache = await getStartAtLogin().catch(() => false);
    rebuildTray();
    pushState();
  }

  function setCloseAction(action) {
    if (!['tray', 'quit'].includes(action)) return;
    settings.set('closeAction', action);
    rebuildTray();
    pushState();
  }

  // ---------------------------------------------------------------- Frivo's page <-> app

  async function appState() {
    const mode = settings.get('mode');
    return {
      version: app.getVersion(),
      platform: process.platform,
      mode,
      host: mode === 'remote' ? hostOf(settings.get('remoteUrl')) : 'this PC',
      local: mode === 'local' ? {
        running: state.connected,
        version: state.install ? state.install.version : '',
        lanUrl: state.lanUrl,
        outdated: frivoOutdated(),
        minimum: pkg.frivo.minimumFrivo,
      } : null,
      closeAction: settings.get('closeAction'),
      startAtLogin: Boolean(state.startAtLoginCache),
      startAtLoginAvailable: IS_WINDOWS,
      update: { state: state.update.state, version: state.update.version, error: state.update.error, percent: state.update.percent },
      hotkeys: { ...settings.get('hotkeys') },
      hotkeyErrors: { ...state.hotkeyErrors },
      vrchat: oscBridge.status(),   // NEW (2.0.0)
    };
  }

  async function pushState() {
    if (state.showing !== 'frivo' || !state.win || state.win.isDestroyed()) return;
    try { state.win.webContents.send('app:state', await appState()); } catch { /* page gone */ }
  }

  function handle(channel, guard, fn) {
    ipcMain.handle(channel, async (event, ...args) => {
      if (!guard(event)) throw new Error('Not allowed from this page.');
      return fn(...args);
    });
  }

  handle('app:get-state', fromFrivo, () => appState());
  handle('app:set-close-action', fromFrivo, (a) => { setCloseAction(String(a)); return appState(); });
  handle('app:set-start-at-login', fromFrivo, async (on) => { await setStartAtLogin(Boolean(on)); await refreshStartAtLogin(); return appState(); });
  handle('app:stop-frivo', fromFrivo, () => { stopFrivo(); return true; });
  handle('app:copy', fromFrivo, (text) => { clipboard.writeText(String(text || '').slice(0, 2000)); return true; });
  handle('app:change-connection', fromFrivo, () => { welcomeView(); return true; });
  handle('app:check-update', fromFrivo, async () => { await checkForAppUpdate({ manual: true }); return appState(); });
  handle('app:install-update', fromFrivo, () => { installAppUpdate(); return true; });
  // NEW (2.0.0): FrivOSC built in, on or off.
  handle('app:set-vrchat', fromFrivo, (on) => {
    settings.set('vrchatBridge', Boolean(on));
    oscBridge.setEnabled(Boolean(on));
    return appState();
  });
  handle('app:hotkey-ready', fromFrivo, () => {
    const action = state.queuedHotkey || '';
    state.queuedHotkey = '';
    return action;
  });
  // While Settings is waiting for keys: Windows would otherwise act on a
  // shortcut that's already set before the page saw the keys.
  handle('app:pause-hotkeys', fromFrivo, (paused) => {
    if (paused) globalShortcut.unregisterAll();
    else registerHotkeys();
    return true;
  });
  handle('app:set-hotkey', fromFrivo, (action, accel) => {
    if (!HOTKEY_ACTIONS.includes(action) || !validAccelerator(accel)) {
      throw new Error("That isn't a key combination the app can use.");
    }
    const keys = { ...settings.get('hotkeys') };
    const clash = HOTKEY_ACTIONS.find((other) => other !== action && accel && keys[other] === accel);
    if (clash) keys[clash] = '';
    keys[action] = accel;
    settings.set('hotkeys', keys);
    registerHotkeys();
    return appState();
  });

  handle('shell:ready', fromShell, () => state.view);
  handle('shell:choose-local', fromShell, () => { chooseLocal(); return true; });
  handle('shell:choose-remote', fromShell, (text, name) => chooseRemote(text, name));
  // NEW: the pairing code typed from the other PC's screen.
  handle('shell:pair', fromShell, async (typed) => {
    const p = state.pendingTrust;
    if (!p || !state.view || state.view.name !== 'pair') return { ok: false, error: 'Start again from "Change where Frivo runs".' };
    const code = pairing.normalizeCode(typed);
    if (!code) return { ok: false, error: 'A pairing code is twelve letters and numbers, like K7Q4-MD2X-9P3R.' };
    if (code !== p.code) {
      return { ok: false, error: "That isn't this Frivo's pairing code. Check it on that PC: Frivo's launcher, or Settings › Other devices." };
    }
    // A matching code only counts for a real authority (see trust.js).
    if (!trust.isSelfSignedAuthority(p.pin.pem)) {
      return { ok: false, error: "This server's certificate can't be paired with a code. Use \"Compare the certificate instead\"." };
    }
    state.pendingTrust = null;
    settings.set('trusted', { ...settings.get('trusted'), [p.key]: p.pin });
    connectRemote();
    return { ok: true };
  });
  handle('shell:trust', fromShell, async (accept, fingerprint) => {
    const view = state.view;
    const pending = state.pendingTrust;
    if (!view || view.name !== 'trust' || !pending) return false;
    if (!accept) { state.pendingTrust = null; welcomeView(); return true; }
    state.pendingTrust = null;
    if (fingerprint !== pending.pin.fingerprint) return false;
    settings.set('trusted', { ...settings.get('trusted'), [pending.key]: pending.pin });
    connectRemote();
    return true;
  });
  handle('shell:action', fromShell, async (id) => {
    switch (id) {
      case 'retry': connect(); break;
      case 'start': startFrivo(); break;
      case 'change': state.pendingTrust = null; welcomeView(); break;
      case 'back': connect(); break;
      case 'install': installFrivo(); break;
      case 'compare': fingerprintView(); break;     // NEW: no pairing code to hand
      case 'pair': pairView(); break;
      case 'rescan': if (state.view && state.view.name === 'welcome') { startDiscovery(); state.view = { ...state.view, discovery: state.discovery }; sendView(); } break;
      case 'log': if (fs.existsSync(local.serverLog)) shell.openPath(local.serverLog); break;
      default: return false;
    }
    return true;
  });

  // ---------------------------------------------------------------- session

  function setUpSession() {
    const ses = session.defaultSession;
    ses.setUserAgent(`${ses.getUserAgent()} FrivoApp/${app.getVersion()}`);
    ses.setCertificateVerifyProc(trust.makeVerifier(() => ({ ...settings.get('trusted'), ...state.localPins })));

    // Frivo asks for the microphone (dictation, listening) and the clipboard;
    // anything else, and anything from another site, is turned down.
    const allowed = new Set(['media', 'clipboard-read', 'clipboard-sanitized-write', 'notifications', 'fullscreen', 'speaker-selection']);
    const fromFrivoPage = (url) => Boolean(state.origin) && originOf(url) === state.origin;
    ses.setPermissionRequestHandler((wc, permission, callback, details) => {
      callback(allowed.has(permission) && fromFrivoPage(details.requestingUrl || wc.getURL()));
    });
    ses.setPermissionCheckHandler((wc, permission, requestingOrigin) => {
      return allowed.has(permission) && fromFrivoPage(requestingOrigin || (wc && wc.getURL()));
    });
  }

  // ---------------------------------------------------------------- go

  app.on('second-instance', (event, argv) => {
    if (argv.includes('--hidden')) return;
    showWindow();
    // Opened from a Frivo shortcut while showing "Frivo is stopped": that
    // shortcut has just started Frivo, so go and find it.
    if (settings.get('mode') === 'local' && !state.connected && state.view && state.view.title === 'Frivo is stopped') {
      connect();
    }
  });

  app.on('window-all-closed', () => { /* the tray keeps the app running */ });
  app.on('will-quit', () => { try { globalShortcut.unregisterAll(); } catch { /* quitting */ } });

  // Windows shutting down or signing out, or anything else that quits the
  // app as a whole: let the window close instead of hiding it in the tray.
  // (Frivo itself stops with Windows anyway.)
  app.on('before-quit', () => {
    state.quitting = true;
    stopProbing();
    oscBridge.close();   // NEW (2.0.0): typing dots off, port released
  });

  app.whenReady().then(async () => {
    // NEW (2.0.0): an update waiting from last time goes in first.
    if (app.isPackaged && installPendingUpdate()) { app.exit(0); return; }
    setUpSession();
    state.win = createWindow();

    state.tray = new Tray(nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 }));
    state.tray.on('click', showWindow);
    state.tray.on('double-click', showWindow);
    rebuildTray();

    // Something to see straight away, while the app works out where Frivo is.
    if (settings.get('mode')) busyView('Opening Frivo…', '');
    if (!hiddenStart) showWindow();
    registerHotkeys();   // NEW
    await refreshStartAtLogin();
    await connect();

    setInterval(() => checkForAppUpdate(), UPDATE_EVERY_MS);
  });

  // Exposed for the tests, which drive the app from outside.
  global.__frivoApp = { state, settings, connect, chooseRemote, chooseLocal, quitApp, appState };
}
