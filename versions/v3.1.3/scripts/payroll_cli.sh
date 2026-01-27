#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

if [ -x "$PYTHON_BIN" ]; then
  PYTHON="$PYTHON_BIN"
else
  PYTHON="python3"
fi

export PYTHONPATH="$ROOT_DIR/src"
exec "$PYTHON" "$ROOT_DIR/src/payroll_cli.py" "$@"
