#!/usr/bin/env python3
"""NEW (2.0.0): one quiet connection can't freeze Frivo.

cheroot does the TLS handshake on the thread that accepts every connection.
A client that connected and said nothing held up everyone else for the idle
timeout (3 minutes): Frivo ran but answered nobody, and the app said it had
stopped responding. Frivo's PatientSSLAdapter (serve() in app.py) hands such
a connection on with its handshake still to do.

  * with several silent connections open, requests are still answered
  * a client that waits before its handshake is still served
  * the scheme is still https for it (wsgi.url_scheme)

Usage:  python3 tests/test-tls-stall.py     (run from the repo root)
Needs:  Frivo's Python packages (cheroot, cryptography).
"""

import importlib.util
import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 5191
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-stall-data-")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-stall-home-")
spec = importlib.util.spec_from_file_location("frivo_stall", os.path.join(ROOT, "app", "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_stall"] = mod
spec.loader.exec_module(mod)
cert, key = mod.ensure_self_signed_cert()
mod.start_update_checker = lambda: None   # no GitHub, no voices: just the server
mod.warm_free_voices = lambda: None
threading.Thread(target=mod.serve, args=("127.0.0.1", PORT, cert, key), daemon=True).start()
for _ in range(60):
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
        break
    except OSError:
        time.sleep(0.2)

context = ssl._create_unverified_context()


def request(path="/static/icon.png", wait_first=0.0):
    started = time.time()
    try:
        raw = socket.create_connection(("127.0.0.1", PORT), timeout=8)
        if wait_first:
            time.sleep(wait_first)
        tls = context.wrap_socket(raw)
        tls.sendall(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            data += chunk
        tls.close()
        return time.time() - started, data
    except Exception as exc:   # noqa: BLE001 - reported as a failure
        return time.time() - started, repr(exc).encode()


took, data = request()
check("Frivo answers", data.startswith(b"HTTP/1.1 200"), data[:60])

silent = [socket.create_connection(("127.0.0.1", PORT)) for _ in range(5)]
time.sleep(0.3)
took, data = request()
check("with five silent connections open, it still answers", data.startswith(b"HTTP/1.1 200"), data[:80])
check("quickly (it used to wait up to 3 minutes)", took < 3, round(took, 2))

took, data = request(wait_first=1.0)
check("a client that waits before its handshake is still served", data.startswith(b"HTTP/1.1 200"), data[:80])
took, data = request("/api/hello", wait_first=0.5)
body = data.split(b"\r\n\r\n", 1)[-1]
try:
    hello = json.loads(body)
except ValueError:
    hello = {}
check("and sees https", hello.get("https") is True, body[:120])

for s in silent:
    s.close()
took, data = request()
check("and answers after they close", data.startswith(b"HTTP/1.1 200"), data[:60])

print()
if failures:
    print(f"{len(failures)} failed")
    os._exit(1)
print("All TLS stall checks passed.")
os._exit(0)
