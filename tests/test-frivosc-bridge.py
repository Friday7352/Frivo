#!/usr/bin/env python3
"""Frivo's half of the FrivOSC bridge.

Frivo speaks no OSC. FrivOSC runs on the VRChat PC, checks in over HTTP,
collects queued chatbox messages, and reports the microphone state back.
This exercises that contract through Flask's test client against the real
app.py — the queue, the acknowledgements, the connected/not-connected
rule, the settings switch, and the entry in the header status chip.

Two of these exist because of bugs that shipped:

  * "the switch keeps switching back off when I press save" — the settings
    POST silently dropped osc_enabled. An earlier version of this test
    passed anyway, because a previous assertion had set the value directly
    in CFG and left it there. Every case now starts from reset().

  * the chip listed FrivOSC with the same "falling back to OpenAI" warning
    as the providers, which is not a thing that can happen to a chatbox.

Usage:  python3 tests/test-frivosc-bridge.py     (run from the repo root)
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


def load_app():
    """Import app.py from a copy, so the test never writes into the repo."""
    workspace = tempfile.mkdtemp(prefix="frivo-bridge-")
    target = os.path.join(workspace, "app.py")
    shutil.copy(os.path.join(ROOT, "app", "app.py"), target)
    spec = importlib.util.spec_from_file_location("frivo_app", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules["frivo_app"] = module
    spec.loader.exec_module(module)
    return module


mod = load_app()
client = mod.app.test_client()


def reset():
    """Known state before every case.

    Not optional bookkeeping: the version of this file that missed the
    save bug did so because state leaked from one assertion to the next.
    """
    mod.CFG["osc_enabled"] = False
    mod.CFG["osc_mute_sync"] = False
    mod.CFG["osc_unmute_on_send"] = False
    with mod.FRIVOSC_LOCK:
        mod.FRIVOSC_STATE.update({
            "connected_at": None, "last_seen": None,
            "version": "", "hostname": "", "muted": None,
        })
        mod.FRIVOSC_OUTBOX.clear()


def settings_post(payload):
    return client.post("/api/settings", json=payload)


print("--- the settings switch ---")
reset()
response = settings_post({"osc_enabled": True})
check("saving is accepted", response.status_code == 200, response.status_code)
check("SAVE STICKS (the bug)", mod.CFG.get("osc_enabled") is True, mod.CFG.get("osc_enabled"))

saved = json.load(open(mod.CONFIG_PATH))
check("and reaches config.json", saved.get("osc_enabled") is True, saved.get("osc_enabled"))

reset()
mod.CFG["osc_enabled"] = True
settings_post({"osc_enabled": False})
check("turning it back off also sticks", mod.CFG.get("osc_enabled") is False,
      mod.CFG.get("osc_enabled"))

reset()
mod.CFG["osc_enabled"] = True
settings_post({"allow_openai_fallback": True})
check("a save that does not mention it leaves it alone",
      mod.CFG.get("osc_enabled") is True, mod.CFG.get("osc_enabled"))


reset()
settings_post({"osc_mute_sync": True})
check("mute sync saves independently of the chatbox switch",
      mod.CFG.get("osc_mute_sync") is True and mod.CFG.get("osc_enabled") is False,
      (mod.CFG.get("osc_mute_sync"), mod.CFG.get("osc_enabled")))

reset()
mod.CFG["osc_mute_sync"] = True
settings_post({"osc_enabled": True})
check("and turning the chatbox on does not disturb it",
      mod.CFG.get("osc_mute_sync") is True, mod.CFG.get("osc_mute_sync"))

reset()
mod.CFG["osc_mute_sync"] = True
status = client.get("/api/frivosc/status").get_json()
check("the browser is told whether mute sync is on",
      status.get("mute_sync") is True, status)


print("\n--- checking in ---")
reset()
status = client.get("/api/frivosc/status").get_json()
check("nothing has checked in, so nothing is connected",
      status["connected"] is False, status)

client.post("/api/frivosc/hello", json={"version": "1.0.0", "hostname": "VRPC"})
status = client.get("/api/frivosc/status").get_json()
check("a hello marks it connected", status["connected"] is True, status)
check("and records which machine", status.get("hostname") == "VRPC", status)

with mod.FRIVOSC_LOCK:
    mod.FRIVOSC_STATE["last_seen"] = time.time() - (mod.FRIVOSC_STALE_SECONDS + 5)
status = client.get("/api/frivosc/status").get_json()
check("it goes down again when it stops reporting",
      status["connected"] is False, status)


print("\n--- saving the switches on their own ---")
# They live in the sidebar status panel, which has no Save button. Without
# an endpoint of their own they flipped, were never persisted, and the next
# poll read the unchanged value back and silently flipped them off again.
reset()
mod.CFG["voice_name"] = "Rachel"
mod.CFG["max_words"] = 80
response = client.post("/api/frivosc/settings", json={"osc_mute_sync": True})
check("the switches can be saved without the Settings sheet",
      response.status_code == 200, response.status_code)
check("and the save sticks", mod.CFG.get("osc_mute_sync") is True,
      mod.CFG.get("osc_mute_sync"))
check("the response says what the server now holds",
      response.get_json().get("osc_mute_sync") is True, response.get_json())
check("saving one switch leaves the other alone",
      mod.CFG.get("osc_enabled") is False, mod.CFG.get("osc_enabled"))
check("and does not disturb unrelated settings",
      mod.CFG.get("voice_name") == "Rachel" and mod.CFG.get("max_words") == 80,
      (mod.CFG.get("voice_name"), mod.CFG.get("max_words")))
saved = json.load(open(mod.CONFIG_PATH))
check("it reaches config.json", saved.get("osc_mute_sync") is True,
      saved.get("osc_mute_sync"))

client.post("/api/frivosc/settings", json={"osc_mute_sync": False})
check("and turning it back off saves too", mod.CFG.get("osc_mute_sync") is False,
      mod.CFG.get("osc_mute_sync"))


print("\n--- what mute sync acts on ---")
reset()
mod.CFG["osc_mute_sync"] = True
status = client.get("/api/frivosc/status").get_json()
check("no companion means the mic state is unknown, not unmuted",
      status["muted"] is None, status)

client.post("/api/frivosc/hello", json={"version": "1.0.0", "hostname": "VRPC"})
status = client.get("/api/frivosc/status").get_json()
check("still unknown before VRChat has said anything", status["muted"] is None, status)

client.post("/api/frivosc/state", json={"muted": False})
status = client.get("/api/frivosc/status").get_json()
check("unmuted is reported once VRChat says so", status["muted"] is False, status)

client.post("/api/frivosc/state", json={"muted": True})
status = client.get("/api/frivosc/status").get_json()
check("and muted after that", status["muted"] is True, status)

with mod.FRIVOSC_LOCK:
    mod.FRIVOSC_STATE["last_seen"] = time.time() - (mod.FRIVOSC_STALE_SECONDS + 5)
status = client.get("/api/frivosc/status").get_json()
check("a companion that stopped reporting goes back to unknown, not unmuted",
      status["muted"] is None, status)


print("\n--- unmute on send ---")
# VRChat exposes a button, not a settable state, so this can only ever
# unmute. There is deliberately no matching mute: silencing someone
# mid-conversation is a far worse failure than failing to open their mic.
reset()
response = client.post("/api/frivosc/unmute")
check("refused while VRChat OSC is off", response.status_code == 400, response.status_code)

reset()
mod.CFG["osc_enabled"] = True
response = client.post("/api/frivosc/unmute")
check("refused while the switch itself is off", response.status_code == 400,
      response.status_code)

reset()
mod.CFG["osc_enabled"] = True
mod.CFG["osc_unmute_on_send"] = True
response = client.post("/api/frivosc/unmute")
check("refused when FrivOSC is not there to do it", response.status_code == 503,
      response.status_code)

reset()
mod.CFG["osc_enabled"] = True
mod.CFG["osc_unmute_on_send"] = True
client.post("/api/frivosc/hello", json={"version": "1.0.0", "hostname": "VRPC"})
client.post("/api/frivosc/state", json={"muted": False})
response = client.post("/api/frivosc/unmute")
check("nothing queued when already unmuted",
      response.status_code == 200 and response.get_json().get("queued") is False,
      response.get_json())
check("and the outbox stays empty", len(mod.FRIVOSC_OUTBOX) == 0,
      len(mod.FRIVOSC_OUTBOX))

client.post("/api/frivosc/state", json={"muted": True})
response = client.post("/api/frivosc/unmute")
check("queued when muted", response.get_json().get("queued") is True,
      response.get_json())
outbox = client.get("/api/frivosc/outbox").get_json()
queued = (outbox.get("messages") or [])
check("FrivOSC is handed an unmute", any(m.get("unmute") for m in queued), outbox)
check("with no text, so it is not also a chatbox message",
      all(not m.get("text") for m in queued if m.get("unmute")), outbox)

# The mute state can be unknown — no companion, or one that has not heard
# from VRChat yet. Queue it and let FrivOSC decide, since it is the one
# that can actually see the state.
reset()
mod.CFG["osc_enabled"] = True
mod.CFG["osc_unmute_on_send"] = True
client.post("/api/frivosc/hello", json={"version": "1.0.0", "hostname": "VRPC"})
response = client.post("/api/frivosc/unmute")
check("an unknown mute state still queues, for FrivOSC to judge",
      response.get_json().get("queued") is True, response.get_json())

reset()
response = client.post("/api/frivosc/settings", json={"osc_unmute_on_send": True})
check("the switch saves with the others",
      mod.CFG.get("osc_unmute_on_send") is True, mod.CFG.get("osc_unmute_on_send"))
check("and is reported back to the browser",
      response.get_json().get("osc_unmute_on_send") is True, response.get_json())


print("\n--- the queue ---")
reset()
client.post("/api/frivosc/hello", json={"version": "1.0.0", "hostname": "VRPC"})
mod.CFG["osc_enabled"] = True
client.post("/api/osc/chatbox", json={"text": "Hello VRChat."})
outbox = client.get("/api/frivosc/outbox").get_json()
check("a chatbox message is queued for collection",
      any(m.get("text") == "Hello VRChat." for m in outbox.get("messages", [])), outbox)

message_id = outbox["messages"][0]["id"]
client.post("/api/frivosc/ack", json={"id": message_id, "pages": 1})
outbox = client.get("/api/frivosc/outbox").get_json()
check("an acknowledged message is not handed out twice",
      not outbox.get("messages"), outbox)

reset()
mod.CFG["osc_enabled"] = True
for index in range(mod.FRIVOSC_OUTBOX_MAX + 10):
    client.post("/api/osc/chatbox", json={"text": "message %d" % index})
check("the queue is bounded, so a disconnected FrivOSC cannot grow it forever",
      len(mod.FRIVOSC_OUTBOX) <= mod.FRIVOSC_OUTBOX_MAX, len(mod.FRIVOSC_OUTBOX))


print("\n--- the header status chip (same shape as Evora's) ---")
reset()
services = client.get("/api/local-status").get_json()["services"]
check("hidden entirely while the feature is off",
      not [s for s in services if s["id"] == "frivosc"], services)

reset()
mod.CFG["osc_enabled"] = True
services = client.get("/api/local-status").get_json()["services"]
entry = next((s for s in services if s["id"] == "frivosc"), None)
check("listed once the feature is on", entry is not None, services)
check("and reads as down until it checks in", entry and entry["ok"] is False, entry)
check("carries the same fields Evora's entry does",
      entry and {"id", "name", "ok", "message", "url", "used_for"} <= set(entry), entry)
check("marked as having no OpenAI fallback",
      entry and entry.get("fallback") is False, entry)

client.post("/api/frivosc/hello", json={"version": "1.0.0", "hostname": "VRPC"})
services = client.get("/api/local-status").get_json()["services"]
entry = next((s for s in services if s["id"] == "frivosc"), None)
check("flips to up once it checks in", entry and entry["ok"] is True, entry)

print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("All FrivOSC bridge assertions passed.")
