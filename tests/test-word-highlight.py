#!/usr/bin/env python3
"""NEW (1.5.0): the timings behind the word highlight.

The highlight follows the voice only when the timing is exact, so this
checks the server side of that:

  * ElevenLabs' per-character timings become one [start, end] per word, and
    timings that don't follow the text exactly give none
  * a Windows voice's word boundaries become the same, across pages, with
    punctuation-only words sharing the word before's time; a missing word
    gives none
  * /api/chat sends word_times for ElevenLabs (every reply, one page or
    many, through the with-timestamps request) and none for Frivo's own
    voices, which don't report words

Usage:  python3 tests/test-word-highlight.py     (run from the repo root)
Needs:  flask, openai (import only).
"""

import base64
import importlib.util
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-words-home-")
ws = tempfile.mkdtemp(prefix="frivo-words-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_words", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_words"] = mod
spec.loader.exec_module(mod)
# CHANGED (1.5.0): these checks are for the whole-clip request; streaming is in test-speech-stream.py.
mod.CFG["elevenlabs_streaming"] = False

TEXT = "Hey there,  friend. Ready?"
# Character i starts at i/10 s and ends at i/10 + 0.08 s.
ALIGN = {"characters": list(TEXT),
         "character_start_times_seconds": [i / 10 for i in range(len(TEXT))],
         "character_end_times_seconds": [i / 10 + 0.08 for i in range(len(TEXT))]}

print("--- ElevenLabs ---")
got = mod.word_times_from_alignment(TEXT, ALIGN)
check("one [start, end] per word", got == [[0.0, 0.28], [0.4, 0.98], [1.2, 1.88], [2.0, 2.58]], got)
bad = dict(ALIGN, characters=list(TEXT.replace("friend", "frienb")))
check("timings for different text: none", mod.word_times_from_alignment(TEXT, bad) is None)
check("no alignment: none", mod.word_times_from_alignment(TEXT, None) is None)
check("lists of different lengths: none",
      mod.word_times_from_alignment(TEXT, dict(ALIGN, character_start_times_seconds=[0.0])) is None)

print("--- Windows ---")
pages = ["Hello there, friend —", "how are you?"]
# [character position, length, seconds into the page]
bounds = [[[0, 5, 0.0], [6, 6, 0.4], [13, 6, 0.9]], [[0, 3, 0.0], [4, 3, 0.3], [8, 4, 0.5]]]
got = mod.word_times_from_boundaries(pages, bounds, [1.5, 2.6])
want = [[0.0, 0.4], [0.4, 0.9], [0.9, 0.9], [0.9, 1.5], [1.5, 1.8], [1.8, 2.0], [2.0, 2.6]]
check("words across pages, the dash shares 'friend's time", got == want, got)
check("a word with no boundary: none",
      mod.word_times_from_boundaries(pages, [bounds[0][:2], bounds[1]], [1.5, 2.6]) is None)
check("no boundaries reported: none", mod.word_times_from_boundaries(pages, None, [1.5, 2.6]) is None)

print("--- /api/chat ---")
mod.AUDIO_DIR = tempfile.mkdtemp(prefix="frivo-words-audio-")
posts = []


def fake_post(url, **kw):
    posts.append(url)
    text = kw["json"]["text"]
    align = {"characters": list(text),
             "character_start_times_seconds": [i / 10 for i in range(len(text))],
             "character_end_times_seconds": [i / 10 + 0.08 for i in range(len(text))]}
    return SimpleNamespace(status_code=200, text="", content=b"mp3",
                           json=lambda: {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": align})


mod.requests.post = fake_post
mod.record_usage = lambda credits: None
mod.CFG.update(elevenlabs_api_key="k", response_style="mimic", follow_length=False, voice_id="EL1",
               speaking_speed=1.0)
client = mod.app.test_client()
res = client.post("/api/chat", json={"message": "Short and sweet.", "speak": True, "language": "English",
                                      "max_words": 80})
data = res.get_json() or {}
check("ElevenLabs, one page: timed request", posts and posts[-1].endswith("/with-timestamps"), posts)
check("ElevenLabs, one page: a time for every word",
      res.status_code == 200 and len(data.get("word_times") or []) == 3, (res.status_code, data.get("word_times"), data.get("error")))

mod.CFG.update(voice_id="piper:alba")
mod.piper_problem = lambda *a, **k: None   # no voice files in a test
mod.free_tts_audio = lambda text, voice_id, language: "piper.wav"
mod.get_tts_audio = lambda text, voice_id, language="English": "piper.wav"
res = client.post("/api/chat", json={"message": "Short and sweet.", "speak": True, "language": "English",
                                      "max_words": 80})
data = res.get_json() or {}
check("Frivo's own voice: no word times (not exact)", res.status_code == 200 and data.get("word_times") is None,
      (res.status_code, data.get("word_times"), data.get("error")))

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("All word-highlight checks passed.")
