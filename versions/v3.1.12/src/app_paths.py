#!/usr/bin/env python3
"""Shared application paths with an opt-in isolated data root."""

from __future__ import annotations

import os
from pathlib import Path


DATA_ROOT_ENV = "PAYROLL_PROCESSOR_DATA_ROOT"


def get_data_root() -> Path | None:
    """Return the explicit application data root, if one was configured."""
    raw_root = os.environ.get(DATA_ROOT_ENV, "").strip()
    if not raw_root:
        return None

    data_root = Path(raw_root).expanduser()
    if not data_root.is_absolute():
        raise ValueError(f"{DATA_ROOT_ENV} must be an absolute path")
    return data_root


DATA_ROOT = get_data_root()

if DATA_ROOT is None:
    CONFIG_DIR = Path.home() / ".payroll_processor"
    DEFAULT_REPORT_DIR = Path.home() / "Documents" / "Payroll Processor Reports"
else:
    CONFIG_DIR = DATA_ROOT / "config"
    DEFAULT_REPORT_DIR = DATA_ROOT / "reports"

CONFIG_PATH = CONFIG_DIR / "db_config.json"
PREFS_PATH = CONFIG_DIR / "ui_prefs.json"
