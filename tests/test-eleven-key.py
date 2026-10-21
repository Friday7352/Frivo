#!/usr/bin/env python3
"""NEW (1.5.0): the ElevenLabs key is actually tried.

  * a good key: how many voices (how many your own) and the plan's credits
  * a key not allowed to read voices: said so, naming the permission, and
    the voice list says why it's empty instead of a bare 401
  * a wrong key: "not accepted"
  * no key: nothing to try

Usage:  python3 tests/test-eleven-key.py     (run from the repo root)
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-key-home-")
ws = tempfile.mkdtemp(prefix="frivo-key-")
shutil.copy(os.path.join(ROOT, "app", "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_key", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_key"] = mod
spec.loader.exec_module(mod)
state = {"mode": "good"}


def resp(status, body):
    return SimpleNamespace(status_code=status, text=json.dumps(body), json=lambda: body,
                           raise_for_status=lambda: None)


def fake_get(url, *a, **kw):
    mode = state["mode"]
    if mode == "invalid":
        return resp(401, {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}})
    if url.endswith("/v1/voices"):
        if mode == "no_voices":
            return resp(401, {"detail": {"status": "missing_permissions",
                                         "message": "The API key you used is missing the permission voices_read to execute this operation."}})
        return resp(200, {"voices": [{"voice_id": "a1b2c3d4e5", "name": "Rachel", "category": "premade"},
                                     {"voice_id": "f6g7h8i9j0", "name": "Mine", "category": "cloned"},
                                     {"voice_id": "k1l2m3n4o5", "name": "Lib", "category": "professional"}]})
    if url.endswith("/v1/user/subscription"):
        return resp(200, {"tier": "creator", "character_count": 4000, "character_limit": 100000})
    raise AssertionError(url)


mod.requests.get = fake_get
mod.piper_voice_entries = lambda: [{"voice_id": "piper:alba", "name": "Alba"}]
mod.windows_voice_entries = lambda: []
mod.upgrade_desktop_voices = lambda: None
client = mod.app.test_client()

check("no key: nothing to try", client.get("/api/elevenlabs/check").get_json()["state"] == "missing")
mod.CFG["elevenlabs_api_key"] = "sk_test"
d = client.get("/api/elevenlabs/check").get_json()
check("a good key: connected", d["state"] == "ok", d)
check("... with how many voices, and how many yours", d["voices"] == 3 and d["own_voices"] == 2, d)
check("... and the plan's credits", d["account"] == {"tier": "creator", "used": 4000, "limit": 100000}, d)

state["mode"] = "no_voices"
d = client.get("/api/elevenlabs/check").get_json()
check("not allowed to read voices: said so", d["state"] == "no_voices" and "Voices (read)" in d["problems"][0]["message"], d)
v = client.get("/api/voices").get_json()
check("the voice list says why, and still has the free voices",
      v.get("eleven_problem") is True and "Voices (read)" in v.get("notice", "") and v["voices"][0]["voice_id"] == "piper:alba", v)

state["mode"] = "invalid"
d = client.get("/api/elevenlabs/check").get_json()
check("a wrong key: not accepted", d["state"] == "invalid" and "doesn't accept" in d["problems"][0]["message"], d)

print()
if failures:
    print(f"{len(failures)} failed: {failures}")
    sys.exit(1)
print("All ElevenLabs-key checks passed.")
