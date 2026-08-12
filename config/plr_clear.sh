#!/bin/sh
# plr_clear.sh - drop the recovery point (clean print start / end).
set -eu
STATE_DIR="${PLR_STATE_DIR:-__PLR_STATE_DIR__}"
rm -f "$STATE_DIR/state" "$STATE_DIR/.state.tmp"
sync "$STATE_DIR" 2>/dev/null || true
