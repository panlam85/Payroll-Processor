import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import db_storage
from dashboard_alerts import ALERT_COLUMNS, DashboardAlert, alert_key, anomaly_alerts, jump_alert
from payroll_gui import PayrollProcessorGUI
from test_db_storage_full import FakeConnection, FakeCursor


def test_alert_identity_survives_renames_filters_and_rounding_but_not_new_events():
    row = ("Same Name", "01", "salary", datetime.date(2026, 8, 1),
           Decimal("100"), Decimal("200"), Decimal("100"), Decimal("100"))
    original = jump_alert(row)
    renamed = jump_alert(("Renamed", *row[1:4], 120, 200, 80, 66.666))
    assert renamed.key == original.key
    assert jump_alert((row[0], "001", *row[2:])).key != original.key
    assert jump_alert((*row[:3], datetime.date(2026, 9, 1), *row[4:])).key != original.key
    assert jump_alert((*row[:2], "bonus", *row[3:])).key != original.key
    rows = [("High Net Pay", "Same Name", row[3], "salary", 200, 50, "entry-1"),
            ("High Net Pay", "Same Name", row[3], "salary", 200, 50, "entry-2"),
            ("High Insurance", "Same Name", row[3], "salary", 200, 50, "entry-1")]
    alerts = anomaly_alerts((*ALERT_COLUMNS, "entry_id"), rows)
    assert len({a.key for a in alerts}) == 3
    assert alerts[0].values == rows[0][:6]


def test_acknowledgements_are_committed_atomically_and_restore_only_selected(monkeypatch):
    cursor = FakeCursor(rowcount_sequence=[0, 2])
    conn = FakeConnection(cursor)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: conn)
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    assert db_storage.set_alerts_acknowledged({}, ["key-b", "key-a", "key-b"]) == 2
    assert conn.committed
    assert "CREATE TABLE IF NOT EXISTS" in cursor.queries[0]
    assert "ON CONFLICT (alert_key) DO NOTHING" in cursor.queries[1]
    assert cursor.params[1] == (["key-a", "key-b"],)
    conn.committed = False
    db_storage.set_alerts_acknowledged({}, ["key-a"], False)
    assert conn.committed
    assert "DELETE FROM alert_acknowledgements WHERE alert_key = ANY" in cursor.queries[-1]
    assert cursor.params[-1] == (["key-a"],)


def test_acknowledgements_reload_from_database_and_old_databases_start_empty(monkeypatch):
    cursor = FakeCursor(fetchone_sequence=[("alert_acknowledgements",)],
                        fetchall_sequence=[[('key-a',), ('key-b',)]])
    conn = FakeConnection(cursor)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: conn)
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    assert db_storage.fetch_acknowledged_alerts({}) == {"key-a", "key-b"}
    cursor.fetchone_sequence = [(None,)]
    assert db_storage.fetch_acknowledged_alerts({}) == set()
    assert not conn.committed  # Loading is read-only.
    db_storage.ensure_alert_acknowledgements_table({})
    assert conn.committed


def test_empty_acknowledgement_does_not_connect(monkeypatch):
    connect = Mock(side_effect=AssertionError("Nothing selected"))
    monkeypatch.setattr(db_storage, "get_connection", connect)
    assert db_storage.set_alerts_acknowledged({}, []) == 0
    connect.assert_not_called()


@pytest.mark.parametrize("query", ["anomaly", "jump"])
def test_dashboard_fetches_beyond_old_limit_so_reviewed_alerts_do_not_hide_new_ones(monkeypatch, query):
    cursor = FakeCursor()
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    if query == "anomaly":
        db_storage.fetch_anomaly_entries({}, limit=None, include_identity=True)
        assert "pe.id AS entry_id" in cursor.queries[0]
    else:
        db_storage.fetch_entry_jumps({}, limit=None)
    assert "LIMIT" not in cursor.queries[0]
    assert cursor.queries[0].count("%s") == len(cursor.params[0])


class Variable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Tree:
    def __init__(self):
        self.rows = {}
        self.selected = ()

    def get_children(self):
        return tuple(self.rows)

    def insert(self, _parent, _position, iid, values, tags):
        self.rows[iid] = (values, tags)

    def selection(self):
        return self.selected

    def heading(self, *_args, **_kwargs):
        pass

    column = heading
    tag_configure = heading


@pytest.fixture
def gui():
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    gui.db_config = {"enabled": True, "database": "payroll"}
    gui._async_tokens = {"dashboard": 1}
    gui._alert_write_pending = False
    gui._acknowledged_alerts = set()
    gui.dashboard_anomaly_tree = Tree()
    gui.dashboard_acknowledge_btn = Mock()
    gui.dashboard_restore_alert_btn = Mock()
    gui.dashboard_show_acknowledged_var = Variable(False)
    gui.dashboard_alert_status_var = Variable()
    gui.theme = SimpleNamespace(muted="#777777")
    gui._reset_treeview = lambda tree, columns: tree.rows.clear()
    gui.refresh_dashboard = Mock()
    gui.show_message = Mock()
    gui._dashboard_alerts = [DashboardAlert(alert_key("entry", str(i)),
                             ("High Net Pay", "Employee", "2026-08-01", "salary", 200, 20))
                             for i in range(30)]
    return gui


def test_acknowledged_alerts_stay_hidden_and_later_candidates_stay_visible(gui):
    gui._acknowledged_alerts = {alert.key for alert in gui._dashboard_alerts[:25]}
    gui._render_dashboard_alerts()
    assert set(gui.dashboard_anomaly_tree.rows) == {a.key for a in gui._dashboard_alerts[25:]}
    gui.dashboard_show_acknowledged_var.set(True)
    gui._render_dashboard_alerts()
    assert len(gui.dashboard_anomaly_tree.rows) == 30
    hidden_row = gui.dashboard_anomaly_tree.rows[gui._dashboard_alerts[0].key]
    assert hidden_row[0][0].startswith("Acknowledged")
    assert hidden_row[1] == ("acknowledged",)
    gui.dashboard_show_acknowledged_var.set(False)
    gui._render_dashboard_alerts()
    assert len(gui.dashboard_anomaly_tree.rows) == 5


def test_acknowledgement_hides_selected_only_after_successful_save(gui, monkeypatch):
    selected = gui._dashboard_alerts[0].key
    gui._render_dashboard_alerts()
    gui.dashboard_anomaly_tree.selected = (selected,)
    pending = {}
    gui._run_async = lambda name, work, done, on_error: pending.update(work=work, done=done, error=on_error)
    save = Mock(return_value=1)
    monkeypatch.setattr(db_storage, "set_alerts_acknowledged", save)
    gui._set_selected_alerts_acknowledged(True)
    assert selected in gui.dashboard_anomaly_tree.rows
    assert not gui._acknowledged_alerts
    assert gui._alert_write_pending
    assert gui._async_tokens["dashboard"] == 2  # Discard older dashboard reads.
    result = pending['work']()
    pending['done'](result)
    save.assert_called_once_with(gui.db_config, {selected}, True)
    assert gui._acknowledged_alerts == {selected}
    assert selected not in gui.dashboard_anomaly_tree.rows
    assert len(gui.dashboard_anomaly_tree.rows) == 29
    assert not gui._alert_write_pending
    gui.refresh_dashboard.assert_called_once()


def test_failed_save_does_not_hide_alert_or_claim_it_was_acknowledged(gui):
    selected = gui._dashboard_alerts[0].key
    gui._render_dashboard_alerts()
    gui.dashboard_anomaly_tree.selected = (selected,)
    gui._run_async = lambda name, work, done, error: error(RuntimeError("database unavailable"))
    gui._set_selected_alerts_acknowledged(True)
    assert selected in gui.dashboard_anomaly_tree.rows
    assert not gui._acknowledged_alerts
    assert not gui._alert_write_pending
    gui.show_message.assert_called_once()


def test_restore_selected_preserves_other_acknowledgements(gui):
    one, two = (a.key for a in gui._dashboard_alerts[:2])
    gui._acknowledged_alerts = {one, two}
    gui.dashboard_anomaly_tree.selected = (one,)
    gui._run_async = lambda name, work, done, error: done(1)
    gui._set_selected_alerts_acknowledged(False)
    assert gui._acknowledged_alerts == {two}
    assert one in gui.dashboard_anomaly_tree.rows
    assert two not in gui.dashboard_anomaly_tree.rows


def test_old_database_save_callback_cannot_hide_new_database_alerts(gui):
    selected = gui._dashboard_alerts[0].key
    gui.dashboard_anomaly_tree.selected = (selected,)
    pending = {}
    gui._run_async = lambda name, work, done, error: pending.update(done=done)
    gui._set_selected_alerts_acknowledged(True)
    gui.db_config = {"enabled": True, "database": "other"}
    pending['done'](1)
    assert not gui._acknowledged_alerts
    gui.refresh_dashboard.assert_called_once()


def test_empty_or_busy_selection_does_not_write(gui):
    gui._run_async = Mock()
    gui._set_selected_alerts_acknowledged(True)
    gui._run_async.assert_not_called()
    gui.dashboard_anomaly_tree.selected = (gui._dashboard_alerts[0].key,)
    gui._alert_write_pending = True
    gui._set_selected_alerts_acknowledged(True)
    gui._run_async.assert_not_called()
