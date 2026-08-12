# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] - 2026-08-13

First public release. Developed and tested on an Ender 3 V3 SE with a
Raspberry Pi Zero 2 W, Fluidd, and OrcaSlicer.

### Added
- Layer-granularity recovery point logging with `fsync` durability.
- `plr_build.py` — resume file generation with layer-marker snap-back,
  thumbnail/header preservation, `EXCLUDE_OBJECT_DEFINE` carry-over, and
  both relative and absolute extruder mode handling.
- Recovery preamble that never re-homes Z, using `SET_KINEMATIC_POSITION`
  against the logged toolhead Z.
- Correct bed mesh ordering: cleared while anchoring, reloaded after the
  toolhead returns to the real X/Y.
- Sequential heating — bed to target alone, then the hotend — to stop the
  nozzle drooling into the part during a long bed soak.
- Retract on reheat and configurable prime on resume; optional purge line.
- `PLR_RESUME` auto-start via Moonraker's unauthenticated unix socket,
  with a spoken countdown, an arm lock against duplicate invocations, and
  `PLR_CANCEL_START` to abort.
- `install.sh` / `uninstall.sh` with path substitution and a hard failure
  if any placeholder survives.
- Documentation: install, usage, internals, troubleshooting.
