#!/usr/bin/env python3
"""NEW (2.0.0): Frivo keeps a copy of each browser's preferences.

Favourite voices, the audio devices and the rest live in the browser, so
uninstalling the Frivo app (or clearing a browser) lost them even when
setup kept everything else. This checks:

  * /api/browser-prefs keeps one copy per kind of device and browser, only
    Frivo's own keys (never the session or the transcript), and hands a
    browser back its own kind's copy and nobody else's
  * a browser with no preferences of its own takes that copy and reloads,
    once; one that has its own keeps them
  * a saved audio device whose id changed (the browser's data was wiped) is
    found again by its name
  * the uninstaller and setup offer to put the API keys in their backup

Usage:  python3 tests/test-browser-prefs.py     (run from the repo root)
Needs:  Frivo's Python packages. Playwright for the browser part.
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-prefs-data-")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-prefs-home-")
spec = importlib.util.spec_from_file_location("frivo_prefs", os.path.join(ROOT, "app", "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_prefs"] = mod
spec.loader.exec_module(mod)
mod.start_update_checker = lambda: None
mod.warm_free_voices = lambda: None
client = mod.app.test_client()

APP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Electron/44.5.1 Safari/537.36 FrivoApp/2.0.0"
APP_NEWER = APP.replace("FrivoApp/2.0.0", "FrivoApp/2.0.1")
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"

print("The copy Frivo keeps")
r = client.post("/api/browser-prefs", headers={"User-Agent": APP}, json={"prefs": {
    "voice_console_voice_favorites": '["alba"]', "frivo_output_device": "dev-1",
    "voice_console_session": "secret-session", "frivo_transcript_v1": "[...]", "someone_elses_key": "x"}})
check("kept", r.status_code == 200 and r.get_json().get("kept"), r.get_json())
got = client.get("/api/browser-prefs", headers={"User-Agent": APP_NEWER}).get_json()
check("the app gets its copy back, after an update too", got["prefs"].get("voice_console_voice_favorites") == '["alba"]', got)
check("without the session, the transcript or other sites' keys",
      set(got["prefs"]) == {"voice_console_voice_favorites", "frivo_output_device"}, got["prefs"])
check("a phone doesn't get the PC app's", client.get("/api/browser-prefs", headers={"User-Agent": IPHONE}).get_json()["prefs"] == {})
check("it's in Frivo's data folder (kept by setup and its backups)", os.path.isfile(mod.BROWSER_PREFS_PATH))
r = client.post("/api/browser-prefs", headers={"User-Agent": APP}, json={"prefs": {"frivo_x": "y" * 300000, "frivo_y": "z" * 300000}})
check("too much is refused", r.status_code == 413, r.status_code)

print("Setup and the uninstaller")
inst = open(os.path.join(ROOT, "installer", "Install.ps1"), encoding="utf-8-sig").read()
unin = open(os.path.join(ROOT, "installer", "Uninstall.ps1"), encoding="utf-8-sig").read()
check("setup offers the API keys in its backup", "chkSetupBackupKeys" in inst and "-IncludeKeys:$script:wantBackupKeys" in inst)
check("so does the uninstaller", "chkBackupKeys" in unin and "-IncludeKeys:$BackupKeys" in unin)
check("and a silent uninstall can ask for them", "[switch] $BackupKeys" in unin)

print("In a browser")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    print("  SKIP  Playwright isn't installed")
if sync_playwright:
    import logging
    from werkzeug.serving import make_server
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server = make_server("127.0.0.1", 5194, mod.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    URL = "http://127.0.0.1:5194/"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # The app before it was uninstalled: favourites and an output device.
        first = browser.new_context(user_agent=APP)
        page = first.new_page()
        page.goto(URL)
        page.wait_for_selector("#dictateBtn", timeout=20000)
        page.evaluate("""() => {
            localStorage.setItem('voice_console_voice_favorites', JSON.stringify(['rachel','alba']));
            localStorage.setItem('frivo_output_device', 'old-device-id');
            localStorage.setItem('frivo_device_labels', JSON.stringify({frivo_output_device: 'Headphones (USB)'}));
            window.frivoPushPrefs();
        }""")
        time.sleep(1.0)
        first.close()
        kept = mod.load_browser_prefs().get("Windows PC|Frivo app", {}).get("prefs", {})
        check("the page keeps its copy with Frivo", kept.get("frivo_output_device") == "old-device-id", kept)

        # Reinstalled: a new, empty browser profile.
        second = browser.new_context(user_agent=APP)
        page = second.new_page()
        loads = []
        page.on("load", lambda: loads.append(1))
        page.goto(URL)
        page.wait_for_selector("#dictateBtn", timeout=20000)
        time.sleep(2.0)
        favs = page.evaluate("localStorage.getItem('voice_console_voice_favorites')")
        check("a fresh browser takes them back", favs == json.dumps(["rachel", "alba"]).replace(" ", ""), favs)
        check("and reloads once to use them", len(loads) == 2, len(loads))
        # The device's id is new after the wipe; its name is the same.
        page.evaluate("""() => healSavedDevices([
            {kind: 'audiooutput', deviceId: 'default', label: 'Default - Speakers'},
            {kind: 'audiooutput', deviceId: 'new-device-id', label: 'Headphones (USB)'}])""")
        check("a saved device whose id changed is found by its name",
              page.evaluate("localStorage.getItem('frivo_output_device')") == "new-device-id")
        page.evaluate("""() => { localStorage.setItem('voice_console_mic_device_id', 'mic-1');
            healSavedDevices([{kind: 'audioinput', deviceId: 'mic-1', label: 'Studio Mic'}]); }""")
        check("and a device's name is remembered when it's there",
              json.loads(page.evaluate("localStorage.getItem('frivo_device_labels')")).get("voice_console_mic_device_id") == "Studio Mic")
        second.close()

        # A browser that already has its own preferences keeps them.
        third = browser.new_context(user_agent=APP)
        page = third.new_page()
        page.add_init_script("""if (!sessionStorage.getItem('seeded')) {
            sessionStorage.setItem('seeded', '1');
            localStorage.setItem('voice_console_voice_favorites', '["mine"]'); }""")
        page.goto(URL)
        page.wait_for_selector("#dictateBtn", timeout=20000)
        time.sleep(1.5)
        check("one with its own preferences keeps them",
              page.evaluate("localStorage.getItem('voice_console_voice_favorites')") == '["mine"]')
        third.close()
        browser.close()
    server.shutdown()

print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("All browser preference checks passed.")
