#!/usr/bin/env python3
"""NEW (1.5.0): the free voices included with Frivo (Piper).

Setup downloads them once with app/voice_pack.py, and Frivo speaks them with
sherpa-onnx on one CPU thread. This checks:

  voice_pack.py, against a stand-in download server:
  * only voices that may be shared are listed, each with a size and SHA-256
  * a download that doesn't match is thrown away and tried again
  * nothing in an archive can be written outside the voices folder
  * the pronunciation data is unpacked once and shared
  * "check" says what's there; a damaged model is found and replaced;
    voices that are fine aren't downloaded again
  * one voice that can't be had doesn't stop the others

  Frivo, with the real voices (if app/voices holds them and sherpa-onnx is
  installed; run "python app/voice_pack.py install" once to get them):
  * they're listed first, as free, and speak with no key and no credits
  * one CPU thread, at most two voices loaded
  * the speed is honoured; another language gets a clear message
  * a long reply gets exact chatbox page times
  * a missing voice says to run Repair
  * a removed Kokoro voice moves to a Frivo voice of the same gender
  * previews are made once

Usage:  python3 tests/test-frivo-voices.py     (run from the repo root)
Needs:  flask, openai (import only); sherpa-onnx for the second half.
"""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


print("--- voice_pack.py ---")
vp = load(os.path.join(APP, "voice_pack.py"), "frivo_vp_test")
keys = [v["key"] for v in vp.VOICES]
check("six voices", keys == ["kristin", "cori", "alba", "john", "joe", "norman"], keys)
check("none with a non-commercial license", not any(k in keys for k in ("ryan", "lessac", "hfc_female", "hfc_male", "amy")))
check("every one has sizes and SHA-256s", all(v["archive_size"] > 0 and len(v["archive_sha256"]) == 64
                                              and len(v["model_sha256"]) == 64 for v in vp.VOICES))
check("three female, three male", sorted(v["gender"] for v in vp.VOICES) == ["female"] * 3 + ["male"] * 3)


def make_archive(voice, model_bytes, extra=()):
    """A small archive laid out like sherpa-onnx's, for the stand-in server."""
    top = voice["archive"][:-len(".tar.bz2")]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        def add(name, data):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        add(f"{top}/{voice['model']}", model_bytes)
        add(f"{top}/tokens.txt", b"_ 0\n")
        add(f"{top}/MODEL_CARD", b"card")
        add(f"{top}/{voice['model']}.json", b"{}")
        add(f"{top}/espeak-ng-data/phontab", b"phonemes")
        add(f"{top}/espeak-ng-data/voices/!v/Mr serious", b"variant")
        for name, data in extra:
            add(name, data)
    return buf.getvalue()


# Small stand-in voices: the manifest is pointed at them.
served = {}
for v in vp.VOICES:
    model = (v["key"] * 1000).encode()
    extra = [(f"{v['archive'][:-8]}/../../escaped.txt", b"nope"), ("/etc/evil", b"nope")] if v["key"] == "cori" else ()
    blob = make_archive(v, model, extra)
    v.update(archive_size=len(blob), archive_sha256=hashlib.sha256(blob).hexdigest(),
             model_size=len(model), model_sha256=hashlib.sha256(model).hexdigest())
    served[v["archive"]] = blob

requests_seen, tamper = [], {"once": set(), "always": set()}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(request, timeout=None):
    name = request.full_url.rsplit("/", 1)[-1]
    requests_seen.append(name)
    data = served[name]
    if name in tamper["always"] or name in tamper["once"]:
        tamper["once"].discard(name)
        data = data[:-10]
    return FakeResponse(data)


vp.urllib.request.urlopen = fake_urlopen
vp.time.sleep = lambda s: None
root = tempfile.mkdtemp(prefix="frivo-voicepack-")
voices_dir = os.path.join(root, "voices", "piper")
logs = []
tamper["once"].add(vp.VOICES[0]["archive"])
failed = vp.install(voices_dir, log=logs.append)
check("all six installed", failed == [], failed)
check("a bad download is thrown away and tried again",
      requests_seen.count(vp.VOICES[0]["archive"]) == 2 and any("attempt 1 failed" in m for m in logs), logs[:3])
check("check says ready", vp.main(["check", "--dir", voices_dir]) == 0)
check("nothing escaped the voices folder",
      not os.path.exists(os.path.join(root, "escaped.txt")) and not os.path.exists(os.path.join(voices_dir, "..", "escaped.txt")))
check("pronunciation data unpacked once, shared",
      os.path.isfile(os.path.join(voices_dir, "espeak-ng-data", "voices", "!v", "Mr serious"))
      and not any(os.path.isdir(os.path.join(voices_dir, k, "espeak-ng-data")) for k in keys))
check("each voice has model.onnx and tokens.txt",
      all(os.path.isfile(os.path.join(voices_dir, k, f)) for k in keys for f in ("model.onnx", "tokens.txt")))
check("no temporary files left", not [n for n in os.listdir(voices_dir) if n.startswith(".")], os.listdir(voices_dir))
check("credits written", "CC BY 4.0" in open(os.path.join(voices_dir, "CREDITS.txt"), encoding="utf-8").read())

requests_seen.clear()
check("installed voices aren't downloaded again", vp.install(voices_dir, log=logs.append) == [] and requests_seen == [],
      requests_seen)
with open(os.path.join(voices_dir, "john", "model.onnx"), "r+b") as f:
    f.write(b"X")
check("a damaged model is noticed (deep check)", not vp.voice_ready(vp.VOICES_BY_KEY["john"], voices_dir, deep=True))
vp.install(voices_dir, log=logs.append)
check("and replaced", requests_seen == [vp.VOICES_BY_KEY["john"]["archive"]]
      and vp.voice_ready(vp.VOICES_BY_KEY["john"], voices_dir, deep=True), requests_seen)
shutil.rmtree(os.path.join(voices_dir, "norman"))
tamper["always"].add(vp.VOICES_BY_KEY["norman"]["archive"])
failed = vp.install(voices_dir, log=logs.append)
check("one voice that can't be had doesn't stop the others", failed == ["norman"], failed)
check("check says something's missing", vp.main(["check", "--dir", voices_dir]) == 1)
check("install exits 1 and says Repair", vp.main(["install", "--dir", voices_dir]) == 1)

print("--- Frivo, with the real voices ---")
real_voices = os.path.join(APP, "voices", "piper")
try:
    import sherpa_onnx  # noqa: F401
    have_sherpa = True
except Exception:
    have_sherpa = False
real_vp = load(os.path.join(APP, "voice_pack.py"), "frivo_vp_real")
if not have_sherpa or not all(real_vp.voice_ready(v, real_voices) for v in real_vp.VOICES):
    print("  SKIP  sherpa-onnx or the real voices aren't here (python app/voice_pack.py install)")
else:
    home = tempfile.mkdtemp(prefix="frivo-voices-home-")
    os.environ["APPDATA"] = home
    ws = tempfile.mkdtemp(prefix="frivo-piper-")
    for name in ("app.py", "voice_pack.py"):
        shutil.copy(os.path.join(APP, name), os.path.join(ws, name))
    os.makedirs(os.path.join(ws, "voices"))
    os.symlink(real_voices, os.path.join(ws, "voices", "piper"))
    mod = load(os.path.join(ws, "app.py"), "frivo_piper_app")
    mod.windows_voices_available = lambda: False
    mod.record_usage = lambda credits: None
    client = mod.app.test_client()

    def say(text, voice, language="English", speed=1.0):
        mod.CFG.update(openai_api_key="", elevenlabs_api_key="", response_style="mimic", follow_length=False,
                       voice_id=voice, voice_name="", speaking_speed=speed)
        res = client.post("/api/chat", json={"message": text, "language": language, "max_words": 400})
        return res.status_code, (res.get_json() or {})

    listed = client.get("/api/voices").get_json().get("voices", [])
    ids = [v["voice_id"] for v in listed]
    check("all six listed", [i for i in ids if i.startswith("piper:")] == ["piper:" + k for k in keys], ids)
    check("as free voices included with Frivo", all(v["category"] == "included with Frivo" for v in listed if v["voice_id"].startswith("piper:")))
    status = client.get("/api/voices/free").get_json()["piper"]
    check("status: 6 of 6", status == {"available": True, "problem": "", "count": 6, "total": 6}, status)

    code, data = say("Hello there, this is a test of Frivo's own voices.", "piper:kristin")
    path = os.path.join(mod.AUDIO_DIR, (data.get("audio_url") or "/x").split("/")[-1])
    check("speaks with no key", code == 200 and os.path.isfile(path), (code, data.get("error")))
    check("no credits, the Frivo engine", data.get("credits") == 0 and data.get("voice_engine") == "piper"
          and data.get("voice_engine_name") == "Frivo voice (free)", data)
    with wave.open(path) as w:
        normal = w.getnframes() / w.getframerate()
    check("real audio, about the right length", 2.0 < normal < 6.0, normal)
    check("one CPU thread", mod.PIPER_THREADS == 1)
    # NEW (1.5.0): every voice actually loads and speaks. (The half-size
    # files for John and Joe didn't load, which is why they're full-size.)
    spoke = {}
    for k in keys:
        try:
            parts = mod._piper_generate(mod.piper_voice("piper:" + k), ["Testing, one two three."])
            spoke[k] = len(parts[0][0]) > 10000
        except Exception as e:
            spoke[k] = str(e)[:80]
    check("every voice loads and speaks", all(v is True for v in spoke.values()), spoke)

    # A longer line, so the voice's own small variation doesn't decide it.
    # Pauses don't shrink with the speed, so 1.2x is a little under 1/1.2.
    lengths = {}
    for speed in (1.0, 1.2):
        code, data = say("This is a slightly longer sentence, so the speed of the voice can be measured "
                         "properly, without one short pause deciding the result.", "piper:kristin", speed=speed)
        with wave.open(os.path.join(mod.AUDIO_DIR, data["audio_url"].split("/")[-1])) as w:
            lengths[speed] = w.getnframes() / w.getframerate()
    check("the speed is honoured", lengths[1.2] < lengths[1.0] * 0.93, lengths)

    long_text = ("Okay so here is the thing about the backrooms world. The lights hum all the time, "
                 "and if you stand still long enough you start to hear footsteps that are not yours. "
                 "Honestly, I think that's the best part. Come by tonight and I'll show you around.")
    code, data = say(long_text, "piper:john")
    ats = [p.get("at") for p in data.get("chatbox_pages") or []]
    check("a long reply gets exact page times", code == 200 and len(ats) > 1 and ats[0] == 0.0
          and all(isinstance(a, float) and a > 0 for a in ats[1:]) and ats == sorted(ats), ats)
    say("One more.", "piper:alba")
    check("at most two voices loaded", len(mod.PIPER_ENGINES) == 2 and list(mod.PIPER_ENGINES) == ["john", "alba"],
          list(mod.PIPER_ENGINES))

    # Asked of the voice directly: a reply in another language needs OpenAI
    # to translate it first, which this test doesn't have.
    problem = mod.free_voice_problem("piper:cori", "Spanish")
    check("another language gets a clear message", "speak English" in (problem or ""), problem)
    real_ready = mod.VOICE_PACK.voice_ready
    mod.VOICE_PACK.voice_ready = lambda v, r, deep=False: v["key"] != "joe" and real_ready(v, r, deep)
    code, data = say("Hello.", "piper:joe")
    check("a missing voice says to run Repair", code == 400 and "Repair" in (data.get("error") or ""), data)
    check("and isn't listed", "piper:joe" not in [v["voice_id"] for v in client.get("/api/voices").get_json()["voices"]])
    mod.VOICE_PACK.voice_ready = real_ready

    mod.CFG.update(voice_id="kokoro:bm_george", voice_name="George")
    mod.save_profiles([{"id": "p", "name": "P", "voice_id": "kokoro:af_heart", "voice_name": "Heart"}])
    mod.warm_free_voices()
    check("a removed Kokoro voice moves to a Frivo voice of the same gender",
          mod.CFG["voice_id"] == "piper:john" and mod.load_profiles()[0]["voice_id"] == "piper:kristin",
          (mod.CFG["voice_id"], mod.load_profiles()[0]["voice_id"]))

    first = client.get("/api/voices/preview?voice_id=piper%3Anorman")
    made = [n for n in os.listdir(mod.AUDIO_DIR) if n.startswith("preview-")]
    second = client.get("/api/voices/preview?voice_id=piper%3Anorman")
    check("a preview plays, and is made once", first.status_code == 200 and second.status_code == 200
          and len(made) == 1, made)

print()
if failures:
    print(f"{len(failures)} failed: " + ", ".join(failures))
    sys.exit(1)
print("All Frivo-voice checks passed.")
