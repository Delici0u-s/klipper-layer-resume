#!/usr/bin/env bash
#
# klipper-layer-resume installer.
#
# Copies config/ into <printer_data>/config/plr, substitutes the absolute
# paths Klipper needs, and verifies nothing was left unsubstituted.
#
# Usage:
#   ./install.sh                          # autodetect ~/printer_data
#   ./install.sh --data-path ~/printer_1_data
#   ./install.sh --python /usr/bin/python3.11
#   ./install.sh --dry-run

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_PATH="${PRINTER_DATA:-$HOME/printer_data}"
PYTHON_BIN=""
DRY_RUN=0

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
info() { printf '  %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --data-path) DATA_PATH="${2:?--data-path needs a value}"; shift 2 ;;
    --python)    PYTHON_BIN="${2:?--python needs a value}"; shift 2 ;;
    --dry-run)   DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

# ---------------------------------------------------------------- discovery --

DATA_PATH="${DATA_PATH%/}"
[ -d "$DATA_PATH" ] || die "printer data path not found: $DATA_PATH (try --data-path)"
[ -d "$DATA_PATH/config" ] || die "$DATA_PATH/config does not exist - is this a Klipper data dir?"

if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
[ -n "$PYTHON_BIN" ] || die "python3 not found (try --python /path/to/python3)"
[ -x "$PYTHON_BIN" ] || die "not executable: $PYTHON_BIN"

PLR_DIR="$DATA_PATH/config/plr"
STATE_DIR="$DATA_PATH/plr"

echo "klipper-layer-resume install"
info "data path : $DATA_PATH"
info "config    : $PLR_DIR"
info "state     : $STATE_DIR"
info "python    : $PYTHON_BIN"
echo

if [ "$DRY_RUN" -eq 1 ]; then
  echo "dry run, nothing written."
  exit 0
fi

# -------------------------------------------------------------------- checks --

if ! grep -rqs 'gcode_shell_command' "$DATA_PATH/config" \
   && [ ! -e "$HOME/klipper/klippy/extras/gcode_shell_command.py" ]; then
  echo "WARNING: gcode_shell_command does not appear to be installed."
  echo "         Install it with KIAUH (Advanced -> gcode_shell_command)"
  echo "         before restarting Klipper, or nothing here will run."
  echo
fi

# --------------------------------------------------------------------- copy --

mkdir -p "$PLR_DIR" "$STATE_DIR"

for f in plr.cfg plr_build.py plr_start.py plr_log.sh plr_clear.sh plr_check.sh plr_abort.sh; do
  [ -f "$SRC_DIR/config/$f" ] || die "missing source file: config/$f"
  if [ -f "$PLR_DIR/$f" ]; then
    cp -p "$PLR_DIR/$f" "$PLR_DIR/$f.bak"
  fi
  cp "$SRC_DIR/config/$f" "$PLR_DIR/$f"
done

# ------------------------------------------------------------- substitution --

for f in plr.cfg plr_build.py plr_start.py plr_log.sh plr_clear.sh plr_check.sh plr_abort.sh; do
  sed -i \
    -e "s|__PLR_DIR__|$PLR_DIR|g" \
    -e "s|__PLR_STATE_DIR__|$STATE_DIR|g" \
    -e "s|__PYTHON__|$PYTHON_BIN|g" \
    "$PLR_DIR/$f"
done

chmod +x "$PLR_DIR"/*.sh "$PLR_DIR"/*.py

# An unsubstituted placeholder produces "Error running command" with no output,
# which is miserable to debug. Fail loudly here instead.
if grep -rq '__[A-Z_]\+__' "$PLR_DIR"; then
  echo
  echo "FAILED: placeholders were left unsubstituted:"
  grep -rn '__[A-Z_]\+__' "$PLR_DIR" >&2
  exit 1
fi

# --------------------------------------------------------------- smoke test --

if ! "$PYTHON_BIN" -m py_compile "$PLR_DIR/plr_build.py" "$PLR_DIR/plr_start.py"; then
  die "python files failed to compile with $PYTHON_BIN"
fi
rm -rf "$PLR_DIR/__pycache__"

if ! sh "$PLR_DIR/plr_check.sh" >/dev/null; then
  die "plr_check.sh did not run cleanly"
fi

# ------------------------------------------------------------------- finish --

cat <<EOF

Installed.

Next steps (none of these are automatic):

1. printer.cfg - add:

       [include plr/plr.cfg]

2. macros.cfg - add PLR_BEGIN as the last line of PRINT_START,
   and PLR_FINISH as the first line of PRINT_END and CANCEL_PRINT.
   See examples/macros.cfg.snippet.

3. Slicer - add PLR_LOG to the layer change G-code.
   See examples/slicer_layer_change.txt.

4. FIRMWARE_RESTART, then run PLR_STATUS in the console.
   It should answer, not error.

Full instructions: docs/INSTALL.md
EOF
