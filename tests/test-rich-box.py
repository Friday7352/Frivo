#!/usr/bin/env python3
"""NEW (1.5.0): the message box with tag chips.

Drives the real page in a real browser:

  * a [tag] is a chip; the plain box (what the rest of Frivo reads) gets
    "[tag]" text; one Backspace removes a whole chip; a tag typed in full
    becomes a chip
  * instant tags: "lol " becomes [laughs] as you type; Backspace straight
    after puts "lol" back
  * a chip's menu swaps or removes it
  * ghost tags: the AI's ideas show in the text; Tab takes the next one
  * dragging a chip moves it to another word, with the magnifier showing
    while you drag, and nothing left floating after
  * Enter sends; Shift+Enter is a new line; pasted text comes in plain

Usage:  python3 tests/test-rich-box.py     (run from the repo root)
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
PORT = 5099

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile
ws = tempfile.mkdtemp(prefix="frivo-rich-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)
mod.app.run(host="127.0.0.1", port=5099, debug=False, use_reloader=False, threaded=True)
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
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.addInitScript(() => {
    localStorage.setItem('frivo_auto_tags', 'off');
    localStorage.setItem('frivo_tag_ideas', 'off');
  });
  await p.goto('http://127.0.0.1:5099/', { waitUntil: 'networkidle' });
  await wait(800);
  await p.evaluate(() => {
    // An ElevenLabs voice and a Clean up profile, without asking ElevenLabs.
    elevenVoiceNow = () => true;
    activeVoiceStyle = () => ({ style: 'echo', shaping: false });
    tagWordsState = [{ word: 'lol', tag: '' }, { word: 'haha', tag: '' }, { word: 'ugh', tag: '' }];
    window.__sent = [];
    send = () => { window.__sent.push(messageInput.value); messageInput.value = ''; };
  });
  const val = () => p.evaluate(() => messageInput.value);
  const chips = () => p.locator('#messageRich .rich-chip:not(.is-ghost)').allTextContents();
  const reset = async (v = '') => { await p.evaluate(v => { messageInput.value = v; }, v); await p.click('#messageRich'); };

  console.log('--- chips ---');
  await reset('hey [sighs] there');
  check('a tag is a chip', JSON.stringify(await chips()) === '["sighs"]', await chips());
  check('and text in the plain box', (await val()) === 'hey [sighs] there');
  await p.evaluate(() => richSetCaret('hey [sighs]'.length));
  await p.keyboard.press('Backspace');
  check('one Backspace removes the whole chip', !(await val()).includes('[') && (await chips()).length === 0, await val());
  await reset('');
  await p.keyboard.type('wait [whispers] what', { delay: 10 });
  check('a tag typed in full becomes a chip', JSON.stringify(await chips()) === '["whispers"]' && (await val()) === 'wait [whispers] what', [await chips(), await val()]);

  console.log('--- instant tags ---');
  await reset('');
  await p.keyboard.type('so funny lol ', { delay: 10 });
  check('"lol " becomes [laughs]', (await val()) === 'so funny [laughs] ', await val());
  await p.keyboard.press('Backspace');
  check('Backspace straight after puts the word back', (await val()) === 'so funny lol ', await val());
  await p.keyboard.type('ok', { delay: 10 });
  check('... and it stays a word', (await val()) === 'so funny lol ok', await val());
  await p.evaluate(() => { activeVoiceStyle = () => ({ style: 'reply', shaping: false }); });
  await reset('');
  await p.keyboard.type('lol ', { delay: 10 });
  check('not for a Reply profile (you are talking to the AI)', (await val()) === 'lol ', await val());
  await p.evaluate(() => { activeVoiceStyle = () => ({ style: 'echo', shaping: false }); });

  console.log('--- the chip menu ---');
  await reset('hey [sighs] there');
  await p.locator('#messageRich .rich-chip').first().click();
  await wait(150);
  check('a click opens its menu', await p.isVisible('.rich-chip-menu'));
  await p.locator('.rich-chip-menu button.is-remove').click();
  await wait(100);
  check('Remove takes it out', (await val()) === 'hey there', await val());

  console.log('--- ghost tags ---');
  await p.evaluate(() => localStorage.setItem('frivo_tag_ideas', 'on'));
  await reset('I finally beat the level.');
  await p.evaluate(() => {
    const words = spokenWords(messageInput.value).map(w => w.word);
    tagIdeasState.paused = false;
    tagIdeasState.ideas = withWords([{ tag: 'gasps', at: 0 }], words);
    renderTagIdeas();
  });
  await wait(100);
  check('an idea shows in the text', JSON.stringify(await p.locator('#messageRich .rich-chip.is-ghost').allTextContents()) === '["gasps"]');
  check('... but not in the message', (await val()) === 'I finally beat the level.');
  await p.keyboard.press('Tab');
  await wait(100);
  check('Tab takes it', (await val()) === '[gasps] I finally beat the level.', await val());
  await p.evaluate(() => localStorage.setItem('frivo_tag_ideas', 'off'));

  console.log('--- dragging ---');
  await reset('[laughs] I finally beat the maze level after forty tries.');
  const chip = await p.locator('#messageRich .rich-chip').first().boundingBox();
  const target = await p.evaluate(() => {
    const off = messageInput.value.indexOf('forty');
    const pt = richPointAt(off); const r = document.createRange(); r.setStart(pt.node, pt.offset); r.collapse(true);
    const rc = r.getClientRects()[0]; return { x: rc.left + 3, y: rc.top + rc.height / 2 };
  });
  await p.mouse.move(chip.x + chip.width / 2, chip.y + chip.height / 2);
  await p.mouse.down();
  for (let i = 1; i <= 20; i++) {
    await p.mouse.move(chip.x + chip.width / 2 + (target.x - chip.x - chip.width / 2) * i / 20,
                       chip.y + chip.height / 2 + (target.y - chip.y - chip.height / 2) * i / 20);
    await wait(16);
  }
  await wait(300);
  check('the magnifier shows where it will go', await p.evaluate(() => !!document.querySelector('.rich-drop.is-on')));
  await p.mouse.up();
  await wait(500);
  check('dropped before that word', (await val()) === 'I finally beat the maze level after [laughs] forty tries.', await val());
  check('nothing left floating', (await p.locator('.rich-chip.is-floating, .rich-drop').count()) === 0);

  console.log('--- sending and lines ---');
  await reset('');
  await p.keyboard.type('line one', { delay: 5 });
  await p.keyboard.press('Shift+Enter');
  await p.keyboard.type('line two', { delay: 5 });
  check('Shift+Enter is a new line', (await val()) === 'line one\nline two', await val());
  await p.keyboard.press('Enter');
  await wait(100);
  check('Enter sends', JSON.stringify(await p.evaluate(() => window.__sent)) === JSON.stringify(['line one\nline two']), await p.evaluate(() => window.__sent));
  check('and the box is empty again', (await val()) === '' && await p.evaluate(() => rich.el.classList.contains('is-empty')));
  await reset('');
  await p.evaluate(() => {
    const dt = new DataTransfer(); dt.setData('text/html', '<b>bold</b> [sighs] text'); dt.setData('text/plain', 'bold [sighs] text');
    rich.el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  });
  await wait(100);
  check('pasted text comes in plain, its tags as chips', (await val()) === 'bold [sighs] text' && (await p.locator('#messageRich b').count()) === 0, await val());

  console.log('\nerrors: ' + (errors.length ? JSON.stringify(errors) : 'none'));
  check('no page errors', errors.length === 0, errors);
  await b.close();
  process.exit(fails.length ? 1 : 0);
})();
"""


def main():
    env = dict(os.environ, APPDATA=tempfile.mkdtemp(prefix="frivo-rich-home-"))
    server = subprocess.Popen([sys.executable, "-c", f"APP = {APP!r}\n" + SERVER], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        run = tempfile.mkdtemp(prefix="frivo-rich-run-")
        script = os.path.join(run, "browser.cjs")
        with open(script, "w") as f:
            f.write(BROWSER)
        node_path = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        result = subprocess.run(["node", script], env=dict(os.environ, NODE_PATH=node_path), timeout=240)
        if result.returncode:
            print("Rich-box checks failed.")
            sys.exit(1)
        print("All rich-box checks passed.")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
