"""Coverage for db_storage paths not exercised by the existing suites.

Focuses on the pg-tool discovery fallback, the employee-column cache,
per-employee monthly totals, and the IBAN branch of receipt matching.
"""

import datetime

import db_storage

from test_db_storage_full import (
    ConnectionFactory,
    FakeCursor,
    _clear_caches,
)


CONFIG = {"host": "db", "port": 5432, "database": "payroll", "user": "me"}


def test_find_pg_tool_falls_back_to_install_locations(monkeypatch, tmp_path):
    """When the tool is not on PATH, known macOS install dirs are searched."""
    monkeypatch.setattr(db_storage.shutil, "which", lambda name: None)

    bin_dir = tmp_path / "opt" / "bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "pg_dump"
    tool.write_text("#!/bin/sh\n")

    real_path = db_storage.Path

    # Redirect the hard-coded search bases at our temp dir.
    monkeypatch.setattr(
        db_storage,
        "Path",
        lambda p: bin_dir if p in ("/opt/homebrew/bin", "/usr/local/bin") else real_path(p),
    )

    assert db_storage._find_pg_tool("pg_dump") == str(tool)


def test_find_pg_tool_returns_none_when_absent(monkeypatch, tmp_path):
    """A tool that exists nowhere yields None rather than raising."""
    monkeypatch.setattr(db_storage.shutil, "which", lambda name: None)
    empty = tmp_path / "empty"
    empty.mkdir()
    real_path = db_storage.Path
    monkeypatch.setattr(
        db_storage,
        "Path",
        lambda p: empty if p in ("/opt/homebrew/bin", "/usr/local/bin") else real_path(p),
    )
    assert db_storage._find_pg_tool("definitely_not_a_tool") is None


def test_test_connection_success_and_failure(monkeypatch):
    """test_connection reports both outcomes without propagating exceptions."""
    monkeypatch.setattr(
        db_storage, "get_connection", ConnectionFactory([FakeCursor()])
    )
    ok, message = db_storage.test_connection(CONFIG)
    assert ok is True
    assert "successful" in message.lower()

    def boom(_config):
        raise RuntimeError("no route to host")

    monkeypatch.setattr(db_storage, "get_connection", boom)
    ok, message = db_storage.test_connection(CONFIG)
    assert ok is False
    assert "no route to host" in message


def test_employee_columns_caches_and_swallows_errors(monkeypatch):
    """The column probe is cached per-config and degrades to {} on failure."""
    _clear_caches()

    cursor = FakeCursor(fetchall_sequence=[[("id",), ("iban",), ("full_name",)]])
    factory = ConnectionFactory([cursor])
    calls = []

    def counting_factory(config):
        calls.append(config)
        return factory(config)

    monkeypatch.setattr(db_storage, "get_connection", counting_factory)

    columns = db_storage._employee_columns(CONFIG)
    assert columns == {"id": True, "iban": True, "full_name": True}

    # Second call is served from cache — no further connections.
    again = db_storage._employee_columns(CONFIG)
    assert again == columns
    assert len(calls) == 1

    # A different database is a different cache key, and errors become {}.
    _clear_caches()

    def boom(_config):
        raise RuntimeError("relation missing")

    monkeypatch.setattr(db_storage, "get_connection", boom)
    assert db_storage._employee_columns(CONFIG) == {}


def test_insurance_period_columns_defaults_without_config():
    """No config means the legacy claim_* column names."""
    assert db_storage._insurance_period_columns() == ("claim_year", "claim_month")


def test_insurance_period_columns_prefers_period_names(monkeypatch):
    """When period_* columns exist they win over the legacy names."""
    _clear_caches()
    monkeypatch.setattr(
        db_storage,
        "_insurance_claims_columns",
        lambda config: {"period_year": True, "period_month": True},
    )
    assert db_storage._insurance_period_columns(CONFIG) == ("period_year", "period_month")

    monkeypatch.setattr(
        db_storage, "_insurance_claims_columns", lambda config: {"claim_year": True}
    )
    assert db_storage._insurance_period_columns(CONFIG) == ("claim_year", "claim_month")


def test_fetch_employee_monthly_totals_builds_filtered_query(monkeypatch):
    """Per-employee monthly totals filter by code and optional date range."""
    _clear_caches()
    rows = [(2026, 1, 1200.0, 150.0, 300.0, 450.0)]
    cursor = FakeCursor(fetchall_sequence=[rows])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    result = db_storage.fetch_employee_monthly_totals(
        CONFIG,
        "EMP-1",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 3, 31),
    )

    assert result == rows
    query = cursor.queries[0]
    assert "e.employee_code = %s" in query
    assert "GROUP BY year, month" in query
    # Employee code leads, then the two date bounds.
    assert cursor.params[0][0] == "EMP-1"
    assert len(cursor.params[0]) == 3


def test_fetch_employee_monthly_totals_without_date_range(monkeypatch):
    """Omitting the range leaves the employee code as the only parameter."""
    _clear_caches()
    cursor = FakeCursor(fetchall_sequence=[[]])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    assert db_storage.fetch_employee_monthly_totals(CONFIG, "EMP-2") == []
    assert cursor.params[0] == ["EMP-2"]


def test_mark_paid_by_receipt_total_matches_on_iban(monkeypatch):
    """An IBAN match short-circuits before the name-based fallback."""
    _clear_caches()
    cursor = FakeCursor(rowcount_sequence=[2])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")
    monkeypatch.setattr(db_storage, "_employee_columns", lambda config: {"iban": True})
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    updated = db_storage.mark_paid_by_receipt_total(
        CONFIG,
        "Some Employee",
        1500.0,
        datetime.date(2026, 2, 10),
        iban="GR1601101250000000012300695",
    )

    assert updated == 2
    # Only the IBAN query ran; the name fallback was skipped.
    assert len(cursor.queries) == 1
    assert "e.iban = %s" in cursor.queries[0]
    assert cursor.params[0][0] == "GR1601101250000000012300695"
    # Year/month default to the paid date when not given explicitly.
    assert cursor.params[0][1] == 2026
    assert cursor.params[0][2] == 2


def test_mark_paid_by_receipt_total_respects_explicit_period(monkeypatch):
    """An explicit payroll year/month overrides the paid date."""
    _clear_caches()
    cursor = FakeCursor(rowcount_sequence=[1])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")
    monkeypatch.setattr(db_storage, "_employee_columns", lambda config: {"iban": True})
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    db_storage.mark_paid_by_receipt_total(
        CONFIG,
        "Some Employee",
        900.0,
        datetime.date(2026, 5, 3),
        iban="GR99",
        payroll_year=2025,
        payroll_month=12,
    )

    assert cursor.params[0][1] == 2025
    assert cursor.params[0][2] == 12


def test_mark_paid_by_receipt_total_guards_bad_input(monkeypatch):
    """A missing name or date returns 0 without touching the database."""
    _clear_caches()
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")
    monkeypatch.setattr(db_storage, "_employee_columns", lambda config: {})

    def fail(_config):  # pragma: no cover - must never be reached
        raise AssertionError("should not connect")

    monkeypatch.setattr(db_storage, "get_connection", fail)

    assert db_storage.mark_paid_by_receipt_total(
        CONFIG, "", 100.0, datetime.date(2026, 1, 1)
    ) == 0
    assert db_storage.mark_paid_by_receipt_total(CONFIG, "Name", 100.0, None) == 0
