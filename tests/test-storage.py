#!/usr/bin/env python3
"""NEW (1.6.1): Settings > Storage.

  * by default everything is in Frivo's data folder
  * moving each kind (built-in AI, voices you add, saved replies, reply
    audio) to another folder copies the files into a subfolder there,
    switches Frivo over, then deletes the old copy; saved replies still list
  * a folder that already has Frivo's files asks first; "use" switches to
    them without moving; back to Frivo's folder works
  * a picked folder that can't be reached at start-up is reported, and
    Frivo uses its own folder meanwhile
  * the folder browser lists folders (not files) and can make one
  * restoring a backup never brings another PC's folders

Usage:  python3 tests/test-storage.py     (run from the repo root)
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


def load(tag, data):
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-st-home-")
    os.environ["VOICE_CONSOLE_DATA"] = data
    ws = tempfile.mkdtemp(prefix=f"frivo-st-{tag}-")
    for name in ("app.py", "voice_pack.py", "cleanup_rules.py", "builtin_ai.py"):
        shutil.copy(os.path.join(ROOT, "app", name), os.path.join(ws, name))
    spec = importlib.util.spec_from_file_location(f"frivo_st_{tag}", os.path.join(ws, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"frivo_st_{tag}"] = mod
    spec.loader.exec_module(mod)
    return mod


data = tempfile.mkdtemp(prefix="frivo-st-data-")
mod = load("a", data)
c = mod.app.test_client()

st = c.get("/api/storage").get_json()
check("four kinds, all in Frivo's folder", [k["id"] for k in st["kinds"]] == ["builtin_ai", "voices", "saved", "audio"]
      and all(k["is_default"] and k["folder"].startswith(data) for k in st["kinds"]), st["kinds"])

# Something of each.
os.makedirs(os.path.join(mod.BUILTIN_AI.root, "models"), exist_ok=True)
open(os.path.join(mod.BUILTIN_AI.root, "models", "m.gguf"), "wb").write(b"x" * 300_000)
os.makedirs(os.path.join(mod.CUSTOM_VOICES_DIR, "custom-amy-abc123"), exist_ok=True)
open(os.path.join(mod.CUSTOM_VOICES_DIR, "custom-amy-abc123", "model.onnx"), "wb").write(b"v" * 1000)
mod.write_custom_voices([{"key": "custom-amy-abc123", "name": "Amy"}])
sid = "a" * 32
os.makedirs(mod.SAVED_DIR, exist_ok=True)
open(os.path.join(mod.SAVED_DIR, sid + ".mp3"), "wb").write(b"ID3")
mod.write_saved([{"id": sid, "file": sid + ".mp3", "text": "hi", "voiced": "hi", "saved_at": 1}])
open(os.path.join(mod.AUDIO_DIR, "r.mp3"), "wb").write(b"ID3")


def wait():
    for _ in range(200):
        job = c.get("/api/storage").get_json()["job"]
        if job.get("state") != "moving":
            return job
        time.sleep(0.05)
    return job


big = tempfile.mkdtemp(prefix="frivo-st-big-")
for kind in ("builtin_ai", "voices", "saved", "audio"):
    old = {"builtin_ai": mod.BUILTIN_AI.root, "voices": mod.CUSTOM_VOICES_DIR, "saved": mod.SAVED_DIR,
           "audio": mod.AUDIO_DIR}[kind]
    res = c.post("/api/storage", json={"kind": kind, "folder": big})
    job = wait()
    sub = mod.STORAGE_BY_ID[kind]["sub"]
    check(f"{kind}: moved", res.status_code == 200 and job["state"] == "done", (res.get_json(), job))
    check(f"{kind}: old copy gone", not os.path.exists(old), old)
    check(f"{kind}: saved as the picked folder", mod.CFG[f"storage_{kind}"] == big, mod.CFG.get(f"storage_{kind}"))
    check(f"{kind}: in a subfolder of it", os.path.isdir(os.path.join(big, sub)))
check("built-in AI files arrived", os.path.getsize(os.path.join(big, "builtin_ai", "models", "m.gguf")) == 300_000)
check("Frivo's paths switched", mod.BUILTIN_AI.root == os.path.join(big, "builtin_ai")
      and mod.SAVED_DIR == os.path.join(big, "saved") and mod.AUDIO_DIR == os.path.join(big, "audio_cache")
      and mod.CUSTOM_VOICES_DIR == os.path.join(big, "voices"))
check("saved replies still list", [i["id"] for i in mod.load_saved()] == [sid])
check("added voices still list", [v["key"] for v in mod.load_custom_voices()] == ["custom-amy-abc123"])
check("saved audio served from the new place", c.get(f"/saved-audio/{sid}.mp3").status_code == 200)
st = c.get("/api/storage").get_json()
check("status shows the new folders and their size", all(not k["is_default"] for k in st["kinds"])
      and next(k for k in st["kinds"] if k["id"] == "builtin_ai")["size"] >= 300_000, st["kinds"])

# Back to Frivo's folder.
res = c.post("/api/storage", json={"kind": "saved", "default": True})
wait()
check("back to Frivo's folder", mod.CFG["storage_saved"] == "" and mod.SAVED_DIR == os.path.join(data, "saved")
      and [i["id"] for i in mod.load_saved()] == [sid], mod.SAVED_DIR)

# A folder that already has Frivo's files: asked first, "use" switches.
other = tempfile.mkdtemp(prefix="frivo-st-other-")
os.makedirs(os.path.join(other, "saved"))
open(os.path.join(other, "saved", "saved.json"), "w").write("[]")
res = c.post("/api/storage", json={"kind": "saved", "folder": other})
check("existing files: asked first", res.status_code == 409 and res.get_json().get("exists"), res.get_json())
check("nothing moved meanwhile", mod.SAVED_DIR == os.path.join(data, "saved"))
res = c.post("/api/storage", json={"kind": "saved", "folder": other, "mode": "use"})
wait()
check("use the files there", mod.SAVED_DIR == os.path.join(other, "saved") and mod.load_saved() == []
      and os.path.exists(os.path.join(data, "saved", "saved.json")), mod.SAVED_DIR)

# Refused.
res = c.post("/api/storage", json={"kind": "saved", "folder": "relative/path"})
check("relative path refused", res.status_code == 400)
res = c.post("/api/storage", json={"kind": "builtin_ai", "folder": os.path.join(big, "builtin_ai", "deeper")})
check("inside the current folder refused", res.status_code == 400, res.get_json())
res = c.post("/api/storage", json={"kind": "nope", "folder": big})
check("unknown kind refused", res.status_code == 400)

# The folder browser.
os.makedirs(os.path.join(big, "Zed"))
open(os.path.join(big, "file.txt"), "w").write("x")
b = c.get(f"/api/storage/browse?path={big}").get_json()
check("browser lists folders, not files", "Zed" in b["folders"] and "file.txt" not in b["folders"] and b["writable"], b)
res = c.post("/api/storage/mkdir", json={"path": big, "name": "New one"})
check("make a folder", res.status_code == 200 and os.path.isdir(os.path.join(big, "New one")))
res = c.post("/api/storage/mkdir", json={"path": big, "name": "../escape"})
check("odd names refused", res.status_code == 400)

# Backups keep this PC's folders.
check("restores keep this PC's folders", {"storage_builtin_ai", "storage_saved"} <= mod.BACKUP_KEEP_HERE)

# A picked folder that isn't there at start-up.
mod.CFG["storage_audio"] = os.path.join(tempfile.gettempdir(), "frivo-not-plugged-in-xyz")
mod.save_config(mod.CFG)
mod2 = load("b", data)
st = mod2.app.test_client().get("/api/storage").get_json()
audio = next(k for k in st["kinds"] if k["id"] == "audio")
check("unreachable folder reported", "can't be reached" in audio["problem"], audio)
check("and Frivo's folder used meanwhile", mod2.AUDIO_DIR == os.path.join(data, "audio_cache"), mod2.AUDIO_DIR)
check("the choice is kept for when it's back", mod2.CFG["storage_audio"].endswith("frivo-not-plugged-in-xyz"))

print()
print("FAILED: %d" % len(failures) if failures else "All passed.")
sys.exit(1 if failures else 0)
