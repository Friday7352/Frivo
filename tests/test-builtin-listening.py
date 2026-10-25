#!/usr/bin/env python3
"""NEW (2.0.0): Listening with Frivo's own dictation model.

The listening panel can stream what it hears to Frivo, like Live (Frivo)
dictation, instead of sending clips to Evora or OpenAI. Here the models are
stand-ins (a "word" for every half second of loud audio, as in
test-builtin-dictation.py) with the real streaming code around them, and
translation is a stand-in that marks what it translated, so what's checked
is Frivo's side:

  * /api/listen/stream: refused with nothing downloaded; lines as they're
    said, with the language the model heard (Small's tag, Large's own
    answer) and a translation into the panel's language
  * nothing translated when they already speak your language
  * a finished line translated as soon as it's finished, away from the
    audio (a slow translation doesn't hold up the stream); with Live
    updates, the line still being said translated too, at most every
    LISTEN_LIVE_TRANSLATE_SECONDS; without, never
  * "Commit every" finishing a line that goes on without a pause
  * Stop returning every line translated; an ended session refused
  * in Chromium, with a fake audio source: the panel using Frivo's model by
    itself once one is downloaded, translated lines with the original under
    them, the loudness gate keeping quiet sounds out, Evora's speaker
    controls stepping aside, and Settings › Providers' choice to use Evora
    or OpenAI instead

Usage:  python3 tests/test-builtin-listening.py     (run from the repo root)
Needs:  Frivo's Python packages. Playwright for the browser part.
"""

import hashlib
import importlib.util
import math
import os
import struct
import sys
import tempfile
import threading
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-listen-data-")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-listen-home-")
spec = importlib.util.spec_from_file_location("frivo_listen_test", os.path.join(ROOT, "app", "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_listen_test"] = mod
spec.loader.exec_module(mod)
mod.start_update_checker = lambda: None
mod.warm_free_voices = lambda: None
client = mod.app.test_client()
BD = mod.BUILTIN_DICTATION
M = mod.BUILTIN_DICTATION_MODULE

# ---------------------------------------------------------------- stand-ins

HEARD = {"tag": "ja-JP", "whisper": "es"}
TRANSLATED = []
SLOW = {"seconds": 0.0}


def fake_translate(text, target):
    TRANSLATED.append(text)
    time.sleep(SLOW["seconds"])
    return f"[{target}] {text}"


mod.translate_text = fake_translate


def words_for(samples):
    import numpy as np
    loud = sum(1 for i in range(0, len(samples), 160) if float(np.max(np.abs(samples[i:i + 160]))) > 0.05)
    return int(loud * 0.01 / 0.5)


class FakeOnlineStream:
    def __init__(self):
        self.loud = 0.0
        self.quiet = 0.0
        self.finished = False

    def set_option(self, k, v):
        pass

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
    def create_stream(self):
        return FakeOnlineStream()

    def is_ready(self, s):
        return False

    def decode_stream(self, s):
        pass

    def get_result(self, s):
        n = int(s.loud / 0.5) + (1 if s.finished and s.loud % 0.5 > 0.1 else 0)
        words = " ".join(f"palabra{i + 1}" for i in range(n))
        return f"{words} <{HEARD['tag']}>" if n and HEARD["tag"] else words

    def is_endpoint(self, s):
        return s.loud > 0 and s.quiet >= 0.8

    def reset(self, s):
        s.loud = 0.0
        s.quiet = 0.0


class FakeSmall(M.NemotronEngine):
    def __init__(self, folder, threads):
        self.rec = FakeOnlineRecognizer()


class FakeSentenceEngine:
    on_gpu = False
    word = "medium"

    def __init__(self, folder, threads):
        pass

    def stream(self, language, max_seconds=None):
        return M._SentenceStream(self, language, 0.5, max_seconds)

    def transcribe(self, samples, language=None, final=True):
        return " ".join(f"{self.word}{i + 1}" for i in range(max(1, words_for(samples)))) if len(samples) else ""

    def close(self):
        pass


class FakeLarge(FakeSentenceEngine):
    on_gpu = True
    word = "large"

    def transcribe(self, samples, language=None, final=True):
        self.last_language = HEARD["whisper"]
        return super().transcribe(samples, language, final)


M.ENGINES.update({"nemotron": FakeSmall, "parakeet": FakeSentenceEngine, "whisper": FakeLarge})


def pretend_downloaded(model_id):
    folder = BD.model_dir(model_id)
    os.makedirs(folder, exist_ok=True)
    for f in M.MODELS_BY_ID[model_id]["files"]:
        with open(os.path.join(folder, f["name"]), "wb") as out:
            out.write(b"x")
        f["size"] = 1
    open(os.path.join(folder, ".complete"), "w").close()


def pcm(seconds, loud):
    n = int(16000 * seconds)
    amp = 8000 if loud else 30
    return b"".join(struct.pack("<h", int(amp * math.sin(i / 8))) for i in range(n))


def send(sid, data):
    r = client.post(f"/api/listen/stream/{sid}", data=data, content_type="application/octet-stream")
    return r.status_code, (r.get_json() or {})


def settle(sid, seconds=1.0):
    """Quiet audio until the translations have come back."""
    end = time.time() + seconds
    lines = []
    while time.time() < end:
        _, d = send(sid, pcm(0.05, False))
        lines = d.get("lines", [])
        if lines and not any(l["translating"] for l in lines):
            break
        time.sleep(0.05)
    return lines


print("Before a model is downloaded")
r = client.post("/api/listen/stream", json={"target_language": "English"})
check("listening with Frivo's model is refused, and says where to go",
      r.status_code == 409 and "Settings › Models & downloads" in r.get_json()["error"] and "Settings › Providers" in r.get_json()["error"],
      r.get_json())

for model_id in ("small", "medium"):
    pretend_downloaded(model_id)
check("(stand-in models in place)", not BD.problem(), BD.problem())

print("Small, someone speaking Japanese, shown in English")
mod.CFG["builtin_dictation_model"] = "small"
r = client.post("/api/listen/stream", json={"target_language": "English", "live": True, "max_seconds": 6})
d = r.get_json()
sid = d.get("id")
check("a session starts, naming the model", r.status_code == 200 and sid and d.get("model"), d)
TRANSLATED.clear()
code, d = send(sid, pcm(1.6, True))
check("the words come while they talk", code == 200 and d["lines"] and d["lines"][0]["original"].startswith("palabra1")
      and not d["lines"][0]["complete"], d)
check("with the language the model heard", d["lines"][0]["detected_language"] == "ja", d["lines"])
time.sleep(0.2)
code, d = send(sid, pcm(0.5, True))
end = time.time() + 2
while time.time() < end and not d["lines"][0]["translated"]:
    time.sleep(0.05)
    code, d = send(sid, pcm(0.05, True))
check("with Live updates, the line still being said is translated", d["lines"][0]["text"].startswith("[English] palabra")
      and not d["lines"][0]["complete"], d["lines"])
check("and the original is kept beside it", d["lines"][0]["original"].startswith("palabra"), d["lines"])
interim_calls = len(TRANSLATED)
for _ in range(5):
    send(sid, pcm(0.2, True))
check("but not on every bit of audio (at most every 1.5 s)", len(TRANSLATED) <= interim_calls + 1, TRANSLATED)
send(sid, pcm(1.0, False))
lines = settle(sid)
check("a pause finishes the line, translated in full", lines and lines[0]["complete"] and lines[0]["translated"]
      and lines[0]["text"] == "[English] " + lines[0]["original"] and not lines[0]["behind"], lines)

print("Translation happens beside the stream")
SLOW["seconds"] = 0.8
send(sid, pcm(1.2, True))
t = time.time()
code, d = send(sid, pcm(1.0, False))
took = time.time() - t
check("a slow translation doesn't hold up the audio", took < 0.5, round(took, 2))
check("the finished line shows its original while it's translated", d["lines"][-1]["complete"] and d["lines"][-1]["translating"]
      and d["lines"][-1]["text"] == d["lines"][-1]["original"], d["lines"][-1:])
lines = settle(sid, 3)
check("and its translation arrives with a later answer", lines[-1]["translated"] and not lines[-1]["translating"], lines[-1:])
SLOW["seconds"] = 0.0

print("Stop")
SLOW["seconds"] = 0.4
send(sid, pcm(0.8, True))
r = client.post(f"/api/listen/stream/{sid}/stop", data=pcm(0.6, True), content_type="application/octet-stream")
final = r.get_json()["lines"]
check("Stop finishes the last line and waits for its translation", final and final[-1]["complete"] and final[-1]["translated"]
      and not any(l["translating"] for l in final), final[-1:])
SLOW["seconds"] = 0.0
code, d = send(sid, pcm(0.2, True))
check("an ended session is refused", code == 409, d)

print("Already in your language")
HEARD["tag"] = "en-US"
sid = client.post("/api/listen/stream", json={"target_language": "English", "live": True}).get_json()["id"]
TRANSLATED.clear()
send(sid, pcm(2.0, True))
send(sid, pcm(1.0, False))
lines = settle(sid)
check("English heard, English wanted: nothing is translated", lines and not TRANSLATED and not lines[0]["translated"]
      and lines[0]["text"] == lines[0]["original"] and not lines[0]["translating"], (TRANSLATED, lines))
client.post(f"/api/listen/stream/{sid}/stop")
HEARD["tag"] = "ja-JP"

print("Without Live updates")
sid = client.post("/api/listen/stream", json={"target_language": "German", "live": False}).get_json()["id"]
TRANSLATED.clear()
send(sid, pcm(2.0, True))
time.sleep(1.6)
send(sid, pcm(0.5, True))
check("the line being said isn't translated", not TRANSLATED, TRANSLATED)
send(sid, pcm(1.0, False))
lines = settle(sid)
check("only the finished line, into the language picked", len(TRANSLATED) == 1 and lines[0]["text"].startswith("[German] "),
      (TRANSLATED, lines))
client.post(f"/api/listen/stream/{sid}/stop")

print("Medium (it doesn't say the language)")
mod.CFG["builtin_dictation_model"] = "medium"
sid = client.post("/api/listen/stream", json={"target_language": "English", "max_seconds": 3}).get_json()["id"]
TRANSLATED.clear()
for _ in range(14):
    send(sid, pcm(0.5, True))
lines = settle(sid)
check("Commit every finishes a line that goes on without a pause", sum(1 for l in lines if l["complete"]) >= 2, lines)
check("not knowing the language, it's translated anyway", lines and lines[0]["translated"] and lines[0]["detected_language"] == "",
      lines[:1])
client.post(f"/api/listen/stream/{sid}/stop")

print("Large (it says what it heard)")
M.IS_WINDOWS = True
M.cuda_devices = lambda: 1
M._faster_whisper = lambda: object()
M.register_cuda = lambda folder: True
BD.cuda_ready = lambda: True
pretend_downloaded("large")
mod.CFG["builtin_dictation_model"] = "large"
sid = client.post("/api/listen/stream", json={"target_language": "English"}).get_json()["id"]
send(sid, pcm(1.5, True))
send(sid, pcm(1.0, False))
lines = settle(sid)
check("the language Whisper heard is on the line", lines and lines[0]["detected_language"] == "es" and lines[0]["translated"], lines)
client.post(f"/api/listen/stream/{sid}/stop")
mod.CFG["builtin_dictation_model"] = "small"
r = client.post("/api/listen/stream/nonsense/stop")
check("stopping one that isn't there is harmless", r.status_code == 200 and r.get_json()["lines"] == [])

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
    wav = os.path.join(tempfile.mkdtemp(prefix="frivo-listen-mic-"), "room.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        frames = bytearray()
        # A hum the stand-in model would hear as words but that's under the
        # gate (set to 30 below), then two sentences, then the hum again.
        for amp, seconds in ((2300, 1.5), (9000, 2.0), (2300, 2.0), (9000, 2.0), (2300, 4.0)):
            for i in range(int(48000 * seconds)):
                frames += struct.pack("<h", int(amp * math.sin(i / 20)))
        w.writeframes(bytes(frames))
    server = make_server("127.0.0.1", 5197, mod.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                          f"--use-file-for-fake-audio-capture={wav}%noloop", "--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:5197/")
        page.wait_for_selector("#listenToggle", timeout=20000)
        page.evaluate("localStorage.setItem('voice_console_listen_live', '1'); localStorage.setItem('voice_console_listen_threshold', '30')")
        page.reload()
        page.wait_for_selector("#listenToggle", timeout=20000)
        TRANSLATED.clear()
        page.click("#listenToggle")
        page.click("#listenStartBtn")
        page.wait_for_function("document.getElementById('listenPanel').classList.contains('is-builtin')", timeout=10000)
        check("with a model downloaded, the panel uses it by itself", True)
        check("Evora's speaker controls step aside", not page.is_visible("#listenResetSpeakersBtn") and not page.is_visible("#listenPeople"))
        page.wait_for_function("document.querySelectorAll('#listenLog .listen-entry').length >= 2"
                               " && !document.querySelector('#listenLog .listen-entry.is-pending')", timeout=25000)
        page.click("#listenStartBtn")
        time.sleep(1.5)
        if os.environ.get("FRIVO_SCREENSHOT"):
            page.locator("#listenPanel").screenshot(path=os.environ["FRIVO_SCREENSHOT"])
        texts = page.eval_on_selector_all("#listenLog .listen-entry .listen-text", "els => els.map(e => e.textContent)")
        originals = page.eval_on_selector_all("#listenLog .listen-entry .listen-original:not(.is-hidden)", "els => els.map(e => e.textContent)")
        check("both sentences, translated", len(texts) == 2 and all(t.startswith("[English] palabra") for t in texts), texts)
        check("with what was said under them", len(originals) == 2 and all(o.startswith("palabra") for o in originals), originals)
        # Each sentence is 2 s (4 words); the 0.3 s before the gate opens
        # and after it closes go up as heard, so 5 at most. Without the gate
        # the hum runs them together into one line of a dozen.
        check("the hum under the gate never reached the model", all(t.count("palabra") <= 5 for t in texts), texts)
        check("each says the language heard", page.eval_on_selector_all("#listenLog .listen-entry-lang", "els => els.map(e => e.textContent)") == ["ja", "ja"])
        check("no script errors", not errors, errors)
        # Settings › Providers: Evora or OpenAI instead.
        page.click("#settingsToggle")
        page.click('.settings-nav-btn[data-settings-section="providers"]')
        page.evaluate("(() => { const s = document.getElementById('listenEngineSelect'); s.value = 'provider'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        check("the choice is remembered", page.evaluate("localStorage.getItem('voice_console_listen_engine')") == "provider")
        check("and with it, listening goes to Evora or OpenAI", page.evaluate("listenUsesFrivo()") is False)
        page.evaluate("(() => { const s = document.getElementById('listenEngineSelect'); s.value = 'auto'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        client.delete("/api/builtin-dictation")
        check("with nothing downloaded, the default goes there too", page.evaluate("listenUsesFrivo()") is False)
        browser.close()
    server.shutdown()

import shutil
shutil.rmtree(BD.root, ignore_errors=True)
print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("All built-in listening checks passed.")
