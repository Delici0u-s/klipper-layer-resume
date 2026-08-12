# How it works

## Logging

`PLR_LOG` fires once per layer from the slicer's layer change G-code. It
renders a single `RUN_SHELL_COMMAND` line — it has to be a single line,
because Klipper treats each line a macro renders as a separate G-code
command, and a quoted string split across lines produces a malformed
command.

Thirteen values are captured:

| Value | Source | Used for |
|---|---|---|
| file path | `virtual_sdcard.file_path` | which file to resume |
| byte offset | `virtual_sdcard.file_position` | where to resume |
| X, Y | `gcode_move.gcode_position` | where to return to |
| Z (gcode) | `gcode_move.gcode_position.z` | the layer height to command |
| Z (toolhead) | `toolhead.position.z` | the physical anchor |
| gcode offset Z | `gcode_move.homing_origin.z` | babystep, re-applied |
| fan | `fan.speed` | restored |
| speed / extrude factor | `gcode_move` | `M220` / `M221` |
| extruder, bed target | heaters | reheat |
| mesh profile | `bed_mesh.profile_name` | reload the right mesh |

Both Z values are needed. `gcode_position.z` is what the file commanded;
`toolhead.position.z` is where the nozzle physically is after the bed mesh
transform and any gcode offset. They differ by the mesh value at that X/Y,
which can be most of a millimetre.

`plr_log.sh` writes to a temp file, `sync`s it, renames over the real
state file, then `sync`s the directory. Without that, the write sits in
the page cache and is lost in exactly the scenario the whole system exists
for. It costs 50–150 ms per layer on a Pi Zero 2 W; set `PLR_NOSYNC=1` in
the shell command's environment to skip it, at the cost of possibly losing
the last layer or two of state.

## Why once per layer

Logging every N lines gets you finer resolution and a worse printer. Each
`RUN_SHELL_COMMAND` forks a shell from inside the G-code queue and blocks
it. Thousands of those per print stutters motion on a slow host and wears
the SD card. Once per layer, during a travel move, the cost disappears.

The price is that you resume at a layer boundary and re-print the
interrupted layer from its start. Part of that layer gets a second pass
of material. Over-extrusion on one layer is a much better failure than a
void.

## Building the resume file

`plr_build.py`:

1. **Find the split point.** `virtual_sdcard.file_position` runs ahead of
   actual motion by the lookahead buffer, so the logged offset is somewhere
   inside the layer that was printing. The script scans backwards from it
   for the nearest layer marker (`;LAYER_CHANGE`, `;LAYER:`,
   `;BEFORE_LAYER_CHANGE`, `;AFTER_LAYER_CHANGE`) and splits there. If no
   marker is found it falls back to the last complete line.

2. **Copy the header.** The leading comment block — slicer metadata and
   embedded thumbnails — is copied verbatim so the resume file still shows
   a preview and sane estimates in Moonraker and the web UI.

3. **Carry over object definitions.** With Moonraker's
   `enable_object_processing`, `EXCLUDE_OBJECT_DEFINE` lines are injected
   near the top of the file. They sit above the split point, so without
   copying them the `EXCLUDE_OBJECT_START` calls in the body would fail
   with an unknown object.

4. **Work out the extruder mode.** The last `M82`/`M83` before the split
   decides it. Relative E needs nothing beyond re-issuing `M83`. Absolute
   E needs a `G92 E<value>`, reconstructed by replaying the last 2 MB
   before the split and tracking `G92 E` and `G0/G1 E` as they occur.

5. **Emit the preamble, then the remainder** of the original file from the
   split point to EOF. Written to a temp file, fsynced, renamed.

## The preamble, and why the order matters

```gcode
M140 S<bed>
M190 S<bed>        ; bed alone
M104 S<hot>
M109 S<hot>        ; nozzle last
M83
G1 E-<retract>
BED_MESH_CLEAR
SET_KINEMATIC_POSITION X=0 Y=0 Z=<toolhead z>
G91 / G1 Z<lift> / G90
G28 X Y
BED_MESH_PROFILE LOAD=<profile>
G1 X<x> Y<y>
SET_GCODE_OFFSET Z=<offset>
G1 Z<gcode z>
M83 (or M82 + G92 E)
M106 / M220 / M221
```

**Bed first, alone.** A stock bed can take twenty times as long as the
hotend to reach temperature. Starting both together leaves the nozzle
molten and parked in the print for the whole soak, drooling a blob into
it. The nozzle stays cold until the bed is done, then comes up in about a
minute.

**Retract before moving.** As soon as the nozzle is liquid, pull filament
back so the travel and homing moves don't string.

**Z is never homed.** `G28` would run the printer's normal Z homing
routine. If that probes anywhere over the part — which it does on any
machine using `safe_z_home` near the bed centre — the probe collides with
the print. `SET_KINEMATIC_POSITION` tells Klipper where the nozzle already
is instead. This is why `plr.cfg` enables `[force_move]`: the command is
gated behind it.

**The mesh dance.** Klipper's transform chain is
`gcode_move → bed_mesh → toolhead`. `SET_KINEMATIC_POSITION` sets the
post-transform (physical) position. If the mesh is loaded when you anchor,
`gcode_move` derives its base position by subtracting the mesh value at
whatever X/Y the toolhead currently claims — and after a restart, before
homing, that X/Y is meaningless. The error then propagates into every
subsequent Z move.

Clearing the mesh first makes gcode Z and physical Z identical at the
anchor point. The mesh is reloaded only after `G28 X Y` and the move back
to the real X/Y, at which point the transform is anchored correctly and
`G1 Z<gcode z>` lands exactly where the original file intended.

Skipping the mesh entirely is not an option: without `fade_end`, Klipper
applies mesh compensation at every height, so dropping it mid-print shifts
Z by the full mesh amplitude.

## Auto-start

`PLR_RESUME` cannot simply call `SDCARD_PRINT_FILE`. Klipper renders an
entire macro template before executing any of it, so the macro has no way
to learn a filename that only exists once the build has run.

Starting the print from inside the shell command deadlocks:
`RUN_SHELL_COMMAND` holds the G-code queue until the child exits, and
Moonraker's print start needs that queue free to reach Klipper.

So `plr_build.py` spawns `plr_start.py` in a new session, detached, and
returns immediately. The helper counts down, polls `print_stats.state`
until Klipper is idle, and issues `printer.print.start`.

It talks to Moonraker over the unix domain socket at
`<data>/comms/moonraker.sock` rather than HTTP. The socket requires no
authentication, which matters because `[authorization] force_logins` will
reject an unauthenticated HTTP POST from a script. Requests are JSON-RPC
terminated with an ETX byte (0x03); asynchronous notifications arrive on
the same socket, so replies are matched by request id. HTTP remains as a
fallback.

An arm lock (`plr/start.lock`, holding the helper's pid and deadline)
prevents a second `PLR_RESUME` from spawning a rival helper or — worse —
rewriting the output file at the moment Klipper opens it.

Everything the helper does goes to `plr/start.log`, since its stdio is
detached from the console.

## Failure modes worth knowing

| Symptom | Cause |
|---|---|
| Z is off by roughly the mesh amplitude | mesh loaded/cleared in the wrong order, or the anchor used the gcode Z instead of the toolhead Z |
| Nozzle collides with the print | Z moved between the outage and recovery, or the state file was stale |
| Resume point far behind the outage | last state write did not reach disk — check that `sync` is not disabled |
| Under-extrusion at the resume point | melt zone emptied by ooze — raise `PRIME` |
| `Unknown object` errors | `EXCLUDE_OBJECT_DEFINE` lines were not carried over |
| Nothing happens after `PLR_RESUME` | read `plr/start.log` |
