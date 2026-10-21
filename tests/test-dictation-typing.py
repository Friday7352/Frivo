#!/usr/bin/env python3
"""NEW (1.5.0): typing while dictation is on never erases what you typed.

Dictation used to keep its own copy of the message box and write that copy
back over the box every time it heard a word, so anything typed while the
mic was on vanished on the next word. Now what you type becomes part of the
text dictation adds to.

Drives the real page in a real browser with Live (Evora) dictation, the
microphone level and the transcription under the test's control:

  * typed while you are quiet: kept, and the next thing you say goes after it
  * typed while a preview of your words is on screen: kept, and when the
    finished transcription arrives it replaces the preview instead of
    adding the same words a second time
  * a space you typed at the end isn't swallowed
  * typing pauses auto-send for that message (as before)

Usage:  python3 tests/test-dictation-typing.py     (run from the repo root)
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
PORT = 5097
failures = []

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, time, threading
ws = tempfile.mkdtemp(prefix="frivo-dtype-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)
mod.CFG["transcription_provider"] = "local_whisper"
mod.CFG["whisper_url"] = "http://192.168.1.9:9000"
mod.probe_provider = lambda name, timeout=2: (True, "Reachable.")
lock = threading.Lock()
# Each answer is "said<N>" where N is how much audio it heard, so a preview
# (part of the clip) and the final (all of it) are different text.
def slow(file_tuple, language=None):
    with lock:
        time.sleep(0.25)
        return "said%d" % len(file_tuple[1])
mod.local_whisper_transcribe = slow
mod.app.run(host="127.0.0.1", port=5097, debug=False, use_reloader=False, threaded=True)
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
    localStorage.setItem('voice_console_dictation_mode', 'live_local');
    localStorage.setItem('voice_console_auto_send', '1');
  });
  await p.goto('http://127.0.0.1:5097/', { waitUntil: 'networkidle' });
  await wait(1000);
  await p.evaluate(() => {
    window.__level = 0;
    window.__sent = [];
    currentRms = () => window.__level;
    send = () => { window.__sent.push(messageInput.value); messageInput.value = ''; resetLiveDictation(); setTypedByHand(false); };
  });
  const level = v => p.evaluate(v => { window.__level = v; }, v);
  const box = () => p.evaluate(() => messageInput.value);
  const said = t => (t.match(/said\d+/g) || []);

  await p.click('#dictateBtn');
  await wait(300);

  console.log('--- typed while quiet ---');
  await p.click('#messageRich');   // CHANGED (1.5.0): the box you type in
  await p.keyboard.type('hey you');
  await wait(200);
  await level(0.2); await wait(1500); await level(0);
  await wait(2000);
  let t = await box();
  check('what you typed is still there', t.startsWith('hey you'), t);
  check('and what you said came after it', /^hey you said\d+$/.test(t), t);
  check('nothing was auto-sent (you typed in it)', (await p.evaluate(() => window.__sent.length)) === 0);

  console.log('--- typed while a preview is showing ---');
  await p.evaluate(() => { messageInput.value = ''; messageInput.dispatchEvent(new Event('input')); });
  await level(0.2); await wait(1400);           // previews are showing now
  t = await box();
  check('(a preview is on screen)', said(t).length === 1, t);
  await p.click('#messageRich');   // CHANGED (1.5.0): the box you type in
  await p.keyboard.press('End');
  await p.keyboard.type(' lol');
  await wait(900);                               // still talking: more previews would have come
  t = await box();
  check('typing over a preview keeps your text', /lol$/.test(t), t);
  await level(0); await wait(2000);
  t = await box();
  check('your text survives the final transcription', t.includes('lol'), t);
  check('the finished words replace the preview — not added twice', said(t).length === 1, t);
  check('and the preview is gone (the final heard more audio)', t.startsWith('said') && t !== '', t);

  console.log('--- a space you typed ---');
  await p.evaluate(() => { messageInput.value = ''; messageInput.dispatchEvent(new Event('input')); });
  await p.click('#messageRich');   // CHANGED (1.5.0): the box you type in
  await p.keyboard.type('ok ');
  await level(0.2); await wait(1200); await level(0); await wait(2000);
  t = await box();
  check('no doubled space', /^ok said\d+$/.test(t), t);

  await p.click('#dictateBtn');
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


if __name__ == "__main__":
    work = tempfile.mkdtemp(prefix="frivo-dtype-run-")
    server_py = os.path.join(work, "server.py")
    with open(server_py, "w") as handle:
        handle.write("APP=%r\n" % APP + SERVER)
    browser_js = os.path.join(work, "browser.cjs")
    with open(browser_js, "w") as handle:
        handle.write(BROWSER)
    server = subprocess.Popen([sys.executable, server_py], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_for_port(PORT):
            failures.append("server started")
        else:
            env = dict(os.environ)
            env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
            if subprocess.run(["node", browser_js], env=env).returncode != 0:
                failures.append("browser")
    finally:
        server.terminate()
    print()
    if failures:
        print("Dictation-typing checks failed.")
        sys.exit(1)
    print("All dictation-typing checks passed.")
