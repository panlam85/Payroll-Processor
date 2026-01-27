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


def test_fetch_monthly_summary_params(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, "Alice", 100, 10, 20)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)
    rows = db.fetch_monthly_summary({}, start, end, document_type="salary", search="Alice")
    assert rows[0][0] == 2024
    params = cursor.params[0]
    assert params[0] == start
    assert params[1] == end
    assert params[2] == "salary"
    assert "%Alice%" in params


def test_fetch_employee_profile_builds_columns(monkeypatch):
    cursor = _DummyCursor(rows=[("E1", "Alice", None, None, None, None, None, None, None, None, None, None)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True, "beneficiary_name": True})
    row = db.fetch_employee_profile({}, "E1")
    assert row[0] == "E1"
    assert "iban" in cursor.executed[0]


def test_update_insurance_claims_for_period_no_claims(monkeypatch):
    monkeypatch.setattr(db, "fetch_insurance_claims_for_period", lambda *_: [])
    monkeypatch.setattr(db, "_insurance_claims_columns", lambda *_: {"claim_type": True})
    updated = db.update_insurance_claims_for_period({}, 2024, 1, efka_total=100)
    assert updated == 0


def test_fetch_export_rows_returns_columns(monkeypatch):
    cursor = _DummyCursor(rows=[("E1", "Alice")], description=[("EmployeeCode",), ("EmployeeName",)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    columns, rows = db.fetch_export_rows({}, [1])
    assert columns == ["EmployeeCode", "EmployeeName"]
    assert rows == [("E1", "Alice")]


def test_fetch_payroll_entry_count(monkeypatch):
    cursor = _DummyCursor(rows=[(5,)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    count = db.fetch_payroll_entry_count({}, None, None)
    assert count == 5


def test_mark_paid_by_receipt_prefers_iban(monkeypatch):
    cursor = _DummyCursor(rowcounts=[1])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True})
    monkeypatch.setattr(db, "_paid_date_column", lambda *_: "paid_date")
    updated = db.mark_paid_by_receipt(
        {},
        employee_name="Alice",
        amount=100.0,
        paid_date=datetime.date(2024, 1, 5),
        iban="GR00",
        payroll_year=2024,
        payroll_month=1,
    )
    assert updated == 1
    assert "iban" in cursor.executed[0]


def test_mark_paid_by_receipt_fallback_name(monkeypatch):
    cursor = _DummyCursor(rowcounts=[0, 2])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True})
    monkeypatch.setattr(db, "_paid_date_column", lambda *_: "paid_date")
    updated = db.mark_paid_by_receipt(
        {},
        employee_name="Alice",
        amount=100.0,
        paid_date=datetime.date(2024, 1, 5),
        iban="GR00",
        payroll_year=2024,
        payroll_month=1,
    )
    assert updated == 2


def test_mark_paid_by_receipt_total(monkeypatch):
    cursor = _DummyCursor(rowcounts=[1])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True})
    monkeypatch.setattr(db, "_paid_date_column", lambda *_: "paid_date")
    updated = db.mark_paid_by_receipt_total(
        {},
        employee_name="Alice",
        amount=300.0,
        paid_date=datetime.date(2024, 1, 31),
        iban="GR00",
        payroll_year=2024,
        payroll_month=1,
    )
    assert updated == 1
