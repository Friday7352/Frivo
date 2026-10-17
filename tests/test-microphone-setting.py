#!/usr/bin/env python3
"""NEW (1.5.0): the microphone setting shows, and keeps, the one you picked.

Until a page is allowed to use the mic, browsers hide every device's id and
name. The Settings list used to be built from that anyway, so it showed
"Microphone 1" instead of your choice (it looked reset), picking from it
could save a blank (it really reset), and it stayed that way until Reload
was clicked even after dictation had been allowed the mic.

In a real browser with fake microphones:

  * picked, then reloaded: the same microphone is shown
  * names hidden: your saved microphone is shown, and nothing is overwritten
  * the list fills in by itself once the mic is allowed, and when Settings
    is opened
  * a saved microphone that's gone is shown as not connected, and
    dictation uses the default one instead of failing

Usage:  python3 tests/test-microphone-setting.py     (run from the repo root)
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
PORT = 5098
failures = []

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile
ws = tempfile.mkdtemp(prefix="frivo-mic-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)
mod.app.run(host="127.0.0.1", port=5098, debug=False, use_reloader=False, threaded=True)
"""

BROWSER = r"""
const { chromium } = require('playwright');
const wait = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
function check(name, cond, got) {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : `   got=${JSON.stringify(got)}`));
  if (!cond) fails.push(name);
}
const base = 'http://127.0.0.1:5098/';
const state = p => p.evaluate(() => ({
  value: micSelect.value,
  text: micSelect.selectedOptions[0] ? micSelect.selectedOptions[0].textContent : '',
  options: [...micSelect.options].map(o => o.textContent),
  saved: localStorage.getItem('voice_console_mic_device_id'),
}));

(async () => {
  const b = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });

  console.log('--- allowed: pick one, reload ---');
  let ctx = await b.newContext({ permissions: ['microphone'] });
  let p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto(base, { waitUntil: 'networkidle' }); await wait(800);
  let s = await state(p);
  const real = await p.evaluate(async () => (await navigator.mediaDevices.enumerateDevices())
    .filter(d => d.kind === 'audioinput' && d.deviceId && d.deviceId !== 'default').map(d => d.deviceId));
  check('(the browser has more than one microphone)', real.length >= 1, real);
  const pick = real[real.length - 1];
  await p.evaluate(id => { micSelect.value = id; micSelect.dispatchEvent(new Event('change')); }, pick);
  await p.reload({ waitUntil: 'networkidle' }); await wait(800);
  s = await state(p);
  check('after a reload the picked microphone is shown', s.value === pick && s.saved === pick, s);
  await ctx.close();

  console.log('--- names hidden (mic not allowed yet) ---');
  ctx = await b.newContext();
  p = await ctx.newPage();
  p.on('pageerror', e => errors.push(String(e)));
  await p.addInitScript(() => {
    // How browsers answer before the mic is allowed: every id and name blank.
    window.__hidden = true;
    const real = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
    navigator.mediaDevices.enumerateDevices = async () => {
      const list = await real();
      return window.__hidden ? list.map(d => ({ kind: d.kind, deviceId: '', label: '', groupId: '' })) : list;
    };
    if (!localStorage.getItem('seeded')) {
      localStorage.setItem('seeded', '1');
      localStorage.setItem('voice_console_mic_device_id', 'my-usb-mic-id');
    }
  });
  await p.goto(base, { waitUntil: 'networkidle' }); await wait(800);
  s = await state(p);
  check('your saved microphone is shown, not "Microphone 1"', s.value === 'my-usb-mic-id' && s.text === 'Your saved microphone', s);
  check('and nothing was overwritten', s.saved === 'my-usb-mic-id', s);
  await p.evaluate(() => micSelect.dispatchEvent(new Event('change')));
  check('choosing from the hidden list can\'t save a blank', (await state(p)).saved === 'my-usb-mic-id');

  console.log('--- allowed later ---');
  await ctx.grantPermissions(['microphone']);
  await p.evaluate(() => { window.__hidden = false; });
  await p.evaluate(() => openMicrophone().then(st => st.getTracks().forEach(t => t.stop())));
  await wait(800);
  s = await state(p);
  check('the list fills in by itself once the mic is allowed', s.options.some(o => /fake/i.test(o)), s.options);
  check('a saved microphone that is gone says so', /not connected/i.test(s.text) && s.value === 'my-usb-mic-id', s);
  const status = await p.evaluate(async () => {
    const st = await openMicrophone(); st.getTracks().forEach(t => t.stop());
    return micFellBack;
  });
  check('and dictation uses the default one instead of failing', status === true);
  await p.evaluate(() => { micSelect.innerHTML = ''; setSettingsOpen(true); });
  await wait(500);
  check('opening Settings rebuilds the list', (await state(p)).options.length > 1);

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
    work = tempfile.mkdtemp(prefix="frivo-mic-run-")
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
        print("Microphone-setting checks failed.")
        sys.exit(1)
    print("All microphone-setting checks passed.")
