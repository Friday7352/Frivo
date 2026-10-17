#!/usr/bin/env python3
"""NEW (1.5.0): typing dots through the reply, and auto-send only for speech.

Two things that used to go wrong between hitting send and the reply landing:

  * The VRChat typing dots dropped the moment the message left the box,
    then nothing showed for the seconds the reply took to write, translate
    and voice. They now stay up until the chatbox message is queued (when
    the voice starts, or straight away with Speak off), drop at once on an
    error, and give up after 30s whatever happens.
  * Auto-send fired on text being edited by hand: dictate a sentence, start
    fixing a word, and the dictation's timer sent it mid-edit. Typing in the
    box now makes that message yours (only Enter sends it) and the switch
    shows it is paused; the next message is back to auto-send.

Real page, real browser, real server, with /api/chat made slow and the
microphone level under the test's control.

Usage:  python3 tests/test-reply-flow.py     (run from the repo root)
Needs:  flask, node, playwright with chromium.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
PORT = 5094

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, time
ws = tempfile.mkdtemp(prefix="frivo-reply-")
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
mod.local_whisper_transcribe = lambda f, language=None: (time.sleep(0.2), "hello there")[1]
from flask import jsonify, request
state = {"fail": False, "chatbox": []}
@mod.app.before_request
def _intercept():
    if request.path == "/api/chat":
        time.sleep(2.0)                          # writing, translating
        if state["fail"]:
            state["fail"] = False
            return jsonify(error="boom"), 500
        return jsonify(reply="Sure thing.", english=None, char_count=11, credits=0,
                       audio_url=None, spoke=False)
    if request.path == "/api/osc/chatbox":
        state["chatbox"].append(time.time())
        return jsonify(ok=True, id="x", delivery="queued", pages=1)
@mod.app.route("/_test/peek")
def _peek():
    return jsonify(typing=mod.frivosc_typing(), chatbox=len(state["chatbox"]))
@mod.app.route("/_test/fail-next")
def _fail():
    state["fail"] = True
    return jsonify(ok=True)
@mod.app.route("/_test/connect")
def _connect():
    mod.frivosc_touch(version="1.2.0", hostname="VRPC")
    return jsonify(ok=True)
mod.app.run(host="127.0.0.1", port=5094, debug=False, use_reloader=False, threaded=True)
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
  const base = 'http://127.0.0.1:5094';
  const keep = setInterval(() => fetch(base + '/_test/connect').catch(() => {}), 1000);
  await fetch(base + '/_test/connect');
  const b = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const ctx = await b.newContext({ permissions: ['microphone'] });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.addInitScript(() => {
    localStorage.setItem('voice_console_osc_enabled', '1');
    localStorage.setItem('voice_console_speak_enabled', '0');
    localStorage.setItem('voice_console_dictation_mode', 'live_local');
    localStorage.setItem('voice_console_auto_send', '1');
  });
  await p.goto(base + '/', { waitUntil: 'networkidle' });
  await wait(1200);
  await p.evaluate(() => pollFrivoscStatus());
  await wait(400);
  const peek = async () => (await (await fetch(base + '/_test/peek')).json());

  console.log('--- dots through the reply ---');
  await p.fill('#messageInput', 'how are you');
  await wait(500);
  await p.press('#messageInput', 'Enter');
  await wait(1200);                                  // reply still being written
  let s = await peek();
  check('the box is empty but the dots stay up while the reply is made', s.typing === true && s.chatbox === 0, s);
  await wait(1800);                                  // reply arrived, chatbox queued
  s = await peek();
  check('the reply goes to the chatbox', s.chatbox === 1, s);
  check('and the dots come down with it', s.typing === false, s);

  await p.evaluate(() => fetch('/_test/fail-next'));
  await p.fill('#messageInput', 'this one fails');
  await wait(300);
  await p.press('#messageInput', 'Enter');
  await wait(1000);
  check('dots up while it tries', (await peek()).typing === true);
  await wait(2000);
  check('a failed reply takes the dots down at once', (await peek()).typing === false);

  console.log('--- auto-send is for speech ---');
  const sent = async () => (await peek()).chatbox;
  await p.evaluate(() => { window.__level = 0; currentRms = () => window.__level; });
  await p.click('#dictateBtn'); await wait(300);

  // Hands-free: still sends by itself.
  let before = await sent();
  await p.evaluate(() => { window.__level = 0.2; }); await wait(1200);
  await p.evaluate(() => { window.__level = 0; });
  await wait(1500 + 2000 + 1500);                    // quiet, send, reply
  check('dictating hands-free still sends by itself', (await sent()) === before + 1, [before, await sent()]);

  // Dictate, then start fixing it by hand: no send.
  before = await sent();
  await p.evaluate(() => { window.__level = 0.2; }); await wait(1200);
  await p.evaluate(() => { window.__level = 0; });
  await wait(1000);                                  // text in, send pending
  await p.type('#messageInput', ' — wait');
  await wait(4000);
  check('typing in a dictated message cancels its auto-send', (await sent()) === before, [before, await sent()]);
  check('the Auto switch shows it is paused', await p.evaluate(() => document.getElementById('autoSendToggle').closest('.switch').classList.contains('is-paused')));
  check('and says so', /paused/i.test(await p.textContent('#status')), await p.textContent('#status'));

  // Speaking more into a message you typed in does not re-arm it.
  await p.evaluate(() => { window.__level = 0.2; }); await wait(1200);
  await p.evaluate(() => { window.__level = 0; });
  await wait(3500);
  check('speaking more into it does not send it either', (await sent()) === before, [before, await sent()]);

  await p.press('#messageInput', 'Enter');
  await wait(3000);
  check('Enter sends it', (await sent()) === before + 1, [before, await sent()]);
  check('and the switch is no longer paused', await p.evaluate(() => !document.getElementById('autoSendToggle').closest('.switch').classList.contains('is-paused')));

  // The next one is back to hands-free.
  before = await sent();
  await p.evaluate(() => { window.__level = 0.2; }); await wait(1200);
  await p.evaluate(() => { window.__level = 0; });
  await wait(5000);
  check('the next dictated message auto-sends again', (await sent()) === before + 1, [before, await sent()]);

  // Typing without dictation never auto-sends (as before).
  await p.click('#dictateBtn'); await wait(300);
  before = await sent();
  await p.fill('#messageInput', ''); await p.type('#messageInput', 'typed only');
  await wait(4000);
  check('typed text alone never auto-sends', (await sent()) === before, [before, await sent()]);
  await p.fill('#messageInput', '');
  await p.type('#messageInput', 'x'); await p.press('#messageInput', 'Backspace');
  await wait(200);
  check('emptying the box by hand clears the pause', await p.evaluate(() => !document.getElementById('autoSendToggle').closest('.switch').classList.contains('is-paused')));

  clearInterval(keep);
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


def main():
    work = tempfile.mkdtemp(prefix="frivo-reply-run-")
    server_py = os.path.join(work, "server.py")
    with open(server_py, "w") as handle:
        handle.write("APP=%r\n" % APP + SERVER)
    browser_js = os.path.join(work, "browser.cjs")
    with open(browser_js, "w") as handle:
        handle.write(BROWSER)
    server = subprocess.Popen([sys.executable, server_py], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_for_port(PORT):
            print("server did not start")
            return 1
        env = dict(os.environ)
        env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        code = subprocess.run(["node", browser_js], env=env).returncode
        if code == 0:
            print("\nAll reply-flow checks passed.")
        return code
    finally:
        server.terminate()


if __name__ == "__main__":
    sys.exit(main())
