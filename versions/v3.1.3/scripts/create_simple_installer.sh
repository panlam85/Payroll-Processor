#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEGACY_SCRIPT="$ROOT_DIR/../v3.1.2/scripts/create_simple_installer.sh"

if [ -x "$LEGACY_SCRIPT" ]; then
  exec "$LEGACY_SCRIPT" "$@"
fi

python3 "$ROOT_DIR/scripts/create_simple_app.py" "$@"
