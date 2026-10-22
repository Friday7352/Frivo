'use strict';
// The app's parts that don't need a window: addresses, GitHub releases,
// certificates, settings, and what it writes to Frivo's launcher.json.
// Run with: npm test (from desktop\).

const test = require('node:test');
const assert = require('node:assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { normalizeAddress, isLoopbackHost } = require('../src/address');
const gh = require('../src/github');
const trust = require('../src/trust');
const { Settings } = require('../src/settings');
const { FrivoLocal, parseRegValue } = require('../src/frivo-local');

const REPO = 'Friday7352/Frivo';
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'frivo-app-test-'));

test('package.json: what the app reads is there once packaged', () => {
  // electron-builder drops "build" from the packaged package.json, so the
  // app reads only "frivo" and "version" at run time.
  const pkg = require('../package.json');
  assert.strictEqual(pkg.frivo.appId, pkg.build.appId);
  for (const key of ['appId', 'repository', 'port', 'minimumFrivo']) assert.ok(pkg.frivo[key], key);
  const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'main.js'), 'utf8');
  assert.ok(!/pkg\.build\b/.test(source), 'main.js must not read pkg.build');
});

test('addresses: Frivo\'s https and port 5000 are filled in', () => {
  assert.deepStrictEqual(normalizeAddress('192.168.1.50'), { ok: true, url: 'https://192.168.1.50:5000', host: '192.168.1.50:5000' });
  assert.strictEqual(normalizeAddress('frivo-box').url, 'https://frivo-box:5000');
  assert.strictEqual(normalizeAddress('https://192.168.1.50:5000/').url, 'https://192.168.1.50:5000');
  assert.strictEqual(normalizeAddress('http://10.0.0.4:8080/chat?x=1').url, 'http://10.0.0.4:8080');
  assert.strictEqual(normalizeAddress('  192.168.1.50:6000 ').url, 'https://192.168.1.50:6000');
  // https on 443 typed in stays on 443 (URL drops the default port)
  assert.strictEqual(normalizeAddress('https://frivo.example:443').url, 'https://frivo.example');
});

test('addresses: what isn\'t one is explained', () => {
  for (const bad of ['', '   ', 'has spaces in it', 'ftp://x', 'https://user:pw@host', 'http://']) {
    const r = normalizeAddress(bad);
    assert.strictEqual(r.ok, false, bad);
    assert.ok(r.error.length > 10, bad);
  }
});

test('addresses: loopback', () => {
  assert.ok(isLoopbackHost('localhost'));
  assert.ok(isLoopbackHost('127.0.0.1'));
  assert.ok(isLoopbackHost('[::1]'));
  assert.ok(!isLoopbackHost('192.168.1.5'));
});

function asset(name, sha = 'a'.repeat(64), repo = REPO, tag = 'x') {
  return { name, size: 10, digest: sha ? `sha256:${sha}` : null, browser_download_url: `https://github.com/${repo}/releases/download/${tag}/${name}` };
}

const RELEASES = [
  { tag_name: 'app-v1.2.0', assets: [asset('FrivoApp-Setup-1.2.0.exe', 'b'.repeat(64))], html_url: 'https://github.com/x' },
  { tag_name: 'app-v1.3.0', prerelease: true, assets: [asset('FrivoApp-Setup-1.3.0.exe')] },
  { tag_name: 'app-v1.4.0', draft: true, assets: [asset('FrivoApp-Setup-1.4.0.exe')] },
  { tag_name: 'app-v1.1.0', assets: [asset('FrivoApp-Setup-1.1.0.exe')] },
  { tag_name: 'v1.7.0', assets: [asset('FrivoSetup.exe', 'c'.repeat(64))] },
  { tag_name: 'v1.8.0', assets: [asset('FrivoSetup.exe', null)] },               // no fingerprint
  { tag_name: 'v1.9.0', assets: [asset('FrivoSetup.exe', 'd'.repeat(64), 'someone/else')] },  // another repo's file
  { tag_name: 'v1.6.1', assets: [asset('FrivoSetup.exe')] },
];

test('releases: the app\'s newest checkable update, and only if newer', () => {
  const found = gh.newerApp(RELEASES, '1.0.0', REPO);
  assert.strictEqual(found.version, '1.2.0');
  assert.strictEqual(found.sha256, 'b'.repeat(64));
  assert.strictEqual(gh.newerApp(RELEASES, '1.2.0', REPO), null);
  assert.strictEqual(gh.newerApp(RELEASES, '2.0.0', REPO), null);
});

test('releases: Frivo\'s setup ignores app releases, unchecked files and other repos', () => {
  const found = gh.latestFrivo(RELEASES, REPO);
  assert.strictEqual(found.version, '1.7.0');
  assert.strictEqual(found.name, 'FrivoSetup.exe');
});

test('releases: versions', () => {
  assert.deepStrictEqual(gh.parseVersion('v1.7'), [1, 7, 0]);
  assert.strictEqual(gh.parseVersion('app-v1.0.0'), null);   // Frivo's own updater skips these too
  assert.strictEqual(gh.compareVersions([1, 6, 2], [1, 7, 0]), -1);
});

function fakeFetch(body, status = 200) {
  return async () => ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => String(body.length) },
    body: { getReader() { let sent = false; return { read: async () => (sent ? { done: true } : ((sent = true), { done: false, value: new Uint8Array(body) })) }; } },
  });
}

test('downloads: kept only when the fingerprint matches', async () => {
  const dir = tmp();
  const body = Buffer.from('frivo setup');
  const sha = crypto.createHash('sha256').update(body).digest('hex');
  const ok = { url: `https://github.com/${REPO}/releases/download/v1.7.0/FrivoSetup.exe`, sha256: sha, size: body.length };
  const dest = path.join(dir, 'FrivoSetup.exe');
  await gh.downloadVerified(fakeFetch(body), ok, dest, REPO);
  assert.strictEqual(fs.readFileSync(dest, 'utf8'), 'frivo setup');

  const wrong = { ...ok, sha256: 'e'.repeat(64) };
  const dest2 = path.join(dir, 'Wrong.exe');
  await assert.rejects(gh.downloadVerified(fakeFetch(body), wrong, dest2, REPO), /fingerprint/);
  assert.ok(!fs.existsSync(dest2) && !fs.existsSync(`${dest2}.partial`));

  await assert.rejects(gh.downloadVerified(fakeFetch(body), { ...ok, url: 'https://evil.example/FrivoSetup.exe' }, dest2, REPO), /releases/);
  await assert.rejects(gh.downloadVerified(fakeFetch(body), { ...ok, sha256: null }, dest2, REPO), /fingerprint/);
});

test('certificates: fingerprints shown in short groups', () => {
  assert.strictEqual(trust.formatFingerprint('85d560e1bba00088befb9f170fc9f2e553ffadfd'), '85D5 60E1 BBA0 0088 BEFB 9F17 0FC9 F2E5');
});

const fixture = (name) => fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8');
const CA = fixture('frivo-ca.pem');
const LEAF = fixture('frivo-leaf.pem');
const ROGUE_CA = fixture('rogue-ca.pem');
const ROGUE_LEAF = fixture('rogue-leaf.pem');
const pinFor = (pem) => ({ fingerprint: trust.sha256Hex(trust.pemToDer(pem)), pem });

test('certificates: a server is trusted only if the pinned authority signed it', () => {
  const pin = pinFor(CA);
  assert.ok(trust.leafTrustedBy(LEAF, pin), 'Frivo\'s own certificate');
  assert.ok(trust.leafTrustedBy(trust.pemToDer(LEAF), pin), 'as DER too');
  // Someone else's certificate, even with the real authority sent alongside
  // it and the same names on everything: not signed by it, not trusted.
  assert.ok(!trust.leafTrustedBy(ROGUE_LEAF, pin));
  // An authority with the same name isn't the same authority.
  assert.ok(!trust.leafTrustedBy(LEAF, pinFor(ROGUE_CA)));
  // A server that sends only its own certificate: pinned as itself.
  assert.ok(trust.leafTrustedBy(LEAF, pinFor(LEAF)));
  assert.ok(!trust.leafTrustedBy(ROGUE_LEAF, pinFor(LEAF)));
  assert.ok(!trust.leafTrustedBy(LEAF, { fingerprint: 'x' }), 'an old pin with no certificate');
  assert.ok(!trust.leafTrustedBy('not a certificate', pin));
});

test('certificates: the verifier keeps Chromium\'s verdict unless the pinned authority signed it', () => {
  const verifier = trust.makeVerifier(() => ({ 'frivo-box': pinFor(CA), 'fe80::1': pinFor(CA) }));
  const result = (req) => { let r; verifier(req, (v) => { r = v; }); return r; };
  // The forged chain: rogue certificate, real authority sent with it.
  const forged = { data: ROGUE_LEAF, issuerCert: { data: CA } };
  const real = { data: LEAF, issuerCert: { data: CA } };
  assert.strictEqual(result({ hostname: 'frivo-box', errorCode: -202, certificate: real }), 0);
  assert.strictEqual(result({ hostname: 'FRIVO-BOX', errorCode: -202, certificate: real }), 0);
  assert.strictEqual(result({ hostname: 'frivo-box', errorCode: -202, certificate: forged }), -3);
  assert.strictEqual(result({ hostname: 'other', errorCode: -202, certificate: real }), -3);
  assert.strictEqual(result({ hostname: 'fe80::1', errorCode: -202, certificate: real }), 0);
  assert.strictEqual(result({ hostname: 'anything', errorCode: 0, certificate: forged }), -3);
});

test('certificates: pins are keyed without IPv6 brackets', () => {
  assert.strictEqual(trust.pinKey('[FE80::1]'), 'fe80::1');
  assert.strictEqual(trust.pinKey('Frivo-Box'), 'frivo-box');
});

test('certificates: Frivo\'s own authority from its data folder', () => {
  const dir = tmp();
  fs.writeFileSync(path.join(dir, 'ca.crt'), CA);
  const pin = trust.localAuthorityPin(path.join(dir, 'ca.crt'));
  assert.ok(trust.leafTrustedBy(LEAF, pin));
  assert.strictEqual(trust.localAuthorityPin(path.join(dir, 'missing.crt')), null);
});

test('settings: saved, reloaded, and bad values put right', () => {
  const file = path.join(tmp(), 'app-settings.json');
  const s = new Settings(file);
  assert.strictEqual(s.get('mode'), null);
  s.update({ mode: 'remote', remoteUrl: 'https://x:5000' });
  assert.strictEqual(new Settings(file).get('remoteUrl'), 'https://x:5000');
  fs.writeFileSync(file, JSON.stringify({ mode: 'sideways', closeAction: 'explode', trusted: 'no' }));
  const t = new Settings(file);
  assert.strictEqual(t.get('mode'), null);
  assert.strictEqual(t.get('closeAction'), 'tray');
  assert.deepStrictEqual(t.get('trusted'), {});
  fs.writeFileSync(file, '{ not json');
  assert.strictEqual(new Settings(file).get('closeAction'), 'tray');
});

test('launcher.json: app mode on and off, keeping the launcher\'s own settings', () => {
  const appData = tmp();
  const exe = path.join(appData, 'FrivoApp.exe');
  const local = new FrivoLocal({ appData, execPath: exe });
  fs.mkdirSync(path.join(appData, 'Frivo'));
  // Windows PowerShell writes it with a BOM.
  fs.writeFileSync(local.launcherJson, '\uFEFF' + JSON.stringify({ closeAction: 'stop', openBrowser: true, lastUpdateNotice: 'u1' }));
  local.setAppMode(true);
  const on = JSON.parse(fs.readFileSync(local.launcherJson, 'utf8').replace(/^\uFEFF/, ''));
  assert.deepStrictEqual(on, { closeAction: 'stop', openBrowser: true, lastUpdateNotice: 'u1', appPath: exe });
  assert.ok(local.isAppMode());
  local.setAppMode(false);
  const off = JSON.parse(fs.readFileSync(local.launcherJson, 'utf8').replace(/^\uFEFF/, ''));
  assert.strictEqual(off.appPath, '');
  assert.strictEqual(off.closeAction, 'stop');
  assert.ok(!local.isAppMode());
});

test('launcher.json: made when Frivo has none yet', () => {
  const appData = tmp();
  const local = new FrivoLocal({ appData, execPath: 'C:\\Apps\\FrivoApp.exe' });
  local.setAppMode(true);
  assert.ok(local.isAppMode());
});

test('registry: reg.exe output', () => {
  const out = '\r\nHKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Frivo\r\n    InstallLocation    REG_SZ    C:\\Program Files\\Frivo\r\n    DisplayVersion    REG_SZ    1.7.0\r\n';
  assert.strictEqual(parseRegValue(out, 'InstallLocation'), 'C:\\Program Files\\Frivo');
  assert.strictEqual(parseRegValue(out, 'displayversion'), '1.7.0');
  assert.strictEqual(parseRegValue(out, 'Missing'), null);
});

test('update status: recent only', () => {
  const programData = tmp();
  const local = new FrivoLocal({ appData: tmp(), programData, execPath: 'x' });
  fs.mkdirSync(path.dirname(local.updateStatusFile), { recursive: true });
  fs.writeFileSync(local.updateStatusFile, JSON.stringify({ state: 'installing', message: 'Installing 1.7.1', started_utc: new Date().toISOString() }));
  assert.deepStrictEqual(local.updateStatus(), { state: 'installing', message: 'Installing 1.7.1', version: '' });
  fs.writeFileSync(local.updateStatusFile, JSON.stringify({ state: 'done', started_utc: new Date(Date.now() - 2 * 3600e3).toISOString() }));
  assert.strictEqual(local.updateStatus(), null);
});

// NEW: pairing codes and finding Frivo on the network.
test('pairing code: ten Crockford base-32 characters from the authority', () => {
  const { pairingCodeFor, normalizeCode } = require('../src/pairing');
  const code = pairingCodeFor(Buffer.from('frivo'));
  assert.match(code, /^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/);
  assert.equal(pairingCodeFor(Buffer.from('frivo')), code);
  assert.notEqual(pairingCodeFor(Buffer.from('frivo!')), code);
  assert.equal(normalizeCode(code.toLowerCase().replace(/-/g, ' ')), code);
  assert.equal(normalizeCode('o123-4567-89AB'), '0123-4567-89AB');
  assert.equal(normalizeCode('i1l1 1000 0000'), '1111-1000-0000');
  assert.equal(normalizeCode('UUUU-UUUU-UUUU'), null);
  assert.equal(normalizeCode('12345-67890'), null);   // the old ten-character form
  assert.equal(normalizeCode('12345'), null);
  assert.equal(normalizeCode(''), null);
});

test('discovery: only private networks, capped in size', () => {
  const { candidateAddresses, isPrivate } = require('../src/discovery');
  assert.ok(isPrivate('192.168.1.5') && isPrivate('10.0.0.1') && isPrivate('172.20.1.1'));
  assert.ok(!isPrivate('8.8.8.8') && !isPrivate('172.32.0.1'));
  const nic = (address, netmask, internal = false) => ({ family: 'IPv4', address, netmask, internal });
  const home = candidateAddresses({ eth: [nic('192.168.1.20', '255.255.255.0')], lo: [nic('127.0.0.1', '255.0.0.0', true)] });
  assert.equal(home.addresses.length, 254);
  assert.ok(home.own.has('192.168.1.20'));
  assert.ok(!home.addresses.includes('192.168.1.0') && !home.addresses.includes('192.168.1.255'));
  const big = candidateAddresses({ eth: [nic('10.4.7.9', '255.0.0.0')] });
  assert.equal(big.addresses.length, 254);
  assert.ok(big.addresses.includes('10.4.7.1'));
  const pub = candidateAddresses({ eth: [nic('203.0.113.4', '255.255.255.0')] });
  assert.equal(pub.addresses.length, 0);
});

test('pairing only trusts a real self-signed authority', () => {
  const fx = (n) => fs.readFileSync(path.join(__dirname, 'fixtures', n), 'utf8');
  assert.equal(trust.isSelfSignedAuthority(fx('frivo-ca.pem')), true);
  assert.equal(trust.isSelfSignedAuthority(fx('frivo-leaf.pem')), false);   // not an authority
  // The authority with its signature changed: same fields, but not signed by its key.
  const der = Buffer.from(fx('frivo-ca.pem').replace(/-----[^-]+-----/g, '').replace(/\s+/g, ''), 'base64');
  der[der.length - 5] ^= 0xff;
  assert.equal(trust.isSelfSignedAuthority(trust.derToPem(der)), false);
});
