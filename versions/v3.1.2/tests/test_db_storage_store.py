import pandas as pd
import pytest

import db_storage as db


class _DummyCursor:
    def __init__(self, fetchall_sequences=None):
        self._fetchall_sequences = list(fetchall_sequences or [])
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
        if self._fetchall_sequences:
            return self._fetchall_sequences.pop(0)
        return []


class _DummyConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


@pytest.fixture(autouse=True)
def _skip_psycopg2(monkeypatch):
    monkeypatch.setattr(db, "_require_psycopg2", lambda: None)


def test_store_insurance_claims_builds_rows(monkeypatch):
    claims = [
        {
            "claim_year": 2024,
            "claim_month": 1,
            "submission_date": None,
            "total_earnings": 100.0,
            "total_contributions": 10.0,
            "tpte_code": "RF1",
            "claim_type": "EFKA",
            "paid_status": False,
            "paid_date": None,
            "source_pdf": "a.pdf",
        }
    ]

    monkeypatch.setattr(
        db,
        "_insurance_claims_columns",
        lambda *_: {
            "claim_year": True,
            "claim_month": True,
            "period_year": True,
            "period_month": True,
            "submission_date": True,
            "total_earnings": True,
            "total_contributions": True,
            "tpte_code": True,
            "claim_type": True,
            "paid_status": True,
            "paid_date": True,
            "source_pdf": True,
        },
    )

    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))

    captured = {}

    class _DummyExtras:
        @staticmethod
        def execute_values(cur, query, rows, page_size=200):
            captured["query"] = query
            captured["rows"] = rows

    monkeypatch.setattr(db, "extras", _DummyExtras)

    inserted = db.store_insurance_claims(claims, {})
    assert inserted == 1
    assert "insurance_claims" in captured["query"]
    assert len(captured["rows"]) == 1


def test_store_payroll_data_empty():
    df = pd.DataFrame()
    assert db.store_payroll_data(df, {}) == 0


def test_store_payroll_data_inserts(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "DocumentType": "Payslip",
                "Date": "01/01/2024",
                "NetPay": "1000",
                "SourcePDF": "a.pdf",
                "SourceArchive": "zip",
            }
        ]
    )

    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))

    captured = {}

    class _DummyExtras:
        @staticmethod
        def execute_values(cur, query, rows, page_size=500):
            captured["rows"] = rows

    monkeypatch.setattr(db, "extras", _DummyExtras)

    inserted = db.store_payroll_data(df, {})
    assert inserted == 1
    assert len(captured["rows"]) == 1


def test_migrate_paid_date_column(monkeypatch):
    cursor = _DummyCursor(fetchall_sequences=[[ ("actual_payment_date",), ("other",) ]])
    conn = _DummyConn(cursor)
    monkeypatch.setattr(db, "get_connection", lambda *_: conn)
    changed = db.migrate_paid_date_column({})
    assert changed is True
    assert any("RENAME COLUMN actual_payment_date" in q for q in cursor.executed)
    assert conn.committed is True


def test_ensure_insurance_claims_table_adds_columns(monkeypatch):
    cursor = _DummyCursor(fetchall_sequences=[[ ("id",), ("claim_year",) ]])
    conn = _DummyConn(cursor)
    monkeypatch.setattr(db, "get_connection", lambda *_: conn)
    db.ensure_insurance_claims_table({})
    # At least one ALTER should be executed for missing columns.
    assert any("ALTER TABLE insurance_claims" in q for q in cursor.executed)
