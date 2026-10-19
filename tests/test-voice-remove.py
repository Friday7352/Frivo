#!/usr/bin/env python3
"""NEW (1.5.0): removing a voice from your ElevenLabs voices.

  * refused for a voice a profile (or the default) still uses, naming them
  * a free voice or a bad id: refused, nothing sent
  * otherwise ElevenLabs is asked to delete it, and its anchors go too
  * ElevenLabs refusing is reported, not hidden
  * the voice list says whose a voice is (is_owner), for the warning

Usage:  python3 tests/test-voice-remove.py     (run from the repo root)
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-vr-home-")
ws = tempfile.mkdtemp(prefix="frivo-vr-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_vr", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_vr"] = mod
spec.loader.exec_module(mod)

deleted = []
answer = {"status": 200, "body": {"status": "ok"}}


def fake_delete(url, **kw):
    deleted.append(url)
    return SimpleNamespace(status_code=answer["status"], text=json.dumps(answer["body"]), json=lambda: answer["body"])


mod.requests.delete = fake_delete
mod.CFG.update(elevenlabs_api_key="k", voice_id="DefaultVoice1")
mod.save_profiles([{"id": "p1", "name": "Echo", "voice_id": "UsedVoice123", "voice_name": "Miki"}])
client = mod.app.test_client()

res = client.delete("/api/voices/elevenlabs/UsedVoice123")
check("in use by a profile: refused, naming it", res.status_code == 409 and "Echo" in res.get_json()["error"] and not deleted, res.get_json())
res = client.delete("/api/voices/elevenlabs/DefaultVoice1")
check("the default's voice: refused", res.status_code == 409 and "Default" in res.get_json()["error"] and not deleted)
check("a free voice: refused", client.delete("/api/voices/elevenlabs/piper:alba").status_code in (400, 404) and not deleted)
check("a bad id: refused", client.delete("/api/voices/elevenlabs/x").status_code == 400 and not deleted)

# An anchor for the voice, to see it go.
os.makedirs(mod.ANCHORS_DIR, exist_ok=True)
open(os.path.join(mod.ANCHORS_DIR, "a" * 32 + ".mp3"), "wb").write(b"mp3")
mod.write_anchors({"FreeToGo123::en::auto": {"id": "r1", "text": "x", "file": "a" * 32 + ".mp3"},
                   "OtherVoice99::en::auto": {"id": "r2", "text": "y"}})
res = client.delete("/api/voices/elevenlabs/FreeToGo123")
check("otherwise: ElevenLabs is asked to delete it", res.status_code == 200 and deleted[-1].endswith("/v1/voices/FreeToGo123"), (res.status_code, deleted))
check("... and its anchor goes, others stay", list(mod.load_anchors()) == ["OtherVoice99::en::auto"]
      and not os.path.exists(os.path.join(mod.ANCHORS_DIR, "a" * 32 + ".mp3")), mod.load_anchors())

answer.update(status=400, body={"detail": {"message": "This voice cannot be deleted."}})
res = client.delete("/api/voices/elevenlabs/Premade0001")
check("ElevenLabs refusing is reported", res.status_code == 502 and "cannot be deleted" in res.get_json()["error"], res.get_json())

check("the list says whose a voice is", mod.tidy_voice({"voice_id": "a", "is_owner": True})["is_owner"] is True
      and mod.tidy_voice({"voice_id": "b"})["is_owner"] is False)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("All voice-removal checks passed.")
