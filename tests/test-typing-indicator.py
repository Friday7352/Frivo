#!/usr/bin/env python3
"""NEW (typing): VRChat's typing dots while you respond.

Frivo works out whether you are putting a reply together and says so on the
outbox reply FrivOSC already polls; FrivOSC (1.2.0+) turns that into
/chatbox/typing. This checks Frivo's half:

  * the outbox carries "typing", and only with OSC on and the switch on
  * a "typing" nobody refreshes expires, so a closed page can't leave the
    dots up
  * the switch saves itself and comes back from /api/settings
  * in a real browser: typing in the box raises it, a draft left sitting
    drops it, sending drops it, talking with Live (Evora) raises it, the
    Chatbox switch off means never, and the Settings switch off means never

Usage:  python3 tests/test-typing-indicator.py     (run from the repo root)
Needs:  flask, node, playwright with chromium.
"""

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
PORT = 5095
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


def server_side():
    print("--- the server ---")
    ws = tempfile.mkdtemp(prefix="frivo-typing-")
    shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
    spec = importlib.util.spec_from_file_location("frivo_typing", os.path.join(ws, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frivo_typing"] = mod
    spec.loader.exec_module(mod)
    client = mod.app.test_client()

    def reset(osc=True, typing=True):
        mod.CFG["osc_enabled"] = osc
        mod.CFG["osc_typing"] = typing
        with mod.FRIVOSC_LOCK:
            mod.FRIVOSC_STATE["typing_until"] = 0.0

    def outbox_typing():
        return client.get("/api/frivosc/outbox").get_json().get("typing")

    reset()
    check("nobody typing: the outbox says so", outbox_typing() is False)
    client.post("/api/frivosc/typing", json={"typing": True})
    check("typing: the outbox carries it", outbox_typing() is True)
    client.post("/api/frivosc/typing", json={"typing": False})
    check("stopped: it is cleared at once", outbox_typing() is False)

    reset()
    client.post("/api/frivosc/typing", json={"typing": True})
    with mod.FRIVOSC_LOCK:
        mod.FRIVOSC_STATE["typing_until"] -= mod.FRIVOSC_TYPING_HOLD + 0.1
    check("a typing nobody refreshes expires", outbox_typing() is False)

    reset(typing=False)
    client.post("/api/frivosc/typing", json={"typing": True})
    check("the switch off means never", outbox_typing() is False)

    reset(osc=False)
    client.post("/api/frivosc/typing", json={"typing": True})
    body = client.get("/api/frivosc/outbox").get_json()
    check("VRChat OSC off means never", not body.get("typing"), body)

    reset()
    saved = client.post("/api/frivosc/settings", json={"osc_typing": False}).get_json()
    check("the switch saves itself", saved.get("osc_typing") is False and mod.CFG["osc_typing"] is False, saved)
    check("and /api/settings reports it", client.get("/api/settings").get_json().get("osc_typing") is False)
    check("and the status poll does", client.get("/api/frivosc/status").get_json().get("typing_enabled") is False)
    client.post("/api/frivosc/settings", json={"osc_typing": True})
    fresh_path = mod.CONFIG_PATH
    mod.CONFIG_PATH = os.path.join(ws, "missing.json")
    check("it is on in a fresh config", mod.load_config().get("osc_typing") is True)
    mod.CONFIG_PATH = fresh_path


SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, time
ws = tempfile.mkdtemp(prefix="frivo-typing-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)
mod.CFG["osc_enabled"] = True
mod.CFG["osc_typing"] = True
mod.CFG["transcription_provider"] = "local_whisper"
mod.CFG["whisper_url"] = "http://192.168.1.9:9000"
mod.probe_provider = lambda name, timeout=2: (True, "Reachable.")
mod.local_whisper_transcribe = lambda f, language=None: (time.sleep(0.3), "hello")[1]
from flask import jsonify
@mod.app.route("/_test/peek")
def _peek():
    # What FrivOSC would see, without emptying the outbox or counting as it.
    return jsonify(typing=mod.frivosc_typing())
@mod.app.route("/_test/connect")
def _connect():
    mod.frivosc_touch(version="1.1.0", hostname="VRPC")
    return jsonify(ok=True)
mod.app.run(host="127.0.0.1", port=5095, debug=False, use_reloader=False, threaded=True)
"""

BROWSER = r"""
const { chromium } = require('playwright');
const wait = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
function check(name, cond, got) {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : `   got=${JSON.stringify(got)}`));
  if (!cond) fails.push(name);
}
(async () => {
  const b = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const ctx = await b.newContext({ permissions: ['microphone'] });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.addInitScript(() => {
    localStorage.setItem('voice_console_osc_enabled', '1');        // the Chatbox switch
    localStorage.setItem('voice_console_dictation_mode', 'live_local');
    localStorage.setItem('voice_console_auto_send', '0');
  });
  const base = 'http://127.0.0.1:5095';
  // FrivOSC "connected" for the whole run.
  const keepAlive = setInterval(() => fetch(base + '/_test/connect').catch(() => {}), 1000);
  await fetch(base + '/_test/connect');
  await p.goto(base + '/', { waitUntil: 'networkidle' });
  await wait(1500);
  await p.evaluate(() => pollFrivoscStatus());
  await wait(500);
  const peek = async () => (await (await fetch(base + '/_test/peek')).json()).typing;

  console.log('--- typing a reply ---');
  check('nothing typed, no dots', (await peek()) === false);
  await p.fill('#messageInput', 'hey, one sec');
  await wait(600);
  check('typing in the box puts the dots up', (await peek()) === true);
  await wait(5000);
  check('a draft left sitting drops them', (await peek()) === false);
  await p.type('#messageInput', ' more');
  await wait(600);
  check('typing again brings them back', (await peek()) === true);
  await p.fill('#messageInput', '');
  await wait(600);
  check('an empty box (sent, or cleared) drops them', (await peek()) === false);

  console.log('--- talking (Live, Evora) ---');
  await p.evaluate(() => { window.__level = 0; currentRms = () => window.__level; });
  await p.click('#dictateBtn'); await wait(300);
  await p.evaluate(() => { window.__level = 0.2; });
  await wait(700);
  check('talking puts the dots up before any text arrives', (await peek()) === true);
  await wait(2500);
  check('and they stay up while you keep talking (refreshed)', (await peek()) === true);
  await p.evaluate(() => { window.__level = 0; });
  await p.click('#dictateBtn'); await wait(400);
  await p.fill('#messageInput', ''); await wait(600);
  check('stopping, with nothing left to send, drops them', (await peek()) === false);

  console.log('--- switches ---');
  await p.evaluate(() => { oscToggle.checked = false; oscToggle.dispatchEvent(new Event('change', { bubbles: true })); });
  await p.fill('#messageInput', 'not for VRChat'); await wait(600);
  check('Chatbox switch off: never', (await peek()) === false);
  await p.evaluate(() => { oscToggle.checked = true; oscToggle.dispatchEvent(new Event('change', { bubbles: true })); });
  await p.type('#messageInput', '!'); await wait(600);
  check('Chatbox switch on again: dots', (await peek()) === true);
  await p.evaluate(() => { const t = document.getElementById('oscTypingToggle'); t.checked = false; t.dispatchEvent(new Event('change', { bubbles: true })); });
  await p.type('#messageInput', '?'); await wait(700);
  check('"Show typing" off in Settings: never', (await peek()) === false);
  await p.reload({ waitUntil: 'networkidle' }); await wait(800);
  check('and it stays off after a reload', await p.evaluate(() => document.getElementById('oscTypingToggle').checked === false));

  clearInterval(keepAlive);
  console.log('\nerrors: ' + (errors.length ? JSON.stringify(errors) : 'none'));
  check('no page errors', errors.length === 0, errors);
  await b.close();
  process.exit(fails.length ? 1 : 0);
})();
"""


def wait_for_port(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


def browser_side():
    print()
    print("--- in the browser ---")
    work = tempfile.mkdtemp(prefix="frivo-typing-run-")
    server_py = os.path.join(work, "server.py")
    with open(server_py, "w") as handle:
        handle.write("APP=%r\n" % APP + SERVER)
    browser_js = os.path.join(work, "browser.cjs")
    with open(browser_js, "w") as handle:
        handle.write(BROWSER)
    server = subprocess.Popen([sys.executable, server_py], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_for_port(PORT):
            check("server started", False)
            return
        env = dict(os.environ)
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        if subprocess.run(["node", browser_js], env=env).returncode != 0:
            failures.append("browser")
    finally:
        server.terminate()


if __name__ == "__main__":
    server_side()
    browser_side()
    print()
    if failures:
        print("%d typing check(s) failed." % len(failures))
        sys.exit(1)
    print("All typing-indicator checks passed.")
