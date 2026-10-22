#!/usr/bin/env python3
"""NEW (1.8.0): Settings › Other devices and what the Frivo app uses.

  * /api/hello says it's Frivo, with the PC's name
  * /api/devices gives the network addresses and the pairing code
  * the pairing code is the same from the server, the app (desktop/src/
    pairing.js) and the launcher (Get-FrivoPairingCode), and matches an
    independent working-out here
  * /api/qr.png is a PNG; bad input is refused
  * /frivo-ca.crt is the authority's certificate, never its key
  * Settings has the Other devices section, and it fills in

Usage:  python3 tests/test-devices.py     (run from the repo root)
"""

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-dev-home-")
data = tempfile.mkdtemp(prefix="frivo-dev-data-")
os.environ["VOICE_CONSOLE_DATA"] = data
ws = tempfile.mkdtemp(prefix="frivo-dev-")
for name in ("app.py", "voice_pack.py", "cleanup_rules.py", "builtin_ai.py"):
    shutil.copy(os.path.join(ROOT, "app", name), os.path.join(ws, name))
shutil.copytree(os.path.join(ROOT, "app", "static"), os.path.join(ws, "static"))
shutil.copytree(os.path.join(ROOT, "app", "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_dev", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_dev"] = mod
spec.loader.exec_module(mod)

# A certificate authority, as Frivo keeps it (ca.crt in its data folder).
ca_pem = open(os.path.join(ROOT, "desktop", "test", "fixtures", "frivo-ca.pem"), "rb").read()
with open(mod.CA_CERT_CRT_PATH, "wb") as f:
    f.write(ca_pem)
der = base64.b64decode(b"".join(re.search(rb"-----BEGIN CERTIFICATE-----(.+?)-----END", ca_pem, re.S).group(1).split()))

# Worked out independently: the top 60 bits of the SHA-256 as an integer.
n = int.from_bytes(hashlib.sha256(der).digest(), "big") >> (256 - 60)
alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
expected = "".join(alphabet[(n >> (55 - 5 * i)) & 31] for i in range(12))
expected = expected[:4] + "-" + expected[4:8] + "-" + expected[8:]

client = mod.app.test_client()
https = {"base_url": "https://localhost:5000"}

r = client.get("/api/hello", **https)
hello = r.get_json()
check("/api/hello says it's Frivo", r.status_code == 200 and hello["frivo"] is True and hello["name"], hello)
check("with the version and that it can pair", hello["version"] == mod.APP_VERSION and hello["pairing"] is True, hello)

r = client.get("/api/devices", **https)
d = r.get_json()
check("the pairing code", d["pairing_code"] == expected, (d["pairing_code"], expected))
check("in the form XXXX-XXXX-XXXX", re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}", d["pairing_code"] or ""), d["pairing_code"])
check("network addresses are https on Frivo's port, never 127.x", all(u.startswith("https://") and u.endswith(":5000") and "127." not in u for u in d["network_urls"]), d["network_urls"])

node = shutil.which("node")
if node:
    js = os.path.join(ROOT, "desktop", "src", "pairing.js").replace("\\", "/")
    out = subprocess.run([node, "-e", "const p=require(%r); const fs=require('fs'); const pem=fs.readFileSync(%r,'utf8'); const b64=pem.split('-----')[2].replace(/\\s+/g,''); console.log(p.pairingCodeFor(Buffer.from(b64,'base64'))); console.log(p.normalizeCode(' %s '))"
                          % (js, os.path.join(ROOT, "desktop", "test", "fixtures", "frivo-ca.pem").replace("\\", "/"), expected.lower().replace("-", " ").replace("0", "o").replace("1", "l"))],
                         capture_output=True, text=True).stdout.split()
    check("the app works out the same code", out[:1] == [expected], out)
    check("and reads a code typed in lower case, with spaces, O for 0 and L for 1", out[1:2] == [expected], out)
else:
    print("  SKIP  the app's code (no node)")

pwsh = shutil.which("pwsh")
if pwsh:
    module = os.path.join(ROOT, "installer", "Frivo.Setup.psm1")
    out = subprocess.run([pwsh, "-NoProfile", "-Command",
                          "Import-Module '%s'; Get-FrivoPairingCode -CertificatePath '%s'" % (module, mod.CA_CERT_CRT_PATH)],
                         capture_output=True, text=True).stdout.strip()
    check("the launcher works out the same code", out == expected, out)
else:
    print("  SKIP  the launcher's code (no pwsh)")

r = client.get("/api/qr.png?text=" + "https%3A%2F%2F192.168.1.250%3A5000", **https)
check("a QR code is a PNG", r.status_code == 200 and r.data[:8] == b"\x89PNG\r\n\x1a\n", (r.status_code, r.data[:8]))
check("not kept in the cache", r.headers.get("Cache-Control") == "no-store")
check("no text, no QR code", client.get("/api/qr.png", **https).status_code == 400)
check("too much text, no QR code", client.get("/api/qr.png?text=" + "x" * 600, **https).status_code == 400)

r = client.get("/frivo-ca.crt", **https)
check("the certificate downloads as Frivo-CA.crt", r.status_code == 200 and r.data == der and "Frivo-CA.crt" in r.headers.get("Content-Disposition", ""), r.headers)
check("and is never the key", b"PRIVATE" not in r.data)

os.remove(mod.CA_CERT_CRT_PATH)
d = client.get("/api/devices", **https).get_json()
check("no certificate, no pairing code", d["pairing_code"] is None and d["certificate"] is False, d)
check("and nothing to download", client.get("/frivo-ca.crt", **https).status_code == 404)

page = client.get("/", **https).get_data(as_text=True)
check("Settings has the Other devices section", 'id="devicesSection"' in page and 'data-settings-section="devices"' in page)

print("")
print("%d failed" % len(failures) if failures else "All devices checks passed.")
sys.exit(1 if failures else 0)
