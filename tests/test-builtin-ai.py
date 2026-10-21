#!/usr/bin/env python3
"""NEW (1.6.0): the built-in AI, and Clean up without AI.

GitHub and Hugging Face are stood in for, so this runs offline. With a
real llama-server and a model, it also starts the engine and gets an
answer (set FRIVO_TEST_LLAMA_DIR to a folder holding llama-server and
FRIVO_TEST_GGUF to a .gguf; skipped otherwise).

  * one click downloads the engine and the model, checks both against the
    checksums GitHub and Hugging Face publish, unpacks the engine, and
    switches Chat replies to Built-in
  * a wrong checksum, a cancelled download and a full drive are refused
    and leave nothing behind
  * status, removing a model, removing everything (replies go back to
    OpenAI)
  * Chat replies: Built-in writes replies through the engine
  * with no AI at all, Clean up in English uses Frivo's rules and says so;
    Reply says it needs an AI and how to get one; Word for word still works
  * when the AI can't be reached, Clean up falls back to the rules

Usage:  python3 tests/test-builtin-ai.py     (run from the repo root)
"""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import zipfile
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-bai-home-")
os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-bai-data-")
ws = tempfile.mkdtemp(prefix="frivo-bai-")
for name in ("app.py", "voice_pack.py", "cleanup_rules.py", "builtin_ai.py"):
    shutil.copy(os.path.join(ROOT, "app", name), os.path.join(ws, name))
spec = importlib.util.spec_from_file_location("frivo_bai", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_bai"] = mod
spec.loader.exec_module(mod)
bai = mod.BUILTIN_AI_MODULE
check("built-in AI loaded", mod.BUILTIN_AI is not None and bai is not None)
check("rules loaded", mod.CLEANUP_RULES is not None)

# ---------------------------------------------------------------- stand-ins
REAL_DIR = os.environ.get("FRIVO_TEST_LLAMA_DIR", "")
REAL_GGUF = os.environ.get("FRIVO_TEST_GGUF", "")
real = bool(REAL_DIR and REAL_GGUF and os.path.isfile(os.path.join(REAL_DIR, bai.ENGINE_EXE)))

# The engine archive: the real llama-server folder when there is one, else
# a stand-in that only has to unpack.
buf = io.BytesIO()
asset = bai.ENGINE_ASSETS.get(sys.platform, bai.ENGINE_ASSETS["linux"])
if asset.endswith(".zip"):
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"build/bin/{bai.ENGINE_EXE}", b"stand-in")
else:
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        if real:
            t.add(REAL_DIR, arcname="build/bin")
        else:
            data = b"#!/bin/sh\nexit 1\n"
            info = tarfile.TarInfo(f"build/bin/{bai.ENGINE_EXE}")
            info.size = len(data)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(data))
ENGINE = buf.getvalue()
MODEL = open(REAL_GGUF, "rb").read() if real else b"GGUF" + b"\0" * 5000
sha = lambda b: hashlib.sha256(b).hexdigest()
state = {"engine_sha": sha(ENGINE), "model_sha": sha(MODEL), "slow": False, "calls": []}


class Resp:
    def __init__(self, status, body=b"", js=None):
        self.status_code = status
        self.ok = status == 200
        self.content = body
        self.text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        self._js = js

    def json(self):
        return self._js

    def raise_for_status(self):
        if not self.ok:
            raise mod.requests.HTTPError(str(self.status_code))

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            if state["slow"]:
                time.sleep(0.3)
            yield self.content[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


real_get = bai.requests.get


def fake_get(url, **kw):
    state["calls"].append(url)
    if url.startswith("http://127.0.0.1"):
        return real_get(url, **kw)
    if "api.github.com" in url:
        return Resp(200, js={"assets": [{"name": asset, "size": len(ENGINE), "digest": "sha256:" + state["engine_sha"]}]})
    if url.startswith("https://github.com/") and url.endswith(asset):
        return Resp(200, ENGINE)
    if "huggingface.co/api/models/" in url:
        return Resp(200, js={"siblings": [{"rfilename": m["file"], "lfs": {"sha256": state["model_sha"], "size": len(MODEL)}}
                                          for m in bai.MODELS]})
    if "huggingface.co/" in url and url.endswith(".gguf"):
        return Resp(200, MODEL)
    return Resp(404)


bai.requests.get = fake_get
c = mod.app.test_client()
B = mod.BUILTIN_AI


def wait_job(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = c.get("/api/builtin-ai").get_json()["job"]
        if job.get("state") not in ("checking", "engine", "model"):
            return job
        time.sleep(0.05)
    return job


# --------------------------------------------------- no AI: Clean up by rules
mod.CFG["openai_api_key"] = ""
mod.CFG["chat_provider"] = "openai"
mod.CFG["response_style"] = "echo"
mod.CFG["language"] = "English"
res = c.post("/api/chat", json={"message": "i dont think teh game is fun", "speak": False, "language": "English"})
data = res.get_json()
check("Clean up works with no AI", res.status_code == 200 and data["reply"] == "I don't think the game is fun.", data)
check("says it was cleaned up without AI", data.get("rule_cleanup") is True and "no OpenAI key" in data.get("rule_cleanup_reason", ""), data)
check("names the rules as the engine", "rules" in data.get("text_engine_name", ""), data.get("text_engine_name"))
res = c.post("/api/chat", json={"message": "hey [laughs] thats so funny lol", "speak": False, "language": "English"})
check("tags and text-speak kept", res.get_json()["reply"].startswith("Hey") and "lol" in res.get_json()["reply"], res.get_json())
mod.CFG["response_style"] = "reply"
res = c.post("/api/chat", json={"message": "hello", "speak": False, "language": "English"})
check("Reply says it needs an AI and how to get one", res.status_code == 400 and "built-in AI" in res.get_json()["error"], res.get_json())
mod.CFG["response_style"] = "mimic"
res = c.post("/api/chat", json={"message": "word for word", "speak": False, "language": "English"})
check("Word for word still works", res.status_code == 200 and res.get_json()["reply"] == "word for word", res.get_json())
res = c.post("/api/chat", json={"message": "hola", "speak": False, "language": "Spanish"})
check("other languages say they need an AI", res.status_code == 400, res.status_code)

# No AI, chosen on purpose.
mod.CFG["chat_provider"] = "none"
mod.CFG["openai_api_key"] = "sk-test"
mod.CFG["response_style"] = "echo"
res = c.post("/api/chat", json={"message": "thats teh one", "speak": False, "language": "English"})
data = res.get_json()
check("No AI: Clean up by the rules, even with a key", res.status_code == 200 and data["reply"] == "That's the one."
      and data.get("rule_cleanup") and "No AI" in data.get("rule_cleanup_reason", ""), data)
mod.CFG["response_style"] = "reply"
res = c.post("/api/chat", json={"message": "hello", "speak": False, "language": "English"})
check("No AI: Reply says No AI is picked", res.status_code == 400 and "No AI" in res.get_json()["error"], res.get_json())
check("No AI listed, last", [p["id"] for p in mod.CHAT_PROVIDERS] == ["openai", "ollama", "builtin", "none"],
      [p["id"] for p in mod.CHAT_PROVIDERS])
res = c.post("/api/settings", json={"chat_provider": "none"})
check("No AI can be saved", mod.CFG["chat_provider"] == "none", mod.CFG["chat_provider"])
mod.CFG["openai_api_key"] = ""
mod.CFG["chat_provider"] = "openai"

# The status pill: not downloaded is said so, and No AI is what happens
# meanwhile; OpenAI only with the switch on and a key.
mod.CFG["chat_provider"] = "builtin"
mod.CFG["allow_openai_fallback"] = True
mod.CFG["openai_api_key"] = ""
svc = next(x for x in c.get("/api/local-status").get_json()["services"] if x["id"] == "builtin")
check("status: not downloaded, No AI meanwhile", svc["state"] == "not downloaded" and not svc["fallback"]
      and "No AI" in svc["fallback_note"], svc)
mod.CFG["openai_api_key"] = "sk-test"
svc = next(x for x in c.get("/api/local-status").get_json()["services"] if x["id"] == "builtin")
check("status: falls back to OpenAI only with the switch and a key", svc["fallback"] is True and not svc["fallback_note"], svc)
check("no key, no OpenAI fallback", (mod.CFG.update(openai_api_key="") or True) and not mod.fallback_allowed())
mod.CFG["allow_openai_fallback"] = False
# The popover names the AI picked for replies, first, whichever it is.
for pick, name, want in (("none", "No AI", "for replies"), ("openai", "OpenAI", "no key")):
    mod.CFG["chat_provider"] = pick
    mod.CFG["translation_provider"] = "builtin"
    svcs = c.get("/api/local-status").get_json()["services"]
    check(f"popover leads with {name}", svcs[0]["name"] == name and svcs[0]["state"] == want and svcs[0]["ok"], svcs[0])
    check(f"... and the built-in AI is listed for translation only", any(x["id"] == "builtin" and x["url"].startswith("Translation")
                                                                       for x in svcs), [x["url"] for x in svcs])
mod.CFG["chat_provider"] = "builtin"
mod.CFG["translation_provider"] = "builtin"
c.post("/api/settings", json={"chat_provider": "none", "translation_provider": "builtin"})
check("moving replies off the built-in AI moves translation too", mod.CFG["translation_provider"] == "openai",
      mod.CFG["translation_provider"])
mod.CFG["translation_provider"] = "openai"
mod.CFG["chat_provider"] = "openai"

# AI chosen but unreachable: Clean up falls back to the rules.
mod.CFG["response_style"] = "echo"
mod.CFG["chat_provider"] = "ollama"
mod.CFG["ollama_url"] = "http://127.0.0.1:9"
res = c.post("/api/chat", json={"message": "im here becuase of you", "speak": False, "language": "English"})
data = res.get_json()
check("unreachable AI: Clean up falls back to the rules",
      res.status_code == 200 and data["reply"] == "I'm here because of you." and data.get("rule_cleanup"), data)
check("and says why", "couldn't be reached" in data.get("rule_cleanup_reason", ""), data.get("rule_cleanup_reason"))

# ------------------------------------------------------------ the download
st = c.get("/api/builtin-ai").get_json()
check("status before: nothing downloaded", st["supported"] and not st["engine"] and not any(m["downloaded"] for m in st["models"]), st)
check("built-in listed as a chat provider", any(p["id"] == "builtin" for p in mod.CHAT_PROVIDERS))

state["engine_sha"] = "0" * 64   # GitHub's checksum doesn't match
res = c.post("/api/builtin-ai/download", json={"model": "small"})
job = wait_job()
check("wrong engine checksum refused", job["state"] == "error" and "checksum" in job["error"], job)
check("nothing left behind", not B.engine_path() and not [n for n in os.listdir(B.root) if n.endswith((".part", ".zip", ".gz"))],
      os.listdir(B.root))
state["engine_sha"] = sha(ENGINE)

Usage = namedtuple("Usage", "total used free")
real_usage = bai.shutil.disk_usage
bai.shutil.disk_usage = lambda p: Usage(10 ** 10, 10 ** 10, 1000)
res = c.post("/api/builtin-ai/download", json={"model": "small"})
check("full drive refused", res.status_code == 400 and "room" in res.get_json()["error"], res.get_json())
bai.shutil.disk_usage = real_usage

state["slow"] = True
c.post("/api/builtin-ai/download", json={"model": "better"})
time.sleep(0.2)
c.post("/api/builtin-ai/cancel")
job = wait_job()
check("download cancelled", job["state"] == "cancelled", job)
state["slow"] = False

res = c.post("/api/builtin-ai/download", json={"model": "small"})
check("one click starts it", res.status_code == 200, res.get_json())
job = wait_job()
st = c.get("/api/builtin-ai").get_json()
check("engine and model downloaded", job["state"] == "done" and st["engine"]
      and next(m for m in st["models"] if m["id"] == "small")["downloaded"], (job, st))
check("engine unpacked where Frivo looks", B.engine_path() and os.path.basename(B.engine_path()) == bai.ENGINE_EXE, B.engine_path())
check("Chat replies switched to Built-in", mod.CFG["chat_provider"] == "builtin" and st["in_use"], mod.CFG["chat_provider"])
check("translation too, as there's no OpenAI key", mod.CFG["translation_provider"] == "builtin", mod.CFG["translation_provider"])
check("model checked against Hugging Face's checksum", any("huggingface.co/api/models/unsloth/Qwen3.5-2B-GGUF" in u for u in state["calls"]))
check("no problem left", mod.builtin_ai_problem() == "", mod.builtin_ai_problem())

res = c.post("/api/builtin-ai/download", json={"model": "small"})
check("already downloaded: used straight away", res.get_json().get("ready") is True, res.get_json())

# Picking Better before it's downloaded: kept as your pick, Small answers meanwhile.
c.post("/api/settings", json={"builtin_ai_model": "better"})
st = c.get("/api/builtin-ai").get_json()
check("your pick is kept even before it's downloaded", st["model"] == "better" and st["active_model"] == "small", st)
c.post("/api/settings", json={"builtin_ai_model": "small"})

# ---------------------------------------------------- replies through it
if real:
    mod.CFG["response_style"] = "reply"
    t0 = time.time()
    res = c.post("/api/chat", json={"message": "hello there", "speak": False, "language": "English"})
    data = res.get_json()
    check("Reply through the built-in AI", res.status_code == 200 and data["reply"], data)
    check("names the built-in AI", "Built-in" in data.get("text_engine_name", ""), data.get("text_engine_name"))
    check("engine running", B.status()["running"])
    res = c.post("/api/builtin-ai/test")
    check("test answers", res.status_code == 200 and res.get_json().get("text"), res.get_json())
    B.stop()
    check("stopped", not B.status()["running"])
else:
    # The engine is a stand-in here: the reply goes through BuiltinAI.chat.
    calls = []
    B.chat = lambda messages, max_tokens, temperature=None: (calls.append(messages) or ("Hi! Nice to meet you.", "stop"))
    mod.CFG["response_style"] = "reply"
    res = c.post("/api/chat", json={"message": "hello there", "speak": False, "language": "English"})
    data = res.get_json()
    check("Reply through the built-in AI", res.status_code == 200 and data["reply"] == "Hi! Nice to meet you." and calls, data)
    check("names the built-in AI", "Built-in" in data.get("text_engine_name", ""), data.get("text_engine_name"))
    print("  (set FRIVO_TEST_LLAMA_DIR and FRIVO_TEST_GGUF to also run the real engine)")

# ---------------------------------------------------------------- removing
c.delete("/api/builtin-ai/small")
check("model removed", not B.model_path("small"))
check("replies go back to OpenAI when nothing's left to answer", mod.CFG["chat_provider"] == "openai", mod.CFG["chat_provider"])
c.delete("/api/builtin-ai")
check("everything removed", not os.path.exists(B.root))

print()
print("FAILED: %d" % len(failures) if failures else "All passed.")
sys.exit(1 if failures else 0)
