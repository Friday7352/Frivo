'use strict';
/*
  Frivo's releases on GitHub: the app's own updates, and Frivo's setup when
  someone picks "Frivo on this PC" and doesn't have it yet.

  The same rules as Frivo's own updater (installer\Frivo.Update.psm1):
    * only this repository's releases, never drafts or pre-releases
    * only a file from this repository's own release downloads
    * only with the SHA-256 fingerprint GitHub publishes for it, and the
      download is checked against it before anything runs

  Both live in the one repository. Frivo's releases are tagged "v1.7.0" and
  carry FrivoSetup.exe; the app's are tagged "app-v1.0.0" and carry
  FrivoApp-Setup-1.0.0.exe. Frivo's updater ignores "app-v" tags (they
  aren't plain versions), and this ignores Frivo's.
*/

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const FRIVO_TAG = /^[vV]?(\d{1,5})(?:\.(\d{1,5}))?(?:\.(\d{1,5}))?$/;
const APP_TAG = /^app-v(\d{1,5})\.(\d{1,5})\.(\d{1,5})$/i;
const FRIVO_ASSET = 'FrivoSetup.exe';
const APP_ASSET = /^FrivoApp-Setup-[0-9.]+\.exe$/i;

function parseVersion(text) {
  const m = String(text || '').trim().match(FRIVO_TAG);
  if (!m) return null;
  return [Number(m[1]), Number(m[2] || 0), Number(m[3] || 0)];
}

function compareVersions(a, b) {
  for (let i = 0; i < 3; i++) {
    if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) < (b[i] || 0) ? -1 : 1;
  }
  return 0;
}

function versionText(v) {
  return v ? v.join('.') : '';
}

function digestOf(asset) {
  const m = String(asset && asset.digest || '').match(/^sha256:([0-9a-f]{64})$/i);
  return m ? m[1].toLowerCase() : null;
}

function downloadPrefix(repository) {
  return `https://github.com/${repository}/releases/download/`;
}

function pickAsset(release, test, repository) {
  for (const asset of release.assets || []) {
    const name = String(asset && asset.name || '');
    if (!(typeof test === 'string' ? name.toLowerCase() === test.toLowerCase() : test.test(name))) continue;
    const url = String(asset.browser_download_url || '');
    if (!url.toLowerCase().startsWith(downloadPrefix(repository).toLowerCase())) return null;
    return { name, url, size: Number(asset.size) || 0, sha256: digestOf(asset) };
  }
  return null;
}

function usable(release) {
  return release && typeof release === 'object' && release.draft !== true && release.prerelease !== true;
}

// The newest Frivo release with FrivoSetup.exe and its fingerprint.
function latestFrivo(releases, repository) {
  let best = null;
  for (const release of Array.isArray(releases) ? releases : []) {
    if (!usable(release)) continue;
    const version = parseVersion(release.tag_name);
    if (!version) continue;
    const asset = pickAsset(release, FRIVO_ASSET, repository);
    if (!asset || !asset.sha256) continue;
    if (!best || compareVersions(version, best.versionParts) > 0) {
      best = { version: versionText(version), versionParts: version, ...asset };
    }
  }
  return best;
}

// The newest app release, if it's newer than `current`.
function newerApp(releases, current, repository) {
  const now = parseVersion(current) || [0, 0, 0];
  let best = null;
  for (const release of Array.isArray(releases) ? releases : []) {
    if (!usable(release)) continue;
    const m = String(release.tag_name || '').match(APP_TAG);
    if (!m) continue;
    const version = [Number(m[1]), Number(m[2]), Number(m[3])];
    if (compareVersions(version, now) <= 0) continue;
    const asset = pickAsset(release, APP_ASSET, repository);
    if (!asset || !asset.sha256) continue;
    if (!best || compareVersions(version, best.versionParts) > 0) {
      best = { version: versionText(version), versionParts: version, notesUrl: String(release.html_url || ''), ...asset };
    }
  }
  return best;
}

async function listReleases(fetchImpl, repository, userAgent) {
  const response = await fetchImpl(`https://api.github.com/repos/${repository}/releases?per_page=50`, {
    headers: { 'User-Agent': userAgent, Accept: 'application/vnd.github+json' },
  });
  if (response.status === 404) return [];
  if (!response.ok) throw new Error(`GitHub answered ${response.status}.`);
  return response.json();
}

/*
  Downloads `asset` to `dest`, checking its SHA-256 as it arrives. The file
  only appears under its real name once it has been checked, so a half
  download or a wrong file is never left where something might run it.
*/
async function downloadVerified(fetchImpl, asset, dest, repository, onProgress) {
  if (!asset || !asset.sha256) throw new Error('GitHub publishes no fingerprint for this file, so it can\'t be checked.');
  if (!String(asset.url).toLowerCase().startsWith(downloadPrefix(repository).toLowerCase())) {
    throw new Error('That download isn\'t from Frivo\'s releases.');
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const partial = `${dest}.partial`;
  const response = await fetchImpl(asset.url, { headers: { 'User-Agent': 'FrivoApp' } });
  if (!response.ok || !response.body) throw new Error(`The download failed (${response.status}).`);
  const total = Number(response.headers.get('content-length')) || asset.size || 0;
  const hash = crypto.createHash('sha256');
  const out = fs.createWriteStream(partial);
  let received = 0;
  try {
    const reader = response.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = Buffer.from(value);
      hash.update(chunk);
      received += chunk.length;
      if (!out.write(chunk)) await new Promise((r) => out.once('drain', r));
      if (onProgress) onProgress(received, total);
    }
    await new Promise((resolve, reject) => out.end((err) => (err ? reject(err) : resolve())));
  } catch (err) {
    out.destroy();
    try { fs.unlinkSync(partial); } catch { /* gone already */ }
    throw err;
  }
  const actual = hash.digest('hex');
  if (actual !== asset.sha256) {
    try { fs.unlinkSync(partial); } catch { /* gone already */ }
    throw new Error('The download doesn\'t match the fingerprint GitHub publishes for it, so it was deleted.');
  }
  try { fs.unlinkSync(dest); } catch { /* none there */ }
  fs.renameSync(partial, dest);
  return dest;
}

module.exports = {
  parseVersion,
  compareVersions,
  versionText,
  latestFrivo,
  newerApp,
  listReleases,
  downloadVerified,
  FRIVO_ASSET,
};
