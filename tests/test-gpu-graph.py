#!/usr/bin/env python3
"""NEW (1.5.0): the graphics-card memory graph in the status popover.

Against stand-in Evora and Ollama servers (requests is replaced), this checks:

  * nothing is sampled, and the graph is hidden, with no local service chosen
  * with Evora: the card, its Ollama / Evora / Other split, and Ollama's
    loaded models; "same card" when Evora saw Ollama on it
  * Windows didn't say who uses the card: Ollama's own figure splits it
    when Ollama is on the same PC, and Evora is counted in Other
  * Ollama on another PC: not stacked onto Evora's card
  * an Evora too old to have /gpu, an unreachable Evora, a PC without an
    NVIDIA card, and Ollama alone: each says what's going on
  * history keeps ten minutes and drops older readings
  * the page has the graph, and app.js draws it

Usage:  python3 tests/test-gpu-graph.py     (run from the repo root)
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
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-gpu-home-")
ws = tempfile.mkdtemp(prefix="frivo-gpu-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
for folder in ("templates", "static"):
    os.symlink(os.path.join(APP, folder), os.path.join(ws, folder))
spec = importlib.util.spec_from_file_location("frivo_gpu", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_gpu"] = mod
spec.loader.exec_module(mod)
client = mod.app.test_client()

MB = 1048576
world = {}


def reset_world():
    world.clear()
    world.update(evora="ok", ollama_up=True, models=[("qwen3.5:4b", 3954, 3954)],
                 parts={"ollama_mb": 3954, "evora_mb": 1150, "other_mb": 688})


def resp(status, body):
    return SimpleNamespace(status_code=status, json=lambda: body,
                           raise_for_status=lambda: None if status < 400 else (_ for _ in ()).throw(RuntimeError(status)))


def fake_get(url, timeout=None, **kw):
    if url.endswith("/gpu"):
        if world["evora"] == "down":
            raise ConnectionError("down")
        if world["evora"] == "old":
            return resp(404, {})
        if world["evora"] == "nocard":
            return resp(200, {"ok": False, "reason": "No NVIDIA graphics card found"})
        return resp(200, {"ok": True, "name": "NVIDIA GeForce RTX 2070 SUPER", "total_mb": 8192,
                          "used_mb": 5792, "util_pct": 23, "temp_c": 54,
                          "parts": dict(world["parts"]) if world["parts"] else None, "processes": [],
                          **({"idle": world["idle"]} if world.get("idle") else {})})
    if url.endswith("/api/ps"):
        if not world["ollama_up"]:
            raise ConnectionError("down")
        return resp(200, {"models": [{"name": n, "size": s * MB, "size_vram": v * MB} for n, s, v in world["models"]]})
    raise AssertionError("unexpected GET " + url)


mod.requests.get = fake_get


def configure(chat="ollama", transcription="local_whisper",
              ollama_url="http://192.168.1.250:11434", whisper_url="http://192.168.1.250:9000"):
    mod.CFG.update(chat_provider=chat, translation_provider="openai", transcription_provider=transcription,
                   ollama_url=ollama_url, whisper_url=whisper_url)
    mod._gpu_state["latest"] = None
    mod._gpu_state["history"].clear()


def get():
    return client.get("/api/gpu").get_json()


print("Nothing local chosen")
reset_world()
configure(chat="openai", transcription="openai")
data = get()
check("graph is off", data == {"enabled": False}, data)
check("watch targets are off", mod.gpu_watch_targets() == (False, False))

print("Evora and Ollama on one PC")
reset_world()
configure()
data = get()
card = data.get("card") or {}
check("enabled", data.get("enabled") is True)
check("card reported", card.get("total_mb") == 8192 and card.get("used_mb") == 5792, card)
check("split kept", card.get("parts") == world["parts"], card.get("parts"))
check("same card", data.get("same_card") is True)
check("Ollama's models listed", [{k: m[k] for k in ("name", "vram_mb", "size_mb")} for m in data.get("ollama_models") or []]
      == [{"name": "qwen3.5:4b", "vram_mb": 3954, "size_mb": 3954}],
      data.get("ollama_models"))
point = (data.get("history") or [{}])[-1]
check("history point", point.get("ollama") == 3954 and point.get("evora") == 1150 and point.get("other") == 688
      and point.get("total") == 8192, point)

print("Windows didn't say who uses the card")
reset_world()
world["parts"] = None
configure()
parts = get()["card"]["parts"]
check("split from Ollama's own figure", parts == {"ollama_mb": 3954, "evora_mb": 0, "other_mb": 1838, "estimated": True}, parts)
configure(ollama_url="http://localhost:11434", whisper_url="http://evora.local:9000")
check("localhost and evora.local are the same PC", get()["same_card"] is True)

print("Ollama on another PC")
reset_world()
world["parts"] = {"ollama_mb": 0, "evora_mb": 1150, "other_mb": 4642}
configure(ollama_url="http://192.168.1.77:11434")
data = get()
check("not the same card", data["same_card"] is False)
check("Ollama still listed", len(data["ollama_models"]) == 1)

print("Problems say what's going on")
for state, words in (("old", "Update Evora"), ("down", "isn't reachable"), ("nocard", "No NVIDIA")):
    reset_world()
    world["evora"] = state
    configure()
    data = get()
    check(f"Evora {state}: no card, says so", data["card"] is None and words in (data["card_problem"] or ""),
          data["card_problem"])
    check(f"Evora {state}: Ollama still graphed", (data["history"] or [{}])[-1].get("ollama") == 3954, data["history"])
reset_world()
world["ollama_up"] = False
configure(transcription="openai")
data = get()
check("Ollama alone and down: says so", "isn't reachable" in (data["ollama_problem"] or "") and data["card"] is None)
check("Ollama alone and down: nothing to graph", data["history"] == [])

print("The idle countdown")   # NEW (1.5.0)
import datetime as _dt
soon = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=42)).strftime("%Y-%m-%dT%H:%M:%S.123456789+00:00")
left = mod.seconds_until_stamp(soon)
check("reads Ollama's nanosecond timestamps", left is not None and 2500 < left <= 2520, left)
check("a timestamp in another zone", abs(mod.seconds_until_stamp("2318-01-01T00:00:00-05:00")) > mod.OLLAMA_FOREVER_SECONDS)
check("nonsense: none", mod.seconds_until_stamp("soon") is None and mod.seconds_until_stamp(None) is None)
real_get = mod._ollama_get
mod._ollama_get = lambda path: {"models": [
    {"name": "a", "size": MB, "size_vram": MB, "expires_at": soon},
    {"name": "b", "size": MB, "size_vram": MB, "expires_at": "2318-02-15T10:00:00.1-05:00"}]}
models, _ = mod.read_ollama_gpu()
check("seconds until each model leaves the card", 2500 < (models[0]["unload_in"] or 0) <= 2520 and not models[0]["forever"], models[0])
check("'Never' reads as forever, not a countdown", models[1]["forever"] and models[1]["unload_in"] is None, models[1])
mod._ollama_get = real_get

print("History keeps ten minutes")
reset_world()
configure()
now = mod.time.time()
for age in (900, 700, 300, 10):
    mod._gpu_state["history"].append({"t": now - age, "total": 8192, "used": 1, "ollama": 1, "evora": 0, "other": 0})
mod.record_gpu_sample(mod.gpu_sample())
ages = [round(now - p["t"]) for p in mod._gpu_state["history"]]
check("older than ten minutes dropped", all(a <= 600 for a in ages) and len(ages) == 3, ages)

print("The page")
html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
js = open(os.path.join(APP, "static", "app.js"), encoding="utf-8").read()
check("graph in the status popover", 'id="gpuCard"' in html and html.index('id="gpuCard"') < html.index('id="creditsToggle"'))
check("app.js draws it", "function renderGpu" in js and "/api/gpu" in js and "function drawGpuChart" in js)
check("only polled while open", "watchGpuWhileStatusOpen" in js)
check("shows the idle countdown", "function gpuIdleNote" in js and "frees the graphics card in" in js)   # NEW (1.5.0)

print("Evora's idle timers")   # NEW (1.5.0)
reset_world()
configure()
world["idle"] = {"listening": False, "listen": {"loaded": True, "unload_in": 200}, "speech": {"loaded": True, "unload_in": 3000}}
data = get()
check("Evora's countdowns reach the graph, not inside the card", data.get("evora_idle", {}).get("listen", {}).get("unload_in") == 200
      and "idle" not in (data.get("card") or {}), data.get("evora_idle"))
world.pop("idle")
configure()
check("an older Evora: none", get().get("evora_idle") is None)
check("app.js shows them", "function evoraIdleNote" in js and "frees the listening models in" in js)
posted = []
mod.requests.post = lambda url, json=None, **kw: posted.append((url, json)) or resp(200, {})
mod.CFG.update(evora_idle_listen="15m", evora_idle_speech="never")
mod.apply_evora_idle_timers()
check("Frivo passes its timers to Evora, in minutes", posted == [("http://192.168.1.250:9000/idle", {"listen_minutes": 15, "speech_minutes": 0})], posted)
posted.clear()
res = client.post("/api/settings", json={"evora_idle_listen": "1h", "evora_idle_speech": "bogus"})
import time as _t
_t.sleep(0.3)
check("a change in Settings is passed on; nonsense is ignored", mod.CFG["evora_idle_listen"] == "1h" and mod.CFG["evora_idle_speech"] == "never"
      and posted and posted[-1][1] == {"listen_minutes": 60, "speech_minutes": 0}, (posted, mod.CFG.get("evora_idle_speech")))
configure(transcription="openai")
posted.clear()
mod.apply_evora_idle_timers()
check("not using Evora: nothing sent", posted == [])
html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
check("the two timers are in Settings", 'id="evoraIdleListen"' in html and 'id="evoraIdleSpeech"' in html)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("All GPU graph checks passed.")
