#!/usr/bin/env python3
"""NEW (1.5.0): chatbox pages that follow the voice, and audio pruning.

FrivOSC used to page a long spoken reply on a fixed 1.6-second timer, far
quicker than anyone talks. Frivo now pages a spoken reply itself, and the
page sends each page when the voice reaches it. This checks:

  * Frivo's pager matches FrivOSC's (if ../FrivOSC is next to this repo),
    and every page fits in one chatbox message, so FrivOSC passes it on
    unchanged
  * the timing plan starts at 0, only goes up, and stays below 1
  * /api/chat returns chatbox_pages (Word for word in English, so no AI or
    key is needed)
  * in node, with a fake clock: page 1 goes when the voice starts, later
    pages go just before the voice reaches them, a pause holds the next
    page, skipping ahead sends only the latest due page, the end sends
    whatever is left, and the Chatbox switch off stops it
  * exact timing: each page after the first is timed to the moment the
    voice finishes the last word of the page before. That comes from
    ElevenLabs' per-character timings, or from speaking Windows voices one
    page at a time. A refused ElevenLabs request falls back
    without being billed twice, and a free voice that fails falls back to
    the estimate
  * pruning deletes old reply audio and leftover job files, and keeps
    previews, recent files and anything Frivo didn't make

Usage:  python3 tests/test-chatbox-follow.py     (run from the repo root)
Needs:  flask, node.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
FRIVOSC = os.path.join(os.path.dirname(ROOT), "FrivOSC", "frivosc_service.py")
failures = []

LONG = ("Okay so here is the thing about the backrooms world. The lights hum all the time, "
        "and if you stand still long enough you start to hear footsteps that are not yours. "
        "Honestly, I think that's the best part. We added a level last week, with wet carpet, "
        "yellow walls, and a door that only opens when nobody is looking at it. "
        "Come by tonight and I'll show you around, but bring a flashlight, seriously.")


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    # CHANGED (1.5.0): these checks are for the whole-clip request; streaming is in test-speech-stream.py.
    mod.CFG["elevenlabs_streaming"] = False
    return mod


def server_side():
    print("--- the server ---")
    ws = tempfile.mkdtemp(prefix="frivo-follow-")
    shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
    mod = load(os.path.join(ws, "app.py"), "frivo_follow")

    samples = [LONG, "Short one.", "word " * 80, "No punctuation at all " * 12,
               "!!! " + LONG + " ...", "a" * 400]
    if os.path.exists(FRIVOSC):
        osc = load(FRIVOSC, "frivosc_follow")
        check("pager matches FrivOSC's",
              all(mod.chatbox_pages(t) == osc.chatbox_pages(t) for t in samples))
        # Every page passes through FrivOSC unchanged, so no version of it
        # re-pages or re-numbers what Frivo sends.
        check("FrivOSC sends each page exactly as it is",
              all(osc.chatbox_pages(p) == [p] for t in samples for p in mod.chatbox_pages(t)))
    else:
        print("  SKIP  FrivOSC isn't next to this repo")

    check("every page fits a chatbox message",
          all(len(p) <= 144 for t in samples for p in mod.chatbox_pages(t)))

    plan = mod.chatbox_page_plan(LONG)
    starts = [p["start"] for p in plan]
    check("a long reply is several pages", len(plan) >= 3, len(plan))
    check("page 1 starts at 0", starts[0] == 0.0, starts)
    check("starts only go up", all(a < b for a, b in zip(starts, starts[1:])), starts)
    check("every start is before the end", all(s < 1 for s in starts), starts)
    check("a short reply is one page at 0",
          mod.chatbox_page_plan("Hi there.") == [{"text": "Hi there.", "start": 0.0}])
    check("nothing to say is no pages", mod.chatbox_page_plan("") == [])

    # /api/chat: Word for word in English uses no AI, so no key is needed.
    mod.CFG.update(response_style="mimic", follow_length=False, language="English")
    client = mod.app.test_client()
    res = client.post("/api/chat", json={"message": LONG, "speak": False,
                                         "language": "English", "max_words": 400})
    data = res.get_json() or {}
    check("/api/chat answers", res.status_code == 200, (res.status_code, data.get("error")))
    check("/api/chat returns the pages",
          data.get("chatbox_pages") == mod.chatbox_page_plan(data.get("reply", "")),
          data.get("chatbox_pages"))

    print("--- pruning ---")
    cache = tempfile.mkdtemp(prefix="frivo-audio-")
    mod.AUDIO_DIR = cache
    now = time.time()
    day = 86400
    files = {
        "a" * 32 + ".mp3": 10 * day,     # old reply: goes
        "b" * 32 + ".wav": 8 * day,      # old free-voice reply: goes
        "c" * 32 + ".mp3": 1 * day,      # recent reply: stays
        "d" * 32 + ".json": 2 * day,     # leftover job: goes
        "e" * 32 + ".json": 60,          # job in use: stays
        "preview-0123456789abcdef.wav": 100 * day,   # preview: stays
        "notes.txt": 100 * day,          # not Frivo's: stays
        "A" * 32 + ".mp3": 100 * day,    # not a name Frivo makes: stays
    }
    for name, age in files.items():
        path = os.path.join(cache, name)
        with open(path, "wb") as f:
            f.write(b"x" * 1000)
        os.utime(path, (now - age, now - age))

    mod.CFG["audio_keep_days"] = 0
    check("0 days keeps everything", mod.prune_audio_cache(now) == (0, 0))
    mod.CFG["audio_keep_days"] = 7
    removed, freed = mod.prune_audio_cache(now)
    left = set(os.listdir(cache))
    check("removes the three it should", removed == 3 and freed == 3000, (removed, freed))
    check("keeps the rest", left == {"c" * 32 + ".mp3", "e" * 32 + ".json",
                                     "preview-0123456789abcdef.wav", "notes.txt",
                                     "A" * 32 + ".mp3"}, sorted(left))
    mod.CFG["audio_keep_days"] = "nonsense"
    check("a bad setting falls back to 7 days", mod.prune_audio_cache(now) == (0, 0))
    os.utime(os.path.join(cache, "c" * 32 + ".mp3"), (now - 3 * day, now - 3 * day))
    mod.CFG["audio_keep_days"] = 2
    check("the setting is honoured", mod.prune_audio_cache(now)[0] == 1)
    check("a missing folder is fine", (setattr(mod, "AUDIO_DIR", os.path.join(cache, "gone"))
                                       or mod.prune_audio_cache(now)) == (0, 0))
    timed_side(mod)
    return plan


def timed_side(mod):
    print("--- exact timing ---")
    import base64
    import wave
    from types import SimpleNamespace
    import numpy as np

    cache = tempfile.mkdtemp(prefix="frivo-timed-")
    mod.AUDIO_DIR = cache
    plan = mod.chatbox_page_plan(LONG)
    bodies = [mod._CHATBOX_COUNTER_RE.sub("", p["text"]) for p in plan]

    # Fake ElevenLabs timings: character i of the original text ends at i/20 s.
    alignment = {"characters": list(LONG),
                 "character_end_times_seconds": [i / 20 for i in range(len(LONG))]}
    want, seen = [], 0
    for body in bodies:
        seen += len(body.replace(" ", ""))
        # The seen-th non-space character in the original text.
        idx = [i for i, c in enumerate(LONG) if not c.isspace()][seen - 1]
        want.append(idx / 20)
    got = mod.page_ends_from_alignment(bodies, alignment)
    check("ElevenLabs timings: each page ends on its last character", got == want, (got, want))
    check("timings that don't line up are refused",
          mod.page_ends_from_alignment(bodies, {"characters": list("abc"),
                                                "character_end_times_seconds": [1, 2, 3]}) is None)

    calls = []

    def post(answer):
        def fake(url, **kw):
            calls.append(url)
            return answer(url)
        return fake

    timed_ok = lambda url: SimpleNamespace(status_code=200, text="", content=b"mp3", json=lambda: {
        "audio_base64": base64.b64encode(b"mp3").decode(), "alignment": alignment})
    mod.CFG.update(elevenlabs_api_key="k", speaking_speed=1.0)
    mod.requests.post = post(timed_ok)
    name, ends = mod.get_tts_audio_timed(LONG, "EL1", "English", plan)
    check("ElevenLabs: one timed request", calls == [
        "https://api.elevenlabs.io/v1/text-to-speech/EL1/with-timestamps"], calls)
    check("ElevenLabs: audio saved, times returned",
          open(os.path.join(cache, name), "rb").read() == b"mp3" and ends == want)

    calls.clear()
    mod.requests.post = post(lambda url: SimpleNamespace(status_code=200, content=b"mp3", text="")
                             if "with-timestamps" not in url else
                             SimpleNamespace(status_code=422, text="nope", content=b""))
    name, ends = mod.get_tts_audio_timed(LONG, "EL1", "English", plan)
    check("ElevenLabs refused: falls back to the plain request", len(calls) == 2 and ends is None, calls)

    calls.clear()
    mod.requests.post = post(lambda url: SimpleNamespace(status_code=200, text="", json=lambda: {}))
    try:
        mod.get_tts_audio_timed(LONG, "EL1", "English", plan)
        raised = False
    except Exception:
        raised = True
    check("ElevenLabs accepted but unreadable: no second (billed) request", raised and len(calls) == 1, calls)

    # CHANGED (1.5.0): Windows voices, through a stand-in for the speech
    # helper that writes each page's wave (10 ms per character). Kokoro has
    # been removed.
    fake = os.path.join(cache, "fake_helper.py")
    with open(fake, "w", encoding="utf-8") as f:
        f.write(
            "import json, sys, wave\n"
            "for raw in sys.stdin.buffer:\n"
            "    req = json.loads(raw)\n"
            "    if req.get('voice') == 'Broken':\n"
            "        print('@@FRIVO ' + json.dumps({'ok': False, 'error': 'boom'}), flush=True); continue\n"
            "    for page, out in zip(req.get('pages', []), req.get('outs', [])):\n"
            "        w = wave.open(out, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)\n"
            "        w.writeframes(b'\\0\\0' * (160 * len(page))); w.close()\n"
            "    print('@@FRIVO ' + json.dumps({'ok': True}), flush=True)\n")
    mod.WINDOWS_SPEECH = mod.WindowsSpeechHost(command=[sys.executable, fake])
    name, ends = mod.get_tts_audio_timed(LONG, mod.ONECORE_PREFIX + "MSTTS_V110_enUS_ZiraM", "English", plan)
    sums = np.cumsum([len(b) * 160 for b in bodies]) / 16000
    with wave.open(os.path.join(cache, name), "rb") as w:
        frames = w.getnframes()
    check("Windows: each page ends where its clip ends",
          ends is not None and np.allclose(ends, sums), (ends, list(sums)))
    check("Windows: one file with every page in it", frames == sum(len(b) * 160 for b in bodies), frames)
    left = [n for n in os.listdir(cache) if ".part." in n]
    check("Windows: page parts are cleaned up", left == [], left)

    mod.free_tts_audio = lambda text, voice_id, language: "fallback.wav"
    name, ends = mod.get_tts_audio_timed(LONG, mod.ONECORE_PREFIX + "Broken", "English", plan)
    check("a free voice that fails falls back to the estimate", (name, ends) == ("fallback.wav", None))
    mod.WINDOWS_SPEECH.close()

    # Through /api/chat, with ElevenLabs.
    mod.requests.post = post(timed_ok)
    mod.record_usage = lambda credits: None
    mod.CFG.update(response_style="mimic", follow_length=False, voice_id="EL1")
    res = mod.app.test_client().post("/api/chat", json={"message": LONG, "speak": True,
                                                         "language": "English", "max_words": 400})
    data = res.get_json() or {}
    ats = [p.get("at") for p in data.get("chatbox_pages") or []]
    check("/api/chat: page 1 at 0, each later page when the last one's words end",
          res.status_code == 200 and ats == [0.0] + [round(e, 3) for e in want[:-1]], (res.status_code, ats, data.get("error")))


NODE_HARNESS = r"""
const fs = require("fs");
const js = fs.readFileSync(process.argv[2], "utf8").replace(/\r\n/g, "\n");
const start = js.indexOf("const CHATBOX_PAGE_LEAD_SECONDS");
const end = js.indexOf("\n}\n", js.indexOf("function makeChatboxFollower")) + 3;
if (start < 0 || end < 3) { console.log(JSON.stringify({ error: "follower not found" })); process.exit(0); }

let clock = 0;                       // seconds
let timers = [];
const sent = [];
let typingEnds = 0, osc = true;
const env = {
  performance: { now: () => clock * 1000 },
  setTimeout: (fn, ms) => { const t = { at: clock + ms / 1000, fn }; timers.push(t); return t; },
  clearTimeout: (t) => { timers = timers.filter((x) => x !== t); },
  sendToChatbox: (text, opts) => sent.push({ text, at: +clock.toFixed(2), keep: opts.keepTyping }),
  beginReplyTyping: () => {}, endReplyTyping: () => { typingEnds++; },
  oscEnabled: () => osc, oscConfigured: true, Infinity,
};
const make = new Function(...Object.keys(env), js.slice(start, end) + "\nreturn makeChatboxFollower;")(...Object.values(env));

function runUntil(t) {
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const next = timers[0];
    if (!next || next.at > t) break;
    timers.shift(); clock = next.at; next.fn();
  }
  clock = t;
}
const pages = [{ text: "one", start: 0 }, { text: "two", start: 0.3 }, { text: "three", start: 0.6 }, { text: "four", start: 0.9 }];
const out = {};

// Plays straight through: 20 s of audio.
let f = make(pages);
f.update(true, 0, 20); runUntil(20); f.update(false, 20, 20);
out.straight = sent.splice(0); out.straightEnds = typingEnds; typingEnds = 0;

// Paused at 7 s for a minute, then played on.
clock = 0; timers = []; f = make(pages);
f.update(true, 0, 20); runUntil(7); f.update(false, 7, 20); runUntil(67);
out.paused = sent.slice(0); f.update(true, 7, 20); runUntil(80); f.update(false, 20, 20);
out.resumed = sent.splice(0);

// Started again from 15 s in (skipped ahead): only the latest due page.
clock = 0; timers = []; f = make(pages);
f.update(true, 15, 20); runUntil(20); f.update(false, 20, 20);
out.skipped = sent.splice(0);

// Stopped by hand at 5 s, never played again: nothing more is sent.
clock = 0; timers = []; f = make(pages);
f.update(true, 0, 20); runUntil(5); f.update(false, 5, 20); runUntil(60);
out.stopped = sent.splice(0);

// Chatbox switched off at 10 s.
clock = 0; timers = []; typingEnds = 0; f = make(pages);
f.update(true, 0, 20); runUntil(10); osc = false; runUntil(20); f.update(false, 20, 20);
out.off = sent.splice(0); out.offEnds = typingEnds; osc = true;

// The audio ended a bit before the last page was due (an estimate that ran long).
clock = 0; timers = []; f = make([{ text: "a", start: 0 }, { text: "b", start: 0.99 }]);
f.update(true, 0, 10); runUntil(9.4); f.update(false, 10, 10);
out.early = sent.splice(0);

// Exact times: page two at 6.0 s and three at 13.0 s (the "at" wins over the
// estimate's 30%/60%).
clock = 0; timers = []; f = make([{ text: "x", start: 0, at: 0 }, { text: "y", start: 0.3, at: 6 }, { text: "z", start: 0.6, at: 13 }]);
f.update(true, 0, 20); runUntil(20); f.update(false, 20, 20);
out.exact = sent.splice(0);
console.log(JSON.stringify(out));
"""


def browser_side():
    print("--- the page (node, fake clock) ---")
    if not shutil.which("node"):
        print("  SKIP  node isn't installed")
        return
    harness = os.path.join(tempfile.mkdtemp(prefix="frivo-follow-js-"), "harness.js")
    with open(harness, "w", encoding="utf-8") as f:
        f.write(NODE_HARNESS)
    run = subprocess.run(["node", harness, os.path.join(APP, "static", "app.js")],
                         capture_output=True, text=True, timeout=60)
    try:
        out = json.loads(run.stdout.strip().splitlines()[-1])
    except Exception:
        check("harness runs", False, run.stderr[-500:] or run.stdout[-500:])
        return
    if out.get("error"):
        check("follower found in app.js", False, out["error"])
        return

    at = lambda rows: [(r["text"], r["at"]) for r in rows]
    # 20 s of audio, 0.4 s early: pages at 0, 5.6, 11.6, 17.6.
    check("straight through: each page just before the voice",
          at(out["straight"]) == [("one", 0), ("two", 5.6), ("three", 11.6), ("four", 17.6)],
          at(out["straight"]))
    check("dots kept up between pages, not after the last",
          [r["keep"] for r in out["straight"]] == [True, True, True, False],
          [r["keep"] for r in out["straight"]])
    check("a pause holds the next page", at(out["paused"]) == [("one", 0), ("two", 5.6)],
          at(out["paused"]))
    check("playing on carries on from the voice",
          at(out["resumed"]) == [("one", 0), ("two", 5.6), ("three", 71.6), ("four", 77.6)],
          at(out["resumed"]))
    check("skipping ahead sends only the latest due page",
          # The clock starts at 0 when it plays from 15 s, so page four
          # (due at 17.6 s in the audio) goes 2.6 s later.
          at(out["skipped"]) == [("three", 0), ("four", 2.6)], at(out["skipped"]))
    # Stopped at 5 s, before page two was due at 5.6 s.
    check("stopped by hand: nothing more", at(out["stopped"]) == [("one", 0)],
          at(out["stopped"]))
    check("chatbox off: stops, and the dots come down",
          at(out["off"]) == [("one", 0), ("two", 5.6)] and out["offEnds"] == 1,
          (at(out["off"]), out["offEnds"]))
    check("exact times: each page just as the last word ends",
          at(out["exact"]) == [("x", 0), ("y", 5.85), ("z", 12.85)], at(out["exact"]))
    check("audio ending first still shows the last page",
          [r["text"] for r in out["early"]] == ["a", "b"], at(out["early"]))


if __name__ == "__main__":
    server_side()
    browser_side()
    print()
    if failures:
        print(f"{len(failures)} failed: " + ", ".join(failures))
        sys.exit(1)
    print("All passed.")
