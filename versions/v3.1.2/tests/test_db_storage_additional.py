import datetime

import pytest

import db_storage as db


class _DummyCursor:
    def __init__(self, rows=None, description=None, rowcounts=None):
        self._rows = rows or []
        self.description = description or []
        self._rowcounts = list(rowcounts or [])
        self.rowcount = 0
        self.executed = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append(query)
        self.params.append(params)
        if self._rowcounts:
            self.rowcount = self._rowcounts.pop(0)

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


def test_fetch_employee_monthly_totals(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, 100, 10, 20, 30)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    rows = db.fetch_employee_monthly_totals({}, "E1")
    assert rows[0][0] == 2024
    assert "EXTRACT" in cursor.executed[0]


def test_fetch_available_years_months(monkeypatch):
    cursor_years = _DummyCursor(rows=[(2023,), (2024,)])
    cursor_months = _DummyCursor(rows=[(1,), (2,)])

    conns = [_DummyConn(cursor_years), _DummyConn(cursor_months)]
    def next_conn(*_):
        return conns.pop(0)

    monkeypatch.setattr(db, "get_connection", next_conn)
    years = db.fetch_available_years({})
    months = db.fetch_available_months({}, 2024)
    assert years == [2023, 2024]
    assert months == [1, 2]


def test_fetch_recent_entries(monkeypatch):
    cursor = _DummyCursor(rows=[("Alice", datetime.date(2024, 1, 1), "salary", 1000)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    columns, rows = db.fetch_recent_entries({}, limit=1)
    assert rows[0][0] == "Alice"
    assert "ORDER BY" in cursor.executed[0]


def test_fetch_unpaid_amount(monkeypatch):
    cursor = _DummyCursor(rows=[(123.45,)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    amount = db.fetch_unpaid_amount({}, None, None)
    assert amount == 123.45


def test_fetch_payment_heatmap(monkeypatch):
    cursor = _DummyCursor(rows=[("Alice", datetime.date(2024, 1, 1), 100)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    rows = db.fetch_payment_heatmap({}, 2024, 1, limit=5)
    assert rows[0][0] == "Alice"


def test_fetch_document_type_breakdown(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, "Salary", 1000)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    rows = db.fetch_document_type_breakdown({}, None, None)
    assert rows[0][2] == "Salary"


def test_fetch_monthly_employee_summary(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, "E1", "Alice", True, None, 1000, 10, 20, 30)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    columns, rows = db.fetch_monthly_employee_summary({}, None, None)
    assert rows[0][3] == "Alice"


def test_fetch_employee_monthly_entries(monkeypatch):
    cursor = _DummyCursor(rows=[(datetime.date(2024, 1, 1), False, "salary", 100, "a.pdf", "zip")])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    columns, rows = db.fetch_employee_monthly_entries({}, employee_code="E1", months=[(2024, 1)])
    assert rows[0][2] == "salary"


def test_delete_payroll_entries(monkeypatch):
    cursor = _DummyCursor(rowcounts=[2])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    deleted = db.delete_payroll_entries({}, [1, 2])
    assert deleted == 2


def test_delete_all_data(monkeypatch):
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    db.delete_all_data({})
    assert "TRUNCATE" in cursor.executed[0]
