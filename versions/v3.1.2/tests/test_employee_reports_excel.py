import pandas as pd

import create_employee_reports as cer


def test_write_detail_report_creates_file(tmp_path):
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "Date": "01/01/2024",
                "DocumentType": "Payslip",
                "NetPay": 1000,
            }
        ]
    )
    out_path = tmp_path / "detail.xlsx"
    cer.write_detail_report(df, str(out_path))
    assert out_path.exists()


def test_write_employee_reports_creates_file(tmp_path):
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "Date": "15/01/2024",
                "DocumentType": "Payslip",
                "NetPay": 1000,
            }
        ]
    )
    summary = cer.prepare_summary(df)
    out_path = tmp_path / "summary.xlsx"
    cer.write_employee_reports(summary, str(out_path))
    assert out_path.exists()
