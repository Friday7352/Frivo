#!/usr/bin/env python3
"""NEW (2.0.0): Frivo hands out the Frivo app it was installed with.

FrivoSetup.exe carries the app and leaves a copy with Frivo
(app-installer/FrivoApp-Setup.exe and app.json). Apps on other PCs update
from it, and a browser's "Get the app" downloads it.

  * /api/app/latest says 404 when there's no copy, or a bad app.json
  * with one: its version, file name, size and SHA-256
  * /api/app/installer is that exact file, as a download

Usage:  python3 tests/test-app-download.py     (run from the repo root)
Needs:  Frivo's Python packages.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-appdl-data-")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-appdl-home-")
spec = importlib.util.spec_from_file_location("frivo_appdl", os.path.join(ROOT, "app", "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_appdl"] = mod
spec.loader.exec_module(mod)

folder = tempfile.mkdtemp(prefix="frivo-appdl-inst-")
mod.APP_INSTALLER_DIR = folder
client = mod.app.test_client()

r = client.get("/api/app/latest")
check("no copy: 404", r.status_code == 404, r.status_code)
check("and the installer too", client.get("/api/app/installer").status_code == 404)

body = os.urandom(4096)
with open(os.path.join(folder, "FrivoApp-Setup.exe"), "wb") as f:
    f.write(body)
with open(os.path.join(folder, "app.json"), "w") as f:
    f.write('{"version": "not a version"}')
check("a bad version: 404", client.get("/api/app/latest").status_code == 404)

with open(os.path.join(folder, "app.json"), "w") as f:
    json.dump({"version": "2.0.0"}, f)
r = client.get("/api/app/latest")
info = r.get_json() or {}
check("with a copy: 200", r.status_code == 200, r.status_code)
check("its version", info.get("version") == "2.0.0", info)
check("its name", info.get("name") == "FrivoApp-Setup-2.0.0.exe", info)
check("its size", info.get("size") == len(body), info)
check("its SHA-256", info.get("sha256") == hashlib.sha256(body).hexdigest(), info)

r = client.get("/api/app/installer")
check("the installer is that file", r.status_code == 200 and r.data == body, r.status_code)
check("as a download with the versioned name",
      "FrivoApp-Setup-2.0.0.exe" in r.headers.get("Content-Disposition", ""), r.headers.get("Content-Disposition"))
r.close()

shutil.rmtree(folder, ignore_errors=True)
print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("All app download checks passed.")
