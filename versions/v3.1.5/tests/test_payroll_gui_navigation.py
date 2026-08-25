"""Regression tests for database-off navigation and notice behavior."""

import inspect
from unittest.mock import Mock

import matplotlib

matplotlib.use("Agg")

from payroll_gui import PayrollProcessorGUI


def _navigation_gui():
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    gui.dashboard_tab = "dashboard"
    gui.analytics_tab = "analytics"
    gui.analytics_grid_view_tab = "analytics-grid-view"
    gui.analytics_grid_tab = "data-grid"
    gui.analytics_detail_tab = "employee-detail"
    gui.analytics_monthly_tab = "monthly-summary"
    gui.insurance_tab = "insurance"
    gui.employees_tab = "employees"
    gui.db_tab = "database"
    gui.settings_tab = "settings"
    gui.analytics_grid_notebook = Mock()
    gui.refresh_data_grid = Mock()
    gui.refresh_monthly_employee_summary = Mock()
    return gui


def test_outer_analytics_refresh_only_refreshes_selected_data_grid_tab():
    gui = _navigation_gui()
    gui.analytics_grid_notebook.select.return_value = "data-grid"

    gui._refresh_active_view("analytics-grid-view")

    gui.refresh_data_grid.assert_called_once_with()
    gui.refresh_monthly_employee_summary.assert_not_called()


def test_outer_analytics_refresh_only_refreshes_selected_monthly_tab():
    gui = _navigation_gui()
    gui.analytics_grid_notebook.select.return_value = "monthly-summary"

    gui._refresh_active_view("analytics-grid-view")

    gui.refresh_monthly_employee_summary.assert_called_once_with()
    gui.refresh_data_grid.assert_not_called()


def test_analytics_header_has_one_status_label():
    source = inspect.getsource(PayrollProcessorGUI.create_analytics_tab)

    assert source.count("textvariable=self.analytics_status_var") == 1


def test_employees_disabled_state_shows_database_notice():
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    gui.db_config = {"enabled": False}
    gui.employees_tab = "employees"
    gui._database_notice = Mock()

    gui.refresh_employees_tab()

    gui._database_notice.assert_called_once_with(
        "employees",
        "Employee profiles are built from stored payroll entries. Turn storage on to see them.",
    )


def test_database_notice_uses_next_free_grid_row():
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    container = Mock()
    container.grid_size.return_value = (1, 2)
    panel = Mock()

    placed = gui._place_database_notice(panel, container)

    assert placed is True
    panel.grid.assert_called_once()
    grid_options = panel.grid.call_args.kwargs
    assert grid_options["row"] == 2
    assert grid_options["columnspan"] == 1
