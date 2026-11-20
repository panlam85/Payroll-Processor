"""Performance architecture regressions introduced in v3.1.7."""

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import db_storage
from payroll_gui import PayrollProcessorGUI


def test_gui_import_defers_heavy_feature_stacks():
    src_dir = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_dir)
    code = (
        "import sys; import payroll_gui; "
        "heavy={'pandas','matplotlib','process_payroll','create_employee_reports'}; "
        "assert not (heavy & set(sys.modules)), heavy & set(sys.modules)"
    )

    subprocess.run([sys.executable, "-c", code], env=env, check=True)


def test_lazy_view_builder_runs_only_once():
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    builder = Mock()
    gui._view_builders = {"Dashboard": builder}
    gui._built_views = {"Processing"}
    gui._view_building = set()

    gui._ensure_view_built("Dashboard")
    gui._ensure_view_built("Dashboard")

    builder.assert_called_once_with()
    assert gui._built_views == {"Processing", "Dashboard"}


def test_filter_refresh_only_updates_active_view():
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    gui._render_filter_chips = Mock()
    gui._refresh_active_view = Mock()
    gui.grid_search_job = object()
    gui.global_filter_status = Mock()
    gui.global_filter_status.get.return_value = "Searching…"

    gui._refresh_all_views()

    gui._render_filter_chips.assert_called_once_with()
    gui._refresh_active_view.assert_called_once_with()
    assert gui.grid_search_job is None
    gui.global_filter_status.set.assert_called_once_with("")


def test_database_connections_have_a_short_default_timeout(monkeypatch):
    connect = Mock(return_value=object())
    monkeypatch.setattr(db_storage, "psycopg2", Mock(connect=connect))
    config = {
        "host": "localhost",
        "port": 5432,
        "database": "payroll",
        "user": "operator",
        "password": "secret",
        "sslmode": "prefer",
    }

    db_storage.get_connection(config)

    assert connect.call_args.kwargs["connect_timeout"] == 3
