#!/usr/bin/env python3
"""NEW (2.0): the new shell — rail, chips, drawer, settings nav, autosave.

The 2.0 layout replaced the three-column console. Everything a feature
owned still works through the same element ids; this checks the new chrome
around them, in a real browser:

  * the rail: Chat / Listening / Voices / Settings go where they say, and
    the active one is lit; Listening shows a dot on the rail while it runs
    with the drawer closed
  * the listening drawer opens and closes, and is closed on a fresh page
  * the chips above the message box: voice opens the voice sheet, length
    and volume open popovers (one at a time, Escape closes), the style chip
    names the style in use
  * the status pill opens the services + credits popover and says Ready
  * Settings: the list shows one section at a time; search finds rows
    across sections; a changed control saves itself and says Saved; the
    Save key button appears only once a key has been typed
  * the voice sheet groups by engine with a cost tag per voice and says
    whose voice it is
  * no page errors, in dark and light

Usage:  python3 tests/test-ui-shell.py     (run from the repo root)
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
PORT = 5093
failures = []

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, json
from types import SimpleNamespace
ws = tempfile.mkdtemp(prefix="frivo-shell-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)
mod.CFG.update(openai_api_key="", elevenlabs_api_key="", response_style="echo",
               voice_id="onecore:MSTTS_V110_enUS_ZiraM", voice_name="Zira", temperature=0.7)
# CHANGED (1.5.0): Kokoro is gone; the free voices are Windows' own.
mod.windows_voices_available = lambda: True
_names = ["Zira", "David", "Mark", "Hazel", "George", "Susan", "Katja", "Hedda", "Helena", "Laura", "Pablo", "Julie"]
mod.list_windows_voices = lambda force=False: [
    {"kind": "onecore", "id": f"MSTTS_V110_enUS_{n}M", "name": f"Microsoft {n}", "gender": "Female",
     "culture": "en-US", "language": "English (United States)"} for n in _names]
saves = []
real_settings = mod.app.view_functions["settings"]
from flask import request, jsonify
@mod.app.route("/_test/saves")
def _saves():
    return jsonify(saves=saves)
@mod.app.before_request
def _record():
    if request.path == "/api/settings" and request.method == "POST":
        saves.append(request.get_json(silent=True) or {})
mod.app.run(host="127.0.0.1", port=5093, debug=False, use_reloader=False, threaded=True)
"""

BROWSER = r"""
const { chromium } = require('playwright');
const wait = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
function check(name, cond, got) {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name + (cond ? '' : `   got=${JSON.stringify(got)}`));
  if (!cond) fails.push(name);
}
const base = 'http://127.0.0.1:5093';
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto(base + '/', { waitUntil: 'networkidle' });
  await wait(1200);
  const vis = sel => p.evaluate(s => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; }, sel);
  const cls = (sel, c) => p.evaluate(([s, c]) => document.querySelector(s).classList.contains(c), [sel, c]);
  const text = sel => p.evaluate(s => (document.querySelector(s) || {}).textContent || '', sel);

  console.log('--- the rail ---');
  check('no old sidebar or version banner', !(await vis('.sidebar')) && !(await vis('.version-warning')));
  check('Chat is lit', await cls('#railChat', 'is-active'));
  check('the listening drawer is closed on a fresh page', !(await vis('#listenPanel')));
  await p.click('#listenToggle'); await wait(400);
  check('Listening opens the drawer', await vis('#listenPanel') && await cls('#listenToggle', 'is-active'));
  check('the chat stays beside it', await vis('#messageInput'));
  await p.click('#listenCloseBtn'); await wait(300);
  check('and its close button closes it', !(await vis('#listenPanel')));
  await p.evaluate(() => setListenLamp(true));
  check('listening running with the drawer closed shows a dot on the rail', await cls('#listenToggle', 'is-live'));
  await p.evaluate(() => setListenLamp(false));
  await p.click('#settingsToggle'); await wait(400);
  check('Settings opens over the stage', await vis('#settingsPanel') && !(await vis('#messageInput')));
  check('and the rail lights Settings, not Chat', await cls('#settingsToggle', 'is-active') && !(await cls('#railChat', 'is-active')));
  await p.click('#railChat'); await wait(300);
  check('Chat brings the conversation back', await vis('#messageInput') && !(await vis('#settingsPanel')));
  await p.click('#railVoices'); await wait(500);
  check('Voices opens the voice sheet', await vis('#voicePop'));
  check('which says whose voice it is', /for Default/.test(await text('#voiceDialogFor')), await text('#voiceDialogFor'));
  // CHANGED (1.7.0): All / Favorites / Free tabs instead of a heading per engine.
  check('no section headings, tabs instead', await p.evaluate(() => !document.querySelector('#voiceList .voice-group') && document.querySelectorAll('#voicePop .vm-tab').length === 3));
  const freeDots = await p.evaluate(() => [...document.querySelectorAll('#voiceList .vm-row')].map(r => !!r.querySelector('.vm-free-dot')));
  check('every Windows voice shows the free dot', freeDots.length > 10 && freeDots.every(Boolean), freeDots.length);
  check('each row has a star and the menu', await p.evaluate(() => [...document.querySelectorAll('#voiceList .vm-row')].every(r => r.querySelector('.vm-star') && r.querySelector('.voice-menu-btn'))));
  const cur = await p.evaluate(() => { const r = document.querySelector('#voiceList .vm-row.is-current'); return r ? r.innerText : ''; });
  check('the voice in use opens its details', /Windows · Free/.test(cur), cur);
  await p.click('#voicePop .vm-tab[data-tab="fav"]'); await wait(200);
  check('Favorites with none starred says how', /Tap the star/.test(await text('#voiceList')));
  await p.click('#voicePop .vm-tab[data-tab="all"]'); await wait(200);
  await p.click('#voiceFilterBtn'); await wait(200);
  check('Filters opens language, gender and type', await vis('#voiceFilterPop'));
  await p.keyboard.press('Escape'); await wait(200);
  check('Escape closes the Filters menu first', !(await vis('#voiceFilterPop')) && await vis('#voicePop'));
  await p.keyboard.press('Escape'); await wait(500);   // CHANGED (1.5.0): the sheet slides out (300 ms)
  check('Escape closes it', !(await vis('#voicePop')));

  console.log('--- the chips and the status pill ---');
  check('the voice chip names the voice, without the bracketed part', (await text('#voiceTriggerName')).trim() === 'Zira', await text('#voiceTriggerName'));
  check('no style chip: the profile decides the style', !(await p.$('#styleChip')));   // CHANGED (1.7.0)
  await p.click('#lengthChip'); await wait(200);
  check('the length chip opens its popover', await vis('#lengthPop') && await vis('#lengthSlider'));
  await p.click('#volumeChip'); await wait(200);
  check('opening another closes the first', await vis('#volumePop') && !(await vis('#lengthPop')));
  await p.keyboard.press('Escape'); await wait(350);   // CHANGED (1.5.0): popovers now animate closed (170 ms)
  check('Escape closes popovers', !(await vis('#volumePop')));
  await p.click('#statusPillBtn'); await wait(200);
  check('the status pill opens services + credits', await vis('#statusPop') && await vis('#creditsToggle'));
  check('and reads Ready', (await text('#statusPillText')) === 'Ready');
  await p.click('body', { position: { x: 300, y: 400 } }); await wait(350);   // CHANGED (1.5.0): popovers now animate closed (170 ms)
  check('a click elsewhere closes it', !(await vis('#statusPop')));
  check('"Ready." is not shown as a status line', await cls('#status', 'is-quiet'));
  check('the profile avatar shows the initial', (await text('#profileAvatar')).trim() === 'D');

  console.log('--- the FrivOSC chip ---');
  check('hidden while FrivOSC is not connected', !(await vis('#oscChip')));
  await p.evaluate(() => { frivoscConnected = true; oscEnabled_setting = true; muteSyncEnabled = false; unmuteOnSendEnabled = true; frivoscMuted = true; syncOscSwitch(); });
  check('appears once FrivOSC connects', await vis('#oscChip'));
  check('and reads Muted with the mic muted', (await text('#oscChipText')) === 'Muted', await text('#oscChipText'));
  await p.click('#oscChip'); await wait(200);
  check('it opens the four switches', await vis('#oscPop') && await vis('#oscQuickMuteSync') + 0 >= 0);
  check('which show the current state', await p.evaluate(() => oscQuickEnabled.checked && !oscQuickMuteSync.checked && oscQuickUnmute.checked));
  const oscBefore = (await (await fetch(base + '/_test/saves')).json()).saves.length;
  await p.evaluate(() => { oscQuickMuteSync.checked = true; oscQuickMuteSync.dispatchEvent(new Event('change', { bubbles: true })); });
  await wait(600);
  check('flipping one drives the Settings switch', await p.evaluate(() => oscMuteSyncToggle.checked && muteSyncEnabled));
  await p.keyboard.press('Escape'); await wait(350);   // CHANGED (1.5.0): popovers now animate closed (170 ms)
  check('Escape closes it', !(await vis('#oscPop')));
  await p.evaluate(() => { frivoscConnected = false; syncOscSwitch(); });
  check('and it goes away when FrivOSC does', !(await vis('#oscChip')));

  console.log('--- settings: one page at a time ---');
  await p.click('#settingsToggle'); await wait(400);
  const shown = () => p.evaluate(() => [...document.querySelectorAll('#settingsRoot .settings-section.is-shown')].map(s => s.dataset.settingsSection));
  check('opens on Replies alone', JSON.stringify(await shown()) === '["replies"]', await shown());
  await p.click('[data-settings-section="dictation"]'); await wait(200);
  check('Dictation shows only Dictation', JSON.stringify(await shown()) === '["dictation"]' && await vis('#micSelect + .pretty-select-trigger'), await shown());
  await p.fill('#settingsSearch', 'temperature'); await wait(200);
  check('search finds the row in another section', (await shown()).includes('replies') && await vis('#temperatureSlider'), await shown());
  const hiddenRows = await p.evaluate(() => [...document.querySelectorAll('#settingsRoot .settings-section.is-shown .srow')].filter(r => !r.classList.contains('is-hidden')).length);
  check('and only that row', hiddenRows === 1, hiddenRows);
  await p.fill('#settingsSearch', 'zzzz'); await wait(200);
  check('nothing matching says so', await vis('#settingsNoMatch'));
  await p.click('[data-settings-section="replies"]'); await wait(200);
  check('picking a section clears the search', (await p.inputValue('#settingsSearch')) === '' && JSON.stringify(await shown()) === '["replies"]');
  check('no Save button for ordinary settings', !(await vis('#saveSettings')));

  console.log('--- settings save themselves ---');
  const before = (await (await fetch(base + '/_test/saves')).json()).saves.length;
  await p.evaluate(() => { const t = document.getElementById('temperatureSlider'); t.value = 120; t.dispatchEvent(new Event('input', { bubbles: true })); t.dispatchEvent(new Event('change', { bubbles: true })); });
  await wait(1200);
  const saves = (await (await fetch(base + '/_test/saves')).json()).saves;
  const last = saves[saves.length - 1] || {};
  check('changing a slider posts the settings', saves.length > before && Math.abs(last.temperature - 1.2) < 1e-6, last.temperature);
  check('and says Saved', await cls('#settingsSaved', 'is-on') && /Saved/.test(await text('#settingsSaved')));
  await p.click('[data-settings-section="accounts"]'); await wait(200);
  await p.click('[data-settings-page="openai"]'); await wait(300);
  check('a key page has no Save button until a key is typed', !(await vis('#saveSettings')));
  await p.type('#openaiKey', 'sk-test'); await wait(100);
  check('typing a key shows Save key', await vis('#saveSettings'));
  const before2 = (await (await fetch(base + '/_test/saves')).json()).saves.length;
  await p.click('#saveSettings'); await wait(800);
  const saves2 = (await (await fetch(base + '/_test/saves')).json()).saves;
  check('Save key sends it', saves2.length > before2 && saves2[saves2.length - 1].openai_api_key === 'sk-test');
  check('and Settings stays open', await vis('#settingsPanel'));
  await p.click('#closeSettings'); await wait(300);
  check('Done returns to the chat', await vis('#messageInput'));

  console.log('--- light theme and errors ---');
  await p.evaluate(() => { themeToggle.checked = false; themeToggle.dispatchEvent(new Event('change', { bubbles: true })); });
  await wait(300);
  check('light theme applies', (await p.evaluate(() => document.documentElement.dataset.theme)) === 'light');
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
    work = tempfile.mkdtemp(prefix="frivo-shell-run-")
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
        print("Shell checks failed.")
        sys.exit(1)
    print("All shell checks passed.")
