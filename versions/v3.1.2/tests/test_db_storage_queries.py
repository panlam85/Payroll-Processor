import datetime

import pytest

import db_storage as db


class _DummyCursor:
    def __init__(self, rows=None, description=None, rowcount=0):
        self._rows = rows or []
        self.description = description or []
        self.rowcount = rowcount
        self.executed = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append(query)
        self.params.append(params)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _DummyConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        return None


@pytest.fixture(autouse=True)
def _skip_psycopg2(monkeypatch):
    monkeypatch.setattr(db, "_require_psycopg2", lambda: None)


def test_fetch_view_rows_rejects_invalid_view():
    try:
        db.fetch_view_rows({}, "not_allowed")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_fetch_view_rows_builds_limit(monkeypatch):
    cursor = _DummyCursor(rows=[(1, "a")], description=[("id",), ("name",)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    columns, rows = db.fetch_view_rows({}, "v_monthly_payroll_summary", limit=10)
    assert columns == ["id", "name"]
    assert rows == [(1, "a")]
    assert "LIMIT 10" in cursor.executed[0]


def test_update_employee_profile_builds_query(monkeypatch):
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True, "beneficiary_name": True})
    db.update_employee_profile({}, "E1", iban="GR", beneficiary_name="Name")
    assert cursor.executed
    assert cursor.params[0][-1] == "E1"


def test_update_employee_bank_details_no_columns(monkeypatch):
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {})
    assert db.update_employee_bank_details_by_name({}, "Alice", iban="GR") == 0


def test_mark_entries_paid_for_month_validates_inputs():
    try:
        db.mark_entries_paid_for_month({}, year=None, month=1)
    except ValueError as exc:
        assert "year and month" in str(exc)
    else:
        raise AssertionError("Expected ValueError")

    try:
        db.mark_entries_paid_for_month({}, year=2024, month=1)
    except ValueError as exc:
        assert "employee_code" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_fetch_paid_unpaid_totals(monkeypatch):
    cursor = _DummyCursor(rows=[(100, 50)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    paid, unpaid = db.fetch_paid_unpaid_totals({}, None, None)
    assert paid == 100.0
    assert unpaid == 50.0


def test_fetch_unpaid_aging_buckets(monkeypatch):
    cursor = _DummyCursor(rows=[(10, 20, 30, 40)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    buckets = db.fetch_unpaid_aging_buckets({}, datetime.date(2024, 1, 31))
    assert buckets == {"0_30": 10.0, "31_60": 20.0, "61_90": 30.0, "90_plus": 40.0}


def test_fetch_kpi_totals(monkeypatch):
    cursor = _DummyCursor(rows=[(100, 15, 25)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    totals = db.fetch_kpi_totals({}, None, None)
    assert totals == (100.0, 15.0, 25.0)


def test_fetch_dashboard_metrics(monkeypatch):
    cursor = _DummyCursor(rows=[(3, 10, 1000, 150, 250)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    metrics = db.fetch_dashboard_metrics({}, None, None)
    assert metrics["employee_count"] == 3
    assert metrics["entry_count"] == 10
    assert metrics["total_net_pay"] == 1000.0
    assert metrics["employee_insurance"] == 150.0
    assert metrics["employer_insurance"] == 250.0
