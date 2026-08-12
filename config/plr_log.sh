#!/bin/sh
# plr_log.sh - persist one recovery point, durably.
# Called once per layer change from the PLR_LOG macro.
#
# Arg order MUST match plr.cfg:
#   1 file_path  2 file_position  3 x  4 y  5 z_gcode  6 z_toolhead
#   7 gcode_offset_z  8 fan(0..1)  9 speed_factor 10 extrude_factor
#  11 extruder_target 12 bed_target 13 mesh_profile

set -eu

STATE_DIR="${PLR_STATE_DIR:-__PLR_STATE_DIR__}"
STATE="$STATE_DIR/state"
TMP="$STATE_DIR/.state.tmp"

[ "$#" -eq 13 ] || { echo "plr_log: expected 13 args, got $#" >&2; exit 1; }

mkdir -p "$STATE_DIR"

{
  printf 'file=%s\n'            "$1"
  printf 'offset=%s\n'          "$2"
  printf 'x=%s\n'               "$3"
  printf 'y=%s\n'               "$4"
  printf 'z_gcode=%s\n'         "$5"
  printf 'z_toolhead=%s\n'      "$6"
  printf 'offset_z=%s\n'        "$7"
  printf 'fan=%s\n'             "$8"
  printf 'speed_factor=%s\n'    "$9"
  printf 'extrude_factor=%s\n'  "${10}"
  printf 'extruder=%s\n'        "${11}"
  printf 'bed=%s\n'             "${12}"
  printf 'mesh=%s\n'            "${13}"
} > "$TMP"

# Durability is the whole point: an un-synced write sits in the page
# cache and dies with the power. Costs ~50-150 ms on a Pi Zero 2 W SD
# card, once per layer. Set PLR_NOSYNC=1 to skip if that stutters.
if [ "${PLR_NOSYNC:-0}" != "1" ]; then
  sync "$TMP" 2>/dev/null || sync
fi

mv -f "$TMP" "$STATE"

if [ "${PLR_NOSYNC:-0}" != "1" ]; then
  sync "$STATE_DIR" 2>/dev/null || sync
fi
