#!/usr/bin/env python3
"""
plr_build.py - build a resume G-code file from a recovery point.

Reads   ~/printer_data/plr/state
Writes  <original_dir>/<name>.plr.gcode

Design notes
------------
* We never re-home Z.  The probe would come down on top of the print.
  Instead SET_KINEMATIC_POSITION tells Klipper where the nozzle already
  physically is, using the *toolhead* (post-transform) Z we logged.
* The bed mesh is cleared while we anchor the position and re-loaded
  only once the toolhead is back over the real X/Y, so the mesh offset
  is never applied twice or at the wrong coordinates.
* We resume from the layer-change marker at or before the logged byte
  offset.  virtual_sdcard.file_position runs ahead of actual motion by
  the lookahead buffer, so snapping backwards to the layer boundary
  costs at most one duplicated layer instead of leaving a gap.
* The leading comment block (slicer header + thumbnails) is copied so
  Fluidd/Moonraker still show a preview and sane metadata, and any
  EXCLUDE_OBJECT_DEFINE lines Moonraker injected are carried over so
  the EXCLUDE_OBJECT_START/END calls in the body still resolve.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

LAYER_MARKERS = (
    b";LAYER_CHANGE",
    b";BEFORE_LAYER_CHANGE",
    b";AFTER_LAYER_CHANGE",
    b";LAYER:",
    b";LAYER ",
)

# How far back we are willing to look for a layer marker / E state.
MARKER_WINDOW = 1 << 20        # 1 MiB
E_WINDOW = 2 << 20             # 2 MiB
HEADER_LIMIT = 4 << 20         # 4 MiB (thumbnails can be big)

RE_M82_83 = re.compile(rb"(?m)^\s*(M8[23])\b")
RE_G92_E = re.compile(rb"(?mi)^\s*G92\b[^;\n]*?\bE(-?\d*\.?\d+)")
RE_MOVE_E = re.compile(rb"(?mi)^\s*G[0123]\b[^;\n]*?\bE(-?\d*\.?\d+)")
RE_EXCLUDE_DEF = re.compile(rb"(?m)^\s*EXCLUDE_OBJECT_DEFINE\b.*$")


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #

def read_state(path: str) -> dict:
    if not os.path.isfile(path):
        die("no recovery point at %s - nothing to resume" % path)
    state = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if "=" in line:
                key, _, val = line.partition("=")
                state[key.strip()] = val
    for required in ("file", "offset", "x", "y", "z_gcode", "z_toolhead"):
        if required not in state:
            die("recovery point is incomplete (missing %r)" % required)
    return state


def fnum(state: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(state.get(key, default))
    except (TypeError, ValueError):
        return default


def die(msg: str) -> "NoReturn":  # noqa: F821
    sys.stderr.write("PLR: %s\n" % msg)
    print("PLR: %s" % msg)
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
# g-code surgery
# --------------------------------------------------------------------------- #

def find_split(data: bytes, offset: int) -> int:
    """Byte index of the start of the layer that was in progress."""
    offset = max(0, min(offset, len(data)))
    start = max(0, offset - MARKER_WINDOW)
    window = data[start:offset]

    best = -1
    for marker in LAYER_MARKERS:
        idx = window.rfind(marker)
        if idx > best:
            best = idx
    if best < 0:
        # No marker: fall back to the last complete line before the offset.
        nl = data.rfind(b"\n", 0, offset)
        return 0 if nl < 0 else nl + 1

    line_start = window.rfind(b"\n", 0, best)
    return start + (0 if line_start < 0 else line_start + 1)


def copy_header(data: bytes) -> bytes:
    """Leading comment/blank block only - slicer metadata and thumbnails."""
    pos = 0
    out = []
    while pos < len(data) and pos < HEADER_LIMIT:
        nl = data.find(b"\n", pos)
        if nl < 0:
            nl = len(data)
        line = data[pos:nl]
        stripped = line.strip()
        if stripped and not stripped.startswith(b";"):
            break
        out.append(line)
        pos = nl + 1
    return b"\n".join(out) + b"\n" if out else b""


def extruder_state(head: bytes) -> tuple[bool, float]:
    """(relative_e, last_absolute_e) for the g-code executed so far."""
    scan = head[-E_WINDOW:] if len(head) > E_WINDOW else head

    mode = RE_M82_83.findall(head)
    relative = True
    if mode:
        relative = mode[-1] == b"M83"

    if relative:
        return True, 0.0

    last_e = 0.0
    for line in scan.split(b"\n"):
        m = RE_G92_E.match(line)
        if m:
            last_e = float(m.group(1))
            continue
        m = RE_MOVE_E.match(line)
        if m:
            last_e = float(m.group(1))
    return False, last_e


def build_preamble(state: dict, relative_e: bool, last_e: float,
                   lift: float, excludes: list[bytes],
                   retract: float, prime: float,
                   purge: float, purge_x: float, purge_y: float,
                   purge_y_end: float, purge_z: float) -> bytes:
    x = fnum(state, "x")
    y = fnum(state, "y")
    z_gcode = fnum(state, "z_gcode")
    z_tool = fnum(state, "z_toolhead")
    off_z = fnum(state, "offset_z")
    fan = int(round(fnum(state, "fan") * 255.0))
    sf = int(round(fnum(state, "speed_factor", 1.0) * 100.0)) or 100
    ef = int(round(fnum(state, "extrude_factor", 1.0) * 100.0)) or 100
    hot = int(round(fnum(state, "extruder")))
    bed = int(round(fnum(state, "bed")))
    mesh = state.get("mesh", "").strip()

    lines = [
        b"; ================= PLR RESUME PREAMBLE =================",
        ("; resuming at Z=%.3f (toolhead Z=%.3f)" % (z_gcode, z_tool)).encode(),
        b"M107                                  ; part fan off while we recover",
    ]

    # Bed to temp FIRST, on its own. The nozzle stays cold and parked in the
    # print for the whole soak, so it cannot ooze. Heating both together means
    # the hotend sits molten for however long the bed takes (~20x longer on a
    # stock V3 SE bed) and drools a blob into the part.
    if bed > 0:
        lines += [
            ("M140 S%d" % bed).encode(),
            ("M190 S%d                              ; bed first, alone" % bed).encode(),
        ]

    # Only now bring the nozzle up, and retract as soon as it is liquid so the
    # travel and homing moves do not string.
    if hot > 0:
        lines += [
            ("M104 S%d" % hot).encode(),
            ("M109 S%d                             ; nozzle last, ~1 min of ooze" % hot).encode(),
        ]
        if retract > 0:
            lines += [
                b"M83",
                ("G1 E-%.3f F1800                       ; retract before moving" % retract).encode(),
            ]

    lines += [
        b"BED_MESH_CLEAR                        ; anchor without the mesh transform",
        ("SET_KINEMATIC_POSITION X=0 Y=0 Z=%.4f" % z_tool).encode(),
        b"G91",
        ("G1 Z%.2f F600                          ; lift clear of the print" % lift).encode(),
        b"G90",
        b"G28 X Y                               ; XY only - never G28 Z here",
    ]

    for definition in excludes:
        lines.append(definition.strip())

    if mesh:
        lines.append(("BED_MESH_PROFILE LOAD=%s" % mesh).encode())
    if abs(off_z) > 1e-6:
        lines.append(("SET_GCODE_OFFSET Z=%.4f" % off_z).encode())

    # Optional purge line off to the side, same spot PRINT_START uses.
    # Refills the melt zone so the resumed layer starts at full flow.
    if purge > 0:
        lines += [
            ("; --- purge line at X%.1f, clear of the part ---" % purge_x).encode(),
            ("G1 X%.3f Y%.3f F6000" % (purge_x, purge_y)).encode(),
            ("G1 Z%.3f F600" % purge_z).encode(),
            b"M83",
            ("G1 Y%.3f E%.3f F1500                  ; purge" % (purge_y_end, purge)).encode(),
            ("G1 X%.3f Y%.3f F1200                  ; wipe off the line"
             % (purge_x - 4.0, purge_y_end - 3.0)).encode(),
            ("G1 E-%.3f F1800" % retract).encode(),
            ("G1 Z%.3f F600" % (z_gcode + lift)).encode(),
        ]

    lines += [
        ("G1 X%.3f Y%.3f F6000" % (x, y)).encode(),
        ("G1 Z%.3f F300                          ; back down to the layer" % z_gcode).encode(),
    ]

    # Un-retract plus a little extra to make up for whatever still oozed out.
    if hot > 0 and (retract + prime) > 0:
        lines += [
            b"M83",
            ("G1 E%.3f F300                          ; prime the melt zone"
             % (retract + prime)).encode(),
        ]

    lines += [
        b"M83" if relative_e else ("M82\nG92 E%.5f" % last_e).encode(),
        ("M106 S%d" % fan).encode(),
        ("M220 S%d" % sf).encode(),
        ("M221 S%d" % ef).encode(),
        b"; =============== END PLR RESUME PREAMBLE ===============",
        b"",
    ]
    return b"\n".join(lines) + b"\n"


# --------------------------------------------------------------------------- #

# Substituted by install.sh. Override at runtime with PLR_STATE_DIR or --state.
DEFAULT_STATE_DIR = "__PLR_STATE_DIR__"


def lock_path(state_dir: str) -> str:
    return os.path.join(state_dir, "start.lock")


def read_lock(state_dir: str):
    """(pid, deadline) if a helper is armed and still alive, else None."""
    try:
        with open(lock_path(state_dir), "r", encoding="utf-8") as fh:
            pid_s, deadline_s = fh.read().split()
        pid, deadline = int(pid_s), float(deadline_s)
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)          # signal 0: liveness check only
    except OSError:
        return None              # stale lock, helper is gone
    return pid, deadline


def queue_print(dst: str, delay: float, state_dir: str) -> None:
    """Hand the file to Moonraker via a DETACHED helper.

    This must not block. RUN_SHELL_COMMAND holds the G-code queue until the
    child exits, and Moonraker's print/start needs that same queue to be free
    to reach Klipper. Doing it inline deadlocks until the 900 s timeout.
    """
    import subprocess

    home = os.path.expanduser("~")
    root = os.environ.get("PLR_GCODE_DIR",
                          os.path.join(home, "printer_data", "gcodes"))
    try:
        rel = os.path.relpath(dst, root)
    except ValueError:
        rel = os.path.basename(dst)
    if rel.startswith(".."):
        print("PLR: %s is outside %s - start it manually" % (dst, root))
        return

    helper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "plr_start.py")
    if not os.path.isfile(helper_path):
        print("PLR: plr_start.py missing - start %s manually" % rel)
        return

    # Send the child's stderr to a log file, not /dev/null. If plr_start.py
    # dies before it can open its own log (import error, wrong interpreter),
    # this is the only trace that will exist.
    try:
        os.makedirs(state_dir, exist_ok=True)
        errlog = open(os.path.join(state_dir, "start.log"), "a")
    except OSError:
        errlog = subprocess.DEVNULL

    try:
        child = subprocess.Popen(
            [sys.executable, helper_path, rel, str(delay)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errlog,
            start_new_session=True,
            close_fds=True,
            env=dict(os.environ, PLR_STATE_DIR=state_dir),
        )
    except OSError as exc:
        print("PLR: could not spawn plr_start.py (%s) - start %s manually"
              % (exc, rel))
        return

    try:
        with open(lock_path(state_dir), "w", encoding="utf-8") as fh:
            fh.write("%d %f\n" % (child.pid, time.time() + delay))
    except OSError:
        pass

    print("PLR: >>> AUTO-START ARMED <<<")
    print("PLR: log -> %s" % os.path.join(state_dir, "start.log"))
    print("PLR: PLR_CANCEL_START stops it without an emergency stop")
    print("PLR: %s begins in %.0f s. EMERGENCY STOP now if anything is wrong."
          % (rel, delay))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a Klipper power-loss resume file")
    ap.add_argument("--state", default=os.environ.get("PLR_STATE_DIR", DEFAULT_STATE_DIR),
                    help="directory holding the recovery point")
    ap.add_argument("--lift", type=float, default=5.0,
                    help="mm to lift before homing XY (default 5)")
    ap.add_argument("--retract", type=float, default=2.0,
                    help="mm to retract once the nozzle is hot (default 2)")
    ap.add_argument("--prime", type=float, default=0.6,
                    help="extra mm to push back before resuming (default 0.6)")
    ap.add_argument("--purge", type=float, default=0.0,
                    help="mm of filament for a purge line off to the side; "
                         "0 disables (default 0)")
    ap.add_argument("--purge-x", type=float, default=222.5)
    ap.add_argument("--purge-y", type=float, default=5.0)
    ap.add_argument("--purge-y-end", type=float, default=80.0)
    ap.add_argument("--purge-z", type=float, default=0.3)
    ap.add_argument("--out", default=None, help="explicit output path")
    ap.add_argument("--start", action="store_true",
                    help="hand the finished file to Moonraker to print")
    ap.add_argument("--start-delay", type=float, default=8.0,
                    help="seconds before the print is started (default 8)")
    args = ap.parse_args()

    # Do not rebuild while a helper is already counting down. Rewriting the
    # file at the moment virtual_sdcard opens it is a race worth avoiding, and
    # a second helper would just fight the first one.
    if args.start:
        armed = read_lock(args.state)
        if armed:
            pid, deadline = armed
            left = max(0.0, deadline - time.time())
            print("PLR: auto-start already armed (pid %d), %.0f s to go." % (pid, left))
            print("PLR: waiting. Use PLR_CANCEL_START to abort it.")
            return 0

    state = read_state(os.path.join(args.state, "state"))

    src = state["file"]
    if not os.path.isfile(src):
        die("original g-code is gone: %s" % src)

    try:
        offset = int(float(state["offset"]))
    except ValueError:
        die("bad offset in recovery point: %r" % state["offset"])

    with open(src, "rb") as fh:
        data = fh.read()

    split = find_split(data, offset)
    if split <= 0:
        die("resume point is at the very start of the file - just reprint it")

    head = data[:split]
    relative_e, last_e = extruder_state(head)
    excludes = RE_EXCLUDE_DEF.findall(head)

    base = os.path.basename(src)
    stem = base[:-6] if base.lower().endswith(".gcode") else base
    if stem.endswith(".plr"):
        stem = stem[:-4]
    dst = args.out or os.path.join(os.path.dirname(src), stem + ".plr.gcode")

    tmp = dst + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(copy_header(data))
        fh.write(build_preamble(state, relative_e, last_e, args.lift, excludes,
                                args.retract, args.prime, args.purge,
                                args.purge_x, args.purge_y,
                                args.purge_y_end, args.purge_z))
        fh.write(data[split:])
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dst)

    pct = 100.0 * split / max(1, len(data))
    print("PLR: resume file written -> %s" % dst)
    print("PLR: skipped %d of %d bytes (%.1f%% of the file)" % (split, len(data), pct))
    print("PLR: extruder mode = %s%s"
          % ("relative (M83)" if relative_e else "absolute (M82)",
             "" if relative_e else ", G92 E%.5f" % last_e))
    if args.start:
        queue_print(dst, args.start_delay, args.state)
    else:
        print("PLR: check the preamble before starting, then print %s"
              % os.path.basename(dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
