'use strict';
/*
  Turning what someone types into the address of a Frivo server.

    192.168.1.50                -> https://192.168.1.50:5000
    frivo-box                   -> https://frivo-box:5000
    https://192.168.1.50:5000/  -> https://192.168.1.50:5000
    http://10.0.0.4:8080/chat   -> http://10.0.0.4:8080

  Frivo serves HTTPS on port 5000 unless set up otherwise, so those are
  filled in when left out. Only the origin is kept: the app always opens
  Frivo's home page.
*/

const DEFAULT_PORT = 5000;

function normalizeAddress(text, port = DEFAULT_PORT) {
  let value = String(text || '').trim();
  if (!value) return { ok: false, error: 'Type the address of the PC Frivo runs on.' };
  if (/\s/.test(value)) return { ok: false, error: "An address can't have spaces in it." };
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) value = `https://${value}`;
  let url;
  try {
    url = new URL(value);
  } catch {
    return { ok: false, error: "That doesn't look like an address. Try something like 192.168.1.50." };
  }
  if (!['https:', 'http:'].includes(url.protocol)) {
    return { ok: false, error: 'Frivo is reached over https:// (or http://).' };
  }
  if (!url.hostname) return { ok: false, error: 'Type the address of the PC Frivo runs on.' };
  if (url.username || url.password) return { ok: false, error: "Leave the name and password out of the address." };
  // A port typed in is kept; without one, Frivo's own (not the protocol's).
  const hasPort = /^[a-z]+:\/\/(\[[^\]]+\]|[^/:?#]+):\d+/i.test(value);
  if (!hasPort) url.port = String(port);
  return { ok: true, url: url.origin, host: url.host };
}

function isLoopbackHost(hostname) {
  const h = String(hostname || '').toLowerCase().replace(/^\[|\]$/g, '');
  return h === 'localhost' || h === '::1' || /^127\./.test(h);
}

module.exports = { normalizeAddress, isLoopbackHost, DEFAULT_PORT };
