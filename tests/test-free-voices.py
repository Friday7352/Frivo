#!/usr/bin/env python3
"""NEW (1.5.0): free voices that run on this PC (Kokoro, Windows voices).

ElevenLabs must work exactly as before; alongside it, choosing a Kokoro or
Windows voice speaks with no ElevenLabs key and costs no credits.

  * the voice id decides the engine ("kokoro:", "windows:", else ElevenLabs)
  * /api/voices lists the free voices with or without an ElevenLabs key, and
    ElevenLabs' too when there is one; ElevenLabs failing doesn't hide them
  * speaking with a free voice needs no ElevenLabs key and records no credits;
    an ElevenLabs voice without a key is still refused, as before
  * Kokoro's model is downloaded once, checked against its size and hash
    (a bad download is thrown away), with progress reported
  * a reply asked for before the download finishes says so and starts it
  * a language Kokoro can't speak is refused with a clear message
  * Windows voices: listed and spoken through PowerShell, with text that
    can't break out of the script, and the speed passed as Windows' rate
  * the preview of a free voice is made once and kept
  * Kokoro installed but unable to load (no Visual C++ runtime) says so

Kokoro and PowerShell are replaced; nothing is downloaded. Set
FRIVO_KOKORO_DIR to a folder holding the real model files to also run one
real Kokoro reply end to end.

Usage:  python3 tests/test-free-voices.py     (run from the repo root)
Needs:  flask, openai (import only), numpy.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import wave
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


ws = tempfile.mkdtemp(prefix="frivo-voices-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_voices", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_voices"] = mod
spec.loader.exec_module(mod)
client = mod.app.test_client()

import numpy as np  # noqa: E402


# --- stand-ins ----------------------------------------------------------------
class FakeKokoro:
    calls = []

    def __init__(self, model, voices):
        self.model = model

    def create(self, text, voice, speed=1.0, lang="en-us"):
        FakeKokoro.calls.append({"text": text, "voice": voice, "speed": speed, "lang": lang})
        return np.zeros(2400, dtype=np.float32), 24000


fake_pkg = SimpleNamespace(Kokoro=FakeKokoro)
sys.modules["kokoro_onnx"] = fake_pkg

kokoro_dir = tempfile.mkdtemp(prefix="frivo-kokoro-")
mod.KOKORO_DIR = kokoro_dir
blobs = {"kokoro-v1.0.fp16.onnx": b"model-bytes" * 100, "voices-v1.0.bin": b"voice-bytes" * 50}
mod.KOKORO_FILES = [{"name": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in blobs.items()]

served = {"tamper": False, "requests": 0}


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.data), 97):
            yield self.data[i:i + 97]


real_get = mod.requests.get


def fake_get(url, stream=False, timeout=None, headers=None):
    if url.startswith(mod.KOKORO_RELEASE):
        served["requests"] += 1
        data = blobs[url[len(mod.KOKORO_RELEASE):]]
        if served["tamper"]:
            data = data[:-1] + b"X"
        return FakeResponse(data)
    if "elevenlabs" in url:
        if served.get("eleven_down"):
            raise RuntimeError("ElevenLabs is down")
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"voices": [{"voice_id": "EL1", "name": "Rachel", "category": "premade"}]})
    return real_get(url, stream=stream, timeout=timeout, headers=headers)


mod.requests.get = fake_get

ps_runs = []


def fake_powershell(script, timeout=60):
    ps_runs.append(script)
    if "GetInstalledVoices" in script:
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
            [{"name": "Microsoft David Desktop", "gender": "Male", "culture": "en-US", "language": "English (United States)"},
             {"name": "Microsoft Zira Desktop", "gender": "Female", "culture": "en-US", "language": "English (United States)"}]))
    # Speak: read the job file the way PowerShell would, and make the wave.
    path = script.split("ReadAllText('", 1)[1].split("'", 1)[0].replace("''", "'")
    job = json.load(open(path, encoding="utf-8"))
    ps_runs.append(job)
    with wave.open(job["out"], "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * 1600)
    return SimpleNamespace(returncode=0, stderr="", stdout="")


mod._run_powershell = fake_powershell
mod.windows_voices_available = lambda: True

eleven_calls = []
mod.requests.post = lambda url, **kw: (eleven_calls.append(url), SimpleNamespace(status_code=200, content=b"mp3", text=""))[1]
usage = []
mod.record_usage = lambda credits: usage.append(credits)


def setup(voice, eleven_key="", style="mimic"):
    mod.CFG.update(openai_api_key="", elevenlabs_api_key=eleven_key, response_style=style,
                   voice_id=voice, speaking_speed=1.0)
    FakeKokoro.calls.clear()
    eleven_calls.clear()
    usage.clear()
    ps_runs.clear()


def say(text, language="English"):
    res = client.post("/api/chat", json={"message": text, "language": language, "session_id": "v"})
    return res.status_code, res.get_json()


def wait_download():
    for _ in range(200):
        if not mod.kokoro_status()["downloading"]:
            return
        time.sleep(0.02)


print("--- which engine ---")
check("kokoro: ids", mod.tts_engine("kokoro:af_heart") == "kokoro")
check("windows: ids", mod.tts_engine("windows:Microsoft Zira Desktop") == "windows")
check("anything else is ElevenLabs, as before", mod.tts_engine("21m00Tcm4TlvDq8ikWAM") == "elevenlabs")

print()
print("--- the voice list ---")
setup("kokoro:af_heart")
body = client.get("/api/voices").get_json()
ids = [v["voice_id"] for v in body.get("voices", [])]
check("no ElevenLabs key: the free voices are listed, not an error", any(i.startswith("kokoro:") for i in ids)
      and any(i.startswith("windows:") for i in ids), body)
genders = {v["gender"] for v in body["voices"] if v["voice_id"].startswith("kokoro:")}
check("male and female Kokoro voices", genders == {"male", "female"}, genders)
check("each says where it runs", all(v["category"] in ("free on this PC", "built into Windows") for v in body["voices"]))
setup("EL1", eleven_key="k")
ids = [v["voice_id"] for v in client.get("/api/voices").get_json()["voices"]]
check("with a key: ElevenLabs voices too", "EL1" in ids and any(i.startswith("kokoro:") for i in ids), ids[:3])
served["eleven_down"] = True
body = client.get("/api/voices").get_json()
check("ElevenLabs down: the free voices still load, with a notice", body.get("voices") and "couldn't be loaded" in body.get("notice", ""), body.get("notice"))
served["eleven_down"] = False

print()
print("--- the one-time download ---")
setup("kokoro:af_heart")
status, body = say("hello there")
check("asked to speak before the download: says it's downloading, not a crash", status == 400 and "Downloading the free voices" in body.get("error", ""), body)
wait_download()
check("and the download ran and finished", mod.kokoro_files_ready() and served["requests"] == 2, (mod.kokoro_files_ready(), served["requests"]))
check("no partial files left behind", not [f for f in os.listdir(kokoro_dir) if f.endswith(".part")])
before = served["requests"]
mod.start_kokoro_download()
wait_download()
check("already downloaded: nothing fetched again", served["requests"] == before)

for f in os.listdir(kokoro_dir):
    os.remove(os.path.join(kokoro_dir, f))
served["tamper"] = True
mod.start_kokoro_download()
wait_download()
st = mod.kokoro_status()
check("a download that doesn't match the expected file is thrown away", not mod.kokoro_files_ready() and "didn't download correctly" in st["error"], st)
served["tamper"] = False
mod.start_kokoro_download()
wait_download()
check("and trying again works", mod.kokoro_files_ready() and mod.kokoro_status()["error"] == "")

print()
print("--- speaking with Kokoro ---")
setup("kokoro:am_michael")
status, body = say("hey whats up")
check("speaks with no ElevenLabs key and no OpenAI key (Word for word)", status == 200 and body.get("audio_url", "").endswith(".wav"), body)
check("with the voice picked", FakeKokoro.calls and FakeKokoro.calls[-1]["voice"] == "am_michael", FakeKokoro.calls)
check("costs no credits, and none are recorded", body.get("credits") == 0 and usage == [], (body.get("credits"), usage))
check("never calls ElevenLabs", eleven_calls == [])
check("says which engine spoke", body.get("voice_engine") == "kokoro")
audio = client.get(body["audio_url"])
check("the audio is a real wave file", audio.status_code == 200 and audio.data[:4] == b"RIFF", audio.status_code)
mod.CFG["speaking_speed"] = 1.2
say("faster")
check("speaking speed is passed on", abs(FakeKokoro.calls[-1]["speed"] - 1.2) < 1e-6, FakeKokoro.calls[-1])
setup("kokoro:bf_emma")
say("cheerio")
check("British voices speak British English", FakeKokoro.calls[-1]["lang"] == "en-gb", FakeKokoro.calls[-1])

setup("kokoro:af_heart", style="mimic")
mod.CFG["openai_api_key"] = "sk"
mod.create_chat_completion = lambda client_, **kw: SimpleNamespace(choices=[SimpleNamespace(
    message=SimpleNamespace(content="Hola amigo\n---EN---\nHello friend"), finish_reason="stop")])
status, body = say("hello friend", language="Spanish")
check("other languages Kokoro knows use their pronunciation", status == 200 and FakeKokoro.calls[-1]["lang"] == "es", FakeKokoro.calls)
status, body = say("hallo", language="German")
check("a language Kokoro can't speak is refused clearly", status == 400 and "can't speak German" in body.get("error", ""), body)

print()
print("--- ElevenLabs, unchanged ---")
setup("EL1")
status, body = say("hi")
check("an ElevenLabs voice without a key is still refused", status == 400 and "ElevenLabs key" in body.get("error", ""), body)
setup("EL1", eleven_key="k")
status, body = say("hi there")
check("with a key it speaks through ElevenLabs", status == 200 and eleven_calls and body["audio_url"].endswith(".mp3"), body)
check("and its credits are counted as before", usage == [len("hi there")], usage)

print()
print("--- Windows voices ---")
setup("windows:Microsoft Zira Desktop")
mod.CFG["speaking_speed"] = 0.8
tricky = "it's \"quoted\"; $(Remove-Item C:\\) `n and 'more'"
status, body = say(tricky)
job = next((r for r in ps_runs if isinstance(r, dict)), {})
check("speaks with no key", status == 200 and body.get("audio_url", "").endswith(".wav"), body)
check("the text reaches Windows exactly, through a file — never pasted into the script",
      job.get("text") == tricky and not any(isinstance(r, str) and "Remove-Item" in r for r in ps_runs), job)
check("with the voice picked", job.get("voice") == "Microsoft Zira Desktop", job)
check("speed 80% is Windows rate -2", job.get("rate") == -2, job)
check("no credits", body.get("credits") == 0 and usage == [])
leftover = [f for f in os.listdir(mod.AUDIO_DIR) if f.endswith(".json")]
check("the job file is cleaned up", leftover == [], leftover)

print()
print("--- previews ---")
setup("kokoro:af_heart")
first = client.get("/api/voices/preview?voice_id=kokoro:if_sara")
n = len(FakeKokoro.calls)
again = client.get("/api/voices/preview?voice_id=kokoro:if_sara")
check("a free voice's preview plays", first.status_code == 200 and first.data[:4] == b"RIFF", first.status_code)
check("in its own language", FakeKokoro.calls and FakeKokoro.calls[0]["lang"] == "it", FakeKokoro.calls[:1])
check("and is made only once", len(FakeKokoro.calls) == n, (n, len(FakeKokoro.calls)))
check("an unknown voice isn't", client.get("/api/voices/preview?voice_id=kokoro:nobody").status_code == 404)

print()
print("--- installed but can't load (no Visual C++ runtime) ---")
sys.modules["kokoro_onnx"] = SimpleNamespace()          # "from kokoro_onnx import Kokoro" fails
mod.KOKORO_STATE.update(engine=None, import_error=None)
setup("kokoro:af_heart")
status, body = say("hi")
check("the reply says what's wrong and how to fix it", status == 500 and "Visual C++" in body.get("error", ""), body)
check("and Settings says so too", "Visual C++" in client.get("/api/voices/free").get_json()["kokoro"]["problem"])
sys.modules["kokoro_onnx"] = fake_pkg
mod.KOKORO_STATE.update(engine=None, import_error=None)

print()
print("--- no package / wrong Python ---")
mod.KOKORO_STATE["import_error"] = "Kokoro needs Python 3.10–3.13, and Frivo is running on 3.9."
body = client.get("/api/voices").get_json()
check("Kokoro unavailable: its voices aren't offered", not any(v["voice_id"].startswith("kokoro:") for v in body["voices"]))
check("Windows voices still are", any(v["voice_id"].startswith("windows:") for v in body["voices"]))
check("and Settings says why", "3.10" in client.get("/api/voices/free").get_json()["kokoro"]["problem"])
setup("kokoro:af_heart")
status, body = say("hi")
check("a reply with a Kokoro voice says why too", status == 400 and "3.10" in body.get("error", ""), body)
mod.KOKORO_STATE["import_error"] = None

# --- optional: the real thing ---------------------------------------------------
real_dir = os.environ.get("FRIVO_KOKORO_DIR")
if real_dir:
    print()
    print("--- real Kokoro ---")
    del sys.modules["kokoro_onnx"]
    import importlib
    spec2 = importlib.util.spec_from_file_location("frivo_real", os.path.join(ws, "app.py"))
    real = importlib.util.module_from_spec(spec2)
    sys.modules["frivo_real"] = real
    spec2.loader.exec_module(real)
    real.KOKORO_DIR = real_dir
    real.CFG.update(openai_api_key="", elevenlabs_api_key="", response_style="mimic", voice_id="kokoro:af_heart")
    started = time.time()
    res = real.app.test_client().post("/api/chat", json={"message": "This voice is made on this computer, for free."})
    body = res.get_json()
    check("a real reply, spoken by Kokoro", res.status_code == 200 and body.get("audio_url"), body)
    print("        (%.1fs including loading the model)" % (time.time() - started))

print()
if failures:
    print("%d free-voice check(s) failed." % len(failures))
    sys.exit(1)
print("All free-voice checks passed.")
