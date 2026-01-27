import pandas as pd

import create_employee_reports as cer


def test_load_payroll_data_empty_returns_empty():
    df = cer.load_payroll_data([])
    assert df.empty


def test_prepare_summary_empty():
    df = pd.DataFrame()
    summary = cer.prepare_summary(df)
    assert summary.empty


def test_prepare_summary_missing_numeric_cols():
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "Date": "01/02/2024",
                "DocumentType": None,
            }
        ]
    )
    summary = cer.prepare_summary(df)
    assert "BasicSalary" in summary.columns
    assert "TotalEarnings" in summary.columns
    assert "NetPay" in summary.columns
    assert "Total" in summary["DocumentType"].values


def test_write_employee_reports_no_data(tmp_path):
    out_path = tmp_path / "out.xlsx"
    cer.write_employee_reports(pd.DataFrame(), str(out_path))
    assert not out_path.exists()


def test_write_detail_report_no_data(tmp_path):
    out_path = tmp_path / "detail.xlsx"
    cer.write_detail_report(pd.DataFrame(), str(out_path))
    assert not out_path.exists()


def test_write_employee_reports_handles_missing_name(tmp_path):
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": None,
                "Date": "01/01/2024",
                "DocumentType": "Payslip",
                "NetPay": 1000,
            }
        ]
    )
    summary = cer.prepare_summary(df)
    out_path = tmp_path / "summary.xlsx"
    cer.write_employee_reports(summary, str(out_path))
    assert summary.empty
    assert not out_path.exists()


def test_sanitize_sheet_name_trims_quotes():
    cleaned = cer._sanitize_sheet_name("'Name'", fallback="Fallback")
    assert cleaned == "Name"


def test_unique_sheet_name_suffixes():
    used = set()
    first = cer._unique_sheet_name("Name", used)
    second = cer._unique_sheet_name("Name", used)
    assert first == "Name"
    assert second.startswith("Name")
