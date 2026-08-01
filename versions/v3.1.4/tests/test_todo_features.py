"""Tests for the features that closed out TODO.md.

Covers the signed-document data model and auto-detection, the
period-over-period comparison, the workforce and payment-status analytics,
and receipt-into-monthly-PDF merging.
"""

import datetime
import os

import matplotlib

matplotlib.use("Agg")

import pytest

import db_storage
import process_payroll

from test_db_storage_full import ConnectionFactory, FakeCursor, _clear_caches


CONFIG = {"host": "db", "port": 5432, "database": "payroll", "user": "me"}


def _reset(monkeypatch, cursor):
    _clear_caches()
    db_storage._SIGNED_COLUMN_CACHE.clear()
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))


# --------------------------------------------------------------------------
# Signed flags: data model
# --------------------------------------------------------------------------


def test_migrate_signed_flags_adds_missing_columns(monkeypatch):
    """All three columns are created when none exist."""
    db_storage._SIGNED_COLUMN_CACHE.clear()
    cursor = FakeCursor(fetchall_sequence=[[("id",), ("net_pay",)]])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    assert db_storage.migrate_signed_flags(CONFIG) is True
    ddl = " ".join(cursor.queries)
    assert "ADD COLUMN signed_employer BOOLEAN" in ddl
    assert "ADD COLUMN signed_employee BOOLEAN" in ddl
    assert "ADD COLUMN signed_date DATE" in ddl


def test_migrate_signed_flags_is_idempotent(monkeypatch):
    """A database that already has the columns is left untouched."""
    db_storage._SIGNED_COLUMN_CACHE.clear()
    existing = [("signed_employer",), ("signed_employee",), ("signed_date",)]
    cursor = FakeCursor(fetchall_sequence=[existing])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    assert db_storage.migrate_signed_flags(CONFIG) is False
    assert not any("ADD COLUMN" in q for q in cursor.queries)


def test_migrate_signed_flags_survives_db_errors(monkeypatch):
    """A migration failure returns False rather than breaking startup."""
    db_storage._SIGNED_COLUMN_CACHE.clear()
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)

    def boom(_config):
        raise RuntimeError("permission denied")

    monkeypatch.setattr(db_storage, "get_connection", boom)
    assert db_storage.migrate_signed_flags(CONFIG) is False


def test_signed_columns_caches_probe(monkeypatch):
    db_storage._SIGNED_COLUMN_CACHE.clear()
    cursor = FakeCursor(fetchall_sequence=[[("signed_employer",), ("signed_date",)]])
    calls = []
    factory = ConnectionFactory([cursor])

    def counting(config):
        calls.append(config)
        return factory(config)

    monkeypatch.setattr(db_storage, "get_connection", counting)

    first = db_storage._signed_columns(CONFIG)
    assert first == {"signed_employer": True, "signed_date": True}
    assert db_storage._signed_columns(CONFIG) == first
    assert len(calls) == 1


# --------------------------------------------------------------------------
# Signed flags: updates
# --------------------------------------------------------------------------


def test_update_signed_flags_sets_only_supplied_flags(monkeypatch):
    """A flag left as None is not written, so the two sides stay independent."""
    cursor = FakeCursor(rowcount_sequence=[3])
    _reset(monkeypatch, cursor)
    monkeypatch.setattr(
        db_storage,
        "_signed_columns",
        lambda c: {"signed_employer": True, "signed_employee": True, "signed_date": True},
    )

    updated = db_storage.update_signed_flags(
        CONFIG, ["a", "b", "c"], signed_employer=True
    )

    assert updated == 3
    query = cursor.queries[0]
    assert "signed_employer = %s" in query
    assert "signed_employee" not in query
    assert "signed_date = COALESCE" in query


def test_update_signed_flags_noops_without_ids_or_flags(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(
        db_storage, "_signed_columns", lambda c: {"signed_employer": True}
    )

    def fail(_config):  # pragma: no cover - must not be reached
        raise AssertionError("should not connect")

    monkeypatch.setattr(db_storage, "get_connection", fail)

    assert db_storage.update_signed_flags(CONFIG, [], signed_employer=True) == 0
    assert db_storage.update_signed_flags(CONFIG, ["a"]) == 0


def test_update_signed_flags_skips_absent_columns(monkeypatch):
    """On a database predating the migration, nothing is written."""
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_signed_columns", lambda c: {})

    def fail(_config):  # pragma: no cover - must not be reached
        raise AssertionError("should not connect")

    monkeypatch.setattr(db_storage, "get_connection", fail)
    assert db_storage.update_signed_flags(CONFIG, ["a"], signed_employee=True) == 0


def test_mark_signed_for_period_filters_by_employee_and_month(monkeypatch):
    cursor = FakeCursor(rowcount_sequence=[2])
    _reset(monkeypatch, cursor)
    monkeypatch.setattr(
        db_storage,
        "_signed_columns",
        lambda c: {"signed_employer": True, "signed_employee": True, "signed_date": True},
    )

    updated = db_storage.mark_signed_for_period(
        CONFIG,
        employee_name="Some Employee",
        year=2026,
        month=3,
        signed_employer=True,
        signed_employee=True,
        signed_date=datetime.date(2026, 3, 31),
    )

    assert updated == 2
    query = cursor.queries[0]
    assert "e.full_name = %s" in query
    assert "EXTRACT(YEAR FROM pe.payment_date) = %s" in query
    params = cursor.params[0]
    assert 2026 in params and 3 in params and "Some Employee" in params


def test_mark_signed_for_period_prefers_employee_code(monkeypatch):
    cursor = FakeCursor(rowcount_sequence=[1])
    _reset(monkeypatch, cursor)
    monkeypatch.setattr(
        db_storage, "_signed_columns", lambda c: {"signed_employer": True}
    )

    db_storage.mark_signed_for_period(
        CONFIG, employee_code="EMP-9", year=2026, month=1, signed_employer=True
    )

    query = cursor.queries[0]
    assert "e.employee_code = %s" in query
    assert "e.full_name" not in query


@pytest.mark.parametrize(
    "kwargs",
    [
        {"year": 2026, "month": 1},  # no employee
        {"employee_name": "X", "month": 1},  # no year
        {"employee_name": "X", "year": 2026},  # no month
    ],
)
def test_mark_signed_for_period_requires_employee_and_period(monkeypatch, kwargs):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)

    def fail(_config):  # pragma: no cover - must not be reached
        raise AssertionError("should not connect")

    monkeypatch.setattr(db_storage, "get_connection", fail)
    assert db_storage.mark_signed_for_period(CONFIG, signed_employer=True, **kwargs) == 0


def test_fetch_signed_status_summary_returns_empty_without_columns(monkeypatch):
    """Databases predating the migration get an empty result, not an error."""
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_signed_columns", lambda c: {})
    assert db_storage.fetch_signed_status_summary(CONFIG) == []


def test_fetch_signed_status_summary_counts_by_month(monkeypatch):
    rows = [(2026, 1, 10, 6, 2, 2)]
    cursor = FakeCursor(fetchall_sequence=[rows])
    _reset(monkeypatch, cursor)
    monkeypatch.setattr(
        db_storage,
        "_signed_columns",
        lambda c: {"signed_employer": True, "signed_employee": True},
    )

    assert db_storage.fetch_signed_status_summary(CONFIG) == rows
    query = cursor.queries[0]
    assert "fully_signed" in query
    assert "partially_signed" in query
    assert "unsigned_entries" in query


# --------------------------------------------------------------------------
# Period-over-period comparison
# --------------------------------------------------------------------------


def test_fetch_period_comparison_computes_deltas(monkeypatch):
    rows = [
        (2026, 3, 1200.0, 100.0, 200.0, 1400.0, 5, 3),   # current
        (2026, 2, 1000.0, 90.0, 180.0, 1180.0, 4, 3),    # previous
    ]
    cursor = FakeCursor(fetchall_sequence=[rows])
    _reset(monkeypatch, cursor)

    result = db_storage.fetch_period_comparison(CONFIG, 2026, 3)

    assert result["net_pay"]["current"] == pytest.approx(1200.0)
    assert result["net_pay"]["previous"] == pytest.approx(1000.0)
    assert result["net_pay"]["delta"] == pytest.approx(200.0)
    assert result["net_pay"]["pct_change"] == pytest.approx(20.0)
    assert result["employee_count"]["delta"] == pytest.approx(0.0)
    assert result["period"] == {"year": 2026, "month": 3}
    assert result["previous_period"] == {"year": 2026, "month": 2}


def test_fetch_period_comparison_wraps_to_previous_year(monkeypatch):
    """January's previous month is December of the prior year."""
    cursor = FakeCursor(fetchall_sequence=[[]])
    _reset(monkeypatch, cursor)

    result = db_storage.fetch_period_comparison(CONFIG, 2026, 1)

    assert result["previous_period"] == {"year": 2025, "month": 12}
    params = cursor.params[0]
    assert params[:4] == [2026, 1, 2025, 12]


def test_fetch_period_comparison_pct_is_none_without_prior_data(monkeypatch):
    """A zero previous month gives None, not an infinity."""
    rows = [(2026, 3, 500.0, 0.0, 0.0, 500.0, 2, 1)]
    cursor = FakeCursor(fetchall_sequence=[rows])
    _reset(monkeypatch, cursor)

    result = db_storage.fetch_period_comparison(CONFIG, 2026, 3)

    assert result["net_pay"]["current"] == pytest.approx(500.0)
    assert result["net_pay"]["previous"] == pytest.approx(0.0)
    assert result["net_pay"]["pct_change"] is None


def test_fetch_period_comparison_requires_a_period(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)

    def fail(_config):  # pragma: no cover - must not be reached
        raise AssertionError("should not connect")

    monkeypatch.setattr(db_storage, "get_connection", fail)
    assert db_storage.fetch_period_comparison(CONFIG, None, None) == {}


# --------------------------------------------------------------------------
# Time / workforce / payment-status analytics
# --------------------------------------------------------------------------


def test_fetch_employer_cost_ratio_guards_zero_net_pay(monkeypatch):
    rows = [(2026, 1, 1000.0, 1250.0, 1.25)]
    cursor = FakeCursor(fetchall_sequence=[rows])
    _reset(monkeypatch, cursor)

    assert db_storage.fetch_employer_cost_ratio_by_month(CONFIG) == rows
    query = cursor.queries[0]
    assert "NULLIF(SUM(pe.net_pay), 0)" in query


def test_fetch_headcount_trend_uses_all_history_for_bounds(monkeypatch):
    """Joiner/leaver bounds are computed unfiltered, so the window cannot
    turn a pre-existing employee into a joiner."""
    rows = [(2026, 1, 5, 1, 0)]
    cursor = FakeCursor(fetchall_sequence=[rows])
    _reset(monkeypatch, cursor)

    assert db_storage.fetch_headcount_trend(
        CONFIG, start_date=datetime.date(2026, 1, 1)
    ) == rows
    query = cursor.queries[0]
    bounds = query.split("monthly AS")[0]
    assert "MIN(pe.payment_date)" in bounds
    assert "MAX(pe.payment_date)" in bounds
    # The date filter belongs to the monthly CTE, not to bounds.
    assert "payment_date >=" not in bounds


def test_fetch_net_pay_distribution_aggregates_per_employee(monkeypatch):
    rows = [(2026, 1, 1500.0, 1200.0, 1000.0, 1800.0, 4)]
    cursor = FakeCursor(fetchall_sequence=[rows])
    _reset(monkeypatch, cursor)

    assert db_storage.fetch_net_pay_distribution(CONFIG) == rows
    query = cursor.queries[0]
    assert "PERCENTILE_CONT(0.5)" in query
    # Grouping per employee first stops a bonus counting as a second person.
    assert "GROUP BY year, month, pe.employee_id" in query


def test_fetch_entry_jumps_applies_both_thresholds(monkeypatch):
    rows = [("Some Employee", "EMP-1", "Salary", datetime.date(2026, 2, 1), 1000.0, 1500.0, 500.0, 50.0)]
    cursor = FakeCursor(fetchall_sequence=[rows])
    _reset(monkeypatch, cursor)

    columns, result = db_storage.fetch_entry_jumps(
        CONFIG, threshold_pct=25.0, min_amount=100.0, limit=5
    )

    assert result == rows
    query = cursor.queries[0]
    assert "LAG(net_pay) OVER" in query
    assert "PARTITION BY employee_code, document_type" in query
    # min_amount, then threshold_pct, then limit.
    assert cursor.params[0][-3:] == [100.0, 25.0, 5]


def test_fetch_entry_jumps_compares_against_own_prior_month(monkeypatch):
    """The comparison is per employee and document type, not a global average."""
    cursor = FakeCursor(fetchall_sequence=[[]])
    _reset(monkeypatch, cursor)

    db_storage.fetch_entry_jumps(CONFIG)

    query = cursor.queries[0]
    assert "prev_net_pay IS NOT NULL" in query
    assert "AVG(" not in query


# --------------------------------------------------------------------------
# Receipt merging
# --------------------------------------------------------------------------


def _make_archive(tmp_path, employee="Some Employee", year=2026, month=3):
    archive_root = tmp_path / "archive"
    emp_dir = archive_root / str(year) / f"{month:02d}" / employee
    emp_dir.mkdir(parents=True)
    return archive_root, emp_dir


def test_find_monthly_payment_pdfs_excludes_receipts(tmp_path):
    archive_root, emp_dir = _make_archive(tmp_path)
    (emp_dir / "2603_Some_Employee_Salary.pdf").write_bytes(b"%PDF-1.4\n")
    (emp_dir / "2603_Some_Employee_Bonus.pdf").write_bytes(b"%PDF-1.4\n")
    (emp_dir / "2603_Some_Employee_Receipt_receipt.pdf").write_bytes(b"%PDF-1.4\n")

    receipt = {
        "employee_name": "Some Employee",
        "paid_date": datetime.date(2026, 3, 15),
    }
    found = process_payroll.find_monthly_payment_pdfs(str(archive_root), receipt)

    names = sorted(os.path.basename(p) for p in found)
    assert names == ["2603_Some_Employee_Bonus.pdf", "2603_Some_Employee_Salary.pdf"]


def test_find_monthly_payment_pdfs_needs_a_date(tmp_path):
    archive_root, _ = _make_archive(tmp_path)
    assert process_payroll.find_monthly_payment_pdfs(
        str(archive_root), {"employee_name": "Some Employee", "paid_date": None}
    ) == []


def test_find_monthly_payment_pdfs_handles_missing_directory(tmp_path):
    receipt = {"employee_name": "Nobody", "paid_date": datetime.date(2026, 3, 1)}
    assert process_payroll.find_monthly_payment_pdfs(str(tmp_path), receipt) == []


def test_merge_receipt_records_merged_targets(tmp_path, monkeypatch):
    archive_root, emp_dir = _make_archive(tmp_path)
    salary = emp_dir / "2603_Some_Employee_Salary.pdf"
    salary.write_bytes(b"%PDF-1.4\n")
    receipt_path = emp_dir / "2603_Some_Employee_Receipt_receipt.pdf"
    receipt_path.write_bytes(b"%PDF-1.4\n")

    merged_calls = []

    def fake_merge(dest, new):
        merged_calls.append((dest, new))
        return True

    monkeypatch.setattr(process_payroll, "_merge_pdf_files", fake_merge)

    receipt = {
        "employee_name": "Some Employee",
        "paid_date": datetime.date(2026, 3, 15),
    }
    outcome = process_payroll.merge_receipt_into_monthly_pdf(
        str(archive_root), str(receipt_path), receipt
    )

    assert outcome["merged"] == [str(salary)]
    assert outcome["skipped"] == []
    assert merged_calls == [(str(salary), str(receipt_path))]


def test_merge_receipt_reports_skips_when_pdfunite_missing(tmp_path, monkeypatch):
    """Without pdfunite nothing merges, and the receipt file survives."""
    archive_root, emp_dir = _make_archive(tmp_path)
    salary = emp_dir / "2603_Some_Employee_Salary.pdf"
    salary.write_bytes(b"%PDF-1.4\n")
    receipt_path = emp_dir / "2603_Some_Employee_Receipt_receipt.pdf"
    receipt_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(process_payroll, "_merge_pdf_files", lambda dest, new: False)

    receipt = {
        "employee_name": "Some Employee",
        "paid_date": datetime.date(2026, 3, 15),
    }
    outcome = process_payroll.merge_receipt_into_monthly_pdf(
        str(archive_root), str(receipt_path), receipt
    )

    assert outcome["merged"] == []
    assert outcome["skipped"] == [str(salary)]
    assert receipt_path.exists()


def test_merge_receipt_handles_missing_receipt_file(tmp_path):
    archive_root, _ = _make_archive(tmp_path)
    outcome = process_payroll.merge_receipt_into_monthly_pdf(
        str(archive_root), str(tmp_path / "nope.pdf"), {"employee_name": "X"}
    )
    assert outcome == {"merged": [], "skipped": []}


def test_merge_receipts_after_archiving_annotates_receipts(tmp_path, monkeypatch):
    archive_root, emp_dir = _make_archive(tmp_path)
    salary = emp_dir / "2603_Some_Employee_Salary.pdf"
    salary.write_bytes(b"%PDF-1.4\n")
    receipt_path = emp_dir / "2603_Some_Employee_Receipt_receipt.pdf"
    receipt_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(process_payroll, "_merge_pdf_files", lambda dest, new: True)

    receipts = [
        {
            "employee_name": "Some Employee",
            "paid_date": datetime.date(2026, 3, 15),
            "archive_path": str(receipt_path),
        },
        {"employee_name": "No Archive", "paid_date": datetime.date(2026, 3, 15)},
    ]
    process_payroll._merge_receipts_after_archiving(str(archive_root), receipts)

    assert receipts[0]["merged_into"] == [str(salary)]
    assert "merged_into" not in receipts[1]


# --------------------------------------------------------------------------
# GUI-side signed detection and comparison rendering
# --------------------------------------------------------------------------


@pytest.fixture
def gui():
    from payroll_gui import PayrollProcessorGUI

    return PayrollProcessorGUI.__new__(PayrollProcessorGUI)


@pytest.mark.parametrize(
    "doc_type,expected",
    [
        ("SIGNED", (True, True)),
        ("ΥΠΟΓΡΑΦΕΣ", (True, True)),
        ("E9", (True, None)),
        ("ΠΡΟΣΛΗΨΗ", (True, None)),
        ("ΕΝΤΥΠΟ3", (True, None)),
        ("GOVGR", (True, None)),
    ],
)
def test_signed_flags_for_doc_type(gui, doc_type, expected):
    assert gui._signed_flags_for_doc_type(doc_type) == expected


def test_signed_flags_ignore_the_unclassified_fallback(gui):
    """_classify_signed_doc returns "Signed" for anything it cannot identify.

    That differs only by case from the explicit "SIGNED" match, so the mapping
    must not upper-case; otherwise every unrecognised PDF would be recorded as
    signed by both parties.
    """
    doc_type, _ = gui._classify_signed_doc("random_document.pdf")
    assert doc_type == "Signed"
    assert gui._signed_flags_for_doc_type(doc_type) == (None, None)

    explicit, _ = gui._classify_signed_doc("contract_signed.pdf")
    assert explicit == "SIGNED"
    assert gui._signed_flags_for_doc_type(explicit) == (True, True)


def test_format_comparison_renders_delta_and_percent(gui):
    change = {"current": 1200.0, "previous": 1000.0, "delta": 200.0, "pct_change": 20.0}
    assert gui._format_comparison(change) == "€ 1,200.00  (+200.00, +20.0%)"


def test_format_comparison_marks_missing_baseline(gui):
    change = {"current": 500.0, "previous": 0.0, "delta": 500.0, "pct_change": None}
    assert gui._format_comparison(change) == "€ 500.00  (+500.00, n/a)"


def test_format_comparison_handles_counts_and_decreases(gui):
    change = {"current": 7, "previous": 9, "delta": -2, "pct_change": -22.2}
    assert gui._format_comparison(change, as_currency=False) == "7  (−2, −22.2%)"


def test_format_comparison_handles_absent_metric(gui):
    assert gui._format_comparison(None) == "—"
    assert gui._format_comparison({}) == "—"


def test_apply_signed_flags_skips_when_database_disabled(gui):
    gui.db_config = {"enabled": False}
    assert gui._apply_signed_flags("SIGNED", "Some Employee", datetime.date(2026, 3, 1)) == 0


def test_apply_signed_flags_skips_unidentified_documents(gui, monkeypatch):
    gui.db_config = {"enabled": True}

    def fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("should not write flags")

    monkeypatch.setattr(db_storage, "mark_signed_for_period", fail)
    assert gui._apply_signed_flags("Signed", "Some Employee", datetime.date(2026, 3, 1)) == 0
    assert gui._apply_signed_flags("SIGNED", None, datetime.date(2026, 3, 1)) == 0


def test_apply_signed_flags_passes_period_and_flags(gui, monkeypatch):
    gui.db_config = {"enabled": True}
    captured = {}

    def fake_mark(config, **kwargs):
        captured.update(kwargs)
        return 4

    monkeypatch.setattr(db_storage, "mark_signed_for_period", fake_mark)

    assert gui._apply_signed_flags("E9", "Some Employee", datetime.date(2026, 3, 20)) == 4
    assert captured["employee_name"] == "Some Employee"
    assert captured["year"] == 2026
    assert captured["month"] == 3
    assert captured["signed_employer"] is True
    assert captured["signed_employee"] is None


def test_apply_signed_flags_survives_db_errors(gui, monkeypatch):
    """Archiving must not fail because the database is unreachable."""
    gui.db_config = {"enabled": True}

    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(db_storage, "mark_signed_for_period", boom)
    assert gui._apply_signed_flags("SIGNED", "Some Employee", datetime.date(2026, 3, 1)) == 0


def test_fetch_jump_alerts_reshapes_rows(gui, monkeypatch):
    gui.db_config = {"enabled": True}
    rows = [
        ("Some Employee", "EMP-1", "Salary", datetime.date(2026, 2, 1), 1000.0, 1500.0, 500.0, 50.0),
        ("Other Employee", "EMP-2", "Bonus", datetime.date(2026, 2, 1), 800.0, 400.0, -400.0, -50.0),
    ]
    monkeypatch.setattr(
        db_storage, "fetch_entry_jumps", lambda *a, **k: (["c"], rows)
    )

    alerts = gui._fetch_jump_alerts()

    assert len(alerts) == 2
    assert alerts[0][0] == "Sudden Jump ▲ 50%"
    assert alerts[1][0] == "Sudden Jump ▼ 50%"
    # Reshaped to the six-column alert layout, insurance left blank.
    assert all(len(row) == 6 for row in alerts)
    assert alerts[0][1] == "Some Employee"
    assert alerts[0][5] == ""


def test_fetch_jump_alerts_degrades_quietly(gui, monkeypatch):
    """A failing query must not take the whole dashboard down."""
    gui.db_config = {"enabled": True}

    def boom(*args, **kwargs):
        raise RuntimeError("no such column")

    monkeypatch.setattr(db_storage, "fetch_entry_jumps", boom)
    assert gui._fetch_jump_alerts() == []
