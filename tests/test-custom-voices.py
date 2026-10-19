#!/usr/bin/env python3
"""NEW (1.5.0): adding your own voices.

With real Piper voices (downloaded from GitHub for the test, once; skipped
without a network), this checks:

  * a plain Piper voice (.onnx + .onnx.json) is converted, tried, kept and
    listed under "added by you", and speaks a reply
  * the same voice in an archive (.tar.gz, .zip) works too, and a voice
    already in the speech library's form (model + tokens.txt) is kept as is
  * a program (.exe), a file that isn't a voice, and an .onnx without its
    .onnx.json are turned away with a reason, and nothing is kept
  * rename and remove; a removed voice says so if a profile still uses it
  * a voice speaks its own language: replying in another one says so

Usage:  python3 tests/test-custom-voices.py     (run from the repo root)
Needs:  flask, openai (import only), sherpa-onnx, and the internet once.
"""

import importlib.util
import io
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
CACHE = os.path.join(tempfile.gettempdir(), "frivo-test-piper-voice")
VOICE_URL = "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-amy-low.tar.gz"
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


try:
    import sherpa_onnx  # noqa: F401
except Exception:
    print("sherpa-onnx isn't installed here; skipping.")
    sys.exit(0)

os.makedirs(CACHE, exist_ok=True)
archive = os.path.join(CACHE, "amy.tar.gz")
if not os.path.isfile(archive):
    try:
        urllib.request.urlretrieve(VOICE_URL, archive + ".part")
        os.replace(archive + ".part", archive)
    except Exception as e:
        print(f"Couldn't download a test voice ({e}); skipping.")
        sys.exit(0)
with tarfile.open(archive) as t:
    t.extractall(CACHE, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(CACHE)
ONNX = os.path.join(CACHE, "en-us-amy-low.onnx")
JSON = ONNX + ".json"

# Frivo's pronunciation data, from wherever this machine has a copy.
espeak = None
for candidate in [os.path.join(APP, "voices", "piper", "espeak-ng-data")] + [
        os.path.join(p, "espeakng_loader", "espeak-ng-data") for p in sys.path if p]:
    if os.path.isfile(os.path.join(candidate, "phonindex")):
        espeak = candidate
        break
if not espeak:
    print("No eSpeak pronunciation data on this machine; skipping.")
    sys.exit(0)

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-custom-home-")
ws = tempfile.mkdtemp(prefix="frivo-custom-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
shutil.copy(os.path.join(APP, "voice_pack.py"), os.path.join(ws, "voice_pack.py"))
spec = importlib.util.spec_from_file_location("frivo_custom", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_custom"] = mod
spec.loader.exec_module(mod)
piper = tempfile.mkdtemp(prefix="frivo-custom-piper-")
shutil.copytree(espeak, os.path.join(piper, "espeak-ng-data"))
open(os.path.join(piper, "espeak-ng-data", ".frivo-complete"), "w").write("test")
mod.PIPER_DIR = piper
client = mod.app.test_client()


def upload(files, name=""):
    data = {"files": [(io.BytesIO(open(p, "rb").read()) if isinstance(p, str) else p[0], os.path.basename(p) if isinstance(p, str) else p[1]) for p in files]}
    if name:
        data["name"] = name
    res = client.post("/api/voices/custom", data=data, content_type="multipart/form-data")
    return res.status_code, res.get_json() or {}


def listed():
    return [e for e in mod.piper_voice_entries() if e.get("custom")]


print("--- a plain Piper voice ---")
status, data = upload([ONNX, JSON])
check("added", status == 200 and data.get("voice_id", "").startswith("piper:custom-amy-"), (status, data))
voice_id = data.get("voice_id", "")
entries = listed()
check("listed under 'added by you', in English", len(entries) == 1 and entries[0]["category"] == "added by you"
      and entries[0]["languages"][0]["name"].startswith("English"), entries)
out = os.path.join(tempfile.mkdtemp(), "reply.wav")
mod.piper_speak("Hello there, this is my own voice.", voice_id, out)
check("it speaks a reply", os.path.getsize(out) > 20000, os.path.getsize(out))
check("and its sample plays", client.get("/api/voices/preview?voice_id=" + voice_id).status_code == 200)

print("--- in archives ---")
# A copy with one byte changed counts as a different voice, for the archive checks.
other = os.path.join(CACHE, "other")
os.makedirs(other, exist_ok=True)
OTHER_ONNX = os.path.join(other, "en-us-amy-low.onnx")
blob = bytearray(open(ONNX, "rb").read())
blob[-1] ^= 1   # the last byte of a weight: still a working voice
open(OTHER_ONNX, "wb").write(bytes(blob))
shutil.copy(JSON, OTHER_ONNX + ".json")
tbuf2 = io.BytesIO()
with tarfile.open(fileobj=tbuf2, mode="w:gz") as t2:
    t2.add(OTHER_ONNX, "en-us-amy-low.onnx")
    t2.add(OTHER_ONNX + ".json", "en-us-amy-low.onnx.json")
tbuf2.seek(0)
status, data = upload([(tbuf2, "amy.tar.gz")], name="Amy Two")
check("a .tar.gz works, with the name given", status == 200 and data.get("name") == "Amy Two", (status, data))
zbuf = io.BytesIO()
with zipfile.ZipFile(zbuf, "w") as z:
    z.write(ONNX, "amy/en-us-amy-low.onnx")
    z.write(JSON, "amy/en-us-amy-low.onnx.json")
zbuf.seek(0)
status, data = upload([(zbuf, "amy.zip")], name="Amy Zip")
check("a .zip is unpacked (and recognised as the voice already added)", status == 400 and "already added" in data.get("error", ""), (status, data))
status, data = upload([archive])
check("the same voice again is recognised, not copied", status == 400 and "already added" in data.get("error", ""), (status, data))
made = os.path.join(mod.CUSTOM_VOICES_DIR, voice_id[len("piper:"):])
tbuf = io.BytesIO()
with tarfile.open(fileobj=tbuf, mode="w:bz2") as t:
    t.add(os.path.join(made, "model.onnx"), "vits-piper-en_US-amy-low/en_US-amy-low.onnx")
    t.add(os.path.join(made, "tokens.txt"), "vits-piper-en_US-amy-low/tokens.txt")
tbuf.seek(0)
status, data = upload([(tbuf, "vits-piper-en_US-amy-low.tar.bz2")])
check("a sherpa-onnx archive is kept as it is", status == 200 and data.get("name") == "Amy", (status, data))
check("three voices now", len(listed()) == 3, [e["name"] for e in listed()])

print("--- turned away ---")
before = sorted(os.listdir(mod.CUSTOM_VOICES_DIR))
status, data = upload([(io.BytesIO(b"MZ\\x90\\x00 not a voice"), "voice.exe")])
check("a program: refused, with a reason", status == 400 and "program" in data.get("error", "").lower(), data)
status, data = upload([(io.BytesIO(b"garbage" * 1000), "broken.onnx"), (io.BytesIO(open(JSON, "rb").read()), "broken.onnx.json")])
check("a broken model: refused", status == 400 and "isn't a voice" in data.get("error", ""), data)
status, data = upload([ONNX])
check("an .onnx without its .onnx.json: says so", status == 400 and ".onnx.json" in data.get("error", ""), data)
check("nothing left behind", sorted(os.listdir(mod.CUSTOM_VOICES_DIR)) == before,
      sorted(set(os.listdir(mod.CUSTOM_VOICES_DIR)) ^ set(before)))

print("--- rename, language, remove ---")
key = voice_id[len("piper:"):]
res = client.patch(f"/api/voices/custom/{key}", json={"name": "My Amy"})
check("renamed", res.status_code == 200 and any(e["name"] == "My Amy" for e in listed()))
check("speaks its own language only", mod.piper_problem(voice_id, "German") and "speaks English" in mod.piper_problem(voice_id, "German"))
check("and English is fine", mod.piper_problem(voice_id, "English") is None)
res = client.delete(f"/api/voices/custom/{key}")
check("removed, with its files", res.status_code == 200 and not os.path.exists(made) and len(listed()) == 2)
check("a profile still using it is told", "removed" in (mod.piper_problem(voice_id, "English") or ""))
check("removing it again: not found", client.delete(f"/api/voices/custom/{key}").status_code == 404)
check("a made-up key: not found", client.delete("/api/voices/custom/..%2F..%2Fconfig").status_code == 404)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("All custom-voice checks passed.")
