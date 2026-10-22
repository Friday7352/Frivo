// End-to-end test of the Frivo app against a real Frivo server (from
// ../../app, started by serve-frivo.py): first run, trusting a certificate,
// Frivo's page and the app bridge, Settings › App, losing and getting back
// the connection, the trusted certificate remembered and a changed one
// caught, an address with nothing there, and "this PC" (with a stand-in
// address, since the Windows parts need Windows).
//
//   npm run test:e2e        (from desktop\; needs Python with Frivo's packages)
//
// On Linux run it under a display: xvfb-run -a npm run test:e2e
// Screenshots land in test/screenshots/ for looking at.
const { _electron: electron } = require('playwright-core');
const { spawn } = require('child_process');
const fs = require('fs'); const os = require('os'); const path = require('path');
const APP = path.join(__dirname, '..');
const ELECTRON = require(path.join(APP, 'node_modules', 'electron'));
const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const CERTS = fs.mkdtempSync(path.join(os.tmpdir(), 'frivo-app-certs-'));
const SHOTS = path.join(__dirname, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });
const failures = [];
const check = (name, ok, got) => { console.log((ok ? '  PASS  ' : '  FAIL  ') + name + (ok ? '' : '   got=' + JSON.stringify(got))); if (!ok) failures.push(name); };
const children = [];   // test servers, killed however the test ends
process.on('exit', () => { for (const c of children) { try { c.kill('SIGKILL'); } catch {} } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function serve(port, https) {
  const mode = https === true ? 'https' : (https || 'http');
  const p = spawn(PYTHON, [path.join(__dirname, 'serve-frivo.py'), String(port), mode],
    { stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, FRIVO_TEST_CERTS: CERTS } });
  children.push(p);
  return p;
}
async function waitUp(url) { for (let i = 0; i < 60; i++) { try { const r = await fetch(url); if (r.ok) return true; } catch {} await sleep(500); } return false; }
async function waitUpTls() { const https = require('https'); for (let i = 0; i < 60; i++) { const ok = await new Promise((r) => { https.get('https://127.0.0.1:5095/static/icon.png', { rejectUnauthorized: false }, (res) => { res.resume(); r(res.statusCode === 200); }).on('error', () => r(false)); }); if (ok) return true; await sleep(500); } return false; }
async function launch(userData, env = {}) {
  const app = await electron.launch({ executablePath: ELECTRON, args: [APP].concat(process.platform === 'linux' ? ['--no-sandbox'] : []), env: { ...process.env, FRIVO_APP_USER_DATA: userData, ...env } });
  const win = await app.firstWindow();
  return { app, win };
}
const shot = (win, name) => win.screenshot({ path: path.join(SHOTS, name) });

(async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'frivo-app-ud-'));
  let server = serve(5095, true);
  check('test Frivo is up', await waitUp('http://127.0.0.1:5095/static/icon.png') || await waitUpTls());

  // ---- first run
  let { app, win } = await launch(userData, { FRIVO_APP_DISCOVER_HOSTS: '127.0.0.1:5095,127.0.0.1:5097' });
  await win.waitForSelector('text=Where does Frivo run?', { timeout: 15000 });
  await win.setViewportSize({ width: 900, height: 760 }).catch(() => {});
  check('first run asks where Frivo runs', true);
  check('no "this PC" choice away from Windows', !(await win.isVisible('text=Use this PC')));

  // NEW: Frivo on the network is listed to pick from
  await win.waitForSelector('.found-item', { timeout: 15000 }).catch(() => {});
  const foundText = await win.textContent('.found').catch(() => '');
  check('Frivo on the network is listed', /127\.0\.0\.1/.test(foundText), foundText);
  check('only Frivo is listed (nothing at the other address)', (await win.$$('.found-item')).length === 1);
  // typing survives the list filling in
  await win.fill('#address', 'typed-before');
  await win.click('text=Look again').catch(() => {});
  await sleep(1500);
  check('typing survives the list redrawing', (await win.inputValue('#address')) === 'typed-before', await win.inputValue('#address'));
  await shot(win, 'app_welcome.png');

  // a bad address is explained
  await win.fill('#address', 'not an address with spaces');
  await win.click('button:has-text("Connect")');
  await win.waitForFunction(() => document.querySelector('.field-error').textContent.length > 0, null, { timeout: 5000 }).catch(() => {});
  check('a bad address is explained', /spaces/.test(await win.textContent('.field-error')), await win.textContent('.field-error'));

  // ---- another PC, picked from the list: asks for the pairing code
  await win.click('.found-item');
  await win.waitForSelector('text=Pair with', { timeout: 20000 }).catch(async (e) => { await shot(win, 'app_debug.png'); console.log('VIEW:', await win.textContent('body')); throw e; });
  check('connecting asks for the pairing code', true);
  await shot(win, 'app_pair.png');
  await win.fill('#pair-code', 'AAAA-AAAA-AAAA');
  await win.click('button:has-text("Pair")');
  await win.waitForFunction(() => /isn't this Frivo/.test(document.querySelector('.field-error').textContent), null, { timeout: 5000 }).catch(() => {});
  check('a wrong code is refused', /isn't this Frivo/.test(await win.textContent('.field-error')), await win.textContent('.field-error'));

  // no code to hand: the certificate can be compared instead
  await win.click('text=Compare the certificate instead');
  await win.waitForSelector('text=Trust Frivo at', { timeout: 10000 });
  const facts = await win.textContent('.facts');
  check('comparing shows the authority', /Frivo Local CA/.test(facts), facts);
  check('and a fingerprint', /[0-9A-F]{4} [0-9A-F]{4}/.test(facts), facts);
  await shot(win, 'app_trust.png');
  await win.click('text=Use the pairing code instead');
  await win.waitForSelector('#pair-code', { timeout: 10000 });

  // the right code, typed loosely (lower case, no dash, O for 0)
  const { pairingCodeFor } = require('../src/pairing');
  const caPem = fs.readFileSync(path.join(CERTS, 'ca.pem'), 'utf8');
  const caDer = Buffer.from(caPem.replace(/-----[^-]+-----/g, '').replace(/\s+/g, ''), 'base64');
  const code = pairingCodeFor(caDer);
  const loose = code.replace(/-/g, '').toLowerCase().replace(/0/g, 'o');
  await win.fill('#pair-code', loose);
  await win.press('#pair-code', 'Enter');
  await win.waitForURL('https://127.0.0.1:5095/', { timeout: 20000 });
  await win.waitForSelector('#messageRich', { timeout: 20000 });
  check('the right pairing code connects', true);
  check("Frivo's page loads after pairing", true);
  const ua = await win.evaluate(() => navigator.userAgent);
  check('the page can tell it is in the app', /FrivoApp\//.test(ua), ua);
  const st = await win.evaluate(() => window.frivoApp && window.frivoApp.getState());
  check('Frivo\'s page gets the app bridge', st && st.mode === 'remote' && st.host === '127.0.0.1:5095', st);
  check('no Node in the page', await win.evaluate(() => typeof require === 'undefined' && typeof process === 'undefined'));
  const set = await win.evaluate(() => window.frivoApp.setCloseAction('quit'));
  check('the page can change the close action', set.closeAction === 'quit', set);
  await win.evaluate(() => window.frivoApp.setCloseAction('tray'));
  await shot(win, 'app_frivo.png');

  // Settings › App: only in the app
  await win.click('#settingsToggle');
  check('Settings has an App section in the app', await win.isVisible('#appNavBtn'));
  await win.click('#appNavBtn');
  await win.waitForSelector('#appSection', { state: 'visible', timeout: 5000 });
  await win.waitForFunction(() => document.getElementById('appVersionValue').textContent !== '—', null, { timeout: 5000 });
  check('which shows where Frivo runs', /127\.0\.0\.1:5095/.test(await win.textContent('#appWhereValue')), await win.textContent('#appWhereValue'));
  check('and no "this PC" rows for another PC', !(await win.isVisible('#appRunRow')) && !(await win.isVisible('#appLanRow')));
  check('the app offer is gone in the app', (await win.$('#appOffer')) === null);
  await shot(win, 'app_settings.png');

  // NEW: shortcuts
  check('dictation has a shortcut to start with', /Ctrl \+ Alt \+ D/.test(await win.textContent('#appHotkeyDictate')), await win.textContent('#appHotkeyDictate'));
  await win.click('#appHotkeys [data-hotkey="send"]');
  check('Change waits for keys', /Press keys/.test(await win.textContent('#appHotkeySend')));
  await win.keyboard.press('Control+Shift+F9');
  await win.waitForFunction(() => /F9/.test(document.getElementById('appHotkeySend').textContent), null, { timeout: 5000 }).catch(() => {});
  check('a new shortcut is set', /Ctrl \+ Shift \+ F9/.test(await win.textContent('#appHotkeySend')), await win.textContent('#appHotkeySend'));
  const hk = await win.evaluate(() => window.frivoApp.getState());
  check('and saved by the app', hk.hotkeys && hk.hotkeys.send === 'CommandOrControl+Shift+F9', hk.hotkeys);
  // Shift and a letter, or Ctrl+C, would take that key from everything else
  await win.click('#appHotkeys [data-hotkey="send"]');
  await win.keyboard.press('Shift+H');
  await win.keyboard.press('Control+C');
  check('Shift+letter and Ctrl+C are refused', /Ctrl, Alt or Win/.test(await win.textContent('#appHotkeySendSub')) && /Press keys/.test(await win.textContent('#appHotkeySend')), await win.textContent('#appHotkeySendSub'));
  await win.keyboard.press('Escape');
  await win.click('#appHotkeys [data-hotkey="send"]');
  await win.keyboard.press('Control+Alt+D');
  await win.waitForFunction(() => /Alt \+ D/.test(document.getElementById('appHotkeySend').textContent), null, { timeout: 5000 }).catch(() => {});
  const hk2 = await win.evaluate(() => window.frivoApp.getState());
  check('one combination is only ever one shortcut', hk2.hotkeys.send === 'CommandOrControl+Alt+D' && hk2.hotkeys.dictate === '', hk2.hotkeys);
  await win.click('#appHotkeys [data-hotkey="dictate"]');
  await win.keyboard.press('Control+Alt+D');
  await win.click('#appHotkeys [data-hotkey="send"]');
  await win.keyboard.press('Control+Shift+F9');
  await sleep(500);
  // waiting for keys stops when Settings closes, and typing works again
  await win.click('#appHotkeys [data-hotkey="dictate"]');
  await win.keyboard.press('Escape');   // cancels waiting
  await win.click('#appHotkeys [data-hotkey="dictate"]');
  await win.evaluate(() => document.getElementById('settingsToggle').click());
  await sleep(400);
  const stillOpen = await win.evaluate(() => Boolean(document.getElementById('appSection').offsetParent));
  if (stillOpen) await win.keyboard.press('Escape');
  await sleep(400);
  await win.focus('#messageRich').catch(() => {});
  await win.keyboard.press('Shift+H');
  const typedOk = /H/.test(await win.evaluate(() => document.getElementById('messageRich').textContent || ''));
  const hk3 = await win.evaluate(() => window.frivoApp.getState());
  check('closing Settings stops waiting for keys, and typing works', typedOk && hk3.hotkeys.dictate === 'CommandOrControl+Alt+D', { typedOk, hk: hk3.hotkeys });
  await win.evaluate(() => { const m = document.getElementById('messageRich'); m.textContent = ''; m.dispatchEvent(new Event('input', { bubbles: true })); });
  // a hotkey pressed anywhere presses Frivo's own button
  await win.evaluate(() => { window.__sent = 0; document.getElementById('sendBtn').addEventListener('click', () => { window.__sent += 1; }); });
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.send('app:hotkey', 'send'));
  await sleep(500);
  check('a hotkey presses Frivo\'s button', (await win.evaluate(() => window.__sent)) === 1);

  // ---- the connection goes, then comes back
  server.kill('SIGKILL');
  await win.waitForSelector('text=Reconnecting to 127.0.0.1:5095', { timeout: 20000 });
  check('losing Frivo says it is reconnecting', true);
  await shot(win, 'app_reconnect.png');
  server = serve(5095, true);
  await win.waitForSelector('#messageRich', { timeout: 40000 });
  check('and Frivo comes back by itself', true);

  // ---- the shell bridge isn't on Frivo's page, the app bridge isn't on the shell
  check("Frivo's page has no shell bridge", await win.evaluate(() => typeof window.frivoShell === 'undefined'));
  await app.close();

  // ---- trusted once is remembered
  ({ app, win } = await launch(userData));
  await win.waitForSelector('#messageRich', { timeout: 30000 });
  check('next start connects without asking again', /127\.0\.0\.1:5095/.test(win.url()), win.url());

  // ---- a different certificate at the same address is caught
  const s = JSON.parse(fs.readFileSync(path.join(userData, 'app-settings.json'), 'utf8'));
  const pin = s.trusted && s.trusted['127.0.0.1'];
  check('the authority is pinned for the address', pin && /^[0-9a-f]{64}$/.test(pin.fingerprint) && /BEGIN CERTIFICATE/.test(pin.pem), pin);
  check('the name picked from the list is kept', typeof s.remoteName === 'string' && s.remoteName.length > 0, s.remoteName);
  check('shortcuts are kept', s.hotkeys && s.hotkeys.dictate === 'CommandOrControl+Alt+D' && s.hotkeys.send === 'CommandOrControl+Shift+F9', s.hotkeys);
  check('the app keeps its settings in its own folder', fs.existsSync(path.join(userData, 'app-settings.json')));
  await app.close();

  // ---- someone else at the address, sending Frivo's real authority along
  // with a certificate it never signed
  server.kill('SIGKILL');
  await sleep(1000);
  const forged = serve(5095, 'forged');
  await waitUpTls();
  ({ app, win } = await launch(userData));
  await win.waitForSelector("text=didn't prove who it is", { timeout: 30000 });
  check('a forged certificate with the real authority is refused', !/5095\/$/.test(win.url()), win.url());
  check('and Frivo\'s page never loads', (await win.$('#messageRich')) === null);
  await shot(win, 'app_forged.png');
  await app.close();
  forged.kill('SIGKILL');
  await sleep(1000);
  server = serve(5095, true);
  await waitUpTls();

  s.trusted['127.0.0.1'] = { fingerprint: 'f'.repeat(64), pem: fs.readFileSync(path.join(__dirname, 'fixtures', 'rogue-ca.pem'), 'utf8') };
  fs.writeFileSync(path.join(userData, 'app-settings.json'), JSON.stringify(s));
  ({ app, win } = await launch(userData));
  await win.waitForSelector('text=again', { timeout: 30000 });
  check('a changed certificate is not accepted silently', /isn't the one this app paired with/.test(await win.textContent('#view')));
  await win.click('text=Compare the certificate instead');
  await win.waitForSelector('text=has a different certificate', { timeout: 10000 });
  check('and comparing says the certificate changed', true);
  await shot(win, 'app_changed.png');
  await app.close();

  // ---- unreachable address
  const ud2 = fs.mkdtempSync(path.join(os.tmpdir(), 'frivo-app-ud-'));
  fs.writeFileSync(path.join(ud2, 'app-settings.json'), JSON.stringify({ mode: 'remote', remoteUrl: 'https://127.0.0.1:5099' }));
  ({ app, win } = await launch(ud2));
  await win.waitForSelector("text=Can't reach Frivo at 127.0.0.1:5099", { timeout: 30000 });
  check('an address with nothing there says so', true);
  await shot(win, 'app_unreachable.png');
  await win.click('text=Change where Frivo runs');
  await win.waitForSelector('text=Where does Frivo run?', { timeout: 10000 });
  check('and Change goes back to the choice', await win.isVisible('text=← Back'));
  await app.close();

  // ---- "this PC" (test mode: a plain http Frivo stands in)
  const local = serve(5096, false);
  await waitUp('http://127.0.0.1:5096/static/icon.png');
  const ud3 = fs.mkdtempSync(path.join(os.tmpdir(), 'frivo-app-ud-'));
  ({ app, win } = await launch(ud3, { FRIVO_APP_LOCAL_ORIGIN: 'http://127.0.0.1:5096' }));
  await win.waitForSelector('text=Use this PC', { timeout: 15000 });
  await win.click('text=Use this PC');
  await win.waitForSelector('#messageRich', { timeout: 30000 });
  const st3 = await win.evaluate(() => window.frivoApp.getState());
  check('"this PC" shows Frivo running here', st3.mode === 'local' && st3.host === 'this PC', st3);
  await app.close();
  local.kill('SIGKILL'); server.kill('SIGKILL');

  console.log(failures.length ? `\n${failures.length} failed` : '\nAll app checks passed.');
  process.exit(failures.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
