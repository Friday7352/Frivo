#!/usr/bin/env python3
"""NEW (2.0.0): built-in dictation (app/builtin_dictation.py).

Three models: Small (Nemotron 3.5 streaming), Medium (Parakeet v3) and Large
(Whisper large-v3-turbo on an NVIDIA card). The real ones are hundreds of
megabytes and need sherpa-onnx, faster-whisper and a graphics card, so here
the engines are stand-ins with the same shape (a "word" for every half
second of loud audio), the files are small ones served by a download site in
this test, and NVIDIA's libraries are two small zips laid out like the real
wheels. What's checked is Frivo's own side, end to end, with the real
streaming code (_NemotronStream and _SentenceStream):

  * status before downloading; Large unavailable without a card (and on a
    PC that isn't Windows), available with one; Live (Frivo) refusing to
    start until something is downloaded
  * the download: progress, every file checked against its size and
    SHA-256, a bad file or a cancel keeping nothing, NVIDIA's DLLs taken out
    of their wheels for Large and removed with it
  * live streams: Small's words as they come and its sentence ends; Medium's
    and Large's sentences by pauses, re-read while being said and once more
    at the end; Stop finishing the last; the language passed through; one
    model loaded for every stream; streams closed and the model freed when
    idle
  * Test with your own voice (16-bit audio in, what it heard out)
  * the GPU graph: Large's memory as its own "dictation" part
  * the page: the card with three models, dictating in Chromium with a fake
    microphone, the error when nothing's downloaded, and the Frivo app never
    offering Live (browser)

Usage:  python3 tests/test-builtin-dictation.py     (run from the repo root)
Needs:  Frivo's Python packages. Playwright for the browser part.
"""

import hashlib
import http.server
import importlib.util
import io
import math
import os
import struct
import sys
import tempfile
import threading
import time
import wave
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


# ---------------------------------------------------------------- a download site

SITE = {"mode": "ok", "hits": 0, "files": {}}


class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        data = SITE["files"].get(self.path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        SITE["hits"] += 1
        if SITE["mode"] == "bad" and self.path.endswith("decoder.int8.onnx"):
            data = data[:-1] + b"X"
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if SITE["mode"] == "slow":
            for i in range(0, len(data), 2000):
                self.wfile.write(data[i:i + 2000])
                time.sleep(0.01)
        else:
            self.wfile.write(data)


site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
threading.Thread(target=site.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % site.server_address[1]

# ---------------------------------------------------------------- Frivo, with stand-ins

os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-dictation-data-")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-dictation-home-")
spec = importlib.util.spec_from_file_location("frivo_dictation_test", os.path.join(ROOT, "app", "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_dictation_test"] = mod
spec.loader.exec_module(mod)
mod.start_update_checker = lambda: None
mod.warm_free_voices = lambda: None
client = mod.app.test_client()
BD = mod.BUILTIN_DICTATION
M = mod.BUILTIN_DICTATION_MODULE

# Small files in place of the real ones, served by the site above.
for model in M.MODELS:
    files = []
    for f in model["files"]:
        body = (f"{model['id']}:{f['name']}:" * 3000).encode()
        SITE["files"][f"/{model['repo']}/resolve/main/{f['name']}"] = body
        files.append({"name": f["name"], "size": len(body),
                      "sha256": hashlib.sha256(body).hexdigest() if f["sha256"] else None})
    model["files"] = files
    model["size"] = sum(f["size"] for f in files)
M.HF = BASE + "/{repo}/resolve/main/{name}"
wheels = []
for lib in ("cublas", "cudnn"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"nvidia/{lib}/bin/{lib}64_test.dll", b"dll" * 1000)
        z.writestr(f"nvidia/{lib}/include/{lib}.h", b"header")
    body = buf.getvalue()
    name = f"nvidia_{lib}_test.whl"
    SITE["files"]["/" + name] = body
    wheels.append({"name": name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest(), "url": BASE + "/" + name})
M.CUDA_WHEELS = wheels
M.CUDA_SIZE = sum(w["size"] for w in wheels)

CARD = {"present": False, "used": 1000}
BD.gpu_reader = lambda: CARD["used"] if CARD["present"] else None
M.cuda_devices = lambda: 1 if CARD["present"] else 0
M._faster_whisper = lambda: object()          # "installed"
M.register_cuda = lambda folder: os.path.isdir(folder)

LOG = {"languages": [], "transcribed": []}


def words_for(samples):
    """A word for each half second of loud audio, like the stand-in model hears it."""
    import numpy as np
    loud = sum(1 for i in range(0, len(samples), 160) if float(np.max(np.abs(samples[i:i + 160]))) > 0.05)
    return int(loud * 0.01 / 0.5)


class FakeOnlineStream:
    def __init__(self):
        self.loud = 0.0
        self.quiet = 0.0
        self.heard = 0
        self.options = {}
        self.finished = False

    def set_option(self, k, v):
        self.options[k] = v
        LOG["languages"].append(v)

    def accept_waveform(self, rate, samples):
        import numpy as np
        for i in range(0, len(samples), 160):
            part = samples[i:i + 160]
            if len(part) and float(np.max(np.abs(part))) > 0.05:
                self.loud += len(part) / rate
                self.quiet = 0.0
            else:
                self.quiet += len(part) / rate

    def input_finished(self):
        self.finished = True


class FakeOnlineRecognizer:
    """The sherpa-onnx OnlineRecognizer calls _NemotronStream makes."""

    def create_stream(self):
        return FakeOnlineStream()

    def is_ready(self, s):
        return False

    def decode_stream(self, s):
        pass

    def get_result(self, s):
        n = int(s.loud / 0.5) + (1 if s.finished and s.loud % 0.5 > 0.1 else 0)
        return " ".join(f"small{i + 1}" for i in range(n)) + (" <en-US>" if n else "")

    def is_endpoint(self, s):
        return s.loud > 0 and s.quiet >= 0.8

    def reset(self, s):
        s.loud = 0.0
        s.quiet = 0.0


class FakeSmall(M.NemotronEngine):
    def __init__(self, folder, threads):
        assert os.path.isfile(os.path.join(folder, "encoder.int8.onnx"))
        self.rec = FakeOnlineRecognizer()


class FakeSentenceEngine:
    on_gpu = False
    word = "medium"
    interim = 0.5

    def __init__(self, folder, threads):
        self.folder = folder

    def stream(self, language):
        LOG["languages"].append(language)
        return M._SentenceStream(self, language, self.interim)

    def transcribe(self, samples, language=None, final=True):
        LOG["transcribed"].append((len(samples), final))
        return " ".join(f"{self.word}{i + 1}" for i in range(max(1, words_for(samples)))) if len(samples) else ""

    def close(self):
        pass


class FakeMedium(FakeSentenceEngine):
    pass


class FakeLarge(FakeSentenceEngine):
    on_gpu = True
    word = "large"
    interim = 0.6

    def __init__(self, folder, threads):
        super().__init__(folder, threads)
        CARD["used"] += 1500   # what loading it took on the card


M.ENGINES.update({"nemotron": FakeSmall, "parakeet": FakeMedium, "whisper": FakeLarge})


def wait_job(limit=30):
    end = time.time() + limit
    while time.time() < end:
        job = client.get("/api/builtin-dictation").get_json()["job"]
        if job.get("state") not in ("checking", "model", "cuda"):
            return job
        time.sleep(0.05)
    return {"state": "timeout"}


def pcm(seconds, loud):
    n = int(16000 * seconds)
    amp = 8000 if loud else 30
    return b"".join(struct.pack("<h", int(amp * math.sin(i / 8))) for i in range(n))


def models():
    return {m["id"]: m for m in client.get("/api/builtin-dictation").get_json()["models"]}


print("Before downloading")
st = client.get("/api/builtin-dictation").get_json()
check("three models: Small, Medium, Large", [m["id"] for m in st["models"]] == ["small", "medium", "large"], st["models"])
check("each says its languages and what it runs on",
      all(m.get("languages") for m in st["models"]) and [m["gpu"] for m in st["models"]] == [False, False, True])
check("Small and Medium can run here", not models()["small"]["problem"] and not models()["medium"]["problem"])
M.IS_WINDOWS = False
check("Large needs Windows", "Windows" in models()["large"]["problem"], models()["large"]["problem"])
M.IS_WINDOWS = True
check("and an NVIDIA card", "NVIDIA" in models()["large"]["problem"], models()["large"]["problem"])
r = client.post("/api/builtin-dictation/download", json={"model": "large"})
check("so Large can't be downloaded without one", r.status_code == 400, r.get_json())
CARD["present"] = True
check("with a card, Large can run", not models()["large"]["problem"], models()["large"]["problem"])
check("and says NVIDIA's libraries come with it the first time", models()["large"]["extra_size"] == M.CUDA_SIZE)
r = client.post("/api/dictation/stream", json={})
check("Live (Frivo) won't start with nothing downloaded", r.status_code == 409 and "Settings › Dictation" in r.get_json()["error"], r.get_json())

print("Downloading")
SITE["mode"] = "bad"
client.post("/api/builtin-dictation/download", json={"model": "medium"})
job = wait_job()
check("a file that doesn't match its checksum fails", job.get("state") == "error" and "checksum" in job.get("error", ""), job)
models_dir = os.path.join(BD.root, "models")
check("and nothing is kept", not os.listdir(models_dir), os.listdir(models_dir))
SITE["mode"] = "slow"
client.post("/api/builtin-dictation/download", json={"model": "medium"})
end = time.time() + 10
while time.time() < end:
    mid = client.get("/api/builtin-dictation").get_json()["job"]
    if mid.get("done"):
        break
    time.sleep(0.02)
check("progress is counted", 0 < mid.get("done", 0) < mid.get("total", 1), mid)
client.post("/api/builtin-dictation/cancel")
job = wait_job()
check("a cancel keeps nothing", job.get("state") == "cancelled" and not os.listdir(models_dir), (job, os.listdir(models_dir)))
SITE["mode"] = "ok"
for mid_ in ("small", "medium", "large"):
    client.post("/api/builtin-dictation/download", json={"model": mid_})
    job = wait_job()
    check(f"{mid_} downloads", job.get("state") == "done", job)
check("all three are there", all(m["downloaded"] for m in models().values()))
check("Large brought NVIDIA's DLLs, out of their wheels", sorted(f for f in os.listdir(BD.cuda_dir) if f.endswith(".dll"))
      == ["cublas64_test.dll", "cudnn64_test.dll"], os.listdir(BD.cuda_dir))
check("and only once", models()["large"]["extra_size"] == 0)
check("the last one downloaded is the one used", mod.CFG["builtin_dictation_model"] == "large")

print("Small: live, as the words come")
client.post("/api/builtin-dictation/settings", json={"model": "small"})
r = client.post("/api/dictation/stream", json={"language": "ja-JP"})
sid = r.get_json().get("id")
check("a stream starts", r.status_code == 200 and sid, r.get_json())
check("with the language asked for", LOG["languages"][-1] == "ja", LOG["languages"][-3:])
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(1.1, True)).get_json()["lines"]
check("words while talking, without the language tag", lines and lines[-1]["text"] == "small1 small2" and not lines[-1]["complete"], lines)
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(1.0, False)).get_json()["lines"]
check("the end of a sentence completes it", lines and lines[-1]["complete"], lines)
client.post(f"/api/dictation/stream/{sid}", data=pcm(0.7, True))
final = client.post(f"/api/dictation/stream/{sid}/stop").get_json()["lines"]
check("Stop finishes the last one", len(final) == 2 and all(l["complete"] for l in final) and final[1]["text"], final)
r = client.post("/api/dictation/stream", json={"language": ""})
check("no language is automatic", LOG["languages"][-1] == "auto", LOG["languages"][-1:])

print("Medium: sentences by pauses")
client.post("/api/builtin-dictation/settings", json={"model": "medium"})
sid = client.post("/api/dictation/stream", json={}).get_json()["id"]
check("the other model takes over (Small's streams closed)", len(BD._streams) == 1, len(BD._streams))
LOG["transcribed"].clear()
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(1.2, True)).get_json()["lines"]
check("read again while being said", lines and lines[-1]["text"].startswith("medium") and not lines[-1]["complete"], lines)
check("(as a draft)", any(not final for _, final in LOG["transcribed"]), LOG["transcribed"])
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(0.8, False)).get_json()["lines"]
check("a pause ends it, read once more in full", lines and lines[-1]["complete"] and LOG["transcribed"][-1][1] is True, (lines, LOG["transcribed"][-1:]))
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(0.3, False)).get_json()["lines"]
check("silence adds nothing", len(lines) == 1, lines)
client.post(f"/api/dictation/stream/{sid}", data=pcm(0.6, True))
final = client.post(f"/api/dictation/stream/{sid}/stop").get_json()["lines"]
check("Stop reads the sentence being said", len(final) == 2 and final[1]["complete"], final)
r = client.post(f"/api/dictation/stream/{sid}", data=pcm(0.2, True))
check("a stream that ended is refused", r.status_code == 409, r.status_code)
check("too much audio at once is refused", client.post(f"/api/dictation/stream/{client.post('/api/dictation/stream', json={}).get_json()['id']}",
      data=b"\0" * (16000 * 2 * 6)).status_code == 409)

print("Large: on the graphics card")
client.post("/api/builtin-dictation/settings", json={"model": "large"})
before = CARD["used"]
sid = client.post("/api/dictation/stream", json={"language": "ko"}).get_json()["id"]
st = client.get("/api/builtin-dictation").get_json()
check("what it takes on the card is measured", st["vram_mb"] == 1500 and CARD["used"] == before + 1500, st.get("vram_mb"))
check("and the GPU graph is told", (BD.gpu_usage() or {}).get("vram_mb") == 1500, BD.gpu_usage())
client.post(f"/api/dictation/stream/{sid}", data=pcm(1.0, True))
final = client.post(f"/api/dictation/stream/{sid}/stop").get_json()["lines"]
check("it reads what's said", final and final[0]["text"].startswith("large"), final)
mod.GPU_LOCAL.snapshot = lambda device="cpu": {"ok": True, "name": "NVIDIA GeForce RTX 2070 SUPER", "total_mb": 8192,
                                               "used_mb": 3600, "util_pct": 10, "temp_c": 50, "processes": [],
                                               "parts": {"ollama_mb": 1000, "evora_mb": 0, "dictation_mb": 1500, "other_mb": 1100},
                                               "source": "nvml"}
mod._gpu_local_state.update(checked=0, present=False)
g = client.get("/api/gpu").get_json()
check("the GPU graph shows the card in this PC", g.get("enabled") and g.get("local_card"), g.get("enabled"))
check("with dictation as its own part", (g.get("card") or {}).get("parts", {}).get("dictation_mb") == 1500
      and g["history"][-1].get("dictation") == 1500, g.get("card"))
check("and which model it is", (g.get("dictation") or {}).get("model") == "Whisper large-v3-turbo", g.get("dictation"))
mod.GPU_LOCAL.snapshot = lambda device="cpu": {"ok": True, "name": "card", "total_mb": 8192, "used_mb": 3600,
                                               "util_pct": None, "temp_c": None, "processes": [], "parts": None, "source": "nvidia-smi"}
mod._gpu_local_state.update(checked=0, present=False)
mod._gpu_state["latest"] = None
g = client.get("/api/gpu").get_json()
check("without Windows' counters, dictation's share is its measured size",
      (g.get("card") or {}).get("parts", {}).get("dictation_mb") == 1500 and g["card"]["parts"].get("estimated"), g.get("card"))

print("Test with your voice")
r = client.post("/api/builtin-dictation/test?language=auto", data=pcm(1.6, True), content_type="application/octet-stream")
d = r.get_json() or {}
check("Test reads what was recorded", r.status_code == 200 and d.get("text", "").startswith("large") and d.get("audio_seconds") == 1.6, d)
r = client.post("/api/builtin-dictation/test", data=b"\0" * 100, content_type="application/octet-stream")
check("an empty recording says so", r.status_code == 400 and "microphone" in r.get_json()["error"], r.get_json())

print("Noise isn't words")
client.post("/api/builtin-dictation/settings", json={"model": "medium"})
sid = client.post("/api/dictation/stream", json={}).get_json()["id"]
LOG["transcribed"].clear()
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(0.5, False) + pcm(0.06, True) + pcm(1.0, False)).get_json()["lines"]
check("a pop isn't even read", not lines and not LOG["transcribed"], (lines, LOG["transcribed"]))
client.post(f"/api/dictation/stream/{sid}/stop")


class Seg:
    def __init__(self, text, no_speech=0.01, logprob=-0.2, ratio=1.2):
        self.text, self.no_speech_prob, self.avg_logprob, self.compression_ratio = text, no_speech, logprob, ratio


class Info:
    language = "en"


class FakeWhisperModel:
    segments = []

    def transcribe(self, samples, **kw):
        return iter(self.segments), Info()


import numpy as np
w = M.WhisperEngine.__new__(M.WhisperEngine)
w.model = FakeWhisperModel()
audio = np.ones(16000, dtype=np.float32) * 0.1


def heard(*segments):
    w.model.segments = list(segments)
    return w.transcribe(audio)


check("Whisper's \"Thank you\" for a noise it wasn't sure of is dropped", heard(Seg(" Thank you.", no_speech=0.4)) == "")
check("and when it wasn't sure of the words", heard(Seg(" Thanks for watching!", logprob=-0.8)) == "")
check("a clear \"thank you\" stays", heard(Seg(" Thank you.")) == "Thank you.")
check("so does a sentence with it in", heard(Seg(" Thank you, that was fun.", no_speech=0.4)) == "Thank you, that was fun.")
check("subtitle credits are always dropped", heard(Seg(" Subtitles by the Amara.org community")) == "")
check("in other languages too", heard(Seg(" ご視聴ありがとうございました", no_speech=0.3)) == "")
check("Whisper's own no-speech rule is applied to each part", heard(Seg(" Hello there."), Seg(" Hmm hmm.", no_speech=0.7, logprob=-1.3)) == "Hello there.")
check("and a part repeating itself is dropped", heard(Seg(" Hello."), Seg(" the the the the the the", ratio=3.1)) == "Hello.")
client.post("/api/builtin-dictation/settings", json={"model": "large"})

print("Idle, and Remove")
client.post("/api/builtin-dictation/settings", json={"idle": "5m", "model": "nonsense"})
check("the idle time is saved, nonsense isn't", mod.CFG["builtin_dictation_idle"] == "5m" and mod.CFG["builtin_dictation_model"] == "large")
BD.idle_check(time.time() + M.STREAM_FORGET_SECONDS + 400)
check("idle streams are closed, then the model is freed", not BD._streams and BD._engine is None, (len(BD._streams), BD._engine))
check("and the graph is told", BD.gpu_usage() is None)
r = client.delete("/api/builtin-dictation/large")
check("Remove deletes Large, and NVIDIA's libraries with it", r.status_code == 200 and not os.path.isdir(BD.model_dir("large"))
      and not os.path.isdir(BD.cuda_dir), r.get_json())
check("the others stay", models()["small"]["downloaded"] and models()["medium"]["downloaded"])
legacy = os.path.join(BD.root, "models", "small")
os.makedirs(legacy, exist_ok=True)
M.BuiltinDictation(os.path.dirname(BD.root), lambda *a: None)
check("the first try's Moonshine models are cleared away", not os.path.isdir(legacy))

# ---------------------------------------------------------------- in a browser

print("In a browser")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    print("  SKIP  Playwright isn't installed")
if sync_playwright:
    import logging
    from werkzeug.serving import make_server
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    client.post("/api/builtin-dictation/settings", json={"model": "small"})
    wav = os.path.join(tempfile.mkdtemp(prefix="frivo-dictation-mic-"), "speech.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        frames = bytearray()
        for loud, seconds in ((False, 0.5), (True, 2.0), (False, 1.4), (True, 2.0), (False, 3.0)):
            amp = 9000 if loud else 0
            for i in range(int(48000 * seconds)):
                frames += struct.pack("<h", int(amp * math.sin(i / 20)))
        w.writeframes(bytes(frames))
    server = make_server("127.0.0.1", 5196, mod.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                          f"--use-file-for-fake-audio-capture={wav}%noloop", "--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:5196/")
        page.wait_for_selector("#dictateBtn", timeout=20000)
        page.evaluate("localStorage.removeItem('voice_console_dictation_mode')")
        page.click("#settingsToggle")
        page.click('.settings-nav-btn[data-settings-section="dictation"]')
        page.wait_for_function("document.getElementById('bdValue').textContent.length > 0", timeout=10000)
        check("the card lists the three models", page.locator("#bdModels .bai-model").count() == 3)
        card_text = page.text_content("#bdModels")
        check("with their languages and what they run on", "About 40" in card_text and "graphics card" in card_text and "processor" in card_text,
              card_text[:300])
        check("Live (Frivo) is the default once one is downloaded", page.evaluate("currentDictationMode()") == "live_frivo")
        page.keyboard.press("Escape")
        page.click("#dictateBtn")
        seen = []
        end = time.time() + 15
        while time.time() < end:
            value = page.input_value("#messageInput")
            if value and value not in seen:
                seen.append(value)
            if value.count("small1") >= 2:
                break
            time.sleep(0.1)
        check("words appear while it talks", any("small1" in v and v.count("small1") == 1 for v in seen), seen)
        page.click("#dictateBtn")
        time.sleep(1.2)
        final = page.input_value("#messageInput")
        check("after Stop both sentences are in the box", final.count("small1") == 2, final)
        check("no script errors", not errors, errors)
        # Nothing downloaded: the mic says so, and Settings opens there.
        client.delete("/api/builtin-dictation")
        page.evaluate("localStorage.setItem('voice_console_dictation_mode', 'live_frivo'); builtinDictationKnown = false;")
        page.click("#dictateBtn")
        page.wait_for_function("/download/i.test(document.getElementById('status').textContent)", timeout=8000)
        time.sleep(0.5)
        check("not downloaded: the mic says why, and it stays said", "download" in page.text_content("#status").lower(), page.text_content("#status"))
        check("and Settings › Dictation opens", page.is_visible("#bdCard"))
        check("and the mic isn't left on", "is-recording" not in (page.get_attribute("#dictateBtn", "class") or ""))
        client.post("/api/builtin-dictation/download", json={"model": "small"})
        wait_job()
        app_page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Electron/44.5.1 Safari/537.36 FrivoApp/2.0.0")
        app_page.goto("http://127.0.0.1:5196/")
        app_page.wait_for_selector("#dictateBtn", timeout=20000)
        app_page.evaluate("localStorage.setItem('voice_console_dictation_mode', 'live')")
        app_page.wait_for_function("builtinDictationKnown === true", timeout=10000)
        app_page.evaluate("buildDictationModeUI()")
        modes = app_page.evaluate("[...document.querySelectorAll('#dictationModeRadios input')].map((i) => i.value)")
        check("the Frivo app doesn't offer Live (browser)", "live" not in modes and "live_frivo" in modes, modes)
        check("and a saved Live (browser) becomes built-in dictation there", app_page.evaluate("currentDictationMode()") == "live_frivo",
              app_page.evaluate("currentDictationMode()"))
        app_page.close()
        browser.close()
    server.shutdown()

import shutil
shutil.rmtree(BD.root, ignore_errors=True)
print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("All built-in dictation checks passed.")
