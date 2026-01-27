#!/usr/bin/env python3
"""Wrapper that delegates to the v3.1.3 app bundle builder."""

from pathlib import Path
import runpy
import sys

VERSION_SCRIPT = Path(__file__).resolve().parent / "versions" / "v3.1.3" / "scripts" / "create_simple_app.py"

if not VERSION_SCRIPT.exists():
    sys.stderr.write(f"Unable to find v3.1.3 builder at {VERSION_SCRIPT}\n")
    sys.exit(1)

globals_dict = runpy.run_path(str(VERSION_SCRIPT))
builder = globals_dict.get("create_simple_app")
if callable(builder):
    builder()
else:
    sys.stderr.write(f"create_simple_app() not found in {VERSION_SCRIPT}\n")
    sys.exit(1)
