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


def test_fetch_monthly_totals(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, 1000, 200, 100)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    rows = db.fetch_monthly_totals({}, None, None)
    assert rows[0][0] == 2024


def test_fetch_insurance_comparison(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, 100, 50, 50, 100, 0, 10, 20, 1000, True, None, None, "RF1", "a.pdf")])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_insurance_claims_columns", lambda *_: {"claim_type": True, "paid_status": True, "paid_date": True})
    rows = db.fetch_insurance_comparison({}, None, None)
    assert rows[0][0] == 2024


def test_fetch_employees_list(monkeypatch):
    cursor = _DummyCursor(rows=[("E1", "Alice", None, None, None, None)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True, "beneficiary_name": True, "first_worked_date": True, "last_paid_date": True})
    rows = db.fetch_employees_list({}, search="Ali")
    assert rows[0][1] == "Alice"


def test_fetch_employee_profile_none(monkeypatch):
    assert db.fetch_employee_profile({}, "") is None


def test_update_employee_iban_by_name(monkeypatch):
    cursor = _DummyCursor(rowcounts=[3])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True})
    updated = db.update_employee_iban_by_name({}, "Alice", "GR")
    assert updated == 3


def test_update_employee_iban_by_name_no_iban(monkeypatch):
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {})
    updated = db.update_employee_iban_by_name({}, "Alice", "GR")
    assert updated == 0


def test_delete_insurance_claims_for_period(monkeypatch):
    cursor = _DummyCursor(rowcounts=[4])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_insurance_period_columns", lambda *_: ("claim_year", "claim_month"))
    deleted = db.delete_insurance_claims_for_period({}, 2024, 1)
    assert deleted == 4


def test_fetch_month_totals_by_year(monkeypatch):
    cursor = _DummyCursor(rows=[(2023, 1000, 200, 100)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    rows = db.fetch_month_totals_by_year({}, 1)
    assert rows[0][0] == 2023


def test_fetch_avg_days_to_paid_by_month(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, 5)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_paid_date_column", lambda *_: "paid_date")
    rows = db.fetch_avg_days_to_paid_by_month({}, None, None)
    assert rows[0][2] == 5


def test_fetch_document_type_breakdown_with_search(monkeypatch):
    cursor = _DummyCursor(rows=[(2024, 1, "Salary", 1000)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    rows = db.fetch_document_type_breakdown({}, None, None, search="Alice")
    assert rows[0][2] == "Salary"


def test_fetch_paid_unpaid_totals_with_document_type(monkeypatch):
    cursor = _DummyCursor(rows=[(10, 5)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    paid, unpaid = db.fetch_paid_unpaid_totals({}, None, None, document_type="salary")
    assert paid == 10.0
    assert unpaid == 5.0


def test_fetch_unpaid_aging_buckets_with_search(monkeypatch):
    cursor = _DummyCursor(rows=[(1, 2, 3, 4)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    buckets = db.fetch_unpaid_aging_buckets({}, datetime.date(2024, 1, 1), search="Alice")
    assert buckets["90_plus"] == 4.0
