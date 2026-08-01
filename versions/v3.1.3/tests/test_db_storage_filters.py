"""Coverage for the optional filter branches of the analytics fetch helpers.

The existing suites call these functions with no filters, so the
`if document_type` / `if employee_code` / `elif employee_name` arms never
execute. Each case here calls one function with its optional filters set
and asserts the corresponding predicate reaches the generated SQL.
"""

import datetime

import pytest

import db_storage

from test_db_storage_full import ConnectionFactory, FakeCursor, _clear_caches


CONFIG = {"host": "db", "port": 5432, "database": "payroll", "user": "me"}
DOC_TYPE = "Salary"


# (function name, positional args after config, extra kwargs)
FILTERED_CALLS = [
    ("fetch_month_totals_by_year", (3,), {}),
    ("fetch_paid_unpaid_totals", (), {}),
    (
        "fetch_unpaid_aging_buckets",
        (datetime.date(2026, 6, 30),),
        {},
    ),
    ("fetch_avg_days_to_paid_by_month", (), {}),
    ("fetch_employer_costs_by_employee", (), {}),
    ("fetch_document_type_breakdown", (), {}),
    ("fetch_kpi_totals", (), {}),
    ("fetch_payment_heatmap", (2026, 4), {}),
    ("fetch_payroll_entries", (), {}),
    ("fetch_duplicate_payroll_entries", (), {}),
]


@pytest.mark.parametrize("func_name,args,kwargs", FILTERED_CALLS)
def test_document_type_filter_reaches_sql(monkeypatch, func_name, args, kwargs):
    """Passing document_type adds the predicate and binds the value."""
    _clear_caches()
    cursor = FakeCursor(fetchall_sequence=[[]], fetchone_sequence=[None])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    func = getattr(db_storage, func_name)
    func(CONFIG, *args, document_type=DOC_TYPE, **kwargs)

    assert cursor.queries, f"{func_name} issued no query"
    combined = " ".join(cursor.queries)
    assert "pe.document_type = %s" in combined, f"{func_name} dropped the filter"

    bound = [p for params in cursor.params if params for p in params]
    assert DOC_TYPE in bound, f"{func_name} did not bind document_type"


def test_kpi_totals_filters_by_employee_code(monkeypatch):
    """employee_code takes the first arm of the employee filter."""
    _clear_caches()
    cursor = FakeCursor(fetchone_sequence=[(0, 0, 0)])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    db_storage.fetch_kpi_totals(CONFIG, employee_code="EMP-7")

    combined = " ".join(cursor.queries)
    assert "e.employee_code = %s" in combined
    assert "e.full_name = %s" not in combined
    bound = [p for params in cursor.params if params for p in params]
    assert "EMP-7" in bound


def test_kpi_totals_falls_back_to_employee_name(monkeypatch):
    """Without a code, the elif arm filters on the employee name instead."""
    _clear_caches()
    cursor = FakeCursor(fetchone_sequence=[(0, 0, 0)])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    db_storage.fetch_kpi_totals(CONFIG, employee_name="Some Employee")

    combined = " ".join(cursor.queries)
    assert "e.full_name = %s" in combined
    assert "e.employee_code = %s" not in combined
    bound = [p for params in cursor.params if params for p in params]
    assert "Some Employee" in bound


def test_kpi_totals_prefers_code_over_name(monkeypatch):
    """When both are supplied the code wins and the name is ignored."""
    _clear_caches()
    cursor = FakeCursor(fetchone_sequence=[(0, 0, 0)])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    db_storage.fetch_kpi_totals(
        CONFIG, employee_code="EMP-7", employee_name="Some Employee"
    )

    combined = " ".join(cursor.queries)
    assert "e.employee_code = %s" in combined
    assert "e.full_name = %s" not in combined
    bound = [p for params in cursor.params if params for p in params]
    assert "Some Employee" not in bound
