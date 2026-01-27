import datetime
import json
from pathlib import Path

import pandas as pd

import db_storage as db


class _DummyCursor:
    def __init__(self, rows=None, description=None):
        self._rows = rows or []
        self.description = description or []
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


def test_load_and_save_db_config_roundtrip(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr(db, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(db, "CONFIG_PATH", config_dir / "db_config.json")

    saved = db.DEFAULT_CONFIG.copy()
    saved["enabled"] = True
    saved["host"] = "db.local"
    db.save_db_config(saved)

    loaded = db.load_db_config()
    assert loaded["enabled"] is True
    assert loaded["host"] == "db.local"


def test_load_ui_prefs_missing_returns_empty(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr(db, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(db, "PREFS_PATH", config_dir / "ui_prefs.json")
    assert db.load_ui_prefs() == {}


def test_save_ui_prefs_roundtrip(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr(db, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(db, "PREFS_PATH", config_dir / "ui_prefs.json")
    prefs = {"theme": "light"}
    db.save_ui_prefs(prefs)
    assert db.load_ui_prefs() == prefs


def test_append_date_range_builds_conditions():
    conditions = []
    params = []
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)
    db._append_date_range(conditions, params, "pe.payment_date", start, end)
    assert conditions == ["pe.payment_date >= %s", "pe.payment_date <= %s"]
    assert params == [start, end]


def test_append_claim_month_range_builds_conditions():
    conditions = []
    params = []
    start = datetime.date(2024, 2, 1)
    end = datetime.date(2024, 3, 1)
    db._append_claim_month_range(conditions, params, start, end)
    assert "claim_year" in conditions[0]
    assert "claim_month" in conditions[0]
    assert params == [2024, 2024, 2, 2024, 2024, 3]


def test_append_search_conditions_string():
    conditions = []
    params = []
    db._append_search_conditions(conditions, params, "alice", ["e.full_name", "e.employee_code"])
    assert "ILIKE" in conditions[0]
    assert params == ["%alice%", "%alice%"]


def test_append_search_conditions_clauses():
    conditions = []
    params = []
    search = [
        {"term": "alice", "op": "AND"},
        {"term": "bob", "op": "NOT"},
    ]
    db._append_search_conditions(conditions, params, search, ["e.full_name"])
    assert "NOT" in conditions[0]
    assert params == ["%alice%", "%bob%"]


def test_prepare_staging_rows_normalizes_columns():
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "DocumentType": "Payslip",
                "Date": "01/01/2024",
                "NetPay": "1000",
            }
        ]
    )
    columns, rows = db._prepare_staging_rows(df)
    assert columns[0] == "employee_code"
    assert rows[0][0] == "1"
    assert rows[0][1] == "Alice"
    assert rows[0][2] == "Payslip"
    assert rows[0][5] == 1000


def test_insurance_period_columns_switch(monkeypatch):
    monkeypatch.setattr(db, "_insurance_claims_columns", lambda *_: {"period_year": True, "period_month": True})
    assert db._insurance_period_columns({}) == ("period_year", "period_month")


def test_paid_date_column_uses_actual_payment_date(monkeypatch):
    cursor = _DummyCursor(rows=[("actual_payment_date",), ("other",)])
    conn = _DummyConn(cursor)
    monkeypatch.setattr(db, "get_connection", lambda *_: conn)
    column = db._paid_date_column({"host": "h", "port": 1, "database": "d", "user": "u"})
    assert column == "actual_payment_date"


def test_append_audit_log_writes_jsonl(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr(db, "CONFIG_DIR", config_dir)
    config = {"audit_user": "tester"}
    db.append_audit_log(config, 1, "net_pay", 10, 11)
    log_path = config_dir / "audit_log.jsonl"
    line = log_path.read_text().strip()
    record = json.loads(line)
    assert record["entry_id"] == 1
    assert record["field"] == "net_pay"
    assert record["old_value"] == 10
    assert record["new_value"] == 11
