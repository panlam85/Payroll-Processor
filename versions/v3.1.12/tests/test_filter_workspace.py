"""Filter choices must agree with the date bounds sent to storage."""

import datetime
from unittest.mock import Mock

import pytest

from payroll_gui import PayrollProcessorGUI


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.fixture
def gui():
    app = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    for name, value in dict(start_year="All", end_year="All", start_month="01", end_month="01",
                            doc_type="All", search="", window_label="All months").items():
        setattr(app, f"global_{name}_var", Variable(value))
    app.search_clauses = []
    app._save_ui_prefs = Mock()
    app._refresh_all_views = Mock()
    return app


@pytest.mark.parametrize("endpoint", ["start", "end"])
def test_saved_half_range_is_applied_instead_of_silently_showing_everything(gui, endpoint):
    getattr(gui, f"global_{endpoint}_year_var").set("2023")
    getattr(gui, f"global_{endpoint}_month_var").set("07")
    gui._update_window_label()
    assert gui._get_global_filters()[:2] == (datetime.date(2023, 7, 1), datetime.date(2023, 7, 31))
    assert gui.global_window_label_var.get() == "Jul 2023"
    assert len(gui._active_filter_chips()) == 1


@pytest.mark.parametrize("preset,today,expected", [
    ("month", datetime.date(2024, 2, 20), (datetime.date(2024, 2, 1), datetime.date(2024, 2, 29))),
    ("previous", datetime.date(2026, 1, 6), (datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))),
    ("year", datetime.date(2026, 10, 6), (datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))),
    ("all", datetime.date(2026, 10, 6), (None, None)),
])
def test_quick_period_uses_complete_calendar_months_and_preserves_other_filters(gui, preset, today, expected):
    gui.global_doc_type_var.set("salary")
    gui.global_search_var.set("Employee")
    gui._set_filter_period(preset, today)
    start, end, doc, search = gui._get_global_filters()
    assert (start, end) == expected
    assert doc == "salary"
    assert search == [{"op": "AND", "term": "Employee"}]
    gui._refresh_all_views.assert_called_once_with()


@pytest.mark.parametrize("endpoint", ["start", "end"])
def test_selecting_a_year_or_all_cannot_leave_half_a_range(gui, endpoint):
    getattr(gui, f"global_{endpoint}_year_var").set("2026")
    gui._on_filter_year_selected(endpoint)
    assert gui._get_global_filters()[:2] == (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    getattr(gui, f"global_{endpoint}_year_var").set("All")
    gui._on_filter_year_selected(endpoint)
    assert gui._get_global_filters()[:2] == (None, None)
    assert gui._active_filter_chips() == []


def test_earlier_end_month_moves_start_and_uses_numeric_storage_value(gui):
    gui._set_filter_period("month", datetime.date(2026, 10, 6))
    gui.filter_end_month_label = Variable("June")
    gui._on_filter_month_selected("end")
    assert gui._get_global_filters()[:2] == (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    assert gui.global_end_month_var.get() == "06"


def test_readable_document_label_preserves_database_filter(gui):
    gui.filter_document_label = Variable("Unused leave compensation")
    gui._sync_filter_controls = Mock()
    gui._on_filter_document_selected()
    assert gui._get_global_filters()[2] == "unused_leave_compensation"
    assert gui._active_filter_chips()[0][0] == "Document: Unused leave compensation"


def test_collapsing_filters_preserves_query_and_summary(gui):
    gui._set_filter_period("month", datetime.date(2026, 6, 5))
    before = gui._get_global_filters()
    gui.filters_expanded = True
    gui.filter_panel = Mock()
    gui.filter_summary_var = Variable("")
    gui.filter_toggle_btn = Mock()
    gui.reset_filters_btn = Mock()
    gui.add_search_clause_btn = Mock()
    gui._filter_slide_job = None
    gui._filter_slide_progress = 1.0
    gui._set_filter_panel_open(False, animate=False)
    assert gui._get_global_filters() == before
    assert gui.filter_summary_var.get() == "Jun 2026 · All documents"
    assert not gui.filters_expanded
    gui.filter_panel.place_forget.assert_called_once_with()


def test_available_years_does_not_silently_replace_empty_selected_period(gui):
    gui._set_filter_period("year", datetime.date(2026, 10, 6))
    gui.db_config = {"enabled": True}
    gui.global_start_year_combo = {}
    gui.global_end_year_combo = {}
    gui._run_async = lambda _name, _work, apply, _failed: apply([2023])
    gui._refresh_global_filters()
    assert gui.global_start_year_var.get() == "2026"
    assert gui._get_global_filters()[:2] == (datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    assert "2026" in gui.global_start_year_combo["values"]


def test_reversing_slide_cancels_old_animation_and_finishes_closed(gui, monkeypatch):
    from types import SimpleNamespace
    import filter_workspace

    now = [0.0]
    monkeypatch.setattr(filter_workspace.time, "monotonic", lambda: now[0])
    pending = {}
    cancelled = []

    def after(_delay, callback):
        pending["slide"] = callback
        return "slide"

    def cancel(job):
        cancelled.append(job)
        pending.pop(job)

    gui.root = SimpleNamespace(after=after, after_cancel=cancel)
    gui.filter_panel = Mock()
    gui.close_filters_btn = Mock()
    gui.filter_toggle_btn = Mock()
    gui._position_filter_drawer = Mock()
    gui._filter_slide_job = None
    gui._filter_slide_progress = 0.0
    gui._set_filter_panel_open(True)
    now[0] = 0.09
    pending.pop("slide")()
    assert 0 < gui._filter_slide_progress < 1
    gui._set_filter_panel_open(False)
    assert cancelled == ["slide"]
    now[0] = 0.30
    pending.pop("slide")()
    assert not pending
    assert gui._filter_slide_progress == 0
    assert not gui.filters_expanded
    gui.filter_panel.place_forget.assert_called_once_with()


def test_outside_click_dismisses_but_drawer_controls_do_not(gui):
    from types import SimpleNamespace

    gui.filters_expanded = True
    gui.filter_panel = SimpleNamespace(master=None)
    gui.global_filter_bar = SimpleNamespace(master=None)
    gui._set_filter_panel_open = Mock()
    field = SimpleNamespace(master=gui.filter_panel)
    gui._dismiss_filter_outside(SimpleNamespace(widget=field))
    gui._set_filter_panel_open.assert_not_called()
    gui._dismiss_filter_outside(SimpleNamespace(widget=SimpleNamespace(master=None)))
    gui._set_filter_panel_open.assert_called_once_with(False, restore_focus=False)


def test_escape_dismisses_open_drawer_only(gui):
    gui._close_filter_panel = Mock()
    gui.filters_expanded = False
    assert gui._dismiss_filter_escape() is None
    gui._close_filter_panel.assert_not_called()
    gui.filters_expanded = True
    assert gui._dismiss_filter_escape() == "break"
    gui._close_filter_panel.assert_called_once_with()
