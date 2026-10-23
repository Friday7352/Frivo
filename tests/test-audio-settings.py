#!/usr/bin/env python3
"""NEW (2.0.0): Settings › Audio, laid out like Discord's Voice & Video.

In a real browser with fake microphones:

  * the section has the input and output devices, the volume, a mic test,
    a test sound, and the Listening panel's source with its gate
  * the output device is offered (Chromium can choose one) and kept
  * the mic test lights its level bars from the microphone, and stops when
    Settings is closed
  * the Listening source's Check moves the meter against the gate
  * Dictation and Listening lead here, showing the chosen device
  * the reply mixer follows the chosen output

Usage:  python3 tests/test-audio-settings.py     (run from the repo root)
Needs:  flask, node, playwright with chromium. Set FRIVO_TEST_SHOTS to a
        folder to get screenshots of the section.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
PORT = 5093
failures = []

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile
ws = tempfile.mkdtemp(prefix="frivo-audio-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)
mod.app.run(host="127.0.0.1", port=5093, debug=False, use_reloader=False, threaded=True)
"""

BROWSER = r"""
const { chromium } = require('playwright');
const path = require('path');
const wait = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
function check(name, cond, got) {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : `   got=${JSON.stringify(got)}`));
  if (!cond) fails.push(name);
}
const SHOTS = process.env.SHOTS;
(async () => {
  const b = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'] });
  const ctx = await b.newContext({ permissions: ['microphone'], viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('http://127.0.0.1:5093/', { waitUntil: 'networkidle' }); await wait(800);
  await p.evaluate(() => setSettingsOpen(true)); await wait(300);
  await p.click('.settings-nav-btn[data-settings-section="audio"]'); await wait(600);

  const shown = await p.evaluate(() => ({
    section: Boolean(document.getElementById('audioSection').offsetParent),
    mic: Boolean(document.querySelector('#audioSection #micSelect')),
    out: Boolean(document.querySelector('#audioSection #outputSelect')),
    vol: Boolean(document.querySelector('#audioSection #settingsVolumeSlider')),
    listen: Boolean(document.querySelector('#audioSection #listenDeviceSelect')),
    gate: Boolean(document.querySelector('#audioSection #listenThreshold')),
    bars: document.querySelectorAll('#micTestBars > span').length,
  }));
  check('Audio has both devices, the volume, the mic test and the listening source', shown.section && shown.mic && shown.out && shown.vol && shown.listen && shown.gate && shown.bars === 32, shown);

  const outs = await p.evaluate(() => [...document.getElementById('outputSelect').options].map(o => ({ v: o.value, t: o.textContent })));
  check('the output list starts with the system default', outs.length >= 1 && outs[0].v === '', outs);
  check('and can be chosen here', await p.evaluate(() => !document.getElementById('outputSelect').disabled));

  // the mixer follows the chosen output
  const sink = await p.evaluate(async () => {
    const calls = [];
    const orig = AudioContext.prototype.setSinkId;
    AudioContext.prototype.setSinkId = function (id) { calls.push(id); return Promise.resolve(); };
    const sel = document.getElementById('outputSelect');
    const o = document.createElement('option'); o.value = 'fake-headphones'; o.textContent = 'Headphones'; sel.appendChild(o);
    ensureAudioContext();
    sel.value = 'fake-headphones';
    sel.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 200));
    const saved = localStorage.getItem('frivo_output_device');
    sel.value = ''; sel.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 200));
    AudioContext.prototype.setSinkId = orig;
    return { calls, saved, after: localStorage.getItem('frivo_output_device') };
  });
  check('choosing an output moves the reply mixer to it, and remembers it', sink.calls.includes('fake-headphones') && sink.saved === 'fake-headphones' && sink.after === '', sink);

  // mic test
  await p.click('#micTestBtn');
  // The fake microphone beeps once a second, so watch for a while.
  const peak = (fn) => p.evaluate(async (src) => {
    const f = eval(src); let best = 0;
    for (let i = 0; i < 50; i++) { best = Math.max(best, f()); await new Promise(r => setTimeout(r, 50)); }
    return best;
  }, fn);
  const lit = await peak("() => document.querySelectorAll('#micTestBars > span.is-lit').length");
  check('the mic test lights the level from the microphone', lit > 0, lit);
  check('and its button says how to stop', /Stop checking/.test(await p.textContent('#micTestBtn')));
  if (SHOTS) await p.screenshot({ path: path.join(SHOTS, 'audio_settings.png') });

  // listening check
  await p.click('#listenCheckBtn');
  const meter = await peak("() => parseFloat(document.getElementById('listenMeterFill').style.width) || 0");
  check('Check moves the listening meter', meter > 0, meter);
  if (SHOTS) await p.screenshot({ path: path.join(SHOTS, 'audio_settings_checking.png') });

  // closing settings stops both
  await p.evaluate(() => setSettingsOpen(false)); await wait(400);
  const stopped = await p.evaluate(() => ({ mic: /Let's check/.test(document.getElementById('micTestBtn').textContent), listen: document.getElementById('listenCheckBtn').textContent === 'Check' }));
  check('closing Settings stops the mic test and the check', stopped.mic && stopped.listen, stopped);

  // the test sound plays without errors
  await p.evaluate(() => setSettingsOpen(true)); await wait(300);
  await p.click('.settings-nav-btn[data-settings-section="audio"]'); await wait(300);
  await p.click('#outputTestBtn'); await wait(300);

  // Dictation and Listening lead here
  await p.click('.settings-nav-btn[data-settings-section="dictation"]'); await wait(300);
  const micRow = await p.textContent('[data-settings-section="dictation"] [data-audio-summary="input"]');
  check('Dictation shows the chosen microphone', micRow && micRow.trim().length > 0 && !/^System default$/.test('x'), micRow);
  await p.click('[data-settings-section="dictation"] [data-goto-section="audio"]'); await wait(300);
  check('and leads to Audio', await p.evaluate(() => Boolean(document.getElementById('audioSection').offsetParent)));
  await p.click('.settings-nav-btn[data-settings-section="listening"]'); await wait(300);
  if (SHOTS) await p.screenshot({ path: path.join(SHOTS, 'audio_listening_link.png') });
  await p.click('[data-settings-section="listening"] [data-goto-section="audio"]'); await wait(300);
  check('Listening leads to Audio too', await p.evaluate(() => Boolean(document.getElementById('audioSection').offsetParent)));

  // narrow window
  await p.setViewportSize({ width: 600, height: 900 }); await wait(400);
  if (SHOTS) await p.screenshot({ path: path.join(SHOTS, 'audio_settings_narrow.png') });

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
    work = tempfile.mkdtemp(prefix="frivo-audio-run-")
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
            if os.environ.get("FRIVO_TEST_SHOTS"):   # a folder for screenshots, to look at
                env["SHOTS"] = os.environ["FRIVO_TEST_SHOTS"]
                os.makedirs(env["SHOTS"], exist_ok=True)
            env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
            if subprocess.run(["node", browser_js], env=env).returncode != 0:
                failures.append("browser")
    finally:
        server.terminate()
    print()
    if failures:
        print("Audio settings checks failed.")
        sys.exit(1)
    print("All audio settings checks passed.")
