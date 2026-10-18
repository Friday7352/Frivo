#!/usr/bin/env python3
"""CHANGED (1.5.0): the free voices are the ones built into Windows.

Kokoro (an AI voice model) has been removed: AI voices are what ElevenLabs
is for. The free voices are Windows' own, spoken by app\\windows_speech.ps1,
which Frivo starts once and keeps running. Here a stand-in helper
answers the same way, so this runs anywhere:

  * the voice id decides the engine: "windows:" and "onecore:" are free,
    "kokoro:" is a removed voice, anything else is ElevenLabs
  * the voices are listed through the helper; a voice Windows has in both
    kinds is listed once (the newer kind), unless the older one is in use
  * /api/voices lists them with or without an ElevenLabs key
  * speaking needs no ElevenLabs key, costs no credits, passes the speed on,
    and sends non-English text as plain ASCII escapes
  * one helper serves every reply; one that stops is started again, and
    one that hangs is replaced
  * a voice the helper can't find comes back as a clear error
  * a long reply gets exact chatbox page times from a Windows voice
  * anything set to a Kokoro voice is moved to a Windows voice of the same
    gender, and the downloaded Kokoro model is deleted
  * the preview of a free voice is made once, in its own language, and kept

Usage:  python3 tests/test-free-voices.py     (run from the repo root)
Needs:  flask, openai (import only).
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


# Frivo keeps its data under %APPDATA% (or ~). Point that at a scratch folder.
home = tempfile.mkdtemp(prefix="frivo-voices-home-")
os.environ["APPDATA"] = home
ws = tempfile.mkdtemp(prefix="frivo-voices-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_voices", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_voices"] = mod
spec.loader.exec_module(mod)
client = mod.app.test_client()
check("data folder is a scratch one", mod.DATA_DIR.startswith((home, tempfile.gettempdir())), mod.DATA_DIR)

# --- a stand-in for windows_speech.ps1 ---------------------------------------
# Same protocol: one JSON request per line in, one "@@FRIVO {...}" line out.
# It logs every request to a file, so the test can see what Frivo sent.
log_path = os.path.join(ws, "helper-log.jsonl")
FAKE = r'''
import json, os, sys, time, wave
LOG = sys.argv[1]
VOICES = [
    {"kind": "sapi", "id": "Microsoft David Desktop", "name": "Microsoft David Desktop", "gender": "Male", "culture": "en-US", "language": "English (United States)"},
    {"kind": "sapi", "id": "Microsoft Zira Desktop", "name": "Microsoft Zira Desktop", "gender": "Female", "culture": "en-US", "language": "English (United States)"},
    {"kind": "sapi", "id": "Microsoft Hazel Desktop", "name": "Microsoft Hazel Desktop", "gender": "Female", "culture": "en-GB", "language": "English (United Kingdom)"},
    {"kind": "onecore", "id": "MSTTS_V110_enUS_DavidM", "name": "Microsoft David", "gender": "Male", "culture": "en-US", "language": "English (United States)"},
    {"kind": "onecore", "id": "MSTTS_V110_enUS_ZiraM", "name": "Microsoft Zira", "gender": "Female", "culture": "en-US", "language": "English (United States)"},
    {"kind": "onecore", "id": "MSTTS_V110_enUS_MarkM", "name": "Microsoft Mark", "gender": "Male", "culture": "en-US", "language": "English (United States)"},
    {"kind": "onecore", "id": "MSTTS_V110_deDE_KatjaM", "name": "Microsoft Katja", "gender": "Female", "culture": "de-DE", "language": "German (Germany)"},
]
def answer(obj):
    sys.stdout.write("@@FRIVO " + json.dumps(obj) + "\n"); sys.stdout.flush()
sys.stdout.write("some unrelated PowerShell output\n"); sys.stdout.flush()
for raw in sys.stdin.buffer:
    line = raw.decode("utf-8")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"pid": os.getpid(), "ascii": all(ord(c) < 128 for c in line), "req": json.loads(line)}) + "\n")
    req = json.loads(line)
    if req["op"] == "ping":
        answer({"ok": True})
    elif req["op"] == "list":
        answer({"ok": True, "voices": VOICES, "onecore_error": ""})
    elif req["op"] == "speak":
        if req["voice"] not in [v["id"] for v in VOICES]:
            answer({"ok": False, "error": "That Windows voice isn't installed anymore: " + req["voice"]}); continue
        text = " ".join(req["pages"])
        if "please die" in text:
            sys.exit(3)
        if "please hang" in text:
            time.sleep(30)
        for page, out in zip(req["pages"], req["outs"]):
            with wave.open(out, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b"\0\0" * (160 * len(page)))   # 10 ms per character
        answer({"ok": True})
'''
fake_path = os.path.join(ws, "fake_helper.py")
with open(fake_path, "w", encoding="utf-8") as f:
    f.write(FAKE)

mod.WINDOWS_SPEECH = mod.WindowsSpeechHost(command=[sys.executable, fake_path, log_path])
mod.windows_voices_available = lambda: True


def helper_log():
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def setup(voice, eleven_key="", style="mimic", speed=1.0):
    mod.CFG.update(openai_api_key="", elevenlabs_api_key=eleven_key, response_style=style,
                   follow_length=False, voice_id=voice, voice_name="", speaking_speed=speed)


def say(text, language="English"):
    res = client.post("/api/chat", json={"message": text, "language": language, "session_id": "v",
                                         "max_words": 400})
    return res.status_code, (res.get_json() or {})


print("--- which engine ---")
check("windows: is free", mod.tts_engine("windows:Microsoft Zira Desktop") == "windows")
check("onecore: is free", mod.tts_engine("onecore:MSTTS_V110_enUS_ZiraM") == "windows")
check("kokoro: is a removed voice", mod.tts_engine("kokoro:af_heart") == "retired")
check("anything else is ElevenLabs", mod.tts_engine("21m00Tcm4TlvDq8ikWAM") == "elevenlabs")
check("Kokoro's code is gone", not any(hasattr(mod, n) for n in ("KOKORO_FILES", "kokoro_engine", "kokoro_status")))

print("--- listing ---")
mod.CFG["voice_id"] = "21m00Tcm4TlvDq8ikWAM"
entries = mod.windows_voice_entries()
ids = [e["voice_id"] for e in entries]
check("the newer voices are listed",
      {"onecore:MSTTS_V110_enUS_DavidM", "onecore:MSTTS_V110_enUS_ZiraM", "onecore:MSTTS_V110_enUS_MarkM"} <= set(ids), ids)
check("a desktop voice with a newer copy isn't listed twice",
      "windows:Microsoft David Desktop" not in ids and "windows:Microsoft Zira Desktop" not in ids, ids)
check("a desktop voice with no newer copy is listed", "windows:Microsoft Hazel Desktop" in ids, ids)
mark = next(e for e in entries if e["voice_id"].endswith("MarkM"))
check("names are short", mark["name"] == "Mark", mark["name"])
check("language and region", mark["languages"] == [{"code": "en", "name": "English · United States"}], mark["languages"])
check("preview address is encoded", mark["preview_url"] == "/api/voices/preview?voice_id=onecore%3AMSTTS_V110_enUS_MarkM",
      mark["preview_url"])
mod.CFG["voice_id"] = "windows:Microsoft Zira Desktop"
mod.WINDOWS_VOICES_CACHE["at"] = 0
check("an older voice that's in use stays listed",
      "windows:Microsoft Zira Desktop" in [e["voice_id"] for e in mod.windows_voice_entries()])
check("one helper answered all of that", len({r["pid"] for r in helper_log()}) == 1, helper_log())

data = client.get("/api/voices").get_json()
check("/api/voices lists them with no ElevenLabs key",
      any(v["voice_id"].startswith("onecore:") for v in data.get("voices", [])), data)
free = client.get("/api/voices/free").get_json()
check("/api/voices/free reports them", free["windows"]["available"] and free["windows"]["newer"] == 4, free)
check("the Kokoro download route is gone", client.post("/api/voices/free/download").status_code in (404, 405))

print("--- speaking ---")
open(log_path, "w").close()
setup("onecore:MSTTS_V110_enUS_ZiraM", speed=1.2)
status, data = say("Hello there, this is a test.")
check("speaks with no ElevenLabs key", status == 200 and data.get("audio_url"), (status, data.get("error")))
check("costs no credits", data.get("credits") == 0 and data.get("voice_engine") == "windows", data.get("credits"))
check("the audio file exists",
      os.path.isfile(os.path.join(mod.AUDIO_DIR, (data.get("audio_url") or "/x").split("/")[-1])))
speak = [r["req"] for r in helper_log() if r["req"]["op"] == "speak"][-1]
check("the newer kind and its id are sent", speak["kind"] == "onecore" and speak["voice"] == "MSTTS_V110_enUS_ZiraM", speak)
check("the speed is sent both ways", speak["speed"] == 1.2 and speak["sapi_rate"] == 2, speak)

setup("windows:Microsoft Hazel Desktop")
status, data = say("Ünïcödé café, naïve.")
last = helper_log()[-1]
check("a desktop voice speaks", status == 200 and last["req"]["kind"] == "sapi", (status, data.get("error")))
check("non-English text is sent as ASCII and arrives intact",
      last["ascii"] and last["req"]["pages"] == ["Ünïcödé café, naïve."], last)

setup("onecore:MSTTS_V110_enUS_GoneM")
status, data = say("Hello.")
check("a missing voice is a clear error", status == 500 and "isn't installed anymore" in (data.get("error") or ""), data)

long_text = ("Okay so here is the thing about the backrooms world. The lights hum all the time, "
             "and if you stand still long enough you start to hear footsteps that are not yours. "
             "Honestly, I think that's the best part. Come by tonight and I'll show you around.")
setup("onecore:MSTTS_V110_enUS_MarkM")
status, data = say(long_text)
pages = data.get("chatbox_pages") or []
bodies = [mod._CHATBOX_COUNTER_RE.sub("", p["text"]) for p in pages]
want = [0.0]
for b in bodies[:-1]:
    want.append(round(want[-1] + len(b) * 0.01, 3))
check("a long reply gets exact page times", len(pages) > 1 and [p.get("at") for p in pages] == want,
      ([p.get("at") for p in pages], want))
check("page parts are cleaned up", not [n for n in os.listdir(mod.AUDIO_DIR) if ".part." in n],
      os.listdir(mod.AUDIO_DIR))

print("--- the helper ---")
pids = {r["pid"] for r in helper_log()}
check("every reply used the same helper", len(pids) == 1, pids)
setup("onecore:MSTTS_V110_enUS_MarkM")
before = {r["pid"] for r in helper_log()}
status, data = say("please die")
# The stand-in dies on this text, so the retry with a fresh helper dies too.
died = {r["pid"] for r in helper_log()} - before
check("a helper that stops is started again once for the same reply", status == 500 and len(died) == 1,
      (status, died))
status, data = say("Back again.")
check("the next reply works with a new helper",
      status == 200 and helper_log()[-1]["pid"] not in before | died, (status, data.get("error")))
t0 = time.time()
try:
    mod.WINDOWS_SPEECH.request({"op": "speak", "kind": "onecore", "voice": "MSTTS_V110_enUS_MarkM", "speed": 1,
                                "sapi_rate": 0, "pages": ["please hang"], "outs": [os.path.join(ws, "h.wav")]},
                               timeout=1)
    hung = False
except RuntimeError as e:
    hung = "too long" in str(e)
check("a helper that hangs times out", hung and time.time() - t0 < 10, time.time() - t0)
hung_pid = helper_log()[-1]["pid"]
status, data = say("And again.")
check("and is replaced", status == 200 and helper_log()[-1]["pid"] != hung_pid, (status, data.get("error")))
mod.WINDOWS_SPEECH.close()
check("close stops it", mod.WINDOWS_SPEECH.proc is None)

print("--- Kokoro, removed ---")
setup("kokoro:af_heart")
status, data = say("Hello.")
check("a Kokoro voice isn't sent to ElevenLabs", status == 400 and "removed" in (data.get("error") or ""), data)
mod.save_profiles([{"id": "p1", "name": "DJ", "voice_id": "kokoro:bm_george", "voice_name": "George"},
                   {"id": "p2", "name": "Eleven", "voice_id": "21m00Tcm4TlvDq8ikWAM", "voice_name": "Rachel"}])
kokoro_dir = os.path.join(mod.DATA_DIR, "voices", "kokoro")
os.makedirs(kokoro_dir, exist_ok=True)
with open(os.path.join(kokoro_dir, "kokoro-v1.0.fp16.onnx"), "wb") as f:
    f.write(b"x" * 1000)
mod.warm_free_voices()
check("the default voice moves to a Windows voice of the same gender",
      mod.CFG["voice_id"] == "onecore:MSTTS_V110_enUS_ZiraM" and mod.CFG["voice_name"] == "Zira", mod.CFG["voice_id"])
profiles = {p["id"]: p for p in mod.load_profiles()}
check("so does a profile, male to male",
      profiles["p1"]["voice_id"] in ("onecore:MSTTS_V110_enUS_DavidM", "onecore:MSTTS_V110_enUS_MarkM")
      and profiles["p1"]["voice_name"] in ("David", "Mark"), profiles["p1"])
check("other profiles are left alone", profiles["p2"]["voice_id"] == "21m00Tcm4TlvDq8ikWAM")
check("the Kokoro model is deleted", not os.path.exists(os.path.join(mod.DATA_DIR, "voices")))

print("--- previews ---")
open(log_path, "w").close()
for _ in range(2):
    res = client.get("/api/voices/preview?voice_id=onecore%3AMSTTS_V110_deDE_KatjaM")
check("a preview plays", res.status_code == 200)
speaks = [r["req"] for r in helper_log() if r["req"]["op"] == "speak"]
check("it's made once and kept", len(speaks) == 1, len(speaks))
check("in the voice's own language", speaks and speaks[0]["pages"] == [mod.FREE_SAMPLE_LINES["de"]], speaks)
check("an ElevenLabs voice has no free preview",
      client.get("/api/voices/preview?voice_id=21m00Tcm4TlvDq8ikWAM").status_code == 400)

print("--- not on Windows ---")
mod.windows_voices_available = lambda: False
setup("onecore:MSTTS_V110_enUS_ZiraM")
status, data = say("Hello.")
check("says Windows voices need Windows", status == 400 and "Windows" in (data.get("error") or ""), data)
check("and lists none", mod.list_windows_voices(force=True) == [])
mod.WINDOWS_SPEECH.close()

print()
if failures:
    print(f"{len(failures)} failed: " + ", ".join(failures))
    sys.exit(1)
print("All free-voice checks passed.")
