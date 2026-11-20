#!/usr/bin/env bash
set -euo pipefail

# The GUI needs a Python that can create virtual environments and includes Tk.
# Homebrew's unversioned python3 can exist without _tkinter, so do not assume
# that the first interpreter on PATH is suitable.
is_gui_python() {
  local candidate="$1"
  [ -x "$candidate" ] || return 1
  "$candidate" -c 'import tkinter, venv' >/dev/null 2>&1
}

if [ -n "${PAYROLL_PROCESSOR_PYTHON:-}" ]; then
  if is_gui_python "$PAYROLL_PROCESSOR_PYTHON"; then
    printf '%s\n' "$PAYROLL_PROCESSOR_PYTHON"
    exit 0
  fi
  printf 'PAYROLL_PROCESSOR_PYTHON is not a usable Tk Python: %s\n' \
    "$PAYROLL_PROCESSOR_PYTHON" >&2
  exit 1
fi

for candidate in \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.10/bin/python3
do
  if is_gui_python "$candidate"; then
    printf '%s\n' "$candidate"
    exit 0
  fi
done

path_python="$(command -v python3 || true)"
if [ -n "$path_python" ] && is_gui_python "$path_python"; then
  printf '%s\n' "$path_python"
  exit 0
fi

cat >&2 <<'EOF'
No usable Python with Tk support was found.
Install Python from python.org, or set PAYROLL_PROCESSOR_PYTHON to a Python 3
executable for which `import tkinter, venv` succeeds.
EOF
exit 1
