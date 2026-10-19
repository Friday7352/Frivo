#!/usr/bin/env python3
"""NEW (1.5.0): voice tags (ElevenLabs audio tags) and Delivery.

  * tags are taken out, tidied, and put back after a suggestion without
    changing a word; they don't count as words
  * what ElevenLabs is sent: Natural with no tags is exactly what Frivo
    always sent; a tag (or Expressive voice) uses v3; Calm and Lively
    change the voice settings
  * /api/chat: the voice gets the tags, the chatbox, word count and word
    highlight don't; a free voice never gets them; Expressive voice tells
    the AI how to use them; Calm drops [shouts]; a refused v3 still speaks
  * /api/voice-tags/suggest adds tags and keeps every word
  * the settings are kept on profiles and in Settings, and the prompt
    preview shows the rules

Usage:  python3 tests/test-voice-tags.py     (run from the repo root)
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


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-tags-home-")
ws = tempfile.mkdtemp(prefix="frivo-tags-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_tags", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_tags"] = mod
spec.loader.exec_module(mod)

print("--- the tags themselves ---")
check("taken out cleanly", mod.strip_audio_tags("[laughs] Okay, fine. [sighs] That's [whispers] ours!")
      == "Okay, fine. That's ours!", mod.strip_audio_tags("[laughs] Okay, fine. [sighs] That's [whispers] ours!"))
check("tidied: lowercase, spaced, after punctuation",
      mod.tidy_audio_tags("[Laughs]okay, fine [SIGHS]. Sure") == "[laughs] okay, fine. [sighs] Sure",
      mod.tidy_audio_tags("[Laughs]okay, fine [SIGHS]. Sure"))
check("not counted as words", mod.count_words("[laughs] one two [clears throat] three") == 3)
got = mod.transplant_audio_tags("I can't believe you did that.", "[gasps] I cannot believe you did [laughs] that!")
check("a suggestion keeps every word", mod.strip_audio_tags(got) == "I can't believe you did that.", got)
check("... and its tags", got.count("[") == 2, got)

print("--- what ElevenLabs is sent ---")
mod.CFG.update(speaking_speed=1.0, voice_delivery="natural", expressive_voice=False)
plain = mod._elevenlabs_payload("Hello there.")
check("Natural, no tags: exactly as before",
      plain == {"text": "Hello there.", "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}, plain)
tagged = mod._elevenlabs_payload("[laughs] Hello there.")
check("a tag: v3, with the tag", tagged["model_id"] == "eleven_v3" and tagged["text"].startswith("[laughs]"), tagged)
check("v3 is told the language, so the accent holds", tagged.get("language_code") == "en" and "seed" in tagged, tagged)
mod.CFG.update(speaking_speed=1.1)
check("v3 has no speed setting", "speed" not in mod._elevenlabs_payload("[laughs] Hi.")["voice_settings"])
check("v2 still gets the speed", mod._elevenlabs_payload("Hi.")["voice_settings"].get("speed") == 1.1)
mod.CFG.update(speaking_speed=1.0, voice_delivery="calm")
check("Calm: steadier v2", mod._elevenlabs_payload("Hi.")["voice_settings"]["stability"] == 0.75)
check("Calm: Robust v3", mod._elevenlabs_payload("[softly] Hi.")["voice_settings"] == {"stability": 1.0})
mod.CFG.update(voice_delivery="lively")
lively = mod._elevenlabs_payload("Hi.")["voice_settings"]
check("Lively: looser, with style", lively["stability"] == 0.3 and lively.get("style") == 0.35, lively)
check("Lively on v3: Natural, never Creative", mod._elevenlabs_payload("[laughs] Hi.")["voice_settings"]["stability"] == 0.5)
mod.CFG.update(voice_delivery="natural")
check("Natural on v3: Natural (the stitching below holds the accent)", mod._elevenlabs_payload("[laughs] Hi.")["voice_settings"]["stability"] == 0.5)
mod.CFG.update(voice_delivery="natural", expressive_voice=True)
check("Expressive voice: v3 even with no tag", mod._elevenlabs_payload("Hi.")["model_id"] == "eleven_v3")
check("the fallback drops the tags", mod._elevenlabs_payload("[laughs] Hi.", force_v2=True)["text"] == "Hi.")
mod.CFG.update(expressive_voice=False)

print("--- the AI's instructions ---")
p = mod.build_system_prompt("Fun.", 80, "English", "reply", voice_style={"expressive": True, "delivery": "natural"})
check("Expressive: told about tags", "VOICE TAGS" in p and "[laughs]" in p)
p = mod.build_system_prompt("Fun.", 80, "English", "reply", voice_style={"expressive": False, "delivery": "calm"})
check("Calm: told not to shout in writing", "ALL CAPITALS" in p and "VOICE TAGS" not in p)
p = mod.build_system_prompt("Fun.", 80, "Spanish", "mimic", voice_style={"expressive": True, "delivery": "natural"})
check("Word for word: keeps your tags, adds none", "AUDIO TAGS" in p and "VOICE TAGS" not in p)
check("a free voice: nothing added", "TAGS" not in mod.build_system_prompt("Fun.", 80, "English", "reply"))

print("--- /api/chat ---")
mod.AUDIO_DIR = tempfile.mkdtemp(prefix="frivo-tags-audio-")
posts = []
refuse_v3 = {"on": False}


def fake_post(url, **kw):
    body = kw["json"]
    posts.append((url, body))
    if refuse_v3["on"] and body["model_id"] == "eleven_v3":
        return SimpleNamespace(status_code=422, text="model not available", content=b"", json=lambda: {})
    text = body["text"]
    align = {"characters": list(text),
             "character_start_times_seconds": [i / 10 for i in range(len(text))],
             "character_end_times_seconds": [i / 10 + 0.08 for i in range(len(text))]}
    return SimpleNamespace(status_code=200, text="", content=b"mp3", headers={"request-id": f"req{len(posts)}"},
                           json=lambda: {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": align})


mod.requests.post = fake_post
mod.record_usage = lambda credits: None
mod.CFG.update(elevenlabs_api_key="k", openai_api_key="sk", response_style="mimic", follow_length=False,
               voice_id="EL1", chat_provider="openai")
client = mod.app.test_client()


def chat(message, **extra):
    body = {"message": message, "speak": True, "language": "English", "max_words": 80}
    body.update(extra)
    res = client.post("/api/chat", json=body)
    return res.status_code, res.get_json() or {}


status, data = chat("[whispers] It's a secret. [laughs] Don't tell.")
url, sent = posts[-1]
check("your tags reach the voice", "[whispers]" in sent["text"] and sent["model_id"] == "eleven_v3", sent)
check("the reply shown and sent to the chatbox has none",
      status == 200 and "[" not in data.get("reply", "") and all("[" not in p["text"] for p in data["chatbox_pages"]), data)
check("'voiced' keeps them", data.get("voiced", "").startswith("[whispers]"), data.get("voiced"))
check("the highlight still has a time per word", len(data.get("word_times") or []) == 5, data.get("word_times"))
check("the tags are counted as credits", data.get("credits") == len(data.get("voiced", "")), data.get("credits"))
check("word count leaves them out", data.get("word_count") == 5, data.get("word_count"))

first_id = "req%d" % len(posts)
status, data = chat("No tags in this one.")
check("after a tag, the next message stays on v3 (no accent jump)", posts[-1][1]["model_id"] == "eleven_v3", posts[-1][1])
check("... and is told to match what the voice just said",
      posts[-1][1].get("previous_request_ids") == [first_id] and "[whispers]" in posts[-1][1].get("previous_text", ""),
      {k: posts[-1][1].get(k) for k in ("previous_request_ids", "previous_text")})
status, data = chat("A third one.")
status, data = chat("A fourth one.")
check("at most the last three", len(posts[-1][1].get("previous_request_ids") or []) == 3, posts[-1][1].get("previous_request_ids"))
status, data = chat("Another, from a different page.", session_id="other")
check("... but another conversation starts on the usual model, with no stitching",
      posts[-1][1]["model_id"] == "eleven_multilingual_v2" and "previous_request_ids" not in posts[-1][1], posts[-1][1])
spoken_free = []
mod.CFG.update(voice_id="piper:alba")
mod.piper_problem = lambda *a, **k: None
mod.free_tts_audio = lambda text, voice_id, language: spoken_free.append(text) or "piper.wav"
orig_get_tts = mod.get_tts_audio
mod.get_tts_audio = lambda text, voice_id, language="English": spoken_free.append(text) or "piper.wav"
status, data = chat("[whispers] It's a secret.")
check("a free voice never hears a tag", status == 200 and spoken_free and "[" not in spoken_free[-1], (status, spoken_free, data.get("error")))
check("... and none are shown as voiced", data.get("voiced") == data.get("reply"), data)
mod.get_tts_audio = orig_get_tts
mod.CFG.update(voice_id="EL1")

sent_prompts = []
model_says = {"text": ""}


def fake_completion(client, **kw):
    sent_prompts.append(kw["messages"])
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=model_says["text"]),
                                                    finish_reason="stop")])


mod.create_chat_completion = fake_completion
mod.make_openai_client = lambda: None
res = client.post("/api/profiles", json={"name": "Actor", "voice_id": "EL1", "voice_name": "Rachel",
                                         "response_style": "reply", "expressive_voice": True,
                                         "voice_delivery": "calm"})
actor = (res.get_json() or {}).get("profile", {})
check("a profile keeps Expressive voice and Delivery",
      actor.get("expressive_voice") is True and actor.get("voice_delivery") == "calm", actor)
model_says["text"] = "[laughs] Oh, that is great [shouts]. [british accent] Anyway, carry on."
status, data = chat("I finished the world!", profile_id=actor["id"])
check("the AI was told about tags", any("VOICE TAGS" in m["content"] for m in sent_prompts[-1] if m["role"] == "system"))
check("Calm takes out [shouts]", "[shouts]" not in data.get("voiced", "") and "[laughs]" in data.get("voiced", ""),
      data.get("voiced"))
check("an accent tag the AI added is taken out", "accent" not in data.get("voiced", ""), data.get("voiced"))
check("the reply reads without tags", data.get("reply") == "Oh, that is great. Anyway, carry on.", data.get("reply"))
check("Expressive voice speaks with v3, Robust", posts[-1][1]["model_id"] == "eleven_v3"
      and posts[-1][1]["voice_settings"] == {"stability": 1.0}, posts[-1][1])
history = mod.SESSIONS.get(f"default::{actor['id']}", [])
check("the AI's memory keeps its tags", history and "[laughs]" in history[-1]["content"], history[-1:] if history else None)

refuse_v3["on"] = True
status, data = chat("I finished the world!", profile_id=actor["id"])
check("v3 refused: still spoken, by the usual model, without tags",
      status == 200 and posts[-1][1]["model_id"] == "eleven_multilingual_v2" and "[" not in posts[-1][1]["text"],
      (status, posts[-1][1], data.get("error")))
refuse_v3["on"] = False

res = client.put(f"/api/profiles/{actor['id']}", json={"expressive_voice": False, "voice_delivery": "lively"})
p = (res.get_json() or {}).get("profile", {})
check("... and changes them", p.get("expressive_voice") is False and p.get("voice_delivery") == "lively", p)
res = client.put(f"/api/profiles/{actor['id']}", json={"expressive_voice": True, "voice_delivery": "nonsense"})
p = (res.get_json() or {}).get("profile", {})
check("an unknown delivery keeps the last one", p.get("voice_delivery") == "lively", p)

print("--- Suggest ---")
model_says["text"] = "<MESSAGE>[excited] Guess what, I got the job! [laughs] Finally.</MESSAGE>"
res = client.post("/api/voice-tags/suggest", json={"text": "Guess what, I got the job! Finally."})
data = res.get_json() or {}
check("tags added, every word kept", res.status_code == 200 and data.get("added") == 2
      and mod.strip_audio_tags(data.get("text", "")) == "Guess what, I got the job! Finally.", data)
check("each new tag, with the word it goes before", data.get("ideas") == [{"at": 0, "tag": "excited"}, {"at": 6, "tag": "laughs"}],
      data.get("ideas"))
model_says["text"] = "[excited] Guess what, I got the job! [laughs] Finally."
res = client.post("/api/voice-tags/suggest", json={"text": "[excited] Guess what, I got the job! Finally."})
check("a tag you already had isn't an idea", (res.get_json() or {}).get("ideas") == [{"at": 6, "tag": "laughs"}],
      (res.get_json() or {}).get("ideas"))
model_says["text"] = "[sad] Guess what, I received the position! Finally."
res = client.post("/api/voice-tags/suggest", json={"text": "Guess what, I got the job! Finally."})
data = res.get_json() or {}
check("reworded by the AI: your words are put back", mod.strip_audio_tags(data.get("text", ""))
      == "Guess what, I got the job! Finally." and data.get("added") == 1, data)
res = client.post("/api/voice-tags/suggest", json={"text": "  [laughs] "})
check("nothing typed: says so", res.status_code == 400)

print("--- Settings and the prompt preview ---")
res = client.post("/api/settings", json={"expressive_voice": True, "voice_delivery": "calm"})
got = client.get("/api/settings").get_json()
check("Settings keeps them", got.get("expressive_voice") is True and got.get("voice_delivery") == "calm", 
      (got.get("expressive_voice"), got.get("voice_delivery")))
check("Settings lists the tags and deliveries", len(got.get("audio_tag_groups") or []) == 3
      and len(got.get("voice_deliveries") or []) == 3)
prev = client.get(f"/api/preview-prompt?profile_id={actor['id']}").get_json()
check("the preview shows the tag rules", "VOICE TAGS" in prev.get("full", ""))

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("All voice-tag checks passed.")
