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


def test_fetch_insurance_claims_for_period(monkeypatch):
    cursor = _DummyCursor(rows=[("id1", "EFKA", 100, 200, None)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_insurance_claims_columns", lambda *_: {"claim_type": True})
    rows = db.fetch_insurance_claims_for_period({}, 2024, 1)
    assert rows[0][1] == "EFKA"
    assert "insurance_claims" in cursor.executed[0]


def test_update_insurance_claims_paid(monkeypatch):
    cursor = _DummyCursor(rowcounts=[3])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_insurance_period_columns", lambda *_: ("claim_year", "claim_month"))
    updated = db.update_insurance_claims_paid({}, 2024, 1, True, paid_date=None)
    assert updated == 3
    assert "paid_status" in cursor.executed[0]


def test_update_insurance_claims_for_period_scaling(monkeypatch):
    claims = [
        ("id1", "EFKA", 100, 1000, None),
        ("id2", "EFKA", 200, 2000, None),
    ]
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "fetch_insurance_claims_for_period", lambda *_: claims)
    monkeypatch.setattr(db, "_insurance_claims_columns", lambda *_: {"claim_type": True, "paid_status": True, "paid_date": True})

    updates = []

    def fake_execute_batch(cur, query, params, page_size=200):
        updates.extend(params)

    class _DummyExtras:
        @staticmethod
        def execute_batch(cur, query, params, page_size=200):
            fake_execute_batch(cur, query, params, page_size=page_size)

    monkeypatch.setattr(db, "extras", _DummyExtras)

    updated = db.update_insurance_claims_for_period(
        {},
        2024,
        1,
        efka_total=600,
        total_earnings=4000,
        submission_date=datetime.date(2024, 1, 10),
        tpte_code="RF1",
        paid_status=True,
        paid_date=None,
    )
    assert updated == 2
    # expect scaled totals 200 and 400
    scaled = sorted([round(val[0], 2) for val in updates])
    assert scaled == [200.0, 400.0]


def test_update_payroll_entry_field_map(monkeypatch):
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_paid_date_column", lambda *_: "paid_date")
    db.update_payroll_entry({}, 1, "net_pay", 123)
    assert "UPDATE payroll_entries" in cursor.executed[0]
    assert cursor.params[0] == (123, 1)


def test_update_payroll_entry_invalid_field():
    with pytest.raises(ValueError):
        db.update_payroll_entry({}, 1, "bad_field", 123)


def test_fetch_payroll_entries(monkeypatch):
    cursor = _DummyCursor(rows=[("id", "E1")], description=[("entry_id",), ("employee_code",)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_paid_date_column", lambda *_: "paid_date")
    columns, rows = db.fetch_payroll_entries({}, limit=1, offset=0)
    assert columns == ["entry_id", "employee_code"]
    assert rows[0][1] == "E1"


def test_fetch_duplicate_payroll_entries(monkeypatch):
    cursor = _DummyCursor(rows=[("id", "E1")], description=[("entry_id",), ("employee_code",)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    columns, rows = db.fetch_duplicate_payroll_entries({})
    assert columns == ["entry_id", "employee_code"]
    assert rows[0][1] == "E1"


def test_fetch_employee_entries(monkeypatch):
    cursor = _DummyCursor(rows=[(datetime.date(2024, 1, 1), False)], description=[("payment_date",), ("paid_status",)])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_paid_date_column", lambda *_: "paid_date")
    columns, rows = db.fetch_employee_entries({}, employee_code="E1")
    assert columns == ["payment_date", "paid_status"]
    assert rows[0][0] == datetime.date(2024, 1, 1)


def test_mark_entries_paid_for_month(monkeypatch):
    cursor = _DummyCursor(rowcounts=[5])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    updated = db.mark_entries_paid_for_month({}, employee_code="E1", year=2024, month=1)
    assert updated == 5
