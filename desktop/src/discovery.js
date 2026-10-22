'use strict';
/*
  Finding Frivo on the local network, so "On another PC" is a list to pick
  from rather than an address to type.

  For each of this PC's private IPv4 networks (192.168.x, 10.x, 172.16-31.x),
  every address on it is asked for Frivo's /api/hello on Frivo's port, a
  few dozen at a time, each giving up quickly. What answers "frivo": true is
  listed with the name it gives. Nothing about the answer is trusted: it's a
  label to pick from. Who the server really is gets settled after, by its
  pairing code (pairing.js) or a certificate the person trusts.

  No change to Frivo or the firewall is needed: it's the same port phones
  use. Big networks (larger than /22, 1,022 addresses) are only searched
  around this PC's own address (its /24), to keep it to a few seconds.
*/

const https = require('https');
const http = require('http');
const os = require('os');

function ipToInt(ip) {
  return ip.split('.').reduce((n, part) => (n << 8) + Number(part), 0) >>> 0;
}

function intToIp(n) {
  return [n >>> 24, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].join('.');
}

function isPrivate(ip) {
  return /^10\./.test(ip) || /^192\.168\./.test(ip) || /^172\.(1[6-9]|2\d|3[01])\./.test(ip);
}

// The addresses worth asking, from this PC's network interfaces.
function candidateAddresses(interfaces = os.networkInterfaces()) {
  const out = new Set();
  const own = new Set();
  for (const list of Object.values(interfaces)) {
    for (const nic of list || []) {
      if (nic.family !== 'IPv4' && nic.family !== 4) continue;
      if (nic.internal || !isPrivate(nic.address)) continue;
      own.add(nic.address);
      const ip = ipToInt(nic.address);
      let mask = ipToInt(nic.netmask || '255.255.255.0');
      const size = (~mask >>> 0) + 1;
      if (size > 1024 || size < 4) mask = ipToInt('255.255.255.0');
      const network = (ip & mask) >>> 0;
      const broadcast = (network | (~mask >>> 0)) >>> 0;
      for (let n = network + 1; n < broadcast; n++) out.add(intToIp(n));
    }
  }
  return { addresses: [...out], own };
}

// Asks one address for Frivo's hello. Resolves to what it said, or null.
function hello(host, port, timeoutMs, scheme = 'https') {
  return new Promise((done) => {
    // CHANGED: settles exactly once, and always: a host that answers and
    // then stalls, or sends too much, gives up on the deadline like one
    // that never answered.
    let settled = false;
    let req = null;
    const resolve = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      if (req) req.destroy();
      done(value);
    };
    const deadline = setTimeout(() => resolve(null), timeoutMs * 2);
    const lib = scheme === 'https' ? https : http;
    req = lib.get({
      host,
      port,
      path: '/api/hello',
      timeout: timeoutMs,
      rejectUnauthorized: false,   // anyone can claim a name here; trust comes later
      headers: { 'User-Agent': 'FrivoApp' },
    }, (res) => {
      if (res.statusCode !== 200) { res.resume(); resolve(null); return; }
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { body += chunk; if (body.length > 4096) resolve(null); });
      res.on('aborted', () => resolve(null));
      res.on('close', () => resolve(null));   // after 'end' has resolved, a no-op
      res.on('end', () => {
        try {
          const info = JSON.parse(body);
          if (info && info.frivo === true) {
            resolve({
              name: String(info.name || host).slice(0, 64),
              version: /^\d+(\.\d+)*$/.test(String(info.version || '')) ? String(info.version).slice(0, 20) : '',
              url: `${scheme}://${host}:${port}`,
              address: host,
            });
            return;
          }
        } catch { /* not Frivo */ }
        resolve(null);
      });
    });
    req.on('timeout', () => resolve(null));
    req.on('error', () => resolve(null));
    req.on('close', () => resolve(null));
  });
}

/*
  Frivo servers on the network, sorted by name. `onFound` is called as each
  one answers, so the list can fill in while the rest are still asked.
  FRIVO_APP_DISCOVER_HOSTS ("host:port,host:port") asks just those, for the
  tests.
*/
async function findFrivo({ port = 5000, timeoutMs = 900, concurrency = 96, onFound, cancelled = () => false } = {}) {
  let targets;
  let own = new Set();
  if (process.env.FRIVO_APP_DISCOVER_HOSTS) {
    targets = process.env.FRIVO_APP_DISCOVER_HOSTS.split(',').map((t) => t.trim()).filter(Boolean).map((t) => {
      const [h, p] = t.split(':');
      return { host: h, port: Number(p) || port };
    });
  } else {
    const found = candidateAddresses();
    own = found.own;
    targets = found.addresses.map((host) => ({ host, port }));
  }
  const results = [];
  let next = 0;
  async function worker() {
    while (next < targets.length && !cancelled()) {   // CHANGED: a newer search stops this one
      const t = targets[next++];
      const info = await hello(t.host, t.port, timeoutMs);
      if (info) {
        info.thisPc = own.has(t.host);
        results.push(info);
        if (onFound) onFound(info);
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, targets.length) }, worker));
  return results.sort((a, b) => a.name.localeCompare(b.name));
}

module.exports = { findFrivo, candidateAddresses, hello, isPrivate };
