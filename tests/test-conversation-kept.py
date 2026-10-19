#!/usr/bin/env python3
"""NEW (1.5.0): the conversation survives a refresh; the volume chip holds still.

In a real browser:

  * messages (yours and replies, with their times, word timings and the
    Save state) come back after a refresh, in order, without playing or
    animating, and a "now talking to" divider comes back too
  * a restored reply loads its audio only when clicked, then plays; one
    whose audio has been cleaned up says so
  * Clear forgets the conversation for good: a refresh after it is empty
  * dragging the volume slider doesn't move the volume chip (the chip row
    used to re-fit under the pointer as the number's width changed)

Usage:  python3 tests/test-conversation-kept.py     (run from the repo root)
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
PORT = 5091
failures = []

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, wave, struct, math
ws = tempfile.mkdtemp(prefix="frivo-kept-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-kept-home-")
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)
mod.CFG.update(openai_api_key="", elevenlabs_api_key="", response_style="echo")
os.makedirs(mod.AUDIO_DIR, exist_ok=True)
w = wave.open(os.path.join(mod.AUDIO_DIR, "d" * 32 + ".wav"), "wb")
w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(16000 * 3)))
w.close()
mod.app.run(host="127.0.0.1", port=5091, debug=False, use_reloader=False, threaded=True)
"""

BROWSER = r"""
const { chromium } = require('playwright');
const wait = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
function check(name, cond, got) {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : `   got=${JSON.stringify(got)}`));
  if (!cond) fails.push(name);
}
const base = 'http://127.0.0.1:5091';
(async () => {
  const b = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
  const p = await (await b.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto(base + '/', { waitUntil: 'networkidle' }); await wait(800);

  console.log('--- before the refresh ---');
  await p.evaluate(() => {
    addTurn('You', 'hello there');
    addTurn('Echo', 'Sure it did.', { audioUrl: '/audio/' + 'd'.repeat(32) + '.wav', wordCount: 3, spoke: true,
      wordTimes: [[0, 0.3], [0.4, 0.6], [0.7, 1.0]], at: Date.parse('2026-10-19T09:15:00'),
      saveData: { audio_url: '/audio/' + 'd'.repeat(32) + '.wav', text: 'Sure it did.', saved_done: true },
      onAudioStart: () => {} });
    addProfileDivider('Now talking to Butler');
    addTurn('Butler', 'An old one.', { audioUrl: '/audio/' + 'e'.repeat(32) + '.wav', wordCount: 3, spoke: true });
  });
  await wait(1500);
  await p.evaluate(() => document.querySelectorAll('.bubble.is-playing').forEach((b) => b._pause && b._pause()));

  console.log('--- after a refresh ---');
  await p.reload({ waitUntil: 'networkidle' }); await wait(800);
  const after = await p.evaluate(() => ({
    texts: [...document.querySelectorAll('.bubble-text')].map((e) => e.textContent),
    divider: !!document.querySelector('.turn-divider'),
    playing: !!document.querySelector('.bubble.is-playing'),
    loading: !!document.querySelector('.bubble.is-loading'),
    stamp: document.querySelectorAll('.bubble-stamp')[1].textContent,
    saved: [...document.querySelectorAll('.turn-save')].map((b) => b.textContent),
  }));
  check('the messages come back, in order', JSON.stringify(after.texts) === JSON.stringify(['hello there', 'Sure it did.', 'An old one.']), after.texts);
  check('the divider too', after.divider);
  check('nothing plays or loads by itself', !after.playing && !after.loading, after);
  check('each keeps its own time', /9:15/.test(after.stamp), after.stamp);
  check('a saved reply still says Saved', after.saved[0] === 'Saved', after.saved);

  await p.locator('.bubble.has-audio').first().click(); await wait(1200);
  const played = await p.evaluate(() => ({ playing: !!document.querySelector('.bubble.is-playing'), glow: !!document.querySelector('.spoken-word.is-spoken') }));
  check('clicking a restored reply plays it', played.playing, played);
  check('with its words glowing', played.glow, played);
  await p.evaluate(() => document.querySelectorAll('.bubble.is-playing').forEach((b) => b._pause && b._pause()));
  await p.locator('.bubble.has-audio').nth(1).click(); await wait(800);
  check('one whose audio was cleaned up says so', await p.evaluate(() => document.querySelectorAll('.bubble.is-audio-gone').length === 1));

  console.log('--- Clear ---');
  await p.click('#clearChatBtn'); await wait(400);
  await p.reload({ waitUntil: 'networkidle' }); await wait(600);
  check('Clear forgets it: empty after a refresh', await p.evaluate(() => document.querySelectorAll('.turn').length === 0));

  console.log('--- the volume chip ---');
  await p.click('#volumeChip'); await wait(400);
  const spots = new Set();
  const widths = new Set();
  for (const v of [90, 95, 100, 105, 150, 5, 100]) {
    await p.evaluate((v) => { const s = document.getElementById('masterVolumeSlider'); s.value = v; s.dispatchEvent(new Event('input', { bubbles: true })); }, v);
    await wait(80);
    const r = await p.evaluate(() => document.getElementById('volumeChip').getBoundingClientRect());
    spots.add(Math.round(r.left)); widths.add(Math.round(r.width));
  }
  check('it stays put while the slider moves', spots.size === 1, [...spots]);
  check('and keeps one width', widths.size === 1, [...widths]);

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
    work = tempfile.mkdtemp(prefix="frivo-kept-run-")
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
        print("Conversation checks failed.")
        sys.exit(1)
    print("All conversation checks passed.")
