#!/usr/bin/env python3
"""NEW (updates): the update dialog, in a real browser, against the real server.

GitHub is replaced by tests/fixtures/github-releases.json and the updater
task by a stand-in that writes status.json the way Update-Frivo.ps1 does —
including the part where setup stops Frivo: the server answers nothing for
a few seconds, then comes back as the new version. Checked:

  * the chip appears for a newer release, and opens the dialog
  * the notes are tidied (no ##, **, backticks; dashes become bullets)
  * Update now follows the task through download progress, the restart and
    back, then reloads into the new version
  * a failure says the task's reason and offers Try again
  * Skip this version hides the chip
  * Settings > About shows the version, and Earlier versions lists only
    what may be gone back to, opening the same dialog worded for going back
  * the automatic-check switch survives a reload

Usage:  python3 tests/test-update-ui.py     (run from the repo root)
Needs:  flask, node, playwright with chromium.
Writes: tests/screenshots/update-*.png, for looking at.
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
PORT = 5098
SHOTS = os.path.join(ROOT, "tests", "screenshots")

SERVER = r"""
import importlib.util, json, os, shutil, sys, tempfile, threading, time
ws = tempfile.mkdtemp(prefix="frivo-update-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)

from flask import jsonify, request
SAMPLE = json.load(open(FIXTURE, encoding="utf-8"))
folder = tempfile.mkdtemp(prefix="frivo-pd-")
state = {"down": False, "fail": False}

mod.APP_VERSION = "1.4.0"
mod.update_policy_path = lambda: POLICY
mod.fetch_releases = lambda policy: mod.parse_release_list(SAMPLE, policy)
mod.update_support = lambda refresh=False: {"ok": True, "mode": "task", "reason": ""}
mod.update_folder = lambda: folder
mod._spawn_update_watcher = lambda request_id: None

def status(**fields):
    tmp = os.path.join(folder, ".s.tmp")
    json.dump(fields, open(tmp, "w"))
    os.replace(tmp, os.path.join(folder, "status.json"))

def task():
    req = json.load(open(os.path.join(folder, "request.json")))
    rid, ver = req["id"], req["version"]
    kind = "update" if mod.parse_version(ver) > mod.parse_version(mod.APP_VERSION) else "rollback"
    base = dict(id=rid, version=ver, kind=kind, restart=False, received=0, total=0, message="")
    time.sleep(0.6); status(**dict(base, state="checking"))
    time.sleep(0.6)
    if state["fail"]:
        state["fail"] = False
        status(**dict(base, state="failed", message="The download failed: The operation has timed out."))
        return
    total = 2275000
    for got in (0, 600000, 1300000, 2275000):
        status(**dict(base, state="downloading", received=got, total=total)); time.sleep(0.45)
    status(**dict(base, state="verifying")); time.sleep(0.6)
    status(**dict(base, state="installing", restart=True)); time.sleep(0.8)
    state["down"] = True            # setup has stopped Frivo
    time.sleep(3.0)
    mod.APP_VERSION = ver           # ...and it comes back as the new one
    with mod.UPDATE_LOCK:
        mod.UPDATE_STATE["pending"] = None   # a fresh process remembers nothing
    mod.check_for_updates()
    status(**dict(base, state="done", restart=True, message="Frivo updated to " + ver))
    state["down"] = False

mod._start_update_task = lambda mode: threading.Thread(target=task, daemon=True).start()

@mod.app.before_request
def _down():
    if state["down"] and not request.path.startswith("/_test"):
        return "restarting", 503

@mod.app.route("/_test/fail-next")
def _fail_next():
    state["fail"] = True
    return jsonify(ok=True)

@mod.app.route("/_test/version/<v>")
def _version(v):
    mod.APP_VERSION = v
    with mod.UPDATE_LOCK:
        mod.UPDATE_STATE["pending"] = None
    mod.CFG["update_skipped"] = ""
    mod.check_for_updates()
    return jsonify(ok=True)

mod.check_for_updates()
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
const SHOTS = process.argv[2];

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1360, height: 860 } });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  const base = 'http://127.0.0.1:5098';
  // Not offsetParent: it is null for anything position:fixed, which the
  // dialog's overlay is.
  const visible = sel => p.evaluate(s => {
    let el = document.querySelector(s);
    if (!el) return false;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      if (n.classList.contains('is-hidden') || getComputedStyle(n).display === 'none') return false;
    }
    return true;
  }, sel);
  const text = sel => p.evaluate(s => (document.querySelector(s) || {}).textContent || '', sel);

  await p.goto(base + '/', { waitUntil: 'networkidle' });
  await wait(800);

  console.log('--- the chip ---');
  check('a newer release puts a chip in the top bar', await visible('#updateChip'));
  check('naming the version', (await text('#updateChipText')).includes('1.5.0'), await text('#updateChipText'));
  await p.screenshot({ path: SHOTS + '/update-chip.png', clip: { x: 0, y: 380, width: 360, height: 480 } });

  await p.click('#updateChip');
  await wait(300);
  check('the chip opens the dialog', await visible('#updateOverlay'));
  check('titled with the version', (await text('#updateTitle')) === 'Frivo 1.5.0 is available', await text('#updateTitle'));
  check('and says what is kept', (await text('#updateSub')).includes('You have 1.4.0'), await text('#updateSub'));
  const notes = await text('#updateNotes');
  check('notes lose their Markdown marks', !/[#*`]/.test(notes.replace(/•/g, '')), notes);
  check('list dashes become bullets', notes.includes('• Updates install from inside Frivo'), notes);
  check('no doubled blank lines', !notes.includes('\n\n\n'), notes);
  check('three buttons: skip, later, update', await visible('#updateSkipBtn') && await visible('#updateLaterBtn')
        && (await text('#updateInstallBtn')) === 'Update now');
  await p.screenshot({ path: SHOTS + '/update-dialog.png' });

  console.log('--- a failure ---');
  await p.evaluate(() => fetch('/_test/fail-next'));
  await p.click('#updateInstallBtn');
  await wait(3000);
  const failText = await text('#updateStatus');
  check('the task\'s reason is shown', failText.includes('timed out'), failText);
  check('with Try again', (await text('#updateInstallBtn')) === 'Try again');
  check('and the chip is back to announcing, not "updating"', (await text('#updateChipText')).startsWith('Update available'),
        await text('#updateChipText'));
  await p.screenshot({ path: SHOTS + '/update-failed.png' });

  console.log('--- an update, through the restart ---');
  await p.click('#updateInstallBtn');
  const seen = new Set();
  let sawProgress = false, sawRestart = false, chipWhileBusy = '';
  const startUrl = p.url();
  let reloaded = false;
  p.on('framenavigated', f => { if (f === p.mainFrame()) reloaded = true; });
  for (let i = 0; i < 60 && !reloaded; i++) {
    await wait(250);
    try {
      const s = await text('#updateStatus');
      seen.add(s.split('…')[0]);
      if (/Downloading… [\d.]+ of 2\.2 MB/.test(s)) {
        sawProgress = true;
        chipWhileBusy = await text('#updateChipText');
        if (!seen.has('__shot')) { seen.add('__shot'); await p.screenshot({ path: SHOTS + '/update-progress.png' }); }
      }
      if (s.startsWith('Frivo is restarting')) sawRestart = true;
    } catch (e) { /* navigating */ }
  }
  check('download progress is shown in MB', sawProgress, [...seen]);
  check('the restart is shown as a restart, not an error', sawRestart, [...seen]);
  check('the chip says it is updating meanwhile', chipWhileBusy === 'Updating to 1.5.0…', chipWhileBusy);
  check('the page reloads once the new version answers', reloaded, [...seen]);
  await p.waitForLoadState('networkidle');
  await wait(800);
  check('and the chip is gone: 1.5.0 is the newest', !(await visible('#updateChip')));

  console.log('--- Settings > About ---');
  await p.click('#settingsToggle'); await wait(300);
  // CHANGED (2.0): Settings shows one section at a time; About is under Updates.
  await p.click('[data-settings-section="about"]'); await wait(300);
  await wait(200);
  check('the version is the new one', (await text('#aboutVersionValue')) === '1.5.0', await text('#aboutVersionValue'));
  check('"Check for updates" reads up to date', (await text('#checkUpdatesValue')) === 'Up to date', await text('#checkUpdatesValue'));
  await p.screenshot({ path: SHOTS + '/update-about.png' });

  await p.click('#earlierVersionsRow'); await wait(600);
  const rows = await p.evaluate(() => [...document.querySelectorAll('#earlierList .srow-label')].map(e => e.textContent));
  check('earlier versions: older, newest first, none below 1.4.0', JSON.stringify(rows) === JSON.stringify(['Frivo 1.4.5', 'Frivo 1.4.0']), rows);
  await p.screenshot({ path: SHOTS + '/update-earlier.png' });
  await p.click('#earlierList .srow:last-child button'); await wait(300);
  check('Install opens the dialog worded for going back', (await text('#updateTitle')) === 'Go back to Frivo 1.4.0', await text('#updateTitle'));
  check('with no notes (old notes read as if they were coming)', !(await visible('#updateNotes')));
  check('and no Skip', !(await visible('#updateSkipBtn')));
  check('Cancel instead of Later', (await text('#updateLaterBtn')) === 'Cancel');
  check('install button names the version', (await text('#updateInstallBtn')) === 'Install 1.4.0');
  await p.screenshot({ path: SHOTS + '/update-rollback.png' });
  await p.keyboard.press('Escape'); await wait(200);
  check('Escape closes the dialog first', !(await visible('#updateOverlay')));
  check('and leaves Settings open', await visible('#settingsPanel'));

  await p.click('#earlierList .srow:first-child button'); await wait(300);
  check('a release with no fingerprint cannot be installed from here', (await text('#updateInstallBtn')) === 'Open releases page',
        await text('#updateInstallBtn'));
  check('and the dialog says why', (await text('#updateWhere')).includes('fingerprint'), await text('#updateWhere'));
  await p.click('#updateLaterBtn');

  console.log('--- the switch, and skipping ---');
  await p.evaluate(() => fetch('/_test/version/1.4.0'));
  await p.reload({ waitUntil: 'networkidle' }); await wait(600);
  await p.click('#settingsToggle'); await wait(200);
  await p.evaluate(() => { const t = document.getElementById('updateAutoToggle'); t.checked = false; t.dispatchEvent(new Event('change', { bubbles: true })); });
  await wait(500);
  await p.reload({ waitUntil: 'networkidle' }); await wait(600);
  check('turning the automatic check off survives a reload', await p.evaluate(() => document.getElementById('updateAutoToggle').checked === false));
  await p.evaluate(() => { const t = document.getElementById('updateAutoToggle'); t.checked = true; t.dispatchEvent(new Event('change', { bubbles: true })); });
  await wait(400);

  check('back on 1.4.0 the chip is back', await visible('#updateChip'));
  await p.click('#updateChip'); await wait(200);
  await p.click('#updateSkipBtn'); await wait(500);
  check('Skip this version hides the chip', !(await visible('#updateChip')));
  await p.reload({ waitUntil: 'networkidle' }); await wait(600);
  check('and it stays hidden after a reload', !(await visible('#updateChip')));

  console.log('--- light theme ---');
  await p.evaluate(() => fetch('/_test/version/1.4.0'));
  await p.evaluate(() => { localStorage.setItem('voice_console_theme', 'light'); });
  await p.reload({ waitUntil: 'networkidle' }); await wait(600);
  await p.click('#updateChip'); await wait(300);
  await p.screenshot({ path: SHOTS + '/update-dialog-light.png' });

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
    os.makedirs(SHOTS, exist_ok=True)
    prelude = "APP=%r\nFIXTURE=%r\nPOLICY=%r\n" % (
        APP, os.path.join(ROOT, "tests", "fixtures", "github-releases.json"),
        os.path.join(ROOT, "installer", "update-policy.json"))
    work = tempfile.mkdtemp(prefix="frivo-update-ui-run-")
    server_py = os.path.join(work, "server.py")
    with open(server_py, "w") as handle:
        handle.write(prelude + SERVER)
    browser_js = os.path.join(work, "browser.cjs")
    with open(browser_js, "w") as handle:
        handle.write(BROWSER)

    server = subprocess.Popen([sys.executable, server_py], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        if not wait_for_port(PORT):
            print("server did not start:", server.stderr.read().decode()[-2000:])
            return 1
        env = dict(os.environ)
        node_path = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        env["NODE_PATH"] = node_path
        result = subprocess.run(["node", browser_js, SHOTS], env=env)
        if result.returncode == 0:
            print("\nAll update-dialog assertions passed.")
        return result.returncode
    finally:
        server.terminate()


if __name__ == "__main__":
    sys.exit(main())
