#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
SELECT_PYTHON="$ROOT_DIR/scripts/select_gui_python.sh"

if [ ! -x "$PYTHON_BIN" ]; then
  BASE_PYTHON="$($SELECT_PYTHON)"
  "$BASE_PYTHON" -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" -c 'import matplotlib, pandas, psycopg2, tkinterdnd2, xlsxwriter' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"
fi

if ! "$PYTHON_BIN" -c 'import tkinter' >/dev/null 2>&1; then
  cat >&2 <<EOF
The development environment cannot load Tk: $VENV_DIR
Remove that generated environment and run again to rebuild it.
EOF
  exit 1
fi

export PYTHONPATH="$ROOT_DIR/src"
exec "$PYTHON_BIN" "$ROOT_DIR/src/payroll_gui.py" "$@"
