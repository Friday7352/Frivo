'use strict';
/*
  Trusting Frivo's certificate.

  Frivo serves HTTPS with a certificate signed by its own small certificate
  authority, made when it was installed. Setup trusts that authority on the
  PC Frivo runs on, so "Frivo on this PC" connects cleanly. Another PC
  doesn't know it, and a browser there shows a warning page.

  The app does what a careful person would: the first time, it shows who
  the certificate says it is and its fingerprint, and asks. Once trusted,
  that fingerprint is remembered for that address, and the app only ever
  accepts a certificate from the same authority there again. Frivo makes a
  new server certificate when the PC's address changes, but signs it with
  the same authority, so that doesn't ask again.

  What's pinned is the certificate at the top of the chain the server sends:
  Frivo sends its own certificate followed by its authority's, so that's the
  authority. A server that sends only its own certificate gets that pinned
  instead, which works the same, just asks again if it changes.

  CHANGED: the authority's whole certificate is kept, not just its
  fingerprint, and a server is only accepted when its own certificate is
  really signed by it (and in date). Frivo's authority certificate is sent to
  anyone who connects, so matching the chain the server sends against a
  fingerprint would let anything at that address pass by sending it along.
*/

const crypto = require('crypto');
const { X509Certificate } = crypto;
const fs = require('fs');
const tls = require('tls');
const net = require('net');

function sha256Hex(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function pemToDer(pem) {
  const match = String(pem || '').match(/-----BEGIN CERTIFICATE-----([\s\S]*?)-----END CERTIFICATE-----/);
  if (!match) return null;
  return Buffer.from(match[1].replace(/\s+/g, ''), 'base64');
}

// "AB12…" in groups, for showing to a person. Only the first 16 bytes:
// enough to compare by eye with what Frivo shows, short enough to read.
function formatFingerprint(hex) {
  return String(hex || '').toUpperCase().slice(0, 32).match(/.{1,4}/g)?.join(' ') || '';
}

// Electron's Certificate: data is PEM, issuerCert the next one up, if sent.
function topOfElectronChain(certificate) {
  let cert = certificate;
  const seen = new Set();
  while (cert && cert.issuerCert && !seen.has(cert.fingerprint)) {
    seen.add(cert.fingerprint);
    if (cert.issuerCert.fingerprint === cert.fingerprint) break;
    cert = cert.issuerCert;
  }
  return cert;
}

function electronFingerprint(certificate) {
  const top = topOfElectronChain(certificate);
  const der = top && pemToDer(top.data);
  return der ? sha256Hex(der) : null;
}

// Node's peer certificate: raw is DER, issuerCertificate the next one up.
function topOfNodeChain(peer) {
  let cert = peer;
  const seen = new Set();
  while (cert && cert.issuerCertificate && cert.issuerCertificate !== cert) {
    const key = cert.fingerprint256;
    if (seen.has(key)) break;
    seen.add(key);
    if (!cert.issuerCertificate.raw || cert.issuerCertificate.fingerprint256 === cert.fingerprint256) break;
    cert = cert.issuerCertificate;
  }
  return cert;
}

function derToPem(der) {
  const b64 = Buffer.from(der).toString('base64').match(/.{1,64}/g).join('\n');
  return `-----BEGIN CERTIFICATE-----\n${b64}\n-----END CERTIFICATE-----\n`;
}

// Pins are keyed by host name, without the [ ] an IPv6 address has in a URL:
// Chromium gives the name without them.
function pinKey(hostname) {
  return String(hostname || '').toLowerCase().replace(/^\[|\]$/g, '');
}

function inDate(cert, now = Date.now()) {
  return Date.parse(cert.validFrom) <= now && now <= Date.parse(cert.validTo);
}

/*
  Is `leaf` (DER or PEM) a certificate the pinned authority stands behind?
  Either it's the pinned certificate itself (a server that sent only its
  own), or the pinned authority signed it. Both in date.
*/
function leafTrustedBy(leaf, pin) {
  if (!leaf || !pin || !pin.pem) return false;
  try {
    const leafCert = new X509Certificate(leaf);
    const authority = new X509Certificate(pin.pem);
    if (!inDate(leafCert)) return false;
    if (leafCert.raw.equals(authority.raw)) return true;
    if (!inDate(authority)) return false;
    return leafCert.checkIssued(authority) && leafCert.verify(authority.publicKey);
  } catch {
    return false;
  }
}

/*
  NEW (1.8.0): is `pem` a real certificate authority, signed by its own key?
  A pairing code only covers part of the authority's fingerprint, so the
  authority has to be one that took a real signature to make, not bytes
  shuffled until the fingerprint matched.
*/
function isSelfSignedAuthority(pem) {
  try {
    const cert = new X509Certificate(pem);
    return cert.ca === true && inDate(cert) &&
      cert.checkIssued(cert) && cert.verify(cert.publicKey);
  } catch {
    return false;
  }
}

function nameOf(subject) {
  if (!subject) return '';
  return subject.CN || subject.O || '';
}

/*
  Connects to an https:// address just far enough to read its certificate,
  without trusting it. Resolves to what's shown when asking, or rejects
  when nothing answers.
*/
function inspectServer(origin, timeoutMs = 6000) {
  return new Promise((resolve, reject) => {
    let url;
    try { url = new URL(origin); } catch (err) { reject(err); return; }
    if (url.protocol !== 'https:') { resolve(null); return; }
    const host = url.hostname.replace(/^\[|\]$/g, '');
    const options = {
      host,
      port: Number(url.port) || 443,
      rejectUnauthorized: false,
      timeout: timeoutMs,
    };
    if (!net.isIP(host)) options.servername = host;
    const socket = tls.connect(options, () => {
      try {
        const peer = socket.getPeerCertificate(true);
        if (!peer || !peer.raw) throw new Error('The server sent no certificate.');
        const top = topOfNodeChain(peer);
        resolve({
          fingerprint: sha256Hex(top.raw),
          // NEW: what the pairing code for this server's authority is.
          pairingCode: require('./pairing').pairingCodeFor(top.raw),
          authorityPem: derToPem(top.raw),
          leafRaw: Buffer.from(peer.raw),
          authority: nameOf(top.subject),
          server: nameOf(peer.subject),
          names: String(peer.subjectaltname || '')
            .split(/,\s*/)
            .map((n) => n.replace(/^(DNS|IP Address):/, ''))
            .filter(Boolean),
          validTo: peer.valid_to || '',
          trustedBySystem: socket.authorized === true,
        });
      } catch (err) {
        reject(err);
      } finally {
        socket.destroy();
      }
    });
    socket.on('timeout', () => { socket.destroy(); reject(new Error('timed out')); });
    socket.on('error', reject);
  });
}

// The authority Frivo made on this PC, from its data folder, as a pin. Lets
// "Frivo on this PC" connect even if setup couldn't add it to Windows'
// trusted list.
function localAuthorityPin(caPath) {
  try {
    const der = pemToDer(fs.readFileSync(caPath, 'utf8'));
    return der ? { fingerprint: sha256Hex(der), pem: derToPem(der) } : null;
  } catch {
    return null;
  }
}

/*
  For session.setCertificateVerifyProc. Chromium's own verdict stands,
  except that a certificate it rejects is accepted when the authority
  pinned for that host signed it. Pins come from pins(), read each time so a
  just-trusted address works at once.
*/
function makeVerifier(pins) {
  return (request, callback) => {
    if (request.errorCode === 0) { callback(-3); return; }
    const pin = pins()[pinKey(request.hostname)];
    const leaf = request.certificate && request.certificate.data;
    if (pin && leafTrustedBy(leaf, pin)) {
      callback(0);
      return;
    }
    callback(-3);
  };
}

module.exports = {
  inspectServer,
  makeVerifier,
  electronFingerprint,
  localAuthorityPin,
  leafTrustedBy,
  pinKey,
  derToPem,
  formatFingerprint,
  sha256Hex,
  pemToDer,
  isSelfSignedAuthority,   // NEW (1.8.0)
};
