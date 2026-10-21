#!/usr/bin/env python3
"""NEW (1.5.0): managing the models on the Ollama PC.

  * the list: sizes, which tier uses each, loaded, whether it fits the card
  * removing asks Ollama to delete it; a bad name is refused
  * downloading follows Ollama's progress, finishes, and can be stopped
  * suggestions have their real size from Ollama's library; one the library
    doesn't have is left out; a lookup says if a typed name exists
  * the drive comes from Evora when it's on the same PC as Ollama

Usage:  python3 tests/test-ollama-manager.py     (run from the repo root)
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-om-home-")
ws = tempfile.mkdtemp(prefix="frivo-om-")
shutil.copy(os.path.join(ROOT, "app", "app.py"), os.path.join(ws, "app.py"))
spec = importlib.util.spec_from_file_location("frivo_om", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_om"] = mod
spec.loader.exec_module(mod)

GB = 1024 ** 3
state = {
    "installed": {"gemma3:4b": int(3.3 * GB), "huihui_ai/qwen3.5-abliterated:9b": int(6.6 * GB)},
    "loaded": ["gemma3:4b"],
    "registry": {"library/qwen3.5/manifests/4b": int(3.4 * GB),
                 "huihui_ai/qwen3.5-abliterated/manifests/4b": int(3.4 * GB),
                 "library/llama3.1/manifests/8b": int(4.9 * GB)},
    "deleted": [],
    "disk": {"found": True, "path": r"C:\Users\Administrator\.ollama\models", "drive": "C:",
             "total_bytes": 500 * GB, "free_bytes": 80 * GB, "used_bytes": 420 * GB},
    "pull_gate": threading.Event(),
}


def resp(status, body=None, lines=None):
    r = SimpleNamespace(status_code=status, text=json.dumps(body or {}), json=lambda: body or {},
                        raise_for_status=lambda: None if status < 400 else (_ for _ in ()).throw(RuntimeError(status)))
    r.closed = False

    def iter_lines():
        for line in lines or []:
            if r.closed:
                raise RuntimeError("connection closed")
            if line == "WAIT":
                state["pull_gate"].wait(5)
                continue
            yield json.dumps(line).encode()
    r.iter_lines = iter_lines
    r.close = lambda: setattr(r, "closed", True)
    r.__enter__ = lambda *a: r
    r.__exit__ = lambda *a: False
    return r


class Ctx:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self.r

    def __exit__(self, *a):
        return False


def fake_get(url, *a, **kw):
    if url.endswith("/api/tags"):
        return resp(200, {"models": [{"name": n, "size": s, "details": {"parameter_size": "9B" if "9b" in n else "4B",
                                                                         "quantization_level": "Q4_K_M"}}
                                     for n, s in state["installed"].items()]})
    if url.endswith("/api/ps"):
        return resp(200, {"models": [{"name": n, "size": 1, "size_vram": 1} for n in state["loaded"]]})
    if url.endswith("/disk"):
        return resp(200, state["disk"])
    if url.endswith("/gpu"):
        return resp(200, {"ok": True, "total_mb": 8192, "used_mb": 2000,
                          "parts": {"ollama_mb": 0, "evora_mb": 1500, "other_mb": 500}})
    if "registry.ollama.ai" in url:
        key = url.split("/v2/")[1]
        size = state["registry"].get(key)
        if size is None:
            return resp(404, {"errors": []})
        return resp(200, {"config": {"size": 0}, "layers": [{"size": size}]})
    raise AssertionError(url)


def fake_post(url, *a, **kw):
    if url.endswith("/api/pull"):
        name = kw["json"]["model"]
        lines = [{"status": "pulling manifest"},
                 {"status": "pulling abc", "digest": "sha256:abc", "total": 100, "completed": 40},
                 "WAIT",
                 {"status": "pulling abc", "digest": "sha256:abc", "total": 100, "completed": 100},
                 {"status": "success"}]
        r = resp(200, lines=lines)
        if name == "nope:1b":
            r = resp(404, {"error": "pull model manifest: file does not exist"})
        state["last_pull"] = r
        return Ctx(r)
    raise AssertionError(url)


def fake_delete(url, *a, **kw):
    name = kw["json"]["model"]
    if name not in state["installed"]:
        return resp(404, {"error": "model not found"})
    state["installed"].pop(name)
    state["deleted"].append(name)
    return resp(200, {})


mod.requests.get = fake_get
mod.requests.post = fake_post
mod.requests.delete = fake_delete
mod.CFG.update(ollama_url="http://192.168.1.250:11434", whisper_url="http://192.168.1.250:9000",
               chat_provider="ollama", ollama_model="gemma3:4b", ollama_model_balanced="qwen3.5:4b",
               ollama_model_best="huihui_ai/qwen3.5-abliterated:9b")
mod.gpu_watch_targets = lambda: (True, True)
mod._gpu_state["latest"] = None
client = mod.app.test_client()

print("--- the list ---")
d = client.get("/api/ollama/models").get_json()
names = [m["name"] for m in d["installed"]]
best = next(m for m in d["installed"] if m["name"].startswith("huihui"))
check("installed models, with sizes", names == ["gemma3:4b", "huihui_ai/qwen3.5-abliterated:9b"] and best["size"] > 6 * GB, d)
check("which tier uses each", best["tiers"] == ["best"] and d["installed"][0]["tiers"] == ["fast"])
check("loaded or not", d["installed"][0]["loaded"] and not best["loaded"])
check("size class and quantisation", best["params"] == "9B" and best["quant"] == "Q4_K_M")
check("the card, with Evora's share", d["card"] == {"total_mb": 8192, "evora_mb": 1500}, d["card"])
check("the 9B doesn't fit beside Evora", best["fit"] == "tight", best["fit"])
check("the 4B does", d["installed"][0]["fit"] == "fits")
check("the drive, from Evora", d["drive"]["ok"] and d["drive"]["free_bytes"] == 80 * GB and d["used_bytes"] > 9 * GB)

print("--- the drive when Evora can't say ---")
mod.CFG["whisper_url"] = "http://192.168.1.99:9000"
check("Evora on another PC: said so", "different PC" in client.get("/api/ollama/models").get_json()["drive"]["reason"])
mod.CFG["whisper_url"] = "http://192.168.1.250:9000"

print("--- suggestions ---")
s = client.get("/api/ollama/suggestions?lookup=llama3.1:8b").get_json()
by = {x["name"]: x for x in s["suggestions"]}
check("real sizes from the library", by["qwen3.5:4b"]["size"] == int(3.4 * GB), by.get("qwen3.5:4b"))
check("installed ones are marked", by["huihui_ai/qwen3.5-abliterated:9b"]["installed"] if "huihui_ai/qwen3.5-abliterated:9b" in by else True)
check("ones the library doesn't have are left out", "gemma3:1b" not in by)
check("grouped", {x["group"] for x in s["suggestions"]} >= {"Everyday", "Uncensored"})
check("a typed name is looked up", s["lookup"]["found"] and s["lookup"]["size"] == int(4.9 * GB) and s["lookup"]["fit"] == "fits", s["lookup"])
s2 = client.get("/api/ollama/suggestions?lookup=madeup:7b").get_json()
check("... and a made-up one isn't found", s2["lookup"]["found"] is False)
check("a bad name isn't even looked up", client.get("/api/ollama/suggestions?lookup=../../etc").get_json()["lookup"] is None)

print("--- downloading ---")
r = client.post("/api/ollama/pull", json={"model": "qwen3.5:4b"})
check("started", r.status_code == 200)
check("twice is refused", client.post("/api/ollama/pull", json={"model": "qwen3.5:4b"}).status_code == 409)
time.sleep(0.3)
p = client.get("/api/ollama/pull").get_json()["pulls"]["qwen3.5:4b"]
check("progress", p["state"] == "pulling" and p["completed"] == 40 and p["total"] == 100, p)
check("knows the expected size", p["expected"] == int(3.4 * GB))
state["pull_gate"].set()
time.sleep(0.3)
p = client.get("/api/ollama/pull").get_json()["pulls"]["qwen3.5:4b"]
check("finished", p["state"] == "done", p)
state["pull_gate"].clear()
client.post("/api/ollama/pull", json={"model": "llama3.1:8b"})
time.sleep(0.3)
client.delete("/api/ollama/pull", json={"model": "llama3.1:8b"})
state["pull_gate"].set()
time.sleep(0.3)
p = client.get("/api/ollama/pull").get_json()["pulls"]["llama3.1:8b"]
check("stopped", p["state"] == "stopped" and not p.get("error"), p)
client.post("/api/ollama/pull", json={"model": "nope:1b"})
time.sleep(0.3)
p = client.get("/api/ollama/pull").get_json()["pulls"]["nope:1b"]
check("a failed one says why", p["state"] == "error" and "does not exist" in p["error"], p)
check("a bad name is refused", client.post("/api/ollama/pull", json={"model": "rm -rf /"}).status_code == 400)

print("--- removing ---")
r = client.delete("/api/ollama/models", json={"model": "gemma3:4b"})
check("removed, and the list comes back", r.status_code == 200 and state["deleted"] == ["gemma3:4b"]
      and [m["name"] for m in r.get_json()["installed"]] == ["huihui_ai/qwen3.5-abliterated:9b"], r.get_json())
check("one that isn't there", client.delete("/api/ollama/models", json={"model": "gemma3:4b"}).status_code == 404)
check("no name", client.delete("/api/ollama/models", json={}).status_code == 400)

print("--- the card fit ---")
check("a model that fits nowhere", mod.model_fit(9 * GB, 8192, 1500) == "big")
check("no card: no claim", mod.model_fit(3 * GB, None, None) == "")

print()
if failures:
    print(f"{len(failures)} failed: {failures}")
    sys.exit(1)
print("All model-manager checks passed.")
