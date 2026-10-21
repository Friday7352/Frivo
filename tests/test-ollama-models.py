#!/usr/bin/env python3
"""NEW (1.5.0): three Ollama models to switch between, and Ollama fixes.

Against a stand-in Ollama server (requests is replaced), this checks:

  * Fast / Balanced / Best: defaults, saved from Settings, reported back,
    and the one in use is what replies are written with
  * switching unloads the other two and loads the new one
  * /api/ollama/status says what's downloaded, loaded, and how much of it is
    on the graphics card; and says so when Ollama can't be reached
  * every request asks for no "thinking" and to stay loaded; an Ollama that
    refuses "think" is asked again without it; a stray <think> block is
    removed; a model that isn't downloaded says to run "ollama pull"
  * a reply says which AI wrote it ("Ollama · gemma3:4b")
  * with Ollama chosen for Chat replies, no OpenAI key is needed; with
    OpenAI chosen, it still is

Usage:  python3 tests/test-ollama-models.py     (run from the repo root)
Needs:  flask, openai (import only).
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-ollama-home-")
ws = tempfile.mkdtemp(prefix="frivo-ollama-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
for folder in ("templates", "static"):   # for the setup guide page
    os.symlink(os.path.join(APP, folder), os.path.join(ws, folder))
spec = importlib.util.spec_from_file_location("frivo_ollama", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_ollama"] = mod
spec.loader.exec_module(mod)
client = mod.app.test_client()

# --- a stand-in Ollama -------------------------------------------------------
ollama = {"up": True, "installed": ["gemma3:4b", "qwen3.5:4b"], "loaded": {}, "think_refused": False,
          "reply": "Hey, that sounds great!", "posts": []}


def resp(status, body):
    return SimpleNamespace(status_code=status, text=json.dumps(body), json=lambda: body,
                           raise_for_status=lambda: None if status < 400 else (_ for _ in ()).throw(RuntimeError(f"HTTP {status}")))


def fake_get(url, timeout=None, **kw):
    if not ollama["up"]:
        raise ConnectionError("down")
    if url.endswith("/api/tags"):
        return resp(200, {"models": [{"name": m} for m in ollama["installed"]]})
    if url.endswith("/api/ps"):
        return resp(200, {"models": [{"name": m, "size": 100, "size_vram": v} for m, v in ollama["loaded"].items()]})
    raise AssertionError(url)


def fake_post(url, json=None, timeout=None, **kw):
    if not ollama["up"]:
        raise ConnectionError("down")
    ollama["posts"].append((url.rsplit("/", 1)[-1], dict(json or {})))
    model = (json or {}).get("model")
    if url.endswith("/api/generate"):
        if json.get("keep_alive") == 0:
            ollama["loaded"].pop(model, None)
        else:
            ollama["loaded"][model] = 100
        return resp(200, {"done": True})
    if url.endswith("/api/chat"):
        if model not in ollama["installed"]:
            return resp(404, {"error": f"model '{model}' not found"})
        if "think" in json and ollama["think_refused"]:
            return resp(400, {"error": f"\"{model}\" does not support thinking"})
        ollama["loaded"][model] = 100
        return resp(200, {"message": {"content": ollama["reply"]}, "done_reason": "stop"})
    raise AssertionError(url)


mod.requests.get = fake_get
mod.requests.post = fake_post
mod.record_usage = lambda c: None


def say(text="hey whats up", style="reply", language="English"):
    mod.CFG.update(response_style=style, follow_length=False, language=language)
    res = client.post("/api/chat", json={"message": text, "language": language, "speak": False,
                                         "session_id": str(time.time()), "max_words": 80})
    return res.status_code, (res.get_json() or {})


print("--- the three slots ---")
check("Fast is the default", mod.ollama_tier() == "fast")
check("Balanced and Best have defaults",
      (mod.tier_model("balanced"), mod.tier_model("best")) == ("qwen3.5:4b", "qwen3.5:9b"))
mod.CFG.update(openai_api_key="", chat_provider="ollama", ollama_url="http://ollama.test:11434",
               allow_openai_fallback=False)
client.post("/api/settings", json={"ollama_model": "gemma3:4b", "ollama_model_balanced": "qwen3.5:4b",
                                   "ollama_model_best": "qwen3.5:9b"})
got = client.get("/api/settings").get_json()
check("Settings saves and reports all three",
      (got["ollama_model"], got["ollama_model_balanced"], got["ollama_model_best"], got["ollama_tier"])
      == ("gemma3:4b", "qwen3.5:4b", "qwen3.5:9b", "fast"), got)

print("--- a reply with Ollama ---")
code, data = say()
chat = [p for kind, p in ollama["posts"] if kind == "chat"][-1]
check("works with no OpenAI key", code == 200 and data.get("reply") == ollama["reply"], (code, data.get("error")))
check("written by the Fast model", chat["model"] == "gemma3:4b", chat["model"])
check("asks for no thinking, and to stay loaded for an hour", chat.get("think") is False and chat.get("keep_alive") == "1h", chat)   # CHANGED (1.5.0)
mod.CFG["ollama_idle_unload"] = "never"   # NEW (1.5.0)
check("'Never' keeps it loaded for good", mod.ollama_keep_alive() == -1, mod.ollama_keep_alive())
mod.CFG["ollama_idle_unload"] = "15m"
check("15 minutes", mod.ollama_keep_alive() == "15m", mod.ollama_keep_alive())
mod.CFG["ollama_idle_unload"] = "nonsense"
check("anything else falls back to an hour", mod.ollama_keep_alive() == "1h", mod.ollama_keep_alive())
mod.CFG["ollama_idle_unload"] = "1h"
# NEW (1.5.0): the timer goes on a model that's already loaded, straight away.
ollama["loaded"] = {"gemma3:4b": 100}
before = len(ollama["posts"])
mod.CFG["chat_provider"] = "ollama"
mod.apply_ollama_idle_timer()
sent = [p for kind, p in ollama["posts"][before:] if kind == "generate"]
check("a loaded model gets the idle timer at once", [(p.get("model"), p.get("keep_alive")) for p in sent] == [("gemma3:4b", "1h")], sent)
check("the reply says which AI wrote it", data.get("text_engine_name") == "Ollama · gemma3:4b", data.get("text_engine_name"))

ollama["think_refused"] = True
ollama["posts"].clear()
code, data = say()
chats = [p for kind, p in ollama["posts"] if kind == "chat"]
check("an Ollama that refuses 'think' is asked again without it",
      code == 200 and len(chats) == 2 and "think" not in chats[1], [list(c) for c in chats])
ollama["think_refused"] = False

ollama["reply"] = "<think>They said hi, so I should say hi.</think>Hi there!"
code, data = say()
check("a stray <think> block is removed", data.get("reply") == "Hi there!", data.get("reply"))
ollama["reply"] = "Hey, that sounds great!"

print("--- switching ---")
res = client.post("/api/ollama/tier", json={"tier": "balanced"}).get_json()
time.sleep(0.5)
check("switching saves it", mod.CFG["ollama_tier"] == "balanced" and res.get("model") == "qwen3.5:4b", res)
check("and loads the new one while unloading the others",
      "qwen3.5:4b" in ollama["loaded"] and "gemma3:4b" not in ollama["loaded"], ollama["loaded"])
code, data = say()
check("replies now use Balanced", [p for k, p in ollama["posts"] if k == "chat"][-1]["model"] == "qwen3.5:4b"
      and data.get("text_engine_name") == "Ollama · qwen3.5:4b", data.get("text_engine_name"))
check("a made-up tier is refused", client.post("/api/ollama/tier", json={"tier": "huge"}).status_code == 400)

client.post("/api/ollama/tier", json={"tier": "best"})
time.sleep(0.5)
code, data = say()
check("a model that isn't downloaded says to pull it",
      code == 500 and "ollama pull qwen3.5:9b" in (data.get("error") or ""), data.get("error"))

print("--- status ---")
ollama["loaded"] = {"qwen3.5:4b": 60}
status = client.get("/api/ollama/status").get_json()
tiers = {t["id"]: t for t in status["tiers"]}
check("says which are downloaded",
      tiers["fast"]["installed"] and tiers["balanced"]["installed"] and not tiers["best"]["installed"], tiers)
check("and how much is on the graphics card", tiers["balanced"].get("gpu_percent") == 60 and tiers["balanced"]["loaded"],
      tiers["balanced"])
check("and which is in use", status["tier"] == "best" and status["reachable"])
ollama["up"] = False
status = client.get("/api/ollama/status").get_json()
check("Ollama down: says so", not status["reachable"] and "isn't reachable" in status["error"], status)
ollama["up"] = True

print("--- the setup guide ---")
page = client.get("/setup/ollama")
html = page.get_data(as_text=True)
check("the guide page opens", page.status_code == 200 and "Set up local AI" in html, page.status_code)
check("and Settings links to it", "/setup/ollama" in open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read())

print("--- the OpenAI key ---")
mod.CFG["chat_provider"] = "openai"
code, data = say()
check("with OpenAI chosen, a key is still needed", code == 400 and "OpenAI key" in (data.get("error") or ""), data)
mod.CFG["chat_provider"] = "ollama"
mod.CFG["ollama_tier"] = "fast"
code, data = say("hey there", style="mimic")
check("Word for word in English uses no AI", code == 200 and data.get("text_engine_name") == "", data.get("text_engine_name"))


print("--- a community model typed without its owner ---")
ollama["installed"] = ["gemma3:4b", "huihui_ai/qwen3.5-abliterated:9b", "huihui_ai/qwen3.5-abliterated:4b"]
mod.CFG.update(ollama_model_balanced="huihui_ai", ollama_model_best="qwen3.5-abliterated:9b")
st = mod.ollama_tier_status()
best = next(t for t in st["tiers"] if t["id"] == "best")
bal = next(t for t in st["tiers"] if t["id"] == "balanced")
check("found under its full name, and saved so", best["installed"] and best["model"] == "huihui_ai/qwen3.5-abliterated:9b"
      and mod.CFG["ollama_model_best"] == "huihui_ai/qwen3.5-abliterated:9b", best)
check("just the owner: its models are offered", not bal["installed"] and "huihui_ai/qwen3.5-abliterated:4b" in bal.get("suggest", []), bal)
check("an unknown name: nothing to offer", mod.match_installed_model("llama9:1b", ollama["installed"]) == (None, []))

print()
if failures:
    print(f"{len(failures)} failed: " + ", ".join(failures))
    sys.exit(1)
print("All Ollama-model checks passed.")
