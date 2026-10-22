'use strict';
/*
  Frivo's pairing code: what you type into the app from the screen of the PC
  Frivo runs on, so the app knows it's talking to that Frivo.

  It's worked out from Frivo's own certificate authority: its SHA-256, the
  first 60 bits, as twelve letters and digits in Crockford's base 32 (no I,
  L, O or U), shown as XXXX-XXXX-XXXX. Frivo's server (pairing_code_for in
  app\app.py) and its launcher (Get-FrivoPairingCode in
  installer\Frivo.Setup.psm1) work it out the same way.

  If the code typed matches the one worked out from the certificate the
  server sent, and that certificate is a real authority signed by its own
  key (trust.isSelfSignedAuthority), it's that Frivo: another server would
  need an authority whose fingerprint starts with the same 60 bits, around
  10^18 signatures to find. The code isn't a secret, just read from a screen you trust.
*/

const crypto = require('crypto');

const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

function pairingCodeFor(der) {
  const digest = crypto.createHash('sha256').update(der).digest();
  let bits = '';
  for (let i = 0; i < 8; i++) bits += digest[i].toString(2).padStart(8, '0');
  bits = bits.slice(0, 60);
  let text = '';
  for (let i = 0; i < 60; i += 5) text += ALPHABET[parseInt(bits.slice(i, i + 5), 2)];
  return format(text);
}

// What someone typed, the way Crockford's base 32 reads it: any case,
// dashes and spaces ignored, O read as 0 and I or L as 1.
function normalizeCode(typed) {
  const text = String(typed || '').toUpperCase().replace(/[\s-]/g, '').replace(/O/g, '0').replace(/[IL]/g, '1');
  if (!/^[0-9A-HJKMNP-TV-Z]{12}$/.test(text)) return null;
  return format(text);
}

function format(text) {
  return `${text.slice(0, 4)}-${text.slice(4, 8)}-${text.slice(8)}`;
}

module.exports = { pairingCodeFor, normalizeCode };
