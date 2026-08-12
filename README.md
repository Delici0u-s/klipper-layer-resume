# klipper-layer-resume

Power loss recovery for Klipper, at layer granularity.

One durable state write per layer. No rewriting of your G-code files. No
per-line shell forks. Small enough to read in one sitting.

```
Power comes back  ->  PLR_STATUS   (what survived?)
                  ->  PLR_PREPARE  (build <name>.plr.gcode)
                  ->  print it     (or PLR_RESUME to do both)
```

## Why another one

Most Klipper PLR projects do one of two things that this one avoids:

**They log every N lines.** That means forking a shell from inside the
G-code queue thousands of times per print. On a Pi Zero 2 W it stutters
motion and hammers the SD card. This logs once per layer instead. You
lose up to one layer of progress; you gain a system that doesn't
interfere with printing.

**They don't fsync.** A plain `echo > file` leaves the data in the page
cache, where it dies with the power — losing exactly the write you needed.
This writes to a temp file, fsyncs, renames, and fsyncs the directory.

Two more things it gets right, both of which are easy to get wrong:

- **Z is never re-homed.** If your `safe_z_home` probes near the middle of
  the bed, a `G28` after power loss drives the probe into the print.
  Recovery uses `SET_KINEMATIC_POSITION` with the toolhead Z that was
  logged before the outage.
- **The bed mesh is not applied twice.** The mesh is cleared while the
  position is anchored, and re-loaded only after the toolhead is back over
  the real X/Y. Get the order wrong and you are off in Z by the full
  amplitude of your mesh.

## Requirements

- Klipper with `[virtual_sdcard]`
- Moonraker (for `PLR_RESUME` auto-start; everything else works without it)
- [`gcode_shell_command`](https://github.com/dw-0/kiauh) — KIAUH, Advanced menu
- `python3` on the host
- A slicer that can emit custom G-code at layer change

Developed and tested on an Ender 3 V3 SE with a Pi Zero 2 W, Fluidd, and
OrcaSlicer. Nothing in it is specific to that printer, but nothing in it
has been tested on another one either.

## Install

```bash
git clone https://github.com/Delici0u-s/klipper-layer-resume.git
cd klipper-layer-resume
./install.sh
```

Then three manual edits — an include in `printer.cfg`, two macro calls in
`macros.cfg`, and one line in your slicer. See
[docs/INSTALL.md](docs/INSTALL.md).

## Macros

| Macro | What it does |
|---|---|
| `PLR_STATUS` | Report the stored recovery point, if any |
| `PLR_PREPARE` | Build `<name>.plr.gcode`, don't start it |
| `PLR_RESUME` | Build it and hand it to Moonraker after a countdown |
| `PLR_CANCEL_START` | Abort a pending auto-start |
| `PLR_DISCARD` | Forget the recovery point |
| `PLR_BEGIN` / `PLR_FINISH` / `PLR_LOG` | Called from G-code, not by hand |

Tuning knobs on `PLR_PREPARE` / `PLR_RESUME`:

```
PLR_RESUME LIFT=5 RETRACT=2.0 PRIME=0.6 PURGE=0 DELAY=20
```

See [docs/USAGE.md](docs/USAGE.md).

## Safety

Recovery ends with the nozzle descending onto an existing part, at a Z
height derived from a value written to disk during a power failure. Read
the generated preamble before you print it, and watch the first move with
a hand near the stop button.

Do not touch the printer between the outage and the recovery. Homing,
jogging Z, or lifting the part invalidates the one assumption the whole
system rests on.

## Limits

- You lose up to one layer. The interrupted layer is re-printed from its
  start, so part of it gets a second pass. Slight over-extrusion beats a void.
- Z must not have moved. Leadscrew backdrive is usually small, not zero.
- The part warping off a cooling bed is the most common failure mode, and
  nothing here detects it.
- Only recovers what the slicer marked. Files sliced before you added
  `PLR_LOG` have no recovery points.

A UPS on both the printer and the host is the only thing that makes power
loss genuinely survivable. This is damage control.

## Disclaimer

This code was written by an AI. Please read
[DISCLAIMER.md](DISCLAIMER.md) before installing.

## License

MIT. See [LICENSE](LICENSE).
