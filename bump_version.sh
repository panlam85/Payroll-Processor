#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 vX.Y.Z" >&2
  exit 1
fi

NEW_VERSION="$1"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACTIVE_VERSION=$(python3 - <<'PY'
from pathlib import Path
import re
agents = Path("AGENTS.md").read_text(encoding="utf-8")
match = re.search(r"versions/(v\d+\.\d+\.\d+)", agents)
if not match:
    raise SystemExit("Could not determine active version from AGENTS.md")
print(match.group(1))
PY
)

SRC_DIR="$ROOT_DIR/versions/$ACTIVE_VERSION"
DST_DIR="$ROOT_DIR/versions/$NEW_VERSION"

if [ ! -d "$SRC_DIR" ]; then
  echo "Active version directory not found: $SRC_DIR" >&2
  exit 1
fi

if [ -e "$DST_DIR" ]; then
  echo "Destination already exists: $DST_DIR" >&2
  exit 1
fi

mkdir -p "$DST_DIR"

# Copy through symlinks so every version directory is a self-contained real copy.
# Passing a symlinked source to ditto would recreate the link, leaving the new
# version pointing back at the old one.
copy_dir() {
  local name="$1"
  local src="$SRC_DIR/$name"
  if [ -e "$src" ]; then
    # cd -P resolves symlinks, so this is the real directory either way.
    if [ -d "$src" ]; then
      src="$(cd -P "$src" && pwd)"
    fi
    /usr/bin/ditto "$src" "$DST_DIR/$name"
  fi
}

copy_file() {
  local name="$1"
  if [ -f "$SRC_DIR/$name" ]; then
    /usr/bin/ditto "$SRC_DIR/$name" "$DST_DIR/$name"
  fi
}

for dir in assets docs resources scripts src tests tools; do
  copy_dir "$dir"
done

for file in requirements.txt requirements-dev.txt pytest.ini .coveragerc; do
  copy_file "$file"
done

python3 - <<PY
from pathlib import Path
import re

root = Path("$ROOT_DIR")
old = "$ACTIVE_VERSION"
new = "$NEW_VERSION"

# Update AGENTS.md
agents = root / "AGENTS.md"
agents_text = agents.read_text(encoding="utf-8")
agents_text = agents_text.replace(f"versions/{old}", f"versions/{new}")
agents.write_text(agents_text, encoding="utf-8")

# Update root wrappers
wrappers = ["run_dev.sh", "launch_gui.sh", "create_simple_installer.sh", "payroll_cli.sh"]
for name in wrappers:
    path = root / name
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    text = text.replace(f"versions/{old}", f"versions/{new}")
    path.write_text(text, encoding="utf-8")

# Update create_simple_app.py
app_builder = root / "create_simple_app.py"
if app_builder.exists():
    text = app_builder.read_text(encoding="utf-8")
    text = text.replace(f"versions/{old}", f"versions/{new}")
    app_builder.write_text(text, encoding="utf-8")

# Update root pytest.ini
pytest_ini = root / "pytest.ini"
if pytest_ini.exists():
    text = pytest_ini.read_text(encoding="utf-8")
    text = text.replace(f"versions/{old}/tests", f"versions/{new}/tests")
    text = text.replace(f"versions/{old}/tests_cli", f"versions/{new}/tests_cli")
    pytest_ini.write_text(text, encoding="utf-8")

# Update root .coveragerc so the coverage gate follows the active version.
coveragerc = root / ".coveragerc"
if coveragerc.exists():
    text = coveragerc.read_text(encoding="utf-8")
    text = text.replace(f"versions/{old}/src", f"versions/{new}/src")
    coveragerc.write_text(text, encoding="utf-8")
PY

chmod +x "$DST_DIR/scripts"/*.sh || true
chmod +x "$ROOT_DIR"/*.sh || true

echo "Created $NEW_VERSION from $ACTIVE_VERSION"
