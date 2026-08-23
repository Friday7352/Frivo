#!/usr/bin/env python3
"""Editing a file must actually reach the browser.

This exists because of a real report: a switch was added to index.html, the
file on disk plainly had it, and it was not on the page. Nothing was wrong
with the code — Jinja compiles a template once per process and, with debug
off (which is how Frivo always runs), never looks at the file again. The
running server was serving HTML it had compiled before the edit.

That failure mode is invisible: no error, no warning, just a feature that
seems not to have been built. So it gets a test.

Two things are checked, both against a real server over real HTTP:

  * a template edit under a running process reaches the next page load
  * the `?v=` stamp on the static URLs moves when app.js or style.css
    changes, so a browser cannot serve an old copy from cache

Usage:  python3 tests/test-hot-reload.py     (run from the repo root)
Needs:  flask.
"""

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
PORT = 5099

SERVER = r"""
import importlib.util, os, shutil, sys, tempfile, time
ws = tempfile.mkdtemp(prefix="frivo-ui-")
shutil.copy(os.path.join(APP, "app.py"), os.path.join(ws, "app.py"))
os.symlink(os.path.join(APP, "static"), os.path.join(ws, "static"))
os.symlink(os.path.join(APP, "templates"), os.path.join(ws, "templates"))
spec = importlib.util.spec_from_file_location("frivo_app", os.path.join(ws, "app.py"))
mod = importlib.util.module_from_spec(spec); sys.modules["frivo_app"] = mod
spec.loader.exec_module(mod)

mod.CFG["transcription_provider"] = "local_whisper"
mod.CFG["osc_enabled"] = True
mod.CFG["osc_mute_sync"] = True
mod.CFG["whisper_url"] = "http://192.168.1.9:9000"
mod.probe_provider = lambda name, timeout=2: (True, "Reachable.")

# A back door for the test only: set what FrivOSC would have reported.
from flask import request, jsonify
@mod.app.route("/_test/mute/<state>")
def _test_mute(state):
    with mod.FRIVOSC_LOCK:
        mod.FRIVOSC_STATE.update({
            "connected_at": time.time(), "last_seen": time.time(),
            "version": "1.0.0", "hostname": "VRPC",
            "muted": None if state == "unknown" else (state == "on"),
        })
    return jsonify({"ok": True, "muted": mod.FRIVOSC_STATE["muted"]})

mod.app.run(host="127.0.0.1", port=5099, debug=False, use_reloader=False)

"""

failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


def port_is_open(port):
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def page():
    return urllib.request.urlopen("http://127.0.0.1:%d/" % PORT, timeout=10).read().decode()


def main():
    if port_is_open(PORT):
        print("SKIP: port %d is already in use." % PORT)
        return 0

    workspace = tempfile.mkdtemp(prefix="frivo-hotreload-")
    server_path = os.path.join(workspace, "server.py")
    with open(server_path, "w", encoding="utf-8") as handle:
        handle.write("APP = %r\n" % APP + SERVER)

    server = subprocess.Popen([sys.executable, server_path],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    template = os.path.join(APP, "templates", "index.html")
    original = None
    try:
        for _ in range(60):
            if port_is_open(PORT):
                break
            if server.poll() is not None:
                print("The test server exited before it was ready.")
                return 1
            time.sleep(0.5)
        else:
            print("The test server never came up.")
            return 1

        with open(template, encoding="utf-8") as handle:
            original = handle.read()

        # Something that is definitely in the template, and definitely not
        # already in the compiled copy the server is holding.
        canary = "HOT-RELOAD-CANARY-%d" % int(time.time())
        anchor = "Follow VRChat mute"
        if anchor not in original:
            print("The anchor this test edits is no longer in index.html.")
            return 1

        check("the template on disk is what gets served", 'id="oscMuteSyncToggle"' in page())

        with open(template, "w", encoding="utf-8") as handle:
            handle.write(original.replace(anchor, canary, 1))
        time.sleep(1.0)
        check("a template edit reaches the browser with no restart",
              canary in page(), "the old compiled template is still being served")

        with open(template, "w", encoding="utf-8") as handle:
            handle.write(original)
        original = None
        time.sleep(1.0)
        check("and undoing the edit comes back too", anchor in page())

        stamp_before = re.search(r"app\.js\?v=(\d+)", page()).group(1)
        future = time.time() + 5
        os.utime(os.path.join(APP, "static", "app.js"), (future, future))
        time.sleep(0.5)
        stamp_after = re.search(r"app\.js\?v=(\d+)", page()).group(1)
        check("the asset stamp moves when a static file changes",
              stamp_before != stamp_after, (stamp_before, stamp_after))
    finally:
        if original is not None:
            with open(template, "w", encoding="utf-8") as handle:
                handle.write(original)
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    print()
    if failures:
        print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("All hot-reload assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
