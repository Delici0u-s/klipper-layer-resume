#!/bin/sh
# plr_abort.sh - cancel an armed auto-start before it fires.
set -eu
STATE_DIR="${PLR_STATE_DIR:-__PLR_STATE_DIR__}"
LOCK="$STATE_DIR/start.lock"

if [ ! -f "$LOCK" ]; then
  echo "PLR: nothing armed."
  exit 0
fi

pid=$(cut -d' ' -f1 "$LOCK")
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid" 2>/dev/null || true
  echo "PLR: auto-start cancelled (pid $pid)."
else
  echo "PLR: stale lock cleared."
fi
rm -f "$LOCK"
