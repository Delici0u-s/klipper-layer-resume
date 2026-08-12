# Installation

## 0. Prerequisites

- Klipper with a `[virtual_sdcard]` section (normally in `fluidd.cfg` or
  `mainsail.cfg`)
- `gcode_shell_command` — install with KIAUH: `./kiauh/kiauh.sh` →
  **Advanced** → **gcode_shell_command**
- `python3` on the host
- Moonraker, if you want `PLR_RESUME` to start the print for you

Check what you have:

```bash
command -v python3
grep -rn "virtual_sdcard" ~/printer_data/config/
ls ~/klipper/klippy/extras/gcode_shell_command.py
```

## 1. Run the installer

```bash
cd ~
git clone https://github.com/Delici0u-s/klipper-layer-resume.git
cd klipper-layer-resume
./install.sh
```

Options:

```bash
./install.sh --data-path ~/printer_1_data    # non-default data dir
./install.sh --python /usr/bin/python3.11    # specific interpreter
./install.sh --dry-run                       # show paths, write nothing
```

The installer copies `config/` to `<data>/config/plr/`, substitutes
absolute paths, creates `<data>/plr/` for state, sets the executable bits,
and refuses to finish if any path placeholder was left unsubstituted.

Existing files are backed up to `*.bak` before being overwritten, so
re-running it to upgrade is safe.

## 2. printer.cfg

```ini
[include plr/plr.cfg]
```

`plr.cfg` brings its own `[force_move] enable_force_move: True`, which is
what makes `SET_KINEMATIC_POSITION` available. If you already have a
`[force_move]` section somewhere, delete the one at the top of `plr.cfg`
and set `enable_force_move: True` in yours — duplicate sections are a hard
config error.

## 3. macros.cfg

Add `PLR_BEGIN` as the **last** line of `PRINT_START`:

```ini
[gcode_macro PRINT_START]
gcode:
  # ... your existing start sequence ...
  PLR_BEGIN
```

Add `PLR_FINISH` as the **first** line of `PRINT_END`:

```ini
[gcode_macro PRINT_END]
gcode:
  PLR_FINISH
  # ... your existing end sequence ...
```

And anywhere in `CANCEL_PRINT`, so a deliberate cancel doesn't leave a
stale recovery point:

```ini
[gcode_macro CANCEL_PRINT]
gcode:
  TURN_OFF_HEATERS
  PLR_FINISH
  # ...
```

Leave `PAUSE` and `RESUME` alone. A pause is not a power loss, and the
recovery point stays valid across one.

See [`examples/macros.cfg.snippet`](../examples/macros.cfg.snippet).

## 4. Slicer

Add `PLR_LOG` on its own line to the layer change G-code, keeping whatever
is already there.

- **OrcaSlicer / Bambu Studio**: Printer Settings → Machine G-code →
  *Layer change G-code*
- **PrusaSlicer / SuperSlicer**: Printer Settings → Custom G-code →
  *After layer change G-code*
- **Cura**: Extensions → Post Processing → Modify G-Code → *Insert at
  layer change*, position **After**

See [`examples/slicer_layer_change.txt`](../examples/slicer_layer_change.txt).

Re-slice anything you want covered. Files sliced before this change have
no recovery points in them.

## 5. Verify

```
FIRMWARE_RESTART
```

Then in the console:

```
PLR_STATUS
```

Expected: `PLR: no recovery point stored (last print ended cleanly).`

If you get `Error running command {plr_check}` instead, see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md). That one command exercises the
same spawn path as the other four, so if it works, they all work.

About ten seconds after every Klipper start, a `[delayed_gcode]` prints
the same check unprompted. That is how you find out an interrupted print
is waiting for you.

## 6. Dry run before you rely on it

Do this once, on a part you don't care about.

1. Slice and start something small and tall — a 20 mm cube is fine.
2. Around layer 5, run `PLR_STATUS`. You should see a real filename, a Z
   matching the current layer, and a non-zero byte offset. If Z reads 0,
   the slicer hook is not firing — fix that before continuing.
3. Hit **Emergency Stop**, then `FIRMWARE_RESTART`.
4. Run `PLR_PREPARE`.
5. Open the generated `.plr.gcode` in your web UI's editor and read the
   preamble. Check the Z values against the layer it stopped on.
6. Print it, watching the first Z descent with a hand near stop.

Then do it for real — flip the printer's power switch mid-print. That is
the only test that proves the `fsync` in `plr_log.sh` is actually reaching
your SD card. Emergency Stop leaves the host running and proves nothing
about durability.

## Upgrading

```bash
cd ~/klipper-layer-resume && git pull && ./install.sh
```

Then `FIRMWARE_RESTART`. Your `printer.cfg`, `macros.cfg`, and slicer
settings are untouched.

## Uninstalling

```bash
./uninstall.sh
```

It removes the config and state directories and tells you what to take out
of `printer.cfg`, `macros.cfg`, and the slicer by hand. Remove `PLR_LOG`
from the slicer, or every subsequently sliced file will fail on its first
layer change with `Unknown command`.
