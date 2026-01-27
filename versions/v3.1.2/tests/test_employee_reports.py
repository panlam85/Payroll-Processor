import pandas as pd

import create_employee_reports as cer


def test_load_payroll_data_skips_missing_files(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("EmployeeCode,EmployeeName,Date,NetPay\n1,Alice,01/01/2024,1000")
    df = cer.load_payroll_data([str(csv_path), str(tmp_path / "missing.csv")])
    assert len(df) == 1
    assert df.loc[0, "EmployeeName"] == "Alice"


def test_prepare_summary_adds_totals_and_months():
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "Date": "15/01/2024",
                "DocumentType": "Payslip",
                "NetPay": "1000",
            },
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "Date": "20/01/2024",
                "DocumentType": "Unknown",
                "NetPay": "200",
            },
        ]
    )
    summary = cer.prepare_summary(df)
    assert set(summary["Month"]) == {"2024-01"}
    assert "Total" in summary["DocumentType"].values
    totals = summary[summary["DocumentType"] == "Total"]
    assert totals["NetPay"].iloc[0] == 1200.0


def test_unique_sheet_name_truncates_and_dedupes():
    used = set()
    name = "A" * 40
    first = cer._unique_sheet_name(name, used)
    second = cer._unique_sheet_name(name, used)
    assert len(first) <= 31
    assert len(second) <= 31
    assert first != second


def test_sanitize_sheet_name_replaces_invalid_chars():
    cleaned = cer._sanitize_sheet_name("Bad/Name*", fallback="Fallback")
    assert cleaned == "Bad-Name-"
