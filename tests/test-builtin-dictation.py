#!/usr/bin/env python3
"""NEW (2.0.0): built-in dictation (app/builtin_dictation.py).

Moonshine itself is replaced by a stand-in (tests/fixtures/fake_moonshine:
the same names, no native library, each half second of loud audio is a word
and a pause ends a line), and its download site by a small server here. So
this checks Frivo's side, end to end:

  * status before anything is downloaded, and Live (Frivo) refusing to start
  * the download: progress, every file checked, the model set to the one
    downloaded; a file that doesn't match its checksum, or a cancelled
    download, keeps nothing (not even the half-finished folder)
  * live streams: words while you talk, a line completed by a pause, the
    last words finished by Stop, a stream that ended refused, the oldest
    stream closed when too many are open, the model loaded once
  * Test, the idle timer freeing the model, Remove
  * the page: Settings › Dictation's card, and dictating in a real browser
    with a fake microphone: words appear while it talks and the sentence is
    in the box at the end (if Playwright and its Chromium are installed)

Usage:  python3 tests/test-builtin-dictation.py     (run from the repo root)
Needs:  Frivo's Python packages. Playwright for the browser part.
"""

import http.server
import importlib.util
import math
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(ROOT, "tests", "fixtures", "fake_moonshine")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


# ---------------------------------------------------------------- a download site

SITE = {"mode": "ok", "hits": 0}


class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        import moonshine_voice
        parts = self.path.strip("/").split("/")   # model/<arch>/<name>
        if len(parts) != 3 or parts[0] != "model":
            self.send_response(404)
            self.end_headers()
            return
        SITE["hits"] += 1
        data = moonshine_voice.download.body(int(parts[1]), parts[2])
        if SITE["mode"] == "bad" and parts[2] == "decoder_kv.ort":
            data = data[:-1] + b"X"
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if SITE["mode"] == "slow":
            for i in range(0, len(data), 1000):
                self.wfile.write(data[i:i + 1000])
                time.sleep(0.006)
        else:
            self.wfile.write(data)


site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
threading.Thread(target=site.serve_forever, daemon=True).start()
os.environ["FAKE_MOONSHINE_URL"] = "http://127.0.0.1:%d" % site.server_address[1]

# ---------------------------------------------------------------- Frivo, with the stand-in

sys.path.insert(0, FAKE)
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
import moonshine_voice as fake   # noqa: E402  (the stand-in)


def wait_job(limit=20):
    end = time.time() + limit
    while time.time() < end:
        job = client.get("/api/builtin-dictation").get_json()["job"]
        if job.get("state") not in ("checking", "model"):
            return job
        time.sleep(0.05)
    return {"state": "timeout"}


def pcm(seconds, loud):
    """16-bit audio: a tone (loud) or near silence."""
    n = int(16000 * seconds)
    amp = 8000 if loud else 30
    return b"".join(struct.pack("<h", int(amp * math.sin(i / 8))) for i in range(n))


print("Before downloading")
check("it loaded", BD is not None)
st = client.get("/api/builtin-dictation").get_json()
check("supported (moonshine-voice is there)", st.get("supported") is True, st)
check("two models: Best and Fast", [m["id"] for m in st.get("models", [])] == ["medium", "small"], st.get("models"))
check("nothing downloaded", not any(m["downloaded"] for m in st["models"]))
check("says it isn't downloaded", "isn't downloaded" in st.get("problem", ""), st.get("problem"))
r = client.post("/api/dictation/stream")
check("Live (Frivo) won't start without it", r.status_code == 409 and "Settings › Dictation" in r.get_json()["error"], r.get_json())

print("A file that doesn't match its checksum")
SITE["mode"] = "bad"
r = client.post("/api/builtin-dictation/download", json={"model": "small"})
check("the download starts", r.status_code == 200, r.get_json())
job = wait_job()
check("it fails, saying why", job.get("state") == "error" and "checksum" in job.get("error", ""), job)
models_dir = os.path.join(BD.root, "models")
check("and keeps nothing", not os.path.isdir(models_dir) or not os.listdir(models_dir), os.listdir(models_dir) if os.path.isdir(models_dir) else None)

print("Cancelling")
SITE["mode"] = "slow"
client.post("/api/builtin-dictation/download", json={"model": "small"})
end = time.time() + 5
while time.time() < end:
    mid = client.get("/api/builtin-dictation").get_json()["job"]
    if mid.get("done"):
        break
    time.sleep(0.05)
check("progress is counted", mid.get("state") == "model" and 0 < mid.get("done", 0) < mid.get("total", 0), mid)
client.post("/api/builtin-dictation/cancel")
job = wait_job()
check("cancelled", job.get("state") == "cancelled", job)
check("and keeps nothing", not os.listdir(models_dir), os.listdir(models_dir))

print("Downloading")
SITE["mode"] = "ok"
r = client.post("/api/builtin-dictation/download", json={"model": "medium"})
job = wait_job()
check("done", job.get("state") == "done", job)
st = client.get("/api/builtin-dictation").get_json()
check("Best is downloaded", {m["id"]: m["downloaded"] for m in st["models"]} == {"medium": True, "small": False}, st["models"])
check("and chosen", mod.CFG.get("builtin_dictation_model") == "medium" and st["active_model"] == "medium", st)
check("nothing left to fix", st["problem"] == "", st["problem"])
check("every file is there", sorted(os.listdir(BD.model_dir("medium"))) == sorted(fake.download.FILES + [".complete"]),
      os.listdir(BD.model_dir("medium")))
hits = SITE["hits"]
r = client.post("/api/builtin-dictation/download", json={"model": "medium"})
check("asking again just uses it", r.get_json().get("ready") is True and SITE["hits"] == hits, r.get_json())

print("Live dictation")
loads = len(fake.LOADS)
r = client.post("/api/dictation/stream")
sid = (r.get_json() or {}).get("id")
check("a stream starts", r.status_code == 200 and sid, r.get_json())
check("the model loads for it", len(fake.LOADS) == loads + 1)
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(1.1, True)).get_json()["lines"]
check("words while talking", len(lines) == 1 and lines[0]["text"] == "word1_1 word1_2" and not lines[0]["complete"], lines)
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(0.8, False)).get_json()["lines"]
check("a pause completes the line", lines and lines[0]["complete"], lines)
lines = client.post(f"/api/dictation/stream/{sid}", data=pcm(0.6, True)).get_json()["lines"]
check("talking again starts the next line", len(lines) == 2 and not lines[1]["complete"], lines)
r = client.post(f"/api/dictation/stream/{sid}/stop", data=pcm(0.3, True))
final = r.get_json()["lines"]
check("Stop finishes the last line", len(final) == 2 and all(l["complete"] for l in final) and final[1]["text"], final)
r = client.post(f"/api/dictation/stream/{sid}", data=pcm(0.2, True))
check("a stream that ended is refused", r.status_code == 409, r.status_code)
check("too much audio at once is refused", client.post(f"/api/dictation/stream/{client.post('/api/dictation/stream').get_json()['id']}",
      data=b"\0" * (16000 * 2 * 6)).status_code == 409)
ids = [client.post("/api/dictation/stream").get_json()["id"] for _ in range(mod.BUILTIN_DICTATION_MODULE.MAX_STREAMS + 1)]
check("never more than a few streams at once", len(BD._streams) == mod.BUILTIN_DICTATION_MODULE.MAX_STREAMS, len(BD._streams))
check("the model was loaded once for all of them", len(fake.LOADS) == loads + 1, len(fake.LOADS) - loads)
check("the Server page sees who's dictating", any(prefix == "/api/dictation/" for prefix, _ in mod.CLIENT_ACTIVITIES))

print("Test, idle and settings")
r = client.post("/api/builtin-dictation/test")
check("Test transcribes the sample", r.status_code == 200 and r.get_json().get("text") == "the sample speech", r.get_json())
r = client.post("/api/builtin-dictation/settings", json={"idle": "5m", "model": "nonsense"})
check("the idle time is saved, nonsense isn't", mod.CFG["builtin_dictation_idle"] == "5m" and mod.CFG["builtin_dictation_model"] == "medium")
BD.idle_check(time.time() + 10)
check("open streams keep it loaded", BD._transcriber is not None)
BD.idle_check(time.time() + mod.BUILTIN_DICTATION_MODULE.STREAM_FORGET_SECONDS + 400)
check("idle streams are closed, then the model is freed", not BD._streams and BD._transcriber is None, (len(BD._streams), BD._transcriber))
r = client.post("/api/dictation/stream")
check("and loads again when needed", r.status_code == 200)

print("Remove")
r = client.delete("/api/builtin-dictation/medium")
check("Remove deletes the model", r.status_code == 200 and not os.path.isdir(BD.model_dir("medium")), r.get_json())
check("and its streams", not BD._streams)
check("so Live (Frivo) says to download it again", client.post("/api/dictation/stream").status_code == 409)

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
    client.post("/api/builtin-dictation/download", json={"model": "small"})
    wait_job()
    # A fake microphone: two sentences, each two seconds of tone and a pause.
    wav = os.path.join(tempfile.mkdtemp(prefix="frivo-dictation-mic-"), "speech.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        frames = bytearray()
        for loud, seconds in ((False, 0.5), (True, 2.0), (False, 1.2), (True, 2.0), (False, 3.0)):
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
        check("the card says it's downloaded", page.text_content("#bdValue") in ("Downloaded", "In use"), page.text_content("#bdValue"))
        check("with both models listed", page.locator("#bdModels .bai-model").count() == 2)
        check("Live (Frivo) is offered", page.locator('#dictationModeRadios input[value="live_frivo"]').count() == 1)
        check("and is the default once downloaded", page.evaluate("currentDictationMode()") == "live_frivo")
        page.click("#closeSettingsBtn") if page.locator("#closeSettingsBtn").count() else page.keyboard.press("Escape")
        page.click("#dictateBtn")
        seen = []
        end = time.time() + 15
        while time.time() < end:
            value = page.input_value("#messageInput")
            if value and value not in seen:
                seen.append(value)
            if "word2_" in value:
                break
            time.sleep(0.1)
        check("words appear while it talks", any("word1_1" in v for v in seen), seen)
        check("the first sentence is kept and the second follows", any("word1_" in v and "word2_" in v for v in seen), seen)
        page.click("#dictateBtn")
        time.sleep(1.0)
        final = page.input_value("#messageInput")
        check("after Stop the sentence is in the box", "word1_" in final and "word2_" in final, final)
        check("no script errors", not errors, errors)
        # NEW (2.0.0): not downloaded on the PC Frivo runs on: the mic says so
        # (it used to be replaced by "Ready." at once) and Settings opens there.
        client.delete("/api/builtin-dictation")
        page.evaluate("localStorage.setItem('voice_console_dictation_mode', 'live_frivo'); builtinDictationKnown = false;")
        page.click("#dictateBtn")
        page.wait_for_function("/download/i.test(document.getElementById('status').textContent)", timeout=8000)
        time.sleep(0.5)
        status = page.text_content("#status")
        check("not downloaded: the mic says why, and it stays said", "download" in status.lower(), status)
        check("and Settings › Dictation opens", page.is_visible('#bdCard'))
        check("and the mic isn't left on", "is-recording" not in (page.get_attribute("#dictateBtn", "class") or ""))
        client.post("/api/builtin-dictation/download", json={"model": "small"})
        wait_job()
        # NEW (2.0.0): the Frivo app has no speech service behind the browser's
        # recogniser, so Live (browser) is never offered or chosen there.
        app_page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Electron/44.5.1 Safari/537.36 FrivoApp/2.0.0")
        app_page.goto("http://127.0.0.1:5196/")
        app_page.wait_for_selector("#dictateBtn", timeout=20000)
        app_page.evaluate("localStorage.setItem('voice_console_dictation_mode', 'live')")
        app_page.evaluate("buildDictationModeUI()")
        modes = app_page.evaluate("[...document.querySelectorAll('#dictationModeRadios input')].map((i) => i.value)")
        check("the app doesn't offer Live (browser)", "live" not in modes and "live_frivo" in modes, modes)
        check("and a saved Live (browser) becomes built-in dictation there", app_page.evaluate("currentDictationMode()") == "live_frivo",
              app_page.evaluate("currentDictationMode()"))
        app_page.close()
        browser.close()
    server.shutdown()

shutil.rmtree(BD.root, ignore_errors=True)
print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("All built-in dictation checks passed.")
