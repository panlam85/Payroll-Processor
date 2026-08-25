import datetime

import pandas as pd

import db_storage


def test_append_date_range():
    conditions = []
    params = []
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 2, 1)
    db_storage._append_date_range(conditions, params, "paid_date", start_date=start, end_date=end)
    assert conditions == ["paid_date >= %s", "paid_date <= %s"]
    assert params == [start, end]


def test_append_claim_month_range():
    conditions = []
    params = []
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 2, 1)
    db_storage._append_claim_month_range(conditions, params, start_date=start, end_date=end)
    assert len(conditions) == 2
    assert params == [2024, 2024, 1, 2024, 2024, 2]


def test_append_search_conditions_string():
    conditions = []
    params = []
    db_storage._append_search_conditions(conditions, params, "alice", ["employee_name", "employee_code"])
    assert "ILIKE" in conditions[0]
    assert params == ["%alice%", "%alice%"]


def test_append_search_conditions_clauses():
    conditions = []
    params = []
    search = [{"term": "alice", "op": "AND"}, {"term": "bob", "op": "NOT"}]
    db_storage._append_search_conditions(conditions, params, search, ["employee_name"])
    assert conditions
    assert params == ["%alice%", "%bob%"]


def test_insurance_period_columns(monkeypatch):
    monkeypatch.setattr(db_storage, "_insurance_claims_columns", lambda config: {"period_year": True, "period_month": True})
    assert db_storage._insurance_period_columns({"host": "x"}) == ("period_year", "period_month")


def test_prepare_staging_rows_normalizes_dataframe():
    df = pd.DataFrame([
        {
            "EmployeeCode": " 1 ",
            "EmployeeName": " Alice ",
            "DocumentType": None,
            "Date": "01/01/2024",
            "BasicSalary": "100",
            "TotalEarnings": "150",
            "NetPay": "120",
            "EFKAEmployee": "10",
            "EFKAEmployer": "20",
            "TEKAEmployee": "1",
            "TEKAEmployer": "2",
            "SourcePDF": "file.pdf",
        }
    ])
    columns, rows = db_storage._prepare_staging_rows(df)
    assert "employee_code" in columns
    assert rows[0][columns.index("employee_code")] == "1"
    assert rows[0][columns.index("document_type")] == ""
    assert rows[0][columns.index("basic_salary")] == 100.0
