#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_FILE="$ROOT_DIR/requirements.txt"
CACHE_ROOT="$ROOT_DIR/.venv-cache"
SELECT_PYTHON="$ROOT_DIR/scripts/select_gui_python.sh"

REQ_HASH="$(shasum -a 256 "$REQ_FILE" | awk '{print $1}')"
VENV_DIR="$CACHE_ROOT/$REQ_HASH"
PYTHON_BIN="$VENV_DIR/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  mkdir -p "$CACHE_ROOT"
  BASE_PYTHON="$($SELECT_PYTHON)"
  "$BASE_PYTHON" -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" -c 'import matplotlib, pandas, psycopg2, tkinterdnd2, xlsxwriter' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
  "$PYTHON_BIN" -m pip install -r "$REQ_FILE"
fi

if ! "$PYTHON_BIN" -c 'import tkinter' >/dev/null 2>&1; then
  cat >&2 <<EOF
The cached environment cannot load Tk: $VENV_DIR
Remove that generated cache directory and launch again to rebuild it.
EOF
  exit 1
fi

export PYTHONPATH="$ROOT_DIR/src"
exec "$PYTHON_BIN" "$ROOT_DIR/src/payroll_gui.py" "$@"
