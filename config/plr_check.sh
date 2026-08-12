#!/bin/sh
# plr_check.sh - report whether an interrupted print is recoverable.
set -eu
STATE_DIR="${PLR_STATE_DIR:-__PLR_STATE_DIR__}"
STATE="$STATE_DIR/state"

if [ ! -f "$STATE" ]; then
  echo "PLR: no recovery point stored (last print ended cleanly)."
  exit 0
fi

f=$(sed -n 's/^file=//p'    "$STATE")
z=$(sed -n 's/^z_gcode=//p' "$STATE")
o=$(sed -n 's/^offset=//p'  "$STATE")

echo "PLR: INTERRUPTED PRINT DETECTED"
echo "PLR:   file   = $(basename "$f")"
echo "PLR:   z      = $z mm"
echo "PLR:   offset = $o bytes"
echo "PLR: run PLR_PREPARE to build the resume file, or PLR_DISCARD to forget it."
