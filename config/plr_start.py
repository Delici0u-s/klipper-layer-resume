#!/usr/bin/env python3
"""
plr_start.py - ask Moonraker to start a print, from outside the G-code queue.

Run detached by plr_build.py --start. It must NOT run inline: RUN_SHELL_COMMAND
holds the G-code queue until the child exits, and Moonraker's print/start needs
that same queue to reach Klipper. Inline = deadlock.

Transport: Moonraker's unix domain socket (<data>/comms/moonraker.sock), which
needs no authentication at all. This matters because [authorization] can be set
to force_logins, and an HTTP POST from a script carries no session. HTTP is
kept only as a fallback.

Everything is logged to <state_dir>/start.log - the parent redirects our stdio
to /dev/null, so this file is the only way to see what happened.

Usage: plr_start.py <relative_gcode_path> [delay_seconds]
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
STATE_DIR = os.environ.get("PLR_STATE_DIR", os.path.join(HOME, "printer_data", "plr"))
SOCKET_PATH = os.environ.get(
    "PLR_MOONRAKER_SOCKET",
    os.path.join(HOME, "printer_data", "comms", "moonraker.sock"))
HTTP_BASE = os.environ.get("PLR_MOONRAKER", "http://127.0.0.1:7125")
LOG_PATH = os.path.join(STATE_DIR, "start.log")

ETX = b"\x03"
IDLE_STATES = ("standby", "complete", "cancelled", "error")
RETRIES = 20
RETRY_WAIT = 3.0


def log(msg: str) -> None:
    line = "%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        # Parent redirects our stderr into the same log, so this is a fallback
        # only - avoid writing twice when the log file opened fine.
        sys.stderr.write(line)


# --------------------------------------------------------------------------- #
# transports
# --------------------------------------------------------------------------- #

def rpc_unix(method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
    """One JSON-RPC call over Moonraker's unix socket. Raises on failure."""
    req_id = int(time.time() * 1000) % 1000000
    payload = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params:
        payload["params"] = params

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall(json.dumps(payload).encode("utf-8") + ETX)

        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            while ETX in buf:
                raw, _, buf = buf.partition(ETX)
                if not raw.strip():
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                # Moonraker pushes async notifications down the same socket;
                # ignore anything that is not the reply to our id.
                if msg.get("id") == req_id:
                    return msg
        raise TimeoutError("no reply to %s" % method)
    finally:
        sock.close()


def rpc_http_post(path: str, query: str = "") -> tuple[int, str]:
    url = HTTP_BASE + path + (("?" + query) if query else "")
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return 0, str(exc)


# --------------------------------------------------------------------------- #

def printer_state() -> str | None:
    try:
        reply = rpc_unix("printer.objects.query", {"objects": {"print_stats": None}})
        return reply["result"]["status"]["print_stats"]["state"]
    except Exception as exc:
        log("state query via socket failed: %s" % exc)

    try:
        url = HTTP_BASE + "/printer/objects/query?print_stats"
        with urllib.request.urlopen(url, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data["result"]["status"]["print_stats"]["state"]
    except Exception as exc:
        log("state query via http failed: %s" % exc)
        return None


def notify(msg: str) -> None:
    """Echo into the Fluidd console so the wait is visibly a wait, not a hang.
    Best effort - never let this break the start."""
    try:
        rpc_unix("printer.gcode.script",
                 {"script": 'RESPOND TYPE=echo MSG="%s"' % msg.replace('"', "'")},
                 timeout=5.0)
    except Exception:
        pass


def start_print(relpath: str) -> bool:
    try:
        reply = rpc_unix("printer.print.start", {"filename": relpath})
        if "error" in reply:
            log("socket start rejected: %s" % json.dumps(reply["error"])[:300])
        else:
            log("socket start accepted: %s" % relpath)
            return True
    except Exception as exc:
        log("socket start failed: %s" % exc)

    status, body = rpc_http_post("/printer/print/start",
                                 urllib.parse.urlencode({"filename": relpath}))
    if status == 200:
        log("http start accepted: %s" % relpath)
        return True
    log("http start rejected: %s %s" % (status, body[:300]))
    return False


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: plr_start.py <relative_path> [delay]\n")
        return 2

    relpath = sys.argv[1]
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0

    log("armed: %s in %.0f s (socket=%s)" % (relpath, delay, SOCKET_PATH))
    if not os.path.exists(SOCKET_PATH):
        log("warning: %s missing, will fall back to HTTP" % SOCKET_PATH)

    # Window for the operator to hit Emergency Stop, and for Moonraker's
    # inotify watcher to see the new file and parse its metadata. Count it
    # down out loud, otherwise the silence reads as a failure and people
    # press the macro again.
    remaining = delay
    for mark in (10.0, 5.0, 2.0):
        if remaining > mark:
            time.sleep(remaining - mark)
            remaining = mark
            notify("PLR: starting %s in %.0f s (PLR_CANCEL_START aborts)"
                   % (relpath, mark))
    if remaining > 0:
        time.sleep(remaining)

    try:
        for attempt in range(1, RETRIES + 1):
            state = printer_state()
            log("attempt %d/%d: print_stats.state=%r" % (attempt, RETRIES, state))
            if state in IDLE_STATES:
                if start_print(relpath):
                    return 0
            time.sleep(RETRY_WAIT)

        log("gave up on %s" % relpath)
        notify("PLR: auto-start failed, see plr/start.log")
        return 1
    finally:
        # Release the arm-lock so the next PLR_RESUME is not blocked.
        try:
            os.unlink(os.path.join(STATE_DIR, "start.lock"))
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
