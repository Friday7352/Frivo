#!/usr/bin/env python3
"""Live (Evora) dictation: how long from the end of a sentence to it being sent.

It used to take about ten seconds from finishing a sentence to it being
sent. Three costs were stacked one after another:

  1. every clip went through Evora's speaker analysis, which dictation
     never uses (the speaker is always you)
  2. the final transcription started only after 0.8s of silence and the
     recorder stopping, and queued behind any live preview still running
  3. auto-send then waited another 1.4s, counted from when the text came
     back rather than from when you stopped talking

This drives the real page in a real browser against the real server, with
the microphone level and Evora both under the test's control. Evora is
made deliberately slow (0.6s a clip) so a regression shows up as time.

  * the end of a sentence is sent about AUTO_SEND_QUIET_MS (1.5s) after
    you stop talking, not 2.8s or more
  * a pause shorter than that is not the end: one message, both halves
  * a brief pause throws away the early final, so no words are lost
  * Frivo asks Evora for words only (speaker=0), retries a busy Evora,
    and the listening panel's own speaker requests are left as they were

Usage:  python3 tests/test-dictation-speed.py     (run from the repo root)
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
PORT = 5096

failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


# ---------------------------------------------------------------- server side

def server_side():
    print("--- what Frivo asks Evora for ---")
    ws = tempfile.mkdtemp(prefix="frivo-dict-")
    shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
    spec = importlib.util.spec_from_file_location("frivo_dict", os.path.join(ws, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frivo_dict"] = mod
    spec.loader.exec_module(mod)

    class Reply:
        def __init__(self, code, payload):
            self.status_code = code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("HTTP %d" % self.status_code)

        def json(self):
            return self._payload

    sent = []
    queue = []

    def fake_post(url, files=None, data=None, timeout=None):
        sent.append({"url": url, "data": dict(data or {})})
        return queue.pop(0) if queue else Reply(200, {"text": " hello there "})

    mod.EVORA_HTTP.post = fake_post
    mod.EVORA_BUSY_WAIT = 0.01

    text = mod.local_whisper_transcribe(("d.webm", b"x", "audio/webm"), "en")
    check("dictation asks for words only (speaker=0)", sent[-1]["data"].get("speaker") == "0", sent[-1])
    check("and still passes the language", sent[-1]["data"].get("language") == "en", sent[-1])
    check("and returns the text", text == "hello there", text)

    sent.clear()
    queue.extend([Reply(429, {"busy": True}), Reply(429, {"busy": True}), Reply(200, {"text": "ok"})])
    text = mod.local_whisper_transcribe(("d.webm", b"x", "audio/webm"))
    check("a busy Evora is retried, not failed", text == "ok" and len(sent) == 3, (text, len(sent)))

    sent.clear()
    queue.extend([Reply(429, {"busy": True})] * (mod.EVORA_BUSY_RETRIES + 1))
    try:
        mod.local_whisper_transcribe(("d.webm", b"x", "audio/webm"))
        check("a busy Evora that stays busy is reported", False, "no error")
    except Exception:
        check("a busy Evora that stays busy is reported, after a bounded number of tries",
              len(sent) == mod.EVORA_BUSY_RETRIES + 1, len(sent))

    with open(os.path.join(APP, "app.py"), encoding="utf-8") as handle:
        source = handle.read()
    verbose = source[source.index("def local_whisper_transcribe_verbose"):]
    verbose = verbose[:verbose.index("\ndef ", 10)]
    check("the listening panel still asks for speakers", '"speaker": "1" if want_speaker' in verbose, verbose[:200])


# ---------------------------------------------------------------- browser

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, time, threading
ws = tempfile.mkdtemp(prefix="frivo-dict-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)

mod.CFG["transcription_provider"] = "local_whisper"
mod.CFG["whisper_url"] = "http://192.168.1.9:9000"
mod.probe_provider = lambda name, timeout=2: (True, "Reachable.")
count = {"n": 0}
lock = threading.Lock()

# A slow Evora, one clip at a time like the real one. Each answer says how
# much audio it was given, so the test can tell a full clip from a partial.
def slow(file_tuple, language=None):
    with lock:
        count["n"] += 1
        time.sleep(0.6)
        return "words(%d)" % len(file_tuple[1])
mod.local_whisper_transcribe = slow

from flask import jsonify
@mod.app.route("/_test/calls")
def _calls():
    return jsonify(n=count["n"])

mod.app.run(host="127.0.0.1", port=5096, debug=False, use_reloader=False, threaded=True)
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
  await p.goto('http://127.0.0.1:5096/', { waitUntil: 'networkidle' });
  await wait(1000);

  // The microphone level, and what "send" does, are the test's to decide.
  await p.evaluate(() => {
    window.__level = 0;
    window.__sent = [];
    currentRms = () => window.__level;
    send = () => { window.__sent.push({ at: Date.now(), text: messageInput.value }); messageInput.value = ''; liveCommitted = ''; };
  });
  const level = v => p.evaluate(v => { window.__level = v; if (v === 0) window.__quietAt = Date.now(); }, v);
  const sent = () => p.evaluate(() => window.__sent.map(s => ({ after: s.at - window.__quietAt, text: s.text })));
  const reset = () => p.evaluate(() => { window.__sent = []; });

  await p.click('#dictateBtn');
  await wait(300);

  console.log('--- the end of a sentence ---');
  await level(0.2); await wait(2000); await level(0);
  await wait(3500);
  let s = await sent();
  check('one message is sent', s.length === 1, s);
  check('about 1.5s after you stop talking (it used to be ~10s)', s.length && s[0].after >= 1300 && s[0].after <= 2100, s);
  check('and it carries the transcription', s.length && /^words\(\d+\)$/.test(s[0].text), s);

  console.log('--- a pause that is not the end ---');
  await reset();
  await level(0.2); await wait(1200); await level(0);
  await wait(1000);                        // past SILENCE_MS, short of the send
  await level(0.2); await wait(1200); await level(0);
  await wait(3500);
  s = await sent();
  check('one message, not two', s.length === 1, s);
  check('with both halves in it', s.length && (s[0].text.match(/words\(/g) || []).length === 2, s);

  console.log('--- a breath mid-sentence ---');
  await reset();
  await level(0.2); await wait(1200); await level(0);
  await wait(450);                         // the early final has started...
  await level(0.2); await wait(1200); await level(0);   // ...and is thrown away
  await wait(3500);
  s = await sent();
  check('one message', s.length === 1, s);
  const sizes = s.length ? (s[0].text.match(/\d+/g) || []).map(Number) : [];
  check('transcribed once, from the whole clip (no words lost to the early final)', sizes.length === 1, s);

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


def browser_side():
    print()
    print("--- in the browser ---")
    work = tempfile.mkdtemp(prefix="frivo-dict-run-")
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
        print("%d dictation check(s) failed." % len(failures))
        sys.exit(1)
    print("All dictation-speed checks passed.")
