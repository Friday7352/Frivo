#!/usr/bin/env python3
"""NEW (1.5.0): the free voice library.

Hugging Face is stood in for, so this runs offline:

  * the library's voices.json is listed (language, quality, size), sorted,
    kept for a day and used from disk when Hugging Face can't be reached
  * voices included with Frivo and ones already added are marked, with
    their voice ids
  * a sample is fetched once and then served from Frivo's copy; a missing
    sample says so
  * the licence is read from the MODEL_CARD
  * a download is checked against the library's checksums, goes through
    "Add a voice" with a friendly name, and is marked with its library key;
    a wrong checksum, a full drive and an unknown voice are refused
  * a download can be cancelled

Usage:  python3 tests/test-voice-library.py     (run from the repo root)
"""

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-vlib-home-")
os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-vlib-data-")
ws = tempfile.mkdtemp(prefix="frivo-vlib-")
shutil.copy(os.path.join(ROOT, "app", "app.py"), os.path.join(ws, "app.py"))
shutil.copy(os.path.join(ROOT, "app", "voice_pack.py"), os.path.join(ws, "voice_pack.py"))
spec = importlib.util.spec_from_file_location("frivo_vlib", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_vlib"] = mod
spec.loader.exec_module(mod)

MODEL = b"onnx-model-bytes" * 4000
CONFIG = json.dumps({"language": {"code": "en_US"}, "phoneme_id_map": {"a": [1]}}).encode()
CARD = b"# Model card for amy (medium)\n\n* Language: en_US\n* License: CC BY-NC-SA 4.0\n* Dataset: https://example.org/amy\n"
md5 = lambda b: hashlib.md5(b).hexdigest()


def entry(lang, country, region, name, quality, model=MODEL, config=CONFIG, wrong_md5=False):
    base = f"{lang}/{lang}_{region}/{name}/{quality}/{lang}_{region}-{name}-{quality}"
    return {"key": f"{lang}_{region}-{name}-{quality}", "name": name, "quality": quality, "num_speakers": 1,
            "language": {"code": f"{lang}_{region}", "family": lang, "region": region,
                         "name_native": "English" if lang == "en" else "Deutsch",
                         "name_english": "English" if lang == "en" else "German", "country_english": country},
            "files": {base + ".onnx": {"size_bytes": len(model), "md5_digest": "0" * 32 if wrong_md5 else md5(model)},
                      base + ".onnx.json": {"size_bytes": len(config), "md5_digest": md5(config)},
                      os.path.dirname(base) + "/MODEL_CARD": {"size_bytes": len(CARD), "md5_digest": md5(CARD)}},
            "aliases": []}


CATALOG = {e["key"]: e for e in [
    entry("en", "United States", "US", "amy", "medium"),
    entry("en", "United States", "US", "amy", "low"),
    entry("en", "United States", "US", "kristin", "medium"),
    entry("en", "United States", "US", "broken", "medium", wrong_md5=True),
    entry("de", "Germany", "DE", "thorsten", "high"),
]}
SAMPLE = b"ID3fake-mp3"
calls = {"voices.json": 0, "sample": 0, "online": True}


class Resp:
    def __init__(self, status, body=b"", js=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.content = body
        self.text = body.decode("utf-8", "replace")
        self._js = js

    def json(self):
        return self._js if self._js is not None else json.loads(self.content)

    def raise_for_status(self):
        if not self.ok:
            raise mod.requests.HTTPError(f"{self.status_code}")

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            if calls.get("slow"):
                time.sleep(0.5)
            yield self.content[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_get(url, **kw):
    if not calls["online"]:
        raise mod.requests.ConnectionError("offline")
    rel = url[len(mod.VOICE_LIB_URL):]
    if rel == "voices.json":
        calls["voices.json"] += 1
        return Resp(200, json.dumps(CATALOG).encode())
    if rel.endswith("/samples/speaker_0.mp3"):
        calls["sample"] += 1
        return Resp(404) if "thorsten" in rel else Resp(200, SAMPLE)
    if rel.endswith("MODEL_CARD"):
        return Resp(200, CARD)
    if rel.endswith(".onnx"):
        return Resp(200, MODEL)
    if rel.endswith(".onnx.json"):
        return Resp(200, CONFIG)
    return Resp(404)


mod.requests.get = fake_get

added = []


def fake_add(paths, name=""):
    names = sorted(os.path.basename(p) for p in paths)
    data = {os.path.basename(p): open(p, "rb").read() for p in paths}
    added.append({"names": names, "name": name, "model_ok": any(v == MODEL for v in data.values())})
    with mod.CUSTOM_VOICES_LOCK:
        items = mod.load_custom_voices()
        key = f"custom-{name.lower().split()[0]}-{len(added):06x}"
        voice = {"key": key, "name": name, "source": [n for n in names if n.endswith(".onnx")][0], "sha256": "x"}
        items.append(voice)
        mod.write_custom_voices(items)
    return voice


mod.add_custom_voice = fake_add
mod.piper_package_problem = lambda: None
# Kristin is one of the voices included with Frivo.
if mod.VOICE_PACK is None:
    class _VP:
        VOICES = [{"key": "kristin", "model": "en_US-kristin-medium.onnx"}]
        VOICES_BY_KEY = {}
    mod.VOICE_PACK = _VP()

c = mod.app.test_client()

# --- the list ----------------------------------------------------------------
res = c.get("/api/voices/library")
data = res.get_json()
keys = [v["key"] for v in data["voices"]]
check("library listed", res.status_code == 200 and len(keys) == 5, keys)
check("sorted by language then name then quality",
      keys[:2] == ["en_US-amy-low", "en_US-amy-medium"] and keys[-1] == "de_DE-thorsten-high" or keys[0] == "en_US-amy-low", keys)
amy = next(v for v in data["voices"] if v["key"] == "en_US-amy-medium")
check("size is the model plus its config", amy["size"] == len(MODEL) + len(CONFIG), amy["size"])
check("language and country", amy["language"] == "English" and amy["country"] == "United States", amy)
kristin = next(v for v in data["voices"] if v["key"] == "en_US-kristin-medium")
check("voices included with Frivo are marked", kristin["included"] and kristin["voice_id"] == "piper:kristin", kristin)
check("drive space reported", data["disk"].get("free", 0) > 0 and data["disk"].get("total", 0) > 0, data["disk"])
c.get("/api/voices/library")
check("list kept, not fetched again", calls["voices.json"] == 1, calls)
mod.VOICE_LIB_STATE.update(data=None, at=0)
calls["online"] = False
res = c.get("/api/voices/library?refresh=1")
check("saved copy used when offline", res.status_code == 200 and len(res.get_json()["voices"]) == 5)
calls["online"] = True

# --- samples and licence -------------------------------------------------------
res = c.get("/api/voices/library/sample/en_US-amy-medium")
check("sample served", res.status_code == 200 and res.data == SAMPLE and res.mimetype == "audio/mpeg", res.status_code)
res.close()
c.get("/api/voices/library/sample/en_US-amy-medium").close()
check("sample fetched once", calls["sample"] == 1, calls)
res = c.get("/api/voices/library/sample/de_DE-thorsten-high")
check("missing sample says so", res.status_code == 404 and "no sample" in res.get_json()["error"])
check("unknown voice refused", c.get("/api/voices/library/sample/xx_XX-nope-medium").status_code == 404)
check("odd key refused", c.get("/api/voices/library/sample/..%2F..%2Fconfig").status_code == 404)
card = c.get("/api/voices/library/card/en_US-amy-medium").get_json()
check("licence read from the card", card["license"] == "CC BY-NC-SA 4.0", card)


def wait(key, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = c.get("/api/voices/library/install").get_json()["jobs"].get(key, {})
        if job.get("state") not in ("downloading", "adding"):
            return job
        time.sleep(0.05)
    return job


# --- downloading -------------------------------------------------------------
res = c.post("/api/voices/library/install", json={"key": "en_US-amy-medium"})
check("download started", res.status_code == 200, res.get_json())
job = wait("en_US-amy-medium")
check("download finished", job.get("state") == "done" and job.get("voice_id", "").startswith("piper:custom-"), job)
check("went through Add a voice with both files",
      added and added[-1]["names"] == ["en_US-amy-medium.onnx", "en_US-amy-medium.onnx.json"] and added[-1]["model_ok"], added)
check("friendly name", added[-1]["name"] == "Amy", added[-1]["name"])
voice = mod.load_custom_voices()[-1]
check("marked with its library key", voice.get("library_key") == "en_US-amy-medium", voice)
listed = next(v for v in c.get("/api/voices/library").get_json()["voices"] if v["key"] == "en_US-amy-medium")
check("listed as added, with its voice id", listed["voice_id"] == job["voice_id"], listed)

c.post("/api/voices/library/install", json={"key": "en_US-amy-low"})
wait("en_US-amy-low")
check("other qualities named so", added[-1]["name"] == "Amy (low)", added[-1]["name"])

before = len(added)
c.post("/api/voices/library/install", json={"key": "en_US-broken-medium"})
job = wait("en_US-broken-medium")
check("wrong checksum refused", job.get("state") == "error" and "checksum" in job.get("error", ""), job)
check("nothing added for it", len(added) == before)
leftover = [n for n in os.listdir(mod.CUSTOM_VOICES_DIR) if n.startswith(".library-")]
check("download folder cleaned up", not leftover, leftover)

res = c.post("/api/voices/library/install", json={"key": "en_US-nobody-medium"})
check("unknown voice refused", res.status_code == 404)

real_usage = mod.shutil.disk_usage
Usage = namedtuple("Usage", "total used free")
mod.shutil.disk_usage = lambda p: Usage(10 ** 9, 10 ** 9, 1000)
res = c.post("/api/voices/library/install", json={"key": "de_DE-thorsten-high"})
check("full drive refused", res.status_code == 400 and "room" in res.get_json()["error"], res.get_json())
mod.shutil.disk_usage = real_usage

# --- cancel --------------------------------------------------------------------
calls["slow"] = True
c.post("/api/voices/library/install", json={"key": "de_DE-thorsten-high"})
time.sleep(0.15)
c.delete("/api/voices/library/install/de_DE-thorsten-high")
job = wait("de_DE-thorsten-high")
check("download cancelled", job.get("state") == "cancelled", job)
calls["slow"] = False
c.delete("/api/voices/library/install/de_DE-thorsten-high")
check("cancelled one forgotten", "de_DE-thorsten-high" not in c.get("/api/voices/library/install").get_json()["jobs"])

print()
print("FAILED: %d" % len(failures) if failures else "All passed.")
sys.exit(1 if failures else 0)
