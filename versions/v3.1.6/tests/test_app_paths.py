"""Tests for legacy and isolated application data paths."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import app_paths


def test_get_data_root_uses_legacy_paths_when_unset(monkeypatch):
    monkeypatch.delenv(app_paths.DATA_ROOT_ENV, raising=False)

    assert app_paths.get_data_root() is None


def test_get_data_root_treats_whitespace_as_unset(monkeypatch):
    monkeypatch.setenv(app_paths.DATA_ROOT_ENV, "   ")

    assert app_paths.get_data_root() is None


def test_get_data_root_accepts_absolute_path(monkeypatch, tmp_path):
    monkeypatch.setenv(app_paths.DATA_ROOT_ENV, str(tmp_path))

    assert app_paths.get_data_root() == tmp_path


def test_get_data_root_rejects_relative_path(monkeypatch):
    monkeypatch.setenv(app_paths.DATA_ROOT_ENV, "relative/qa-data")

    with pytest.raises(ValueError, match="must be an absolute path"):
        app_paths.get_data_root()


def test_legacy_module_paths_match_previous_locations():
    if app_paths.DATA_ROOT is not None:
        pytest.skip("process was launched with an isolated data root")

    expected_config_dir = Path.home() / ".payroll_processor"
    assert app_paths.CONFIG_DIR == expected_config_dir
    assert app_paths.CONFIG_PATH == expected_config_dir / "db_config.json"
    assert app_paths.PREFS_PATH == expected_config_dir / "ui_prefs.json"
    assert app_paths.DEFAULT_REPORT_DIR == Path.home() / "Documents" / "Payroll Processor Reports"


def test_isolated_root_applies_to_gui_cli_and_database_paths(tmp_path):
    src_dir = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env[app_paths.DATA_ROOT_ENV] = str(tmp_path)
    env["PYTHONPATH"] = str(src_dir)
    script = """
import json
import db_storage
import payroll_cli
import payroll_gui

print(json.dumps({
    "config_dir": str(db_storage.CONFIG_DIR),
    "config_path": str(db_storage.CONFIG_PATH),
    "prefs_path": str(db_storage.PREFS_PATH),
    "gui_reports": str(payroll_gui.DEFAULT_REPORT_DIR),
    "cli_reports": str(payroll_cli.DEFAULT_REPORT_DIR),
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    paths = json.loads(result.stdout.strip())

    assert paths == {
        "config_dir": str(tmp_path / "config"),
        "config_path": str(tmp_path / "config" / "db_config.json"),
        "prefs_path": str(tmp_path / "config" / "ui_prefs.json"),
        "gui_reports": str(tmp_path / "reports"),
        "cli_reports": str(tmp_path / "reports"),
    }
