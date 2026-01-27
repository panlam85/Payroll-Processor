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


def test_fetch_employer_costs_by_employee(monkeypatch):
    cursor = _DummyCursor(rows=[("Alice", 1234.0)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    rows = db.fetch_employer_costs_by_employee({}, limit=5)
    assert rows[0][0] == "Alice"
    assert "LIMIT" in cursor.executed[0]


def test_fetch_anomaly_entries(monkeypatch):
    cursor = _DummyCursor(
        rows=[("High Net Pay", "Alice", datetime.date(2024, 1, 1), "salary", 2000, 300)],
        description=[("alert",), ("employee_name",), ("payment_date",), ("document_type",), ("net_pay",), ("total_insurance",)],
    )
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    columns, rows = db.fetch_anomaly_entries({}, limit=1)
    assert columns[0] == "alert"
    assert rows[0][0] == "High Net Pay"


def test_employee_columns_cache(monkeypatch):
    cursor = _DummyCursor(rows=[("iban",), ("beneficiary_name",)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    config = {"host": "h", "port": 1, "database": "d", "user": "u"}
    first = db._employee_columns(config)
    assert "iban" in first

    def raise_conn(_):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(db, "get_connection", raise_conn)
    second = db._employee_columns(config)
    assert second == first


def test_insurance_claims_columns_cache(monkeypatch):
    cursor = _DummyCursor(rows=[("claim_type", "YES"), ("paid_date", "NO")])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    config = {"host": "h", "port": 1, "database": "d", "user": "u"}
    first = db._insurance_claims_columns(config)
    assert first["claim_type"] is True

    def raise_conn(_):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(db, "get_connection", raise_conn)
    second = db._insurance_claims_columns(config)
    assert second == first


def test_mark_paid_by_receipt_total_fallback_name(monkeypatch):
    cursor = _DummyCursor(rowcounts=[0, 2])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_employee_columns", lambda *_: {"iban": True, "last_paid_date": True})
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
    assert updated == 2
    assert any("UPDATE employees" in q for q in cursor.executed)


def test_serialize_audit_value_datetime():
    value = datetime.date(2024, 1, 1)
    assert db._serialize_audit_value(value) == "2024-01-01"
