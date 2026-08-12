# Usage

## Normal operation

Nothing. Once `PLR_LOG` is in the slicer's layer change G-code, every
print writes a recovery point at each layer with no action from you.
`PLR_BEGIN` arms it at print start, `PLR_FINISH` disarms it at print end,
and a clean finish leaves no state behind.

## After a power loss

**Do not touch the printer.** Do not home, do not jog Z, do not pull the
part off the bed. The recovery depends on the toolhead still being
physically where it was when the power went.

Klipper starts. About ten seconds later:

```
PLR: INTERRUPTED PRINT DETECTED
PLR:   file   = Cube-PETG-0.2mm.gcode
PLR:   z      = 4.2 mm
PLR:   offset = 132304 bytes
PLR: run PLR_PREPARE to build the resume file, or PLR_DISCARD to forget it.
```

Then either:

```
PLR_PREPARE      # build the file, start it yourself
PLR_RESUME       # build it and start it after a countdown
```

`PLR_PREPARE` writes `<name>.plr.gcode` next to the original and stops.
Open it in your web UI's editor, read the preamble, then print it.

`PLR_RESUME` does the same and then hands the file to Moonraker after a
20 second countdown, announced in the console at T-10, T-5, and T-2:

```
PLR: starting Cube-PETG-0.2mm.plr.gcode in 10 s (PLR_CANCEL_START aborts)
```

`PLR_CANCEL_START` aborts a pending start without an emergency stop.

Running `PLR_RESUME` twice does nothing bad — the second call sees the arm
lock and reports how long is left rather than starting a second attempt.

## Parameters

Both `PLR_PREPARE` and `PLR_RESUME` take:

| Parameter | Default | Meaning |
|---|---|---|
| `LIFT` | `5` | mm to lift before homing X/Y |
| `RETRACT` | `2.0` | mm to retract once the nozzle is hot |
| `PRIME` | `0.6` | extra mm pushed back before resuming |
| `PURGE` | `0` | mm of filament for a purge line off to the side |
| `DELAY` | `20` | seconds before auto-start (`PLR_RESUME` only) |

```
PLR_RESUME PRIME=1.5 DELAY=10
PLR_PREPARE LIFT=10 PURGE=12
```

### Under-extrusion at the resume point

The nozzle sits hot and stationary for about a minute while it comes up to
temperature, so some filament oozes out and the melt zone is partly empty
when printing resumes. `PRIME` compensates. Start at the default, raise it
if the first few centimetres come out thin.

If that isn't enough, `PURGE` draws a real purge line off to the side of
the bed before returning to the part. **This is the riskiest move in the
whole preamble** — it drops the nozzle to 0.3 mm above the bed and trusts
the Z anchor completely. If the anchor is off by half a millimetre you
plough the bed instead of purging. Exhaust `PRIME` first.

The purge coordinates default to X222.5, Y5→Y80, which suits a 220×220
bed with the line off the right-hand edge. Adjust with the script's
`--purge-x`, `--purge-y`, `--purge-y-end`, `--purge-z` arguments if your
bed differs; see `plr_build.py --help`.

## Reading the preamble

Worth doing at least until you trust it on your machine:

```gcode
; ================= PLR RESUME PREAMBLE =================
; resuming at Z=4.200 (toolhead Z=4.312)
M107
M140 S80
M190 S80                              ; bed first, alone
M104 S240
M109 S240                             ; nozzle last, ~1 min of ooze
M83
G1 E-2.000 F1800                      ; retract before moving
BED_MESH_CLEAR                        ; anchor without the mesh transform
SET_KINEMATIC_POSITION X=0 Y=0 Z=4.3120
G91
G1 Z5.00 F600                         ; lift clear of the print
G90
G28 X Y                               ; XY only - never G28 Z here
EXCLUDE_OBJECT_DEFINE NAME=...
BED_MESH_PROFILE LOAD=default
G1 X101.234 Y88.500 F6000
G1 Z4.200 F300                        ; back down to the layer
M83
G1 E2.600 F300                        ; prime the melt zone
M106 S255
M220 S100
M221 S100
; =============== END PLR RESUME PREAMBLE ===============
```

The two numbers to sanity-check are the `SET_KINEMATIC_POSITION Z=` and
the `G1 Z` at the end. They should be within a layer height of where the
print actually stopped.

## What is not restored

The recovery file skips `PRINT_START` entirely, so anything that lived
there and isn't in the preamble does not happen. On most setups that
means:

- Enclosure fans, lights, or chamber heaters turned on by `PRINT_START`
- Filament sensor arming, if you do that at print start
- Any `SET_GCODE_OFFSET` beyond the babystep value that was logged

If something in your `PRINT_START` matters for the whole print, add it to
the recovery preamble in `plr_build.py`, or call it by hand before
resuming.

`PRINT_END` **does** run, because it lives at the end of the G-code file
and the recovery file keeps everything from the resume point onward.

## Surviving a second outage

The recovery file still contains `PLR_LOG` calls, so a power loss during
recovery is itself recoverable. The new recovery point points at the
`.plr.gcode`, and the next build strips the `.plr` suffix rather than
producing `.plr.plr.gcode`.

## Files it touches

| Path | Purpose |
|---|---|
| `<data>/plr/state` | The recovery point, rewritten each layer |
| `<data>/plr/start.log` | Auto-start log — check here when `PLR_RESUME` does nothing |
| `<data>/plr/start.lock` | Arm lock, removed when the helper exits |
| `<data>/gcodes/<name>.plr.gcode` | Generated resume file |

Original G-code files are never modified.
