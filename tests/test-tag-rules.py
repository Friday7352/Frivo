#!/usr/bin/env python3
"""NEW (1.5.0): better tags.

  * the rules (refine_tags): a feeling tag at the very end goes, a sound
    stays; a tag that repeats the words next to it goes; one per sentence
    (two on Dramatic, few in all on Subtle); repeats and piles go; your own
    tags are never touched
  * Tag amount changes the AI's instructions and is kept on profiles and
    in Settings
  * the tagger is given the conversation, the persona, examples and your
    taste
  * taste: kept / removed / added are counted, summarised, passed on, and
    a tag you always remove stops being added; Reset clears it
  * /api/retake: the same, without tags, or different ones; the words never
    change; the history keeps the version you heard

Usage:  python3 tests/test-tag-rules.py     (run from the repo root)
"""

import base64
import importlib.util
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-rules-home-")
ws = tempfile.mkdtemp(prefix="frivo-rules-")
shutil.copy(os.path.join(ROOT, "app", "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_rules", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_rules"] = mod
spec.loader.exec_module(mod)
R = mod.refine_tags

print("--- the rules ---")
got = R("[confused] What is going on? [nervous]")
check("a feeling at the very end goes", got == "[confused] What is going on?", got)
got = R("That's hilarious. [laughs]")
check("a sound at the end stays", got == "That's hilarious. [laughs]", got)
got = R("Okay then. [pause]")
check("a pause at the end goes", got == "Okay then.", got)
got = R("[happy] I'm so happy for you!")
check("a tag repeating the words goes", got == "I'm so happy for you!", got)
got = R("[excited] I'm really excited about it.")
check("... excited / excited too", "[excited]" not in got, got)
got = R("[sighs] Fine. [sighs] Whatever. [sighs] Sure.")
check("one per sentence keeps separate sentences", got.count("[sighs]") == 3, got)
got = R("[sad] [softly] [sighs] I miss it, honestly.")
check("a pile of three: one is dropped", got.count("[") <= 2, got)
got = R("[sarcastic] Oh great, [laughs] just great, [sighs] perfect.")
check("Normal: one per sentence, the sound kept first", got.count("[") == 1 and "[laughs]" in got, got)
got = R("[sarcastic] Oh great, [laughs] just great, [sighs] perfect.", amount="dramatic")
check("Dramatic: two per sentence", got.count("[") == 2, got)
got = R("[gasps] No way. [laughs] That's wild. [warmly] I'm proud of you. [softly] Really.", amount="subtle")
check("Subtle: few in all", got.count("[") == 2, got)
got = R("[happy] I'm so happy. [nervous]", protected=["happy", "nervous"])
check("your own tags are never touched", got == "[happy] I'm so happy. [nervous]", got)
got = R("[happy] I'm so happy for you! [laughs] [laughs]")
check("the same tag twice goes", got.count("[laughs]") == 1, got)
check("words never change", mod.strip_audio_tags(R("[sad] [softly] [sighs] I miss it, [nervous] honestly. [happy]"))
      == "I miss it, honestly.")
check("no tags: untouched", R("Just words, here.") == "Just words, here.")

print("--- Tag amount in the instructions ---")
rules = lambda a: mod.expressive_voice_rules("reply", "English", "natural", amount=a)
check("Subtle asks for at most one", "At most one tag" in rules("subtle"))
check("Dramatic asks for more", "Two to four" in rules("dramatic"))
check("examples of good and bad tagging", "MISTAKES TO AVOID" in rules("normal") and "[nervous]" in rules("normal"))
check("Clean up shaping uses the amount", "two to four more" in mod.expressive_voice_rules("echo", "English", "natural", shaping=True, amount="dramatic"))
p = mod.build_tag_suggestion_prompt("Hi there.", "natural", "RECENT LINES: x\n", "subtle", avoid=["laughs"])
check("Suggest: context, amount and things to avoid", "RECENT LINES" in p and "Add at most one" in p and "[laughs]" in p.split("Don't use these")[1][:40])
check("bad amounts fall back to Normal", mod.normalize_tag_amount("loud") == "normal")

print("--- the conversation as context ---")
mod.SESSIONS["s1::default"] = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "SOURCE TEXT (said to you):\n<SOURCE_TEXT>\nmy cat died\n</SOURCE_TEXT>\n\nReply"},
    {"role": "assistant", "content": "[softly] Oh no, I'm so sorry."},
]
ctx = mod.tag_context(None, "s1", None)
check("recent lines, without their tags", "my cat died" in ctx and "Oh no, I'm so sorry." in ctx and "[softly]" not in ctx, ctx)
check("the persona", "PERSONA" in ctx)

print("--- taste ---")
client = mod.app.test_client()
check("empty to begin with", client.get("/api/voice-tags/taste").get_json()["counted"] == 0)
for _ in range(3):
    client.post("/api/voice-tags/feedback", json={"kept": ["chuckles"], "removed": ["confused"], "added": ["sighs"]})
t = client.get("/api/voice-tags/taste").get_json()
check("liked and avoided", "sighs" in t["liked"] and "chuckles" in t["liked"] and "confused" in t["avoided"], t)
check("passed on to the AI", "[confused] (avoid these)" in mod.tag_taste_prompt() and "[sighs]" in mod.tag_taste_prompt())
got = R("[confused] Wait, what happened here?")
check("a tag you always remove isn't added", got == "Wait, what happened here?", got)
check("... unless you typed it", R("[confused] Wait, what?", protected=["confused"]).startswith("[confused]"))
check("rubbish refused", client.post("/api/voice-tags/feedback", json={"kept": "x"}).status_code == 400)
client.post("/api/voice-tags/feedback", json={"kept": ["not a [tag]"]})
check("... and odd tags ignored", "not a [tag]" not in mod.load_tag_taste())
check("Reset clears it", client.delete("/api/voice-tags/taste").get_json()["counted"] == 0)

print("--- Tag amount is kept ---")
client.post("/api/settings", json={"tag_amount": "dramatic"})
check("Settings", client.get("/api/settings").get_json().get("tag_amount") == "dramatic")
check("... and the choices are listed", len(client.get("/api/settings").get_json().get("tag_amounts", [])) == 3)
check("used for the default profile", mod.voice_style_of(None)["amount"] == "dramatic")
mod.CFG["tag_amount"] = "normal"

print("--- Retake ---")
mod.AUDIO_DIR = tempfile.mkdtemp(prefix="frivo-rules-audio-")
posts = []


def fake_post(url, **kw):
    body = kw["json"]
    posts.append(body)
    text = body["text"]
    align = {"characters": list(text), "character_start_times_seconds": [i / 10 for i in range(len(text))],
             "character_end_times_seconds": [i / 10 + 0.08 for i in range(len(text))]}
    return SimpleNamespace(status_code=200, text="", content=b"mp3", headers={"request-id": "r"},
                           json=lambda: {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": align})


asked = []


def fake_completion(client_, **kw):
    asked.append(kw)
    prompt = kw["messages"][-1]["content"]
    msg = prompt.split("<MESSAGE>\n")[1].split("\n</MESSAGE>")[0]
    out = "[laughs] " + msg if "[laughs]" not in prompt.split("Don't use these")[-1][:60] else "[chuckles] " + msg
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out))])


mod.requests.post = fake_post
mod.create_chat_completion = fake_completion
mod.record_usage = lambda c: None
mod.CFG.update(elevenlabs_api_key="k", openai_api_key="sk", voice_id="EL1", chat_provider="openai")
mod.tts_engine = lambda v: "elevenlabs"
mod.SESSIONS["s2::default"] = [{"role": "system", "content": "sys"},
                               {"role": "assistant", "content": "[laughs] You did what? That's amazing."}]
res = client.post("/api/retake", json={"voiced": "[laughs] You did what? That's amazing.", "mode": "same", "session_id": "s2"})
d = res.get_json()
check("same: spoken again with its tags", res.status_code == 200 and posts[-1]["text"].startswith("[laughs]") and d["audio_url"], d)
res = client.post("/api/retake", json={"voiced": "[laughs] You did what? That's amazing.", "mode": "plain", "session_id": "s2"})
d = res.get_json()
check("without tags", d["voiced"] == "You did what? That's amazing." and "[" not in posts[-1]["text"], d)
check("... and says which were dropped (for your taste)", d["removed_tags"] == ["laughs"], d)
check("the history keeps what you heard", mod.SESSIONS["s2::default"][-1]["content"] == "You did what? That's amazing.")
res = client.post("/api/retake", json={"voiced": "[laughs] You did what? That's amazing.", "mode": "fresh", "session_id": "s2"})
d = res.get_json()
check("different tags", res.status_code == 200 and "[laughs]" not in d["voiced"] and "[chuckles]" in d["voiced"], d)
check("... not counted against the old ones (maybe you wanted variety)", d["removed_tags"] == [], d)
check("... the AI was told what to avoid, and to vary", "Don't use these this time: [laughs]" in asked[-1]["messages"][-1]["content"]
      and asked[-1]["temperature"] == 0.8)
check("... the words never change", mod.strip_audio_tags(d["voiced"]) == "You did what? That's amazing.")
check("... with chatbox pages and timing", d["chatbox_pages"] and d["word_times"])
check("nothing to say refused", client.post("/api/retake", json={"voiced": ""}).status_code == 400)
mod.tts_engine = lambda v: "piper"
check("a free voice refused", client.post("/api/retake", json={"voiced": "Hi."}).status_code == 400)

print("--- Suggest with context ---")
mod.tts_engine = lambda v: "elevenlabs"
res = client.post("/api/voice-tags/suggest", json={"text": "That's so funny.", "session_id": "s1"})
check("Suggest works", res.status_code == 200, res.get_json())
check("... and saw the conversation", "my cat died" in asked[-1]["messages"][-1]["content"])

print("--- a line with no words (it used to drop every reply to v2 for an hour) ---")
check("[laughs] alone gets a word", mod.ensure_spoken_words("[laughs]") == "[laughs] Haha!", mod.ensure_spoken_words("[laughs]"))
check("[sighs]. too", mod.ensure_spoken_words("[sighs].") == "[sighs] Hmm.", mod.ensure_spoken_words("[sighs]."))
check("a laughing emoji", mod.ensure_spoken_words("😂😂") == "[laughs] Haha!", mod.ensure_spoken_words("😂😂"))
check("words are left alone", mod.ensure_spoken_words("[laughs] okay") == "[laughs] okay")
check("the payload never has only tags", mod.strip_audio_tags(mod._elevenlabs_payload("[laughs]")["text"]).strip() != "")
mod.REFUSED_MODELS.clear(); mod.MODEL_REFUSALS.clear()
calls = []
def empty_refusal(url, **kw):
    calls.append(kw["json"])
    if mod.is_expressive_model(kw["json"]["model_id"]):
        msg = "Input at position 0 has empty text. All inputs must include non-empty text after removing speaker tags and emojis."
        return SimpleNamespace(status_code=400, text=msg, content=b"", headers={}, json=lambda: {"detail": {"message": msg}})
    return SimpleNamespace(status_code=200, text="", content=b"mp3", headers={}, json=lambda: {})
mod.requests.post = empty_refusal
with mod.app.test_request_context():
    mod.g.voice_style = {"expressive": True, "delivery": "natural"}
    payload = mod._elevenlabs_payload("[laughs] Hello there.")
    resp = SimpleNamespace(status_code=400, text="", json=lambda: {"detail": {"message": "Input at position 0 has empty text. All inputs must include non-empty text after removing speaker tags and emojis."}})
    p2, r2 = mod._step_down("u", {}, "[laughs] Hello there.", payload, resp)
check("an empty-text refusal isn't held against the model", not mod.REFUSED_MODELS and not mod.MODEL_REFUSALS, mod.MODEL_REFUSALS)
check("... the line is still spoken (plain)", r2.status_code == 200 and p2["model_id"] == mod.ELEVEN_V2_MODEL and "[" not in p2["text"], p2)
with mod.app.test_request_context():
    mod.g.voice_style = {"expressive": True, "delivery": "natural"}
    check("... and the next line uses v4 again", mod._elevenlabs_payload("[laughs] Hi.")["model_id"] == "eleven_v4")

print("--- the message's own words in brackets aren't tags ---")
orig = "i was thinking about writing a small novel for my love"
bad = "[i was thinking] [about] [writing] [a] small novel for my [warmly] love"
got = mod.unwrap_message_words(orig, bad)
check("unwrapped", got == "i was thinking about writing a small novel for my [warmly] love", got)
fixed = mod.transplant_audio_tags(orig, got)
check("... so only the real tag is left, in its place", fixed == "i was thinking about writing a small novel for my [warmly] love", fixed)
check("a tag you typed stays", mod.unwrap_message_words("[about] it", "[about] it") == "[about] it")
check("told not to", "Never put the message's own words in brackets" in mod.build_tag_suggestion_prompt("hi there", "natural"))

print()
if failures:
    print(f"{len(failures)} failed: {failures}")
    sys.exit(1)
print("All tag-rule checks passed.")
