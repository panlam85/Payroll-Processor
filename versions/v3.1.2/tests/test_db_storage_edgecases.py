import json
import tempfile

import pytest

import db_storage as db

ORIGINAL_REQUIRE = db._require_psycopg2

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


def test_load_db_config_invalid_json(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "db_config.json"
    config_path.write_text("{bad json")
    monkeypatch.setattr(db, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(db, "CONFIG_PATH", config_path)
    loaded = db.load_db_config()
    assert loaded["host"] == db.DEFAULT_CONFIG["host"]


def test_load_ui_prefs_invalid_json(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    prefs_path = config_dir / "ui_prefs.json"
    prefs_path.write_text("{bad json")
    monkeypatch.setattr(db, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(db, "PREFS_PATH", prefs_path)
    assert db.load_ui_prefs() == {}


def test_require_psycopg2_raises(monkeypatch):
    monkeypatch.setattr(db, "psycopg2", None)
    monkeypatch.setattr(db, "_require_psycopg2", ORIGINAL_REQUIRE)
    with pytest.raises(RuntimeError):
        db._require_psycopg2()


def test_migrate_paid_date_column_no_change(monkeypatch):
    cursor = _DummyCursor(rows=[("paid_date",), ("other",)])
    conn = _DummyConn(cursor)
    monkeypatch.setattr(db, "get_connection", lambda *_: conn)
    changed = db.migrate_paid_date_column({})
    assert changed is False


def test_migrate_paid_date_column_no_target(monkeypatch):
    cursor = _DummyCursor(rows=[("other",)])
    conn = _DummyConn(cursor)
    monkeypatch.setattr(db, "get_connection", lambda *_: conn)
    changed = db.migrate_paid_date_column({})
    assert changed is False


def test_ensure_insurance_claims_table_unique_constraint(monkeypatch):
    # Columns present so unique constraint should be attempted.
    cursor = _DummyCursor(rows=[("claim_year",), ("claim_month",), ("tpte_code",), ("source_pdf",)])
    conn = _DummyConn(cursor)
    monkeypatch.setattr(db, "get_connection", lambda *_: conn)
    db.ensure_insurance_claims_table({})
    assert any("insurance_claims_unique" in q for q in cursor.executed)


def test_update_insurance_claims_for_period_no_claim_type(monkeypatch):
    claims = [("id1", None, 100, 1000, None), ("id2", None, 100, 1000, None)]
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "fetch_insurance_claims_for_period", lambda *_: claims)
    monkeypatch.setattr(db, "_insurance_claims_columns", lambda *_: {})

    updated_rows = []

    class _DummyExtras:
        @staticmethod
        def execute_batch(cur, query, params, page_size=200):
            updated_rows.extend(params)

    monkeypatch.setattr(db, "extras", _DummyExtras)
    updated = db.update_insurance_claims_for_period({}, 2024, 1, efka_total=200)
    assert updated == 2
    assert len(updated_rows) == 2


def test_update_insurance_claims_for_period_paid_status_false(monkeypatch):
    claims = [("id1", "EFKA", 100, 1000, None)]
    cursor = _DummyCursor()
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "fetch_insurance_claims_for_period", lambda *_: claims)
    monkeypatch.setattr(db, "_insurance_claims_columns", lambda *_: {"claim_type": True, "paid_status": True, "paid_date": True})

    class _DummyExtras:
        @staticmethod
        def execute_batch(cur, query, params, page_size=200):
            pass

    monkeypatch.setattr(db, "extras", _DummyExtras)
    updated = db.update_insurance_claims_for_period({}, 2024, 1, paid_status=False)
    assert updated == 1
    assert any("paid_status" in q for q in cursor.executed)
    assert any("paid_date" in q for q in cursor.executed)


def test_delete_insurance_claims_for_period_alt_columns(monkeypatch):
    cursor = _DummyCursor(rowcounts=[2])
    monkeypatch.setattr(db, "get_connection", lambda *_: _DummyConn(cursor))
    monkeypatch.setattr(db, "_insurance_period_columns", lambda *_: ("period_year", "period_month"))
    deleted = db.delete_insurance_claims_for_period({}, 2024, 1)
    assert deleted == 2
