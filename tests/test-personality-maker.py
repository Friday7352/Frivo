#!/usr/bin/env python3
"""NEW (1.5.0): the personality maker.

  * Create: a one-line idea goes to the AI set up for replies (OpenAI or
    Ollama) with what Frivo needs from a personality, and what comes back is
    cleaned of prefaces, fences and markdown
  * ideas to add: parsed from "label | sentence" lines, numbered or not;
    nothing already in the personality or turned down is offered again;
    the conversation with the profile is used when there is one
  * Add all: woven in by the AI, or added at the end when the AI lost
    what was there
  * no AI to ask: says so

Usage:  python3 tests/test-personality-maker.py     (run from the repo root)
Needs:  flask, openai (import only).
"""

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


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-pm-home-")
ws = tempfile.mkdtemp(prefix="frivo-pm-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_pm", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_pm"] = mod
spec.loader.exec_module(mod)

asked = []
answer = {"text": ""}


def fake_completion(client, **kw):
    asked.append(kw)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer["text"]),
                                                    finish_reason="stop")])


mod.create_chat_completion = fake_completion
mod.make_openai_client = lambda: None
client = mod.app.test_client()

print("--- no AI to ask ---")
mod.CFG.update(openai_api_key="", chat_provider="openai")
res = client.post("/api/personality/create", json={"idea": "a sleepy pirate"})
check("says what's needed", res.status_code == 400 and "OpenAI key" in res.get_json()["error"], res.get_json())
mod.CFG.update(chat_provider="ollama")
check("Ollama needs no key", True)

print("--- Create ---")
PIRATE = ("You are Captain Snooze, a pirate who would rather nap than plunder. You speak slowly, "
          "with long yawns between thoughts, and call everyone \"matey\" only when you're half asleep. "
          "You care about naps, hammocks and your cat, Barnacle.")
answer["text"] = "Here's the personality:\n```\n## Captain Snooze\n" + PIRATE + "\n```"
res = client.post("/api/personality/create", json={"idea": "a sleepy pirate who loves cats", "name": "Snooze",
                                                    "response_style": "reply", "language": "Spanish"})
data = res.get_json() or {}
prompt = asked[-1]["messages"][0]["content"]
check("written, with the wrapping taken off", res.status_code == 200 and data.get("text", "").startswith("Captain Snooze\nYou are")
      and "```" not in data["text"] and "Here's" not in data["text"], data)
check("the AI was given the idea and the name", "sleepy pirate who loves cats" in prompt and '"Snooze"' in prompt)
check("... told how a Reply profile uses it", "REPLIES" in prompt)
check("... and the language", "Spanish" in prompt)
check("... and not to set a length or language", "Don't set a reply length or a language" in prompt)
check("used the chat AI (Ollama here)", asked[-1]["provider"] == "ollama")
res = client.post("/api/personality/create", json={"idea": "louder", "current": PIRATE, "build_on": True,
                                                    "response_style": "echo"})
prompt = asked[-1]["messages"][0]["content"]
check("rewriting builds on what's there", "<CURRENT>" in prompt and "Captain Snooze" in prompt)
check("Clean up profiles get delivery, not opinions", "CLEANS UP" in prompt)
answer["text"] = "Sure!"
res = client.post("/api/personality/create", json={"idea": "a pirate"})
check("an unusable answer says so", res.status_code == 502)
res = client.post("/api/personality/create", json={"idea": " "})
check("no idea: asks for one", res.status_code == 400)

print("--- ideas to add ---")
answer["text"] = (
    "Here are some ideas:\n"
    "1. Signature yawn | You end big statements with a long, contented yawn.\n"
    "- Hates alarms | You flinch at the word 'alarm' and change the subject\n"
    "**Cat stories** | You bring up Barnacle the cat whenever someone mentions the sea.\n"
    "Naps | You care about naps, hammocks and your cat, Barnacle.\n"
    "Turned down | Something already turned down.\n"
    "no separator here\n"
)
recent = [{"you": "what's the plan today", "reply": "[yawns] Plan? The plan is a nap, matey."}]
res = client.post("/api/personality/suggest", json={"text": PIRATE, "name": "Snooze", "response_style": "reply",
                                                     "recent": recent, "skip": ["Turned down"]})
data = res.get_json() or {}
labels = [s["label"] for s in data.get("suggestions", [])]
check("parsed: numbered, bulleted, bold", labels == ["Signature yawn", "Hates alarms", "Cat stories"], labels)
check("a sentence gets its full stop", data["suggestions"][1]["text"].endswith("subject."), data["suggestions"][1])
check("what's already written isn't offered", "Naps" not in labels)
check("a turned-down idea isn't offered", "Turned down" not in labels)
prompt = asked[-1]["messages"][0]["content"]
check("the conversation was used", data.get("used_conversation") is True and "The plan is a nap" in prompt
      and "[yawns]" not in prompt, prompt[-500:])
check("... and the turned-down list was passed on", "Turned down" in prompt)
res = client.post("/api/personality/suggest", json={"text": "short"})
check("too short to suggest for: nothing, without asking", res.get_json() == {"suggestions": [], "reason": "short"})

print("--- Add all ---")
ADDS = ["You end big statements with a long, contented yawn.", "You flinch at the word 'alarm'."]
answer["text"] = PIRATE + " You end big statements with a long, contented yawn, and you flinch at the word 'alarm'."
res = client.post("/api/personality/merge", json={"text": PIRATE, "additions": ADDS})
data = res.get_json() or {}
check("woven in by the AI", data.get("woven") is True and "flinch" in data.get("text", ""), data)
answer["text"] = "You are a pirate."
res = client.post("/api/personality/merge", json={"text": PIRATE, "additions": ADDS})
data = res.get_json() or {}
check("the AI lost what was there: added at the end instead",
      data.get("woven") is False and data["text"].startswith(PIRATE) and data["text"].endswith("'alarm'."), data)
res = client.post("/api/personality/merge", json={"text": "", "additions": ADDS})
check("an empty box just gets them", res.get_json().get("text") == " ".join(ADDS))
res = client.post("/api/personality/merge", json={"text": PIRATE, "additions": []})
check("nothing to add: says so", res.status_code == 400)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("All personality-maker checks passed.")
