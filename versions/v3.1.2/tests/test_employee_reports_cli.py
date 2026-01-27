import sys

import pandas as pd

import create_employee_reports as cer


def test_main_no_csvs(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["create_employee_reports.py"])
    cer.main()
    captured = capsys.readouterr()
    assert "No CSV files provided" in captured.out


def test_main_invalid_input_dir(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["create_employee_reports.py", "--input-dir", "/no/such/dir"])
    cer.main()
    captured = capsys.readouterr()
    assert "is not a valid directory" in captured.out


def test_main_with_input_dir_and_detail(tmp_path, monkeypatch):
    csv_dir = tmp_path / "csvs"
    csv_dir.mkdir()
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
    csv_path = csv_dir / "data.csv"
    df.to_csv(csv_path, index=False)

    out_summary = tmp_path / "summary.xlsx"
    out_detail = tmp_path / "detail.xlsx"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_employee_reports.py",
            "--input-dir",
            str(csv_dir),
            "--out-xlsx",
            str(out_summary),
            "--detail-xlsx",
            str(out_detail),
        ],
    )
    cer.main()
    assert out_summary.exists()
    assert out_detail.exists()
