# === osc_relay.py ===
"""
Frivo OSC relay — forwards VRChat's OSC output to a Frivo server on another PC.

Most people do not need this
----------------------------
VRChat can send its OSC output to another machine directly, with a launch
option — no relay, nothing extra running:

    --osc=9000:<frivo-server-ip>:9001

That is the simpler answer when Frivo runs on a different PC than VRChat,
and the README documents it as the main path.

The catch is that VRChat has exactly one OSC output destination. Pointing it
at the Frivo server means local OSC apps on the VRChat PC — face tracking,
avatar tools, VRCOSC — stop receiving anything, because the data no longer
goes to that machine at all.

This relay is for that case. Leave VRChat's output pointed at 127.0.0.1 as
normal so local apps keep working, and run this alongside them to copy the
same traffic onward to the Frivo server.

Standalone on purpose
---------------------
This imports nothing outside Python's standard library — no Flask, no
openai, no cryptography. The PC running VRChat is usually not the PC with
Frivo's dependencies installed, and requiring them here would mean a full
`pip install -r requirements.txt` on a machine that only needs to forward
UDP packets. Any Python 3 install can run this file as-is.

(This was originally a mode of app.py. That didn't work: app.py imports
Flask at module level, so it exits with ModuleNotFoundError long before it
reaches any relay code. Hence a separate file rather than another flag.)

Usage
-----
    python osc_relay.py --target 192.168.1.50
    python osc_relay.py --target 192.168.1.50:9001 --listen-port 9001

Or double-click Start-OSC-Relay.bat in the Frivo folder, which prompts for
the address and calls this.
"""

import socket
import sys

# VRChat's default OSC output port, and the port Frivo's OSC controls
# feature listens on by default. Both ends default to the same number, so
# the common case needs no port flags at all.
DEFAULT_PORT = 9001

USAGE = """Frivo OSC relay

Usage:
  python osc_relay.py --target <Frivo server address>[:port] [--listen-port N]

Run this on the SAME PC as VRChat, when Frivo's server runs on a different
PC. Point --target at that other PC's LAN address.

  --target        Frivo server's address, e.g. 192.168.1.50 or
                  192.168.1.50:9001. Port defaults to 9001.
  --listen-port   Local port to listen on for VRChat's output.
                  Defaults to 9001, which is VRChat's default.

Not needed when VRChat and Frivo run on the same PC — Frivo can listen to
VRChat directly in that case.
"""


def flag_value(args, name, default=None):
    """Reads `--name value` out of an argument list."""
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def parse_target(target):
    """
    Splits "host" or "host:port" into (host, port).

    rpartition rather than split(":") so an IPv6 literal or a hostname
    containing a colon doesn't get chopped at the wrong place.
    """
    if ":" in target:
        host, _, port_text = target.rpartition(":")
        try:
            return host, int(port_text)
        except ValueError:
            print(f"Bad port in --target: {target!r}")
            sys.exit(1)
    return target, DEFAULT_PORT


def run_relay(target_host, target_port, listen_port):
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # 127.0.0.1 rather than 0.0.0.0: VRChat only ever sends to loopback,
        # so there is no reason to accept these packets from the network.
        listen_sock.bind(("127.0.0.1", listen_port))
    except OSError as e:
        print(f"Couldn't bind UDP 127.0.0.1:{listen_port}: {e}")
        print()
        print("Something else is already using this port — most likely another")
        print("copy of this relay, or Frivo itself running on this PC with OSC")
        print("controls turned on.")
        sys.exit(1)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print("Frivo OSC relay")
    print(f"  Listening for VRChat on 127.0.0.1:{listen_port}")
    print(f"  Forwarding to {target_host}:{target_port}")
    print()
    print("  In VRChat, make sure OSC is enabled under the Options menu —")
    print("  this is a pass-through and has nothing to forward until it is.")
    print()
    print("  If Frivo was installed with its installer, the firewall is already")
    print("  handled. Running from source, allow inbound UDP on that PC once:")
    print(f'    netsh advfirewall firewall add rule name="Frivo OSC in" '
          f"dir=in action=allow protocol=UDP localport={target_port}")
    print()
    print("Press CTRL+C to stop.")
    print()

    forwarded = 0
    # Errors are reported once per run rather than per packet: VRChat sends
    # continuously, so a wrong address or a server that's down would
    # otherwise scroll thousands of identical lines past anything useful.
    reported_error = None
    try:
        while True:
            try:
                data, _addr = listen_sock.recvfrom(65535)
            except OSError:
                break
            try:
                # Forwarded byte-for-byte, without decoding. Nothing here
                # needs to understand OSC, and staying format-agnostic means
                # this keeps working for whatever parameters a later version
                # of Frivo decides to read.
                send_sock.sendto(data, (target_host, target_port))
                forwarded += 1
                if forwarded == 1:
                    print(f"Forwarding — first packet received from VRChat.")
            except OSError as e:
                # Keep listening. The server may simply not be up yet, and
                # exiting would mean restarting this by hand once it is.
                if reported_error != str(e):
                    reported_error = str(e)
                    print(f"Can't reach {target_host}:{target_port} — {e}")
                    print("Still listening; will keep trying.")
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\nStopped. Forwarded {forwarded} packet(s) this run.")
        if forwarded == 0:
            print()
            print("Nothing was received from VRChat. Check that OSC is enabled")
            print("in VRChat's Options menu, and that this is running on the")
            print("same PC as VRChat.")
        listen_sock.close()
        send_sock.close()


def main(args):
    if "--help" in args or "-h" in args:
        print(USAGE)
        return 0

    target = flag_value(args, "--target")
    if not target:
        print(USAGE)
        return 1

    target_host, target_port = parse_target(target)

    listen_port_text = flag_value(args, "--listen-port", str(DEFAULT_PORT))
    try:
        listen_port = int(listen_port_text)
    except ValueError:
        print(f"Bad --listen-port: {listen_port_text!r}")
        return 1

    run_relay(target_host, target_port, listen_port)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
