import os
import subprocess
import sys
from pathlib import Path

import payroll_gui


VERSION_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = VERSION_DIR / "scripts"


def test_select_gui_python_accepts_valid_override():
    env = os.environ.copy()
    env["PAYROLL_PROCESSOR_PYTHON"] = sys.executable

    result = subprocess.run(
        [str(SCRIPTS_DIR / "select_gui_python.sh")],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == sys.executable


def test_select_gui_python_rejects_invalid_override():
    env = os.environ.copy()
    env["PAYROLL_PROCESSOR_PYTHON"] = "/usr/bin/false"

    result = subprocess.run(
        [str(SCRIPTS_DIR / "select_gui_python.sh")],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "not a usable Tk Python" in result.stderr


def test_installer_version_defaults_to_its_version_directory():
    installer = (SCRIPTS_DIR / "create_simple_installer.sh").read_text(encoding="utf-8")

    assert 'DEFAULT_APP_VERSION="$(basename "$VERSION_DIR")"' in installer
    assert 'APP_VERSION="${APP_VERSION:-$DEFAULT_APP_VERSION}"' in installer
    assert 'APP_VERSION="${APP_VERSION:-3.1.3}"' not in installer


def test_bundled_gui_version_comes_from_resource_marker(tmp_path, monkeypatch):
    bundled_gui = tmp_path / "payroll_gui.py"
    bundled_gui.write_text("# synthetic bundle layout\n", encoding="utf-8")
    (tmp_path / "APP_VERSION").write_text("9.8.7\n", encoding="utf-8")
    monkeypatch.setattr(payroll_gui, "__file__", str(bundled_gui))

    assert payroll_gui._detect_app_version() == "9.8.7"


def test_bundle_builder_writes_version_marker_and_requires_tk():
    builder = (SCRIPTS_DIR / "create_simple_app.py").read_text(encoding="utf-8")
    expected_version = VERSION_DIR.name.removeprefix("v")

    assert '(resources_dir / "APP_VERSION").write_text' in builder
    assert '[python_bin, "-c", "import tkinter"]' in builder
    assert f'def _detect_app_version(default: str = "{expected_version}")' in builder


def test_installer_always_rebuilds_the_selected_version():
    installer = (SCRIPTS_DIR / "create_simple_installer.sh").read_text(encoding="utf-8")

    assert "Building a fresh app bundle" in installer
    assert 'python3 "$VERSION_DIR/scripts/create_simple_app.py"' in installer


def test_runtime_launchers_use_the_tk_aware_selector():
    for name in ("launch_gui.sh", "run_dev.sh", "payroll_cli.sh"):
        launcher = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
        assert "select_gui_python.sh" in launcher
        assert '"$BASE_PYTHON" -m venv' in launcher


def test_cli_and_gui_share_the_requirement_hashed_cache():
    gui_launcher = (SCRIPTS_DIR / "launch_gui.sh").read_text(encoding="utf-8")
    cli_launcher = (SCRIPTS_DIR / "payroll_cli.sh").read_text(encoding="utf-8")

    for launcher in (gui_launcher, cli_launcher):
        assert 'CACHE_ROOT="$ROOT_DIR/.venv-cache"' in launcher
        assert 'REQ_HASH="$(shasum -a 256 "$REQ_FILE"' in launcher


def test_runtime_launchers_retry_an_incomplete_environment():
    for name in ("launch_gui.sh", "run_dev.sh", "payroll_cli.sh"):
        launcher = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
        assert "import matplotlib, pandas, psycopg2, tkinterdnd2, xlsxwriter" in launcher
        assert launcher.index("if ! \"$PYTHON_BIN\" -c") < launcher.index('pip install -r')
