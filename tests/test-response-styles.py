#!/usr/bin/env python3
"""NEW (1.5.0): Response, Echo and Mimic do what they say.

The old styles asked the model nicely not to reword things, and it didn't
always listen. Now:

  * Mimic in English never calls the model — what you typed is what's said,
    character for character, and it works with no OpenAI key at all. In
    another language it's one literal translation at temperature 0, with no
    personality and no earlier turns to drift from.
  * Echo fixes spelling and grammar only. Its output is checked word by word
    against what you typed (echo_keeps_words); if the model reworded
    anything, it gets one more try with no personality, and if that rewords
    too, your own words are used. Either way the reply is flagged.
  * Echo and Mimic are never shortened to the length fader.
  * Response (reply) works exactly as before.
  * Settings and profiles saved with the old "flair" style read as Echo.

The model is replaced with a script; nothing goes over the network.

Usage:  python3 tests/test-response-styles.py     (run from the repo root)
Needs:  flask, openai (the package, for import only).
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


ws = tempfile.mkdtemp(prefix="frivo-styles-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_styles", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_styles"] = mod
spec.loader.exec_module(mod)
client = mod.app.test_client()

# --- the model, scripted ------------------------------------------------------
calls = []
script = []


def fake_completion(client_, *, max_tokens, provider="openai", temperature=None, messages=None, **kw):
    calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
    text = script.pop(0) if script else "(unscripted)"
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")])


mod.create_chat_completion = fake_completion
mod.get_tts_audio = lambda text, voice_id: "x.mp3"
mod.record_usage = lambda credits: None
mod.CFG["elevenlabs_api_key"] = "el"


def setup(style, key="sk-test"):
    mod.CFG["openai_api_key"] = key
    mod.CFG["response_style"] = style
    mod.CFG["personality_preset"] = "hype_man"
    mod.CFG["system_prompt"] = ""
    calls.clear()
    script.clear()
    with mod.SESSIONS_LOCK:
        mod.SESSIONS.clear()


def say(message, language="English", max_words=80, session="s1"):
    res = client.post("/api/chat", json={"message": message, "language": language,
                                         "max_words": max_words, "session_id": session})
    return res.status_code, res.get_json()


# --- the word check on its own ---------------------------------------------------
print("--- Echo's word check ---")
allowed = [
    ("u coming?", "You coming?"),
    ("teh game is so laggy rn", "The game is SO laggy right now!"),
    ("im heading out now", "I'm heading out now..."),
    ("hey whats up", "Hey! What's up?"),
    ("brb", "Be right back!"),
    ("i going to store", "I am going to the store."),
    ("thats alot of ppl", "That's a lot of people!"),
    ("recieve the pakage", "Receive the package."),
    ("their going to be late", "They're going to be late."),
    ("yo what are we doing tonight", "Yo, what are we doing TONIGHT?"),
]
for src, out in allowed:
    check("allowed: %r -> %r" % (src, out), mod.echo_keeps_words(src, out))
caught = [
    ("im heading out now", "Alright, I'm off!"),
    ("i dont think thats a good idea", "Ugh, honestly, I don't think that's a good idea."),
    ("i dont think thats a good idea", "I don't think that's a good idea, darling."),
    ("can you grab me a drink", "Could you possibly fetch me a beverage?"),
    ("this game is bad", "This game is terrible."),
    ("what time is it", "It is 5pm."),
    ("i love it", "I absolutely love it!"),
    ("good job", "Good job, champ!"),
    ("ok", "Okay, sure."),
    ("hey", ""),
]
for src, out in caught:
    check("caught: %r -> %r" % (src, out), not mod.echo_keeps_words(src, out))

# --- Mimic -----------------------------------------------------------------------
print()
print("--- Mimic ---")
setup("mimic", key="")
typed = "omg   ur SO wrong lol,, teh end"
code, body = say(typed)
check("English: works with no OpenAI key", code == 200, (code, body))
check("English: exactly what was typed", body and body.get("reply") == typed.strip(), body)
check("English: the model is never called", len(calls) == 0, len(calls))

setup("mimic")
long = " ".join(["word"] * 200)
code, body = say(long, max_words=20)
check("English: never shortened to the length fader", body.get("reply") == long and not calls, body.get("word_count"))
check("English: an unpunctuated message is not trimmed", say("hello there. how r u")[1].get("reply") == "hello there. how r u")

setup("mimic")
say("first thing")
script.append("Hola, ¿qué tal?\n---EN---\nHi, how are you?")
code, body = say("hi how r u", language="Spanish")
check("other language: translated", body.get("reply") == "Hola, ¿qué tal?", body)
check("other language: one call, at temperature 0", len(calls) == 1 and calls[0]["temperature"] == 0.0, calls)
sent = calls[0]["messages"] if calls else []
check("other language: only this message is sent, no earlier turns", len(sent) == 2 and "first thing" not in json.dumps(sent), len(sent))
check("other language: no personality in the prompt", "hype" not in sent[0]["content"].lower() if sent else False)

# --- Echo ------------------------------------------------------------------------
print()
print("--- Echo ---")
setup("echo")
script.append("The game is SO laggy right now!")
code, body = say("teh game is so laggy rn")
check("a proper fix goes through", body.get("reply") == "The game is SO laggy right now!", body)
check("and is not flagged", body.get("kept_exact") is False, body)
check("with the personality in the prompt", calls and "hype" in calls[0]["messages"][0]["content"].lower())

setup("echo")
script.append("Zebra crossing.")
say("zebra crossing")
calls.clear()
script.append("Okay.")
say("ok")
sent = calls[0]["messages"] if calls else []
check("earlier turns are not sent (they're what it used to drift towards)", len(sent) == 2 and "zebra" not in json.dumps(sent).lower(), len(sent))

setup("echo")
script.extend(["LET'S GOOO! I'm heading out now, baby!", "I'm heading out now."])
code, body = say("im heading out now")
check("reworded: one more try, with no personality", len(calls) == 2 and "hype" not in calls[1]["messages"][0]["content"].lower(), len(calls))
check("and that try is used when it keeps the words", body.get("reply") == "I'm heading out now.", body)
check("and flagged", body.get("kept_exact") is True, body)

setup("echo")
script.extend(["Alright, I'm off!", "Heading off now!"])
code, body = say("im heading out now")
check("reworded twice: your own words, as typed", body.get("reply") == "im heading out now", body)
check("and flagged", body.get("kept_exact") is True, body)

setup("echo")
src = " ".join(["this is a long sentence"] * 30)
script.append(src.capitalize() + ".")
code, body = say(src, max_words=20)
check("never shortened to the length fader (one call, no rewrite pass)", len(calls) == 1 and body.get("condensed") is False, (len(calls), body.get("condensed")))
check("and given room for the whole message", calls and calls[0]["max_tokens"] > 150 * 1.4, calls and calls[0]["max_tokens"])

setup("echo")
script.append("Hola amigo, ¿vienes?\n---EN---\nHello friend, are you coming?")
code, body = say("hello friend u coming", language="Spanish")
check("other language: translated, personality kept to punctuation", body.get("reply") == "Hola amigo, ¿vienes?" and body.get("english"), body)

# --- Response, unchanged -----------------------------------------------------------
print()
print("--- Response ---")
setup("reply")
script.append("Oh, absolutely!")
say("first")
script.append("Why not?")
code, body = say("want to go?")
check("replies in character", body.get("reply") == "Why not?", body)
check("with the conversation so far", calls and "first" in json.dumps(calls[-1]["messages"]))

# --- old saved styles ----------------------------------------------------------
print()
print("--- old settings and profiles ---")
check("'flair' reads as Echo", mod.normalize_response_style("flair") == "echo")
check("'mimic' is kept", mod.normalize_response_style("mimic") == "mimic")
check("rubbish falls back to Echo", mod.normalize_response_style("nonsense") == "echo")
check("an old fallback of 'flair' is Echo too", mod.normalize_response_style(None, "flair") == "echo")
check("the default is Echo", mod.load_config.__globals__["DEFAULT_RESPONSE_STYLE"] == "echo")
mod.CFG["response_style"] = "flair"
check("/api/settings reports an old 'flair' as Echo", client.get("/api/settings").get_json().get("response_style") == "echo")
names = [s["name"] for s in client.get("/api/settings").get_json().get("response_styles", [])]
check("the three choices are Response, Echo, Mimic", names == ["Response", "Echo", "Mimic"], names)
with open(mod.PROFILES_PATH, "w", encoding="utf-8") as handle:
    json.dump([{"id": "p1", "name": "Old", "voice_id": "v", "response_style": "flair"}], handle)
check("a profile saved as 'flair' loads as Echo", mod.load_profiles()[0]["response_style"] == "echo")

# --- the prompt preview -------------------------------------------------------
print()
print("--- what's sent to the model ---")
mod.CFG["response_style"] = "echo"
prev = client.get("/api/preview-prompt").get_json()
check("Echo: your personality shown separately", "hype" in prev["your_prompt"].lower() and "hype" not in prev["appended"].lower(), prev["appended"][:200])
mod.CFG["response_style"] = "mimic"
prev = client.get("/api/preview-prompt").get_json()
check("Mimic: says nothing is sent in English", "nothing is sent" in prev["personality_source"], prev["personality_source"])

print()
if failures:
    print("%d response-style check(s) failed." % len(failures))
    sys.exit(1)
print("All response-style checks passed.")
