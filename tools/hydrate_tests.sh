#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_DIR=$(python3 - <<'PY'
from pathlib import Path
import re
agents = Path("AGENTS.md").read_text(encoding="utf-8")
match = re.search(r"versions/(v\d+\.\d+\.\d+)", agents)
if not match:
    raise SystemExit("Could not determine active version from AGENTS.md")
print(match.group(1))
PY
)

TEST_DIR="$ROOT_DIR/versions/$VERSION_DIR/tests"

if [ ! -e "$TEST_DIR" ]; then
  echo "Tests path not found: $TEST_DIR" >&2
  exit 1
fi

REAL_TEST_DIR=$(python3 - <<PY
from pathlib import Path
path = Path("$TEST_DIR")
try:
    resolved = path.resolve()
except Exception:
    resolved = path
print(resolved)
PY
)

if command -v brctl >/dev/null 2>&1; then
  brctl download "$REAL_TEST_DIR" || true
fi

python3 - <<PY
from pathlib import Path
import sys
import time

test_dir = Path("$REAL_TEST_DIR")
files = sorted(test_dir.rglob("*.py"))

if not files:
    print(f"No test files found under {test_dir}")
    sys.exit(1)

for attempt in range(1, 4):
    failed = []
    for path in files:
        try:
            path.read_bytes()
        except Exception as exc:
            failed.append((path, exc))
    if not failed:
        print(f"Hydrated {len(files)} test files under {test_dir}")
        sys.exit(0)
    if attempt < 3:
        time.sleep(2)
    else:
        path, exc = failed[0]
        print(f"Failed to read {path}: {exc}")
        sys.exit(1)
PY
