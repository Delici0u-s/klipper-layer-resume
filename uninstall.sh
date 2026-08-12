#!/usr/bin/env bash
#
# klipper-layer-resume uninstaller. Removes the config directory and state.
# Does NOT edit printer.cfg, macros.cfg, or your slicer - see the notes at
# the end for what to take out by hand.
#
# Usage: ./uninstall.sh [--data-path ~/printer_data] [--keep-state]

set -euo pipefail

DATA_PATH="${PRINTER_DATA:-$HOME/printer_data}"
KEEP_STATE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --data-path) DATA_PATH="${2:?}"; shift 2 ;;
    --keep-state) KEEP_STATE=1; shift ;;
    -h|--help) sed -n '3,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

DATA_PATH="${DATA_PATH%/}"
PLR_DIR="$DATA_PATH/config/plr"
STATE_DIR="$DATA_PATH/plr"

if [ -d "$PLR_DIR" ]; then
  rm -rf "$PLR_DIR"
  echo "removed $PLR_DIR"
else
  echo "not found: $PLR_DIR"
fi

if [ "$KEEP_STATE" -eq 0 ] && [ -d "$STATE_DIR" ]; then
  rm -rf "$STATE_DIR"
  echo "removed $STATE_DIR"
fi

cat <<'EOF'

Still to remove by hand:

  printer.cfg   [include plr/plr.cfg]
  macros.cfg    PLR_BEGIN in PRINT_START
                PLR_FINISH in PRINT_END and CANCEL_PRINT
  slicer        PLR_LOG in the layer change G-code

Leaving PLR_LOG in the slicer while the config is gone will make every
sliced file fail on its first layer change with "Unknown command".

Then run FIRMWARE_RESTART.
EOF
