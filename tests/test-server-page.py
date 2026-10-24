#!/usr/bin/env python3
"""NEW (2.0.0): the Server page (/server).

For a PC that runs Frivo for others. This checks:

  * who's using Frivo: what a user agent says (phone, PC, the Frivo app,
    which browser), what a device is doing from what it asks for, that
    static files, the Server page itself and its own polling don't count,
    and when a device stops being "connected now"
  * Recent activity: server.log's lines, newest first, with a level
  * /api/server/status: everything the page draws, and whether the viewer
    is on this PC
  * Restart and Stop: refused from another device; Stop ends Frivo when
    there's no launcher to ask; Restart says so instead
  * the launcher: Restart and Stop events, and opening the Server page
  * Settings: the link to the Server page, and /?settings=<section>
  * the page itself in a browser (if Playwright is installed): filled in,
    no script errors, and nothing wider than a phone

Usage:  python3 tests/test-server-page.py     (run from the repo root)
Needs:  Frivo's Python packages. Playwright for the browser part.
"""

import importlib.util
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


os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-server-data-")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-server-home-")
spec = importlib.util.spec_from_file_location("frivo_server_page", os.path.join(ROOT, "app", "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_server_page"] = mod
spec.loader.exec_module(mod)
mod.start_update_checker = lambda: None
mod.warm_free_voices = lambda: None
mod._look_up_client_name = lambda ip: mod._CLIENT_NAMES.__setitem__(ip, "")   # no network lookups here
client = mod.app.test_client()

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
EDGE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0"
APP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Electron/44.5.1 Safari/537.36 FrivoApp/2.0.0"
ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"

print("Who it is")
check("an iPhone in Safari", mod.describe_client(IPHONE) == ("iPhone", "Safari"), mod.describe_client(IPHONE))
check("Edge on Windows", mod.describe_client(EDGE) == ("Windows PC", "Edge"), mod.describe_client(EDGE))
check("the Frivo app, with its version", mod.describe_client(APP) == ("Windows PC", "Frivo app 2.0.0"), mod.describe_client(APP))
check("Chrome on Android", mod.describe_client(ANDROID) == ("Android", "Chrome"), mod.describe_client(ANDROID))
check("nothing to go on", mod.describe_client("") == ("Device", "Browser"))


def visit(path, ua, ip, method="GET", headers=None):
    h = {"User-Agent": ua}
    h.update(headers or {})
    fn = client.post if method == "POST" else client.get
    return fn(path, headers=h, environ_base={"REMOTE_ADDR": ip})


print("What it's doing")
mod.CLIENTS.clear()
visit("/static/icon.png", IPHONE, "192.168.1.71")
visit("/server", IPHONE, "192.168.1.71")
visit("/api/server/status", IPHONE, "192.168.1.71")
visit("/api/local-status", IPHONE, "192.168.1.71", headers={"X-Frivo-Server-Page": "1"})
check("static files, the Server page and its polling don't count", not mod.client_list(), mod.client_list())
visit("/api/local-status", IPHONE, "192.168.1.71")
visit("/api/transcribe", IPHONE, "192.168.1.71", method="POST")
visit("/api/local-status", EDGE, "192.168.1.80")
visit("/api/frivosc/status", APP, "127.0.0.1")
devices = {d["via"]: d for d in mod.client_list()}
check("three devices", len(devices) == 3, list(devices))
check("dictating, while it is", devices.get("Safari", {}).get("doing") == "Dictating", devices.get("Safari"))
check("a page that's just open is idle", devices.get("Edge", {}).get("doing") == "" and devices["Edge"]["online"], devices.get("Edge"))
check("this PC is said to be this PC", devices.get("Frivo app 2.0.0", {}).get("this_pc") is True, devices.get("Frivo app 2.0.0"))
check("a phone is named for what it is when the network has no name", devices.get("Safari", {}).get("name") == "iPhone", devices.get("Safari"))

later = time.time() + mod.CLIENT_BUSY_SECONDS + 1
check("dictating stops showing once it's stopped", {d["via"]: d for d in mod.client_list(later)}["Safari"]["doing"] == "")
later = time.time() + mod.CLIENT_ONLINE_SECONDS + 5
away = {d["via"]: d for d in mod.client_list(later)}
check("not connected after a minute and a half of nothing", away["Edge"]["online"] is False, away["Edge"])
check("still listed for a while", "Edge" in away)
check("gone after half an hour", not mod.client_list(time.time() + mod.CLIENT_SHOWN_SECONDS + 5))

print("Recent activity")
with open(mod.SERVER_LOG_PATH, "w", encoding="utf-8") as f:
    f.write("[2026-10-23 20:47:01] SERVER THREAD DIED: OSError()\n")
    f.write("Traceback (most recent call last):\n  File x\n")
    f.write("[2026-10-23 22:05:14] Ollama: downloaded llama3.1:8b\n")
    f.write("[2026-10-23 23:12:30] slow dictation clip: 6.8s for 120,000 bytes\n")
    f.write("[2026-10-23 23:20:00] Local Whisper unavailable (ConnectionError()) — falling back to OpenAI.\n")
log = mod.server_log_tail()
check("newest first", [l["time"] for l in log] == ["23:20:00", "23:12:30", "22:05:14", "20:47:01"], [l["time"] for l in log])
check("a traceback's own lines are left out", all("File x" not in l["text"] for l in log))
levels = {l["time"]: l["level"] for l in log}
check("a crash is an error", levels.get("20:47:01") == "error", levels)
check("slow is a warning", levels.get("23:12:30") == "warn", levels)
check("a service down is a warning", levels.get("23:20:00") == "warn", levels)
check("the rest is information", levels.get("22:05:14") == "info", levels)

print("Status")
st = visit("/api/server/status", EDGE, "127.0.0.1").get_json()
for key in ("name", "version", "uptime_seconds", "network_urls", "checks", "devices", "log", "this_pc"):
    check(f"says {key}", key in st, sorted(st))
check("opened on this PC", st.get("this_pc") is True)
check("opened from another device", visit("/api/server/status", IPHONE, "192.168.1.71").get_json().get("this_pc") is False)
ids = [c["id"] for c in st.get("checks", [])]
check("checks the network, HTTPS and updates", all(i in ids for i in ("network", "https", "update")), ids)
check("every check has a state the page knows", all(c["state"] in ("ok", "warn", "bad", "off") for c in st["checks"]), st["checks"])

print("Restart and Stop")
r = visit("/api/server/restart", IPHONE, "192.168.1.71", method="POST")
check("Restart is refused from another device", r.status_code == 403, r.status_code)
r = visit("/api/server/stop", IPHONE, "192.168.1.71", method="POST")
check("Stop is refused from another device", r.status_code == 403, r.status_code)
check("and nothing stopped", not mod.SERVER_STOP.is_set())
if os.name != "nt":
    r = visit("/api/server/restart", EDGE, "127.0.0.1", method="POST")
    check("no launcher: Restart says so", r.status_code == 409 and "launcher" in (r.get_json() or {}).get("error", ""), r.status_code)
    r = visit("/api/server/stop", EDGE, "127.0.0.1", method="POST")
    time.sleep(0.8)
    check("no launcher: Stop ends Frivo itself", r.status_code == 200 and mod.SERVER_STOP.is_set(), r.status_code)
    mod.SERVER_STOP.clear()
with open(mod.SERVER_LOG_PATH, encoding="utf-8") as f:
    check("and the log says who asked", "from the Server page" in f.read())

print("The page and its links")
html = client.get("/server").get_data(as_text=True)
check("/server is the Server page", "srvChecks" in html and "server.js" in html)
index = open(os.path.join(ROOT, "app", "templates", "index.html"), encoding="utf-8").read()
check("Settings › Other devices links to it", 'href="/server"' in index)
appjs = open(os.path.join(ROOT, "app", "static", "app.js"), encoding="utf-8").read()
check("/?settings=<section> opens Settings there", "openSettingsFromAddress" in appjs)
launcher = open(os.path.join(ROOT, "installer", "Launcher.ps1"), encoding="utf-8-sig").read()
check("the launcher hears Restart", "Local\\FrivoLauncherRestart" in launcher)
check("and Stop, without closing", "Local\\FrivoLauncherStopServer" in launcher)
check("and opens the Server page", "$localUrl + '/server'" in launcher)
check("with the chat still on the tray menu", "Open-Chat" in launcher)
check("the same event names in app.py", '"FrivoLauncherRestart"' in open(os.path.join(ROOT, "app", "app.py"), encoding="utf-8").read())

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
    server = make_server("127.0.0.1", 5193, mod.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    mod.CLIENTS.clear()
    visit("/api/local-status", IPHONE, "192.168.1.71")
    visit("/api/transcribe", IPHONE, "192.168.1.71", method="POST")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in ((1280, 900), (390, 844)):
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:5193/server")
            page.wait_for_selector(".srv-check", timeout=10000)
            page.wait_for_timeout(800)
            check(f"{width}px: no script errors", not errors, errors)
            check(f"{width}px: the checks are filled in", page.locator(".srv-check").count() >= 3)
            check(f"{width}px: the phone is listed, dictating",
                  "Dictating" in (page.text_content("#srvDevices") or ""), page.text_content("#srvDevices"))
            check(f"{width}px: looking at the page doesn't list this PC",
                  "This PC" not in (page.text_content("#srvDevices") or ""))
            check(f"{width}px: the log is filled in", page.locator(".srv-log li").count() >= 1)
            check(f"{width}px: the QR code is the address", "/api/qr.png?text=" in (page.get_attribute("#srvQr", "src") or ""))
            wide = page.evaluate("document.documentElement.scrollWidth")
            check(f"{width}px: nothing wider than the window", wide <= width, wide)
            check(f"{width}px: Restart works here (this PC)", page.is_enabled("#srvRestart"))
            page.close()
        browser.close()
    server.shutdown()

print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("All Server page checks passed.")
