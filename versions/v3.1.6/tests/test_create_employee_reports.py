import pandas as pd

import create_employee_reports


def test_prepare_summary_groups_and_adds_totals():
    df = pd.DataFrame([
        {
            "EmployeeCode": "1",
            "EmployeeName": "Alice",
            "Date": "01/01/2024",
            "DocumentType": None,
            "BasicSalary": "100",
            "TotalEarnings": "150",
            "NetPay": "120",
            "EFKAEmployee": "10",
            "EFKAEmployer": "20",
            "TEKAEmployee": "1",
            "TEKAEmployer": "2",
        },
        {
            "EmployeeCode": "1",
            "EmployeeName": "Alice",
            "Date": "15/01/2024",
            "DocumentType": "Bonus",
            "BasicSalary": "0",
            "TotalEarnings": "50",
            "NetPay": "40",
            "EFKAEmployee": "0",
            "EFKAEmployer": "0",
            "TEKAEmployee": "0",
            "TEKAEmployer": "0",
        },
    ])
    summary = create_employee_reports.prepare_summary(df)
    total_row = summary[(summary["DocumentType"] == "Total") & (summary["Month"] == "2024-01")].iloc[0]
    assert total_row["TotalEarnings"] == 200.0
    assert total_row["NetPay"] == 160.0
    assert "Salary" in set(summary["DocumentType"])


def test_sanitize_sheet_name_strips_invalid_chars_and_quotes():
    raw = "'[Bad]:Name?'"
    cleaned = create_employee_reports._sanitize_sheet_name(raw, fallback="Fallback")
    assert "[" not in cleaned and "]" not in cleaned
    assert ":" not in cleaned and "?" not in cleaned
    assert cleaned == "-Bad--Name-"


def test_unique_sheet_name_dedupes_with_suffix():
    used = set()
    first = create_employee_reports._unique_sheet_name("Employee (1)", used)
    second = create_employee_reports._unique_sheet_name("Employee (1)", used)
    assert first == "Employee (1)"
    assert second.startswith("Employee (1)")
    assert second != first
    assert len(second) <= 31


def test_unique_sheet_name_is_case_insensitive_like_excel():
    used = set()
    first = create_employee_reports._unique_sheet_name("Alice (E1)", used)
    second = create_employee_reports._unique_sheet_name("alice (E1)", used)

    assert first == "Alice (E1)"
    assert second.casefold() != first.casefold()
    assert len(second) <= 31


def test_prepare_summary_keeps_code_only_employee():
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": None,
                "Date": "01/01/2026",
                "DocumentType": "Salary",
                "BasicSalary": 1000,
                "TotalEarnings": 1200,
                "NetPay": 900,
            }
        ]
    )

    summary = create_employee_reports.prepare_summary(df)

    assert len(summary) == 2
    assert set(summary["EmployeeName"]) == {"Employee E1"}
    assert set(summary["DocumentType"]) == {"Salary", "Total"}


def test_prepare_summary_labels_missing_date_as_unknown_month():
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Synthetic Employee",
                "Date": None,
                "DocumentType": "Salary",
                "NetPay": 900,
            }
        ]
    )

    summary = create_employee_reports.prepare_summary(df)

    assert set(summary["Month"]) == {"Unknown"}
