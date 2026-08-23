#!/usr/bin/env python3
"""Mute sync: VRChat's mute button driving Frivo's dictation.

The rules this exists to hold onto are all about *not* acting:

  * Before VRChat has said anything the mute state is unknown, which is not
    the same as unmuted. Starting dictation there would turn on a
    microphone for someone who is muted and does not know it.
  * Sync acts on changes, never on the level. That is the whole mechanism
    behind "the mic button still overrides it": stop dictation by hand
    while still unmuted and it stays stopped, because nothing changed.
  * A companion that stops reporting takes the mic state back to unknown —
    and unknown must not yank a running dictation out from under anyone.

None of that is checkable by reading the code, so this drives the real page
in a real browser with a fake microphone, against the real server, and
watches the record button.

Usage:  python3 tests/test-mute-sync.py     (run from the repo root)
Needs:  flask, node, playwright with chromium.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
PORT = 5099

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, time
ws = tempfile.mkdtemp(prefix="frivo-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)

mod.CFG["transcription_provider"] = "local_whisper"
mod.CFG["osc_enabled"] = True
mod.CFG["osc_mute_sync"] = False
mod.CFG["whisper_url"] = "http://192.168.1.9:9000"
mod.probe_provider = lambda name, timeout=2: (True, "Reachable.")

# A back door for the test only: set what FrivOSC would have reported.
from flask import request, jsonify
@mod.app.route("/_test/mute/<state>")
def _test_mute(state):
    with mod.FRIVOSC_LOCK:
        mod.FRIVOSC_STATE.update({
            "connected_at": time.time(), "last_seen": time.time(),
            "version": "1.0.0", "hostname": "VRPC",
            "muted": None if state == "unknown" else (state == "on"),
        })
    return jsonify({"ok": True, "muted": mod.FRIVOSC_STATE["muted"]})

mod.app.run(host="127.0.0.1", port=5099, debug=False, use_reloader=False)

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
  const b = await chromium.launch({ args: [
    '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
    '--autoplay-policy=no-user-gesture-required',
  ]});
  const ctx = await b.newContext({ permissions: ['microphone'] });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));

  await p.goto('http://127.0.0.1:5099/', { waitUntil: 'networkidle' });
  await p.waitForTimeout(1500);

  const mute = async state => { await p.evaluate(s => fetch('/_test/mute/' + s), state); };
  const dictating = () => p.evaluate(() => ({
    isDictating: window.__probe ? window.__probe() : null,
    recording: document.getElementById('dictateBtn').classList.contains('is-recording'),
  }));

  // The flag is module-scoped, so read it through the button's own class,
  // which is the thing the user actually sees.
  const recording = async () => (await dictating()).recording;

  const toggle = async on => {
    await p.evaluate(async want => {
      const box = document.getElementById('oscMuteSyncToggle');
      if (box.checked === want) return;
      box.checked = want;
      box.dispatchEvent(new Event('change', { bubbles: true }));
    }, on);
  };

  console.log('--- the switch saves itself, with no Save button in reach ---');
  // It lives in the sidebar status panel. Save belongs to the Settings
  // sheet, so without an endpoint of its own it flipped, was never written
  // down, and the next poll read the old value back and flipped it off.
  await toggle(true); await wait(800);
  const persisted = await p.evaluate(async () =>
    (await (await fetch('/api/frivosc/status')).json()).mute_sync);
  check('turning it on reaches the server', persisted === true, persisted);
  await wait(2500);   // two polls, which is what used to undo it
  const stillOn = await p.evaluate(() => document.getElementById('oscMuteSyncToggle').checked);
  check('and it is still on two polls later', stillOn === true, stillOn);

  console.log('\n--- before VRChat says anything ---');
  await mute('unknown'); await wait(1600);
  check('unknown mute state does not start dictation', !(await recording()));

  console.log('\n--- unmute in VRChat ---');
  await mute('off'); await wait(2000);
  check('unmuting starts dictation', await recording());

  console.log('\n--- mute in VRChat ---');
  await mute('on'); await wait(2000);
  check('muting stops dictation', !(await recording()));

  console.log('\n--- a repeat of the same state ---');
  await mute('on'); await wait(1600);
  check('staying muted changes nothing', !(await recording()));

  console.log('\n--- manual override while unmuted ---');
  await mute('off'); await wait(2000);
  check('unmuting starts it again', await recording());
  await p.click('#dictateBtn');           // stop it by hand
  await wait(2500);                        // two polls
  check('stopping by hand stays stopped while still unmuted', !(await recording()));

  console.log('\n--- and the next real change still wins ---');
  await mute('on'); await wait(1600);
  await mute('off'); await wait(2000);
  check('unmuting again restarts it', await recording());

  console.log('\n--- switching it on while already unmuted ---');
  // The case that was reported: mic showing Live, switch on, nothing
  // happening. Turning it on used to record the current state as "already
  // handled", so it waited for a mute/unmute cycle that never came.
  await toggle(false); await wait(600);
  await mute('on'); await wait(1600);          // muting also stops anything running
  if (await recording()) await p.click('#dictateBtn');
  await wait(600);
  await mute('off'); await wait(2000);
  check('with the switch off, unmuting does nothing', !(await recording()));
  await toggle(true); await wait(2500);
  check('switching it on while unmuted starts dictation', await recording());

  console.log('\n--- companion disappears ---');
  await p.evaluate(() => fetch('/_test/mute/unknown'));
  await wait(2000);
  check('losing the mic state does not stop what is running', await recording());

  console.log('\nerrors: ' + (errors.length ? JSON.stringify(errors) : 'none'));
  await b.close();
  if (fails.length) { console.log(`\n${fails.length} failed: ${fails.join(', ')}`); process.exit(1); }
  console.log('\nAll mute-sync assertions passed.');
})();

"""


def port_is_open(port):
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main():
    if shutil.which("node") is None:
        print("SKIP: node is not installed; the browser half cannot run.")
        return 0
    if port_is_open(PORT):
        print("SKIP: port %d is already in use." % PORT)
        return 0

    workspace = tempfile.mkdtemp(prefix="frivo-mutesync-")
    server_path = os.path.join(workspace, "server.py")
    browser_path = os.path.join(workspace, "browser.js")
    with open(server_path, "w", encoding="utf-8") as handle:
        handle.write("APP = %r\n" % APP + SERVER)
    with open(browser_path, "w", encoding="utf-8") as handle:
        handle.write(BROWSER)

    server = subprocess.Popen([sys.executable, server_path],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if port_is_open(PORT):
                break
            if server.poll() is not None:
                print("The test server exited before it was ready.")
                return 1
            time.sleep(0.5)
        else:
            print("The test server never came up.")
            return 1

        return subprocess.call(["node", browser_path], cwd=ROOT)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
