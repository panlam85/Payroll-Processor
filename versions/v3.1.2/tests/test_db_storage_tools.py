import os

import pytest

import db_storage as db


class _DummyCursor:
    def __init__(self, fetchall_sequences=None):
        self._fetchall_sequences = list(fetchall_sequences or [])
        self.executed = []
        self.params = []
        self.copy_calls = []

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

    def copy_expert(self, query, handle):
        self.copy_calls.append(query)
        handle.write("col1,col2\n1,2\n")


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


def test_find_pg_tool_uses_path(monkeypatch):
    monkeypatch.setattr(db.shutil, "which", lambda name: f"/bin/{name}")
    assert db._find_pg_tool("pg_dump") == "/bin/pg_dump"


def test_backup_database_builds_args(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_find_pg_tool", lambda *_: "/bin/pg_dump")
    captured = {}

    def fake_call(args, env=None):
        captured["args"] = args
        captured["env"] = env

    monkeypatch.setattr(db.subprocess, "check_call", fake_call)
    config = {
        "host": "localhost",
        "port": 5432,
        "database": "payroll",
        "user": "postgres",
        "password": "secret",
    }
    backup_path = str(tmp_path / "backup.dump")
    db.backup_database(config, backup_path)
    assert captured["args"][0] == "/bin/pg_dump"
    assert backup_path in captured["args"]
    assert captured["env"]["PGPASSWORD"] == "secret"


def test_restore_database_builds_args(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_find_pg_tool", lambda *_: "/bin/pg_restore")
    captured = {}

    def fake_call(args, env=None):
        captured["args"] = args
        captured["env"] = env

    monkeypatch.setattr(db.subprocess, "check_call", fake_call)
    config = {
        "host": "localhost",
        "port": 5432,
        "database": "payroll",
        "user": "postgres",
        "password": "secret",
    }
    backup_path = str(tmp_path / "backup.dump")
    db.restore_database(config, backup_path)
    assert captured["args"][0] == "/bin/pg_restore"
    assert backup_path in captured["args"]
    assert captured["env"]["PGPASSWORD"] == "secret"


def test_export_all_tables_to_csv(monkeypatch, tmp_path):
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    db.export_all_tables_to_csv({}, str(tmp_path))
    # Expect CSV files created for each table.
    expected = {
        "employees.csv",
        "payroll_runs.csv",
        "payroll_entries.csv",
        "insurance_contributions.csv",
        "insurance_claims.csv",
        "documents.csv",
    }
    assert expected.issubset({p.name for p in tmp_path.iterdir()})
    assert cursor.copy_calls


def test_test_connection_success(monkeypatch):
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    ok, message = db.test_connection({})
    assert ok is True
    assert "successful" in message.lower()


def test_test_connection_failure(monkeypatch):
    def raise_conn(_):
        raise RuntimeError("fail")

    monkeypatch.setattr(db, "get_connection", raise_conn)
    ok, message = db.test_connection({})
    assert ok is False
    assert "failed" in message.lower()


def test_ensure_employee_profile_columns_no_missing(monkeypatch):
    cursor = _DummyCursor(fetchall_sequences=[[ ("iban",), ("beneficiary_name",), ("first_worked_date",), ("last_paid_date",),
                                                ("pay_rate_monthly",), ("pay_rate_hourly",), ("pay_rate_daily",), ("pay_rate_double",),
                                                ("pay_rate_abroad",), ("pay_rate_abroad_double",) ]])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    db.ensure_employee_profile_columns({"host": "h", "port": 1, "database": "d", "user": "u"})
    # Only the SELECT should be present, no ALTERs.
    assert not any("ALTER TABLE" in q for q in cursor.executed)
