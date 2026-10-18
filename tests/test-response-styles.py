#!/usr/bin/env python3
"""NEW (1.5.0): Reply, Clean up and Word for word do what they say.

On screen the styles are Reply / Clean up / Word for word; in settings,
profiles and this file they are still "reply" / "echo" / "mimic".

  * Word for word ("mimic") in English never calls the model: what you typed
    is what's said, and it works with no OpenAI key. In another language
    it's one literal translation at temperature 0, with no personality and
    no earlier turns.
  * Clean up ("echo") fixes typos, misheard words and grammar and makes
    garbled bits clear. Its output is checked (cleanup_stays_on_message):
    filler, pet names, new content or an answer instead of your message are
    caught; then it gets one more try with no personality, then your own
    words are used, and the reply is flagged.
  * Follow reply length: whole sentences that fit, or nothing shortened.
  * Reply works exactly as before.
  * Settings and profiles saved with the old "flair" style read as Clean up.

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
mod.get_tts_audio = lambda text, voice_id, language="English": "x.mp3"  # CHANGED (1.5.0): takes the language
# NEW (1.5.0): a reply too long for one chatbox page is spoken through the
# timed path, so that's replaced too.
mod.get_tts_audio_timed = lambda text, voice_id, language, plan: ("x.mp3", None)
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
print("--- Clean up's check ---")
allowed = [
    ("u coming?", "You coming?"),
    ("teh game is so laggy rn", "The game is SO laggy right now!"),
    ("i ment teh thing wiht hte guy", "I meant the thing with the guy."),
    ("can u tel him im runing late caus trafic", "Can you tell him I'm running late because of traffic?"),
    ("lets go too the stor and by some milk", "Let's go to the store and buy some milk."),
    ("the thing at the place was weird yesterday you know", "The thing at the place yesterday was weird, you know?"),
    ("me want food now hungry", "I want food now, I'm hungry."),
    ("my frend sed hi", "My friend said hi."),
    ("i think we shud of left erlier", "I think we should have left earlier."),
    ("brb", "Be right back!"),
]
for src, out in allowed:
    check("allowed: %r -> %r" % (src, out), mod.cleanup_stays_on_message(src, out))
caught = [
    ("im heading out now", "Alright, I'm off!"),
    ("i dont think thats a good idea", "Ugh, honestly, I don't think that's a good idea."),
    ("i dont think thats a good idea", "I don't think that's a good idea, darling."),
    ("can you grab me a drink", "Could you possibly fetch me a beverage?"),
    ("what time is it", "It is 5pm."),
    ("where are you", "I am at home right now, chilling."),
    ("i love it", "I absolutely love it!"),
    ("good job", "Good job, champ!"),
    ("thanks", "Thanks so much, I really appreciate everything you do!"),
    ("hey", ""),
]
for src, out in caught:
    check("caught: %r -> %r" % (src, out), not mod.cleanup_stays_on_message(src, out))

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
script.extend(["Alright, I'm off!", "Alright, I'm off, buddy!"])
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
check("the three choices are Reply, Clean up, Word for word", names == ["Reply", "Clean up", "Word for word"], names)
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

# --- NEW (1.5.0): Follow reply length -------------------------------------------
print()
print("--- Follow reply length ---")
fit = mod.fit_to_length
t, cut = fit("I went to the store. Then I bought milk and eggs. After that I went home and slept.", 10)
check("whole sentences kept while they fit", t == "I went to the store." and cut, t)
t, cut = fit("So I was walking down the street with my friend and we saw this really weird dog barking", 12)
check("one long sentence: cut at a word, no dangling 'the/and', ends with a full stop",
      t.endswith(".") and t.split()[-1].rstrip(".").lower() not in mod._DANGLING_WORDS and len(t.split()) <= 12, t)
check("short enough already: untouched", fit("hey whats up", 15) == ("hey whats up", False))
t, cut = fit("今日はとても良い天気ですね。明日は雨が降るかもしれません。週末は晴れるでしょう。", 15, "Japanese")
check("Japanese: whole sentences too", cut and t.endswith("。") and "週末" not in t, t)

long_msg = "This is the first sentence I typed. " + "And then I just kept on going and going for ages. " * 10

def make_profile(style, follow=None):
    entry = {"id": "pf", "name": "P", "voice_id": "v", "response_style": style}
    if follow is not None:
        entry["follow_length"] = follow
    with open(mod.PROFILES_PATH, "w", encoding="utf-8") as handle:
        json.dump([entry], handle)

def say_profile(message, max_words=15, language="English"):
    res = client.post("/api/chat", json={"message": message, "language": language, "max_words": max_words,
                                         "session_id": "pf", "profile_id": "pf"})
    return res.get_json()

summary = "I typed a first sentence and then kept going for ages."

setup("mimic")
make_profile("mimic", True)
script.append(summary)
body = say_profile(long_msg)
check("Word for word, on: a long message is summarized to fit", body.get("reply") == summary, body.get("reply"))
check("and flagged as shortened", body.get("condensed") is True, body)
check("with one call, asking for a first-person summary within the limit",
      len(calls) == 1 and "no more than 15 words" in calls[0]["messages"][-1]["content"]
      and "first person" in calls[0]["messages"][-1]["content"], len(calls))
check("short enough already: no summary, no call", say_profile("short and sweet").get("reply") == "short and sweet" and len(calls) == 1)

setup("mimic")
make_profile("mimic", True)
script.append("Darling, I typed a first sentence and then kept going for ages.")
body = say_profile(long_msg)
check("a summary that adds things you didn't say isn't used — whole sentences instead",
      body.get("reply") == "This is the first sentence I typed." and body.get("repaired") is True, body.get("reply"))

setup("mimic")
make_profile("mimic", True)
script.append("This is the first sentence I typed. Then I kept going and going and going for ages and ages.")
body = say_profile(long_msg)
check("a summary that's still too long is cut to whole sentences", body.get("reply") == "This is the first sentence I typed.", body.get("reply"))

setup("mimic", key="")
make_profile("mimic", True)
body = say_profile(long_msg)
check("no OpenAI key: whole sentences that fit, and no error", body.get("reply") == "This is the first sentence I typed." and not calls, body)

setup("mimic")
make_profile("mimic", False)
check("Word for word, off: the whole message", say_profile(long_msg).get("reply") == long_msg.strip())
make_profile("mimic")
check("Word for word, saved before the switch existed: the whole message", say_profile(long_msg).get("reply") == long_msg.strip())

setup("echo")
make_profile("echo", True)
script.extend([long_msg.strip(), summary])
body = say_profile(long_msg)
check("Clean up, on: cleaned up, then summarized to fit", body.get("reply") == summary and len(calls) == 2, (body.get("reply"), len(calls)))

setup("echo")
make_profile("echo", True)
script.extend(["Hola, soy yo. Y luego segui y segui durante mucho tiempo sin parar nunca jamas, de verdad, toda la noche entera.\n---EN---\nHi, it's me. And then...",
               "Soy yo, y segui toda la noche."])
body = say_profile("hi its me. and then i kept going for ages without ever stopping all night long, really", max_words=15, language="Spanish")
check("Clean up in another language, on: summarized in that language, stale translation dropped",
      body.get("reply") == "Soy yo, y segui toda la noche." and body.get("english") == "", body)

setup("reply")
make_profile("reply", False)
script.append("Sure thing.")
say_profile("hello", max_words=15)
check("Response, off: no limit sent to the model", calls and "%d words is the MAXIMUM" % mod.MAX_WORDS in calls[0]["messages"][0]["content"])
setup("reply")
make_profile("reply")
script.append("Sure thing.")
say_profile("hello", max_words=15)
check("Response, saved before the switch existed: still follows the slider", calls and "15 words is the MAXIMUM" in calls[0]["messages"][0]["content"])

made = client.post("/api/profiles", json={"name": "N", "voice_id": "v", "response_style": "echo", "follow_length": True}).get_json()
check("a new profile saves the switch", made.get("profile", {}).get("follow_length") is True, made)
pid = made["profile"]["id"]
edited = client.put("/api/profiles/" + pid, json={"follow_length": False}).get_json()
check("and editing changes it", edited.get("profile", {}).get("follow_length") is False, edited)

print()
if failures:
    print("%d response-style check(s) failed." % len(failures))
    sys.exit(1)
print("All response-style checks passed.")
