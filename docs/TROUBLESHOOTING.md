# Troubleshooting

## `Error running command {plr_check}` (or `{plr_build}`, `{plr_log}`, ...)

The shell command could not be executed. In order of likelihood:

**Unsubstituted placeholders.** If the files were copied by hand instead
of by `install.sh`, the paths are still templates and Klipper is trying to
run a program literally called `__PYTHON__`.

```bash
grep -rn '__[A-Z_]*__' ~/printer_data/config/plr/
```

Any output means re-run `./install.sh`.

**Missing executable bit.**

```bash
chmod +x ~/printer_data/config/plr/*.sh ~/printer_data/config/plr/*.py
```

**Wrong python path.** Check `command:` in `plr.cfg` against
`command -v python3`.

**No recovery point.** `PLR_PREPARE` and `PLR_RESUME` exit non-zero when
there is nothing to resume, and that surfaces as `Error running command`.
Run `PLR_STATUS` first — if it says no recovery point is stored, that is
the whole explanation.

## `Malformed command 'RUN_SHELL_COMMAND ...'`

A macro rendered a `PARAMS="..."` string across multiple lines. Klipper
treats each rendered line as its own command, so the quote never closes.
If you have edited `plr.cfg`, keep every `RUN_SHELL_COMMAND` on one
physical line — build the argument string into a Jinja variable first.

## `PLR_STATUS` always says no recovery point, even mid-print

The slicer hook is not firing. Check that `PLR_LOG` is in the layer change
G-code **and that you re-sliced afterwards** — the hook is baked into the
file, not the config. Open the `.gcode` in a text editor and search for
`PLR_LOG`.

Also confirm `[virtual_sdcard]` exists and the print was started through
it (from the web UI), not streamed over USB from a slicer.

## `PLR_RESUME` builds the file but nothing starts

Read the log:

```bash
cat ~/printer_data/plr/start.log
```

A working run looks like:

```
armed: Cube.plr.gcode in 20 s (socket=/home/user/printer_data/comms/moonraker.sock)
attempt 1/20: print_stats.state='standby'
socket start accepted: Cube.plr.gcode
```

| Log line | Meaning |
|---|---|
| `socket=... missing, will fall back to HTTP` | wrong data path, or Moonraker isn't running |
| `state query ... failed` | Moonraker unreachable |
| `print_stats.state='printing'` repeatedly | a print is already running |
| `socket start rejected: ... file not found` | Moonraker hasn't indexed the new file yet — raise `DELAY` |
| `http start rejected: 401` | socket failed and HTTP auth blocked the fallback; fix the socket path |

If the log is empty or absent, the helper never ran. Check that
`plr_start.py` exists next to `plr_build.py` and is executable.

## It armed twice / I pressed `PLR_RESUME` again

Expected and harmless. The second call sees the arm lock and reports the
remaining time instead of starting a rival helper. If a lock is somehow
left behind after a crash, `PLR_CANCEL_START` clears it, and a stale lock
whose process is gone is ignored automatically.

## The nozzle crashed into the print

Stop and work out which of these happened before running another recovery:

- Something moved between the outage and the recovery — homing, jogging,
  removing the part.
- The last state write did not reach disk, so the Z is from an older
  layer. Confirm `sync` is not disabled via `PLR_NOSYNC`.
- The bed mesh order was disturbed by local edits to the preamble.
- Your `PRINT_START` applies a `SET_GCODE_OFFSET` that the log did not
  capture because it was applied after the last `PLR_LOG`.

Run `PLR_PREPARE` (not `PLR_RESUME`) and read the preamble's Z values
against the layer where the print actually stopped.

## Z is off by a fraction of a millimetre

Almost always bed mesh interaction. Check that the preamble does
`BED_MESH_CLEAR` **before** `SET_KINEMATIC_POSITION` and
`BED_MESH_PROFILE LOAD` **after** the move back to the real X/Y. See
[HOW_IT_WORKS.md](HOW_IT_WORKS.md).

If your printer uses `z_tilt`, `quad_gantry_level`, or skew correction,
those transforms are not accounted for and this is expected to be wrong.

## Under-extrusion for the first few centimetres

The melt zone emptied while the nozzle waited. Raise `PRIME`:

```
PLR_RESUME PRIME=1.5
```

If that is not enough, `PURGE=12` draws a real purge line — read the
warning in [USAGE.md](USAGE.md) first.

## A blob welded into the print at the resume point

Check that the preamble heats the bed to target *before* setting the
hotend. If both `M104` and `M140` appear before `M190`, the version
installed is older than the fix.

## Layer markers not found / resume point at the wrong place

The layer marker detection covers `;LAYER_CHANGE`, `;LAYER:`,
`;BEFORE_LAYER_CHANGE`, and `;AFTER_LAYER_CHANGE`. If your slicer emits
something else, the split falls back to the nearest line boundary, which
lands mid-layer. Add your marker to `LAYER_MARKERS` in `plr_build.py`.

## Layer changes stutter

`plr_log.sh` calls `sync` twice per layer. On a slow SD card that is
visible. Add `PLR_NOSYNC=1` to the environment of the `plr_log` shell
command, accepting that a hard power cut may then lose the last layer or
two of state.

## Getting help

Include: the console output, `~/printer_data/plr/start.log`,
`~/printer_data/plr/state`, the preamble from the generated `.plr.gcode`,
your slicer and its layer change G-code, and your printer's kinematics.
