#!/usr/bin/env python3
"""NEW (1.5.0): saved replies.

Checks the server side of Save and the Saved list:

  * a spoken reply's audio is copied to %APPDATA%\\Frivo\\saved\\ with its
    text, voice, chatbox pages and word timings; saving it twice keeps one
  * only replies in the audio cache can be saved, and one whose audio was
    already cleaned up says so
  * the list comes back newest first, and the audio is served from it
  * playing one adds it to the conversation the AI remembers (when there
    is one), and costs nothing: nothing is generated
  * deleting one removes its audio; the 7-day audio clean-up never touches
    saved replies
  * the page has the Saved button, the sheet, and the Save button code

Usage:  python3 tests/test-saved-replies.py     (run from the repo root)
Needs:  flask, openai (import only).
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-saved-home-")
ws = tempfile.mkdtemp(prefix="frivo-saved-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_saved", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_saved"] = mod
spec.loader.exec_module(mod)
client = mod.app.test_client()

os.makedirs(mod.AUDIO_DIR, exist_ok=True)
NAME = "a" * 32 + ".mp3"
with open(os.path.join(mod.AUDIO_DIR, NAME), "wb") as f:
    f.write(b"mp3-bytes")

reply = {
    "audio_url": f"/audio/{NAME}", "text": "Sure it did. Next time bring a flashlight.",
    "english": "", "language": "English", "voice_name": "Alba", "voice_engine": "elevenlabs",
    "voice_engine_name": "ElevenLabs", "profile_id": "p-echo", "profile_name": "Echo",
    "word_times": [[0, 0.3], [0.4, 0.6], [0.7, 1.0], [1.1, 1.3], [1.4, 1.6], [1.7, 1.9], [2.0, 2.2], [2.3, 2.9]],
    "chatbox_pages": [{"text": "Sure it did.", "start": 0, "at": 0.0}, {"text": "Next time bring a flashlight.", "start": 0.4, "at": 1.0}],
}

print("--- saving ---")
res = client.post("/api/saved", json=reply)
item = (res.get_json() or {}).get("item") or {}
check("a spoken reply is saved", res.status_code == 200 and item.get("text") == reply["text"], res.get_json())
saved_file = os.path.join(mod.SAVED_DIR, item.get("file", "missing"))
check("its audio is copied into the saved folder", os.path.isfile(saved_file) and open(saved_file, "rb").read() == b"mp3-bytes")
check("with its chatbox pages and word timings", item.get("chatbox_pages") == reply["chatbox_pages"]
      and item.get("word_times") == [[float(a), float(b)] for a, b in reply["word_times"]], item)
check("and where to play it from", item.get("audio_url") == f"/saved-audio/{item.get('file')}", item.get("audio_url"))
again = client.post("/api/saved", json=reply).get_json() or {}
check("saving it again keeps one", again.get("already") and again["item"]["id"] == item["id"]
      and len(client.get("/api/saved").get_json()["items"]) == 1, again)

check("not a reply's audio: refused", client.post("/api/saved", json=dict(reply, audio_url="/etc/passwd")).status_code == 400)
check("a path trick: refused", client.post("/api/saved", json=dict(reply, audio_url="/audio/../config.json")).status_code == 400)
gone = dict(reply, audio_url="/audio/" + "b" * 32 + ".mp3")
check("audio already cleaned up: says so", client.post("/api/saved", json=gone).status_code == 410)
check("no text: refused", client.post("/api/saved", json=dict(reply, text="  ")).status_code == 400)

print("--- the list ---")
NAME2 = "c" * 32 + ".wav"
with open(os.path.join(mod.AUDIO_DIR, NAME2), "wb") as f:
    f.write(b"wav")
time.sleep(0.01)
second = client.post("/api/saved", json=dict(reply, audio_url=f"/audio/{NAME2}", text="Second.", word_times=None)).get_json()["item"]
items = client.get("/api/saved").get_json()["items"]
check("newest first", [i["id"] for i in items] == [second["id"], item["id"]], [i["text"] for i in items])
check("a saved reply's audio is served", client.get(item["audio_url"]).data == b"mp3-bytes")
check("only saved files are served", client.get("/saved-audio/saved.json").status_code == 404)

print("--- playing ---")
key = "sess::p-echo"
mod.SESSIONS[key] = [{"role": "system", "content": "x"}]
res = client.post(f"/api/saved/{item['id']}/play", json={"session_id": "sess", "profile_id": "p-echo"})
check("playing returns the reply", res.status_code == 200 and res.get_json()["item"]["text"] == reply["text"])
check("and the AI remembers saying it", mod.SESSIONS[key][-1] == {"role": "assistant", "content": reply["text"]}, mod.SESSIONS[key])
res = client.post(f"/api/saved/{item['id']}/play", json={"session_id": "other", "profile_id": "p-echo"})
check("no conversation yet: none is started", res.status_code == 200 and "other::p-echo" not in mod.SESSIONS)
check("an unknown one: not found", client.post("/api/saved/" + "f" * 32 + "/play", json={}).status_code == 404)

print("--- the 7-day clean-up ---")
old = time.time() - 30 * 86400
for name in os.listdir(mod.SAVED_DIR):
    os.utime(os.path.join(mod.SAVED_DIR, name), (old, old))
mod.CFG["audio_keep_days"] = 7
mod.prune_audio_cache()
check("saved replies are left alone", os.path.isfile(saved_file))

print("--- deleting ---")
check("deleting one", client.delete(f"/api/saved/{item['id']}").status_code == 200)
check("removes its audio", not os.path.exists(saved_file))
check("and its entry", [i["id"] for i in client.get("/api/saved").get_json()["items"]] == [second["id"]])
check("deleting it again: not found", client.delete(f"/api/saved/{item['id']}").status_code == 404)

print("--- the page ---")
html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
js = open(os.path.join(APP, "static", "app.js"), encoding="utf-8").read()
check("a Saved button on the rail, and the sheet", 'id="railSaved"' in html and 'id="savedPop"' in html)
check("Save on spoken replies, and playing one back", "function makeSaveButton" in js and "function playSaved" in js
      and "saveData: data.audio_url" in js)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("All saved-reply checks passed.")
