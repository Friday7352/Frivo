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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function serve(port, https) {
  const mode = https === true ? 'https' : (https || 'http');
  const p = spawn(PYTHON, [path.join(__dirname, 'serve-frivo.py'), String(port), mode],
    { stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, FRIVO_TEST_CERTS: CERTS } });
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
  let { app, win } = await launch(userData);
  await win.waitForSelector('text=Where does Frivo run?', { timeout: 15000 });
  await win.setViewportSize({ width: 900, height: 760 }).catch(() => {});
  check('first run asks where Frivo runs', true);
  check('no "this PC" choice away from Windows', !(await win.isVisible('text=Use this PC')));
  await shot(win, 'app_welcome.png');

  // a bad address is explained
  await win.fill('#address', 'not an address with spaces');
  await win.click('button:has-text("Connect")');
  await win.waitForFunction(() => document.querySelector('.field-error').textContent.length > 0, null, { timeout: 5000 }).catch(() => {});
  check('a bad address is explained', /spaces/.test(await win.textContent('.field-error')), await win.textContent('.field-error'));

  // ---- another PC, untrusted certificate
  await win.fill('#address', '127.0.0.1:5095');
  await win.click('button:has-text("Connect")');
  await win.waitForSelector('text=Trust Frivo at', { timeout: 20000 }).catch(async (e) => { await shot(win, 'app_debug.png'); console.log('VIEW:', await win.textContent('body')); throw e; });
  const facts = await win.textContent('.facts');
  check('asks to trust, showing the authority', /Frivo Local CA/.test(facts), facts);
  check('and a fingerprint', /[0-9A-F]{4} [0-9A-F]{4}/.test(facts), facts);
  await shot(win, 'app_trust.png');
  await win.click('text=Trust and connect');
  await win.waitForURL('https://127.0.0.1:5095/', { timeout: 20000 });
  await win.waitForSelector('#messageRich', { timeout: 20000 });
  check("Frivo's page loads after trusting", true);
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
  await win.keyboard.press('Escape');

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
  await win.waitForSelector('text=has a different certificate', { timeout: 30000 });
  check('a changed certificate is not accepted silently', true);
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
