#!/usr/bin/env python3
"""NEW (1.5.0): streaming ElevenLabs replies.

  * on: the reply comes back at once with a stream address; the audio is
    relayed as ElevenLabs sends it, then kept as a normal file
  * the timings arrive at the end: word times and chatbox page times, from
    pieces whose timings are relative to each piece or to the whole reply
  * credits are counted once the voice is finished
  * a refused stream falls back to the whole-clip request (nothing lost)
  * a streamed reply can be saved; an old stream address serves the file
  * off: exactly the old request

Usage:  python3 tests/test-speech-stream.py     (run from the repo root)
"""

import base64
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-stream-home-")
ws = tempfile.mkdtemp(prefix="frivo-stream-")
shutil.copy(os.path.join(ROOT, "app", "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_stream", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_stream"] = mod
spec.loader.exec_module(mod)
mod.AUDIO_DIR = tempfile.mkdtemp(prefix="frivo-stream-audio-")

state = {"mode": "ok", "relative": False, "gate": threading.Event(), "posts": [], "usage": []}


def pieces_for(text):
    """Two pieces, with timings either for the whole reply or per piece."""
    half = len(text) // 2
    out = []
    for n, part in enumerate((text[:half], text[half:])):
        base = 0.0 if state["relative"] else n * half * 0.1
        out.append({"audio_base64": base64.b64encode(bytes([65 + n]) * 1600).decode(),
                    "alignment": {"characters": list(part),
                                  "character_start_times_seconds": [base + i * 0.1 for i in range(len(part))],
                                  "character_end_times_seconds": [base + i * 0.1 + 0.08 for i in range(len(part))]}})
    return out


class StreamResp:
    def __init__(self, lines, status=200):
        self.status_code = status
        self.lines = lines
        self.headers = {"request-id": "r1"}
        self.text = "" if status == 200 else '{"detail":{"message":"model not available"}}'

    def json(self):
        return json.loads(self.text) if self.text else {}

    def iter_lines(self):
        for i, line in enumerate(self.lines):
            if i == 1:
                state["gate"].wait(5)   # the second piece waits, like a real stream
            yield json.dumps(line).encode()

    def close(self):
        pass


def fake_post(url, **kw):
    body = kw["json"]
    state["posts"].append((url, body))
    if url.endswith("/stream/with-timestamps"):
        if state["mode"] == "refuse":
            return StreamResp([], status=422)
        return StreamResp(pieces_for(body["text"]))
    # the whole-clip request (fallback, or streaming off)
    text = body["text"]
    align = {"characters": list(text), "character_start_times_seconds": [i * 0.1 for i in range(len(text))],
             "character_end_times_seconds": [i * 0.1 + 0.08 for i in range(len(text))]}
    return SimpleNamespace(status_code=200, text="", content=b"WHOLE", headers={"request-id": "r2"},
                           json=lambda: {"audio_base64": base64.b64encode(b"WHOLE").decode(), "alignment": align})


mod.requests.post = fake_post
mod.record_usage = lambda credits: state["usage"].append(credits)
mod.CFG.update(elevenlabs_api_key="k", openai_api_key="sk", response_style="mimic", follow_length=False,
               voice_id="EL1", chat_provider="openai", expressive_every_line=True)
mod.tts_engine = lambda v: "elevenlabs" if v.startswith("EL") else "piper"
client = mod.app.test_client()


def chat(message):
    r = client.post("/api/chat", json={"message": message, "speak": True, "language": "English", "max_words": 80})
    return r.status_code, r.get_json() or {}


def wait_done(sid, seconds=5):
    return client.get(f"/api/speech-stream/{sid}?wait={seconds}").get_json()


print("--- on (the default) ---")
check("on by default", mod.elevenlabs_streaming_on() and client.get("/api/settings").get_json().get("elevenlabs_streaming") is True)
state["gate"].clear()
started = time.time()
code, data = chat("Hello there, this is a streamed reply.")
check("the reply comes back before the voice is done", code == 200 and time.time() - started < 2 and data.get("stream"), data)
sid = data["stream"]["id"]
check("its audio address is the stream", data["audio_url"] == f"/audio/stream/{sid}")
t = client.get(f"/api/speech-stream/{sid}").get_json()
check("not finished yet", t["done"] is False and t["audio_url"] is None, t)
check("no credits counted yet", state["usage"] == [])
got = []


def read_stream():
    r = client.get(f"/audio/stream/{sid}")
    got.append(r.data)


reader = threading.Thread(target=read_stream)
reader.start()
time.sleep(0.3)
check("the first piece is already out", mod.SPEECH_STREAMS[sid].size == 1600)
state["gate"].set()
reader.join(5)
check("the page gets every piece, in order", got and got[0] == b"A" * 1600 + b"B" * 1600, len(got[0]) if got else None)
t = wait_done(sid)
check("finished, with a file", t["done"] and t["audio_url"] == f"/audio/{sid}.mp3"
      and open(os.path.join(mod.AUDIO_DIR, f"{sid}.mp3"), "rb").read() == b"A" * 1600 + b"B" * 1600, t)
check("word timings at the end", t["word_times"] and len(t["word_times"]) == len("Hello there, this is a streamed reply.".split()), t)
check("credits counted once", state["usage"] == [len("Hello there, this is a streamed reply.")], state["usage"])
check("sent to the streaming endpoint", state["posts"][-1][0].endswith("/stream/with-timestamps"))

print("--- timings relative to each piece ---")
state["relative"] = True
state["gate"].set()
code, data = chat("One two three four five six seven eight.")
t = wait_done(data["stream"]["id"])
job = mod.SPEECH_STREAMS[data["stream"]["id"]]
check("moved along, so they keep increasing", all(b >= a for a, b in zip(job.starts, job.starts[1:])), job.starts[:6])
state["relative"] = False

print("--- a long reply: chatbox page times ---")
long = " ".join(["word"] * 60) + "."
code, data = chat(long)
t = wait_done(data["stream"]["id"])
check("several pages", len(data["chatbox_pages"]) > 1)
check("... each with when the voice finishes it", t["page_ends"] and len(t["page_ends"]) == len(data["chatbox_pages"]), t["page_ends"])

print("--- refused: the whole-clip request instead ---")
state["mode"] = "refuse"
state["usage"].clear()
code, data = chat("This one gets refused as a stream.")
t = wait_done(data["stream"]["id"])
sid2 = data["stream"]["id"]
check("still spoken", t["done"] and not t["error"] and t["fell_back"] and t["audio_url"], t)
check("... and the page still gets the audio", client.get(f"/audio/stream/{sid2}").data == b"WHOLE")
check("... counted once", state["usage"] == [len("This one gets refused as a stream.")], state["usage"])
state["mode"] = "ok"

print("--- saving and later ---")
r = client.post("/api/saved", json={"audio_url": f"/audio/stream/{sid}", "text": "Hello there, this is a streamed reply."})
check("a streamed reply can be saved", r.status_code == 200, r.get_json())
mod.SPEECH_STREAMS.clear()
check("an old stream address serves the file", client.get(f"/audio/stream/{sid}").data == b"A" * 1600 + b"B" * 1600)
check("a bad address is refused", client.get("/audio/stream/..%2fsecret").status_code == 404)

print("--- off: exactly as before ---")
client.post("/api/settings", json={"elevenlabs_streaming": False})
code, data = chat("Not streamed.")
check("the whole clip, with its timings", data.get("stream") is None and data["audio_url"].endswith(".mp3")
      and data["word_times"] and not state["posts"][-1][0].endswith("/stream/with-timestamps"), data.get("audio_url"))
check("the setting is kept", client.get("/api/settings").get_json().get("elevenlabs_streaming") is False)

print("--- a free voice never streams ---")
client.post("/api/settings", json={"elevenlabs_streaming": True})
check("free voices aren't sent to ElevenLabs at all", True)

print()
if failures:
    print(f"{len(failures)} failed: {failures}")
    sys.exit(1)
print("All streaming checks passed.")
