#!/usr/bin/env python3
"""Clicking a message in the listening panel.

A plain click loads it into the reply box; Ctrl (Cmd on a Mac) adds it to
whatever is already there, so several things people said can be gathered
into one reply.

The interesting cases are all about not destroying text:

  * appending into an empty box must not leave a leading space
  * a trailing space someone typed is theirs — respected, not doubled
  * text already typed must survive an append
  * the caret has to end up at the end, or typing continues in the middle
    of the sentence you just built
  * a message still being transcribed shows a placeholder, and clicking it
    must copy nothing rather than an ellipsis
  * the speaker name renames, so clicking it must not also copy

None of that can be checked by reading the code, so this drives the real
page in a real browser against the real server.

Usage:  python3 tests/test-listen-click.py     (run from the repo root)
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
mod.CFG["osc_mute_sync"] = True
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
  const b = await chromium.launch();
  const p = await b.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:5099/', { waitUntil: 'networkidle' });
  await p.waitForTimeout(1200);

  // Build three entries through the app's own code path.
  await p.evaluate(() => {
    window.__entries = ['How was your day', 'did you eat yet', 'we should go'].map(t => {
      const e = addListenEntry();
      e.text.textContent = t;
      return e.entry.id;
    });
  });
  await p.waitForTimeout(200);

  const box = () => p.inputValue('#messageInput');
  const ids = await p.evaluate(() => window.__entries);

  await p.click('#' + ids[0]);
  check('a plain click loads the message', (await box()) === 'How was your day', await box());

  await p.click('#' + ids[1]);
  check('another plain click replaces it', (await box()) === 'did you eat yet', await box());

  await p.click('#' + ids[0], { modifiers: ['Control'] });
  check('ctrl-click appends instead',
        (await box()) === 'did you eat yet How was your day', await box());

  await p.click('#' + ids[2], { modifiers: ['Control'] });
  check('and keeps appending',
        (await box()) === 'did you eat yet How was your day we should go', await box());

  // Into an empty box, ctrl-click must not leave a leading space.
  await p.fill('#messageInput', '');
  await p.click('#' + ids[0], { modifiers: ['Control'] });
  check('ctrl-click into an empty box adds no leading space',
        (await box()) === 'How was your day', await box());

  // A trailing space the person typed is theirs; do not double it.
  await p.fill('#messageInput', 'so ');
  await p.click('#' + ids[1], { modifiers: ['Control'] });
  check('a trailing space is respected, not doubled',
        (await box()) === 'so did you eat yet', await box());

  // Typed text must survive an append.
  await p.fill('#messageInput', 'I think');
  await p.click('#' + ids[2], { modifiers: ['Control'] });
  check('typed text is not clobbered', (await box()) === 'I think we should go', await box());

  // The caret ends up at the end, so typing continues the sentence.
  const caret = await p.evaluate(() => {
    const el = document.getElementById('messageInput');
    return { start: el.selectionStart, end: el.selectionEnd, len: el.value.length };
  });
  check('the caret lands at the end', caret.start === caret.len && caret.end === caret.len, caret);

  // A placeholder entry must not paste an ellipsis.
  await p.fill('#messageInput', '');
  const pendingId = await p.evaluate(() => {
    const e = addListenEntry();
    e.text.textContent = '…';
    return e.entry.id;
  });
  await p.click('#' + pendingId);
  check('a message still being transcribed copies nothing', (await box()) === '', await box());

  // Clicking the speaker name renames; it must not also copy.
  await p.fill('#messageInput', '');
  await p.evaluate(id => document.querySelector('#' + id + ' .listen-speaker')?.click(),
                   ids[0]);
  await wait(200);
  check('clicking the speaker name does not copy', (await box()) === '', await box());

  const tip = await p.evaluate(id => document.getElementById(id).title, ids[0]);
  check('the tooltip mentions the modifier', /Ctrl|Cmd/.test(tip) && /add it/.test(tip), tip);

  console.log('\nerrors: ' + (errors.length ? JSON.stringify(errors) : 'none'));
  await b.close();
  if (fails.length) { console.log(`\n${fails.length} failed: ${fails.join(', ')}`); process.exit(1); }
  console.log('\nAll listening-panel click assertions passed.');
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

    workspace = tempfile.mkdtemp(prefix="frivo-listen-")
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
