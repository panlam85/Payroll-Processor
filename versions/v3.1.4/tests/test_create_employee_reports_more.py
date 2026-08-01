import sys

import pandas as pd

import create_employee_reports


def test_load_payroll_data_and_prepare_summary(tmp_path, capsys):
    csv1 = tmp_path / "one.csv"
    csv2 = tmp_path / "two.csv"

    pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane",
                "Date": "01/01/2024",
                "DocumentType": "Unknown",
                "BasicSalary": "1000",
                "TotalEarnings": "1200",
                "NetPay": "900",
            }
        ]
    ).to_csv(csv1, index=False)

    pd.DataFrame(
        [
            {
                "EmployeeCode": "E2",
                "EmployeeName": "John",
                "Date": "15/01/2024",
                "DocumentType": "Bonus",
                "BasicSalary": "0",
                "TotalEarnings": "500",
                "NetPay": "500",
            }
        ]
    ).to_csv(csv2, index=False)

    df = create_employee_reports.load_payroll_data([str(csv1), str(csv2)])
    assert len(df) == 2

    summary = create_employee_reports.prepare_summary(df)
    assert not summary.empty
    assert "DocumentType" in summary.columns

    empty_summary = create_employee_reports.prepare_summary(pd.DataFrame())
    assert empty_summary.empty


def test_write_reports(tmp_path, capsys):
    summary_df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane",
                "Month": "2024-01",
                "DocumentType": "Salary",
                "BasicSalary": 1000,
                "TotalEarnings": 1200,
                "NetPay": 900,
                "EFKAEmployee": 10,
                "EFKAEmployer": 20,
                "TEKAEmployee": 3,
                "TEKAEmployer": 4,
            }
        ]
    )
    out_summary = tmp_path / "summary.xlsx"
    create_employee_reports.write_employee_reports(summary_df, str(out_summary))
    assert out_summary.exists()

    detail_df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane",
                "Date": "01/01/2024",
                "DocumentType": "Unknown",
                "BasicSalary": "1000",
                "TotalEarnings": "1200",
                "NetPay": "900",
            }
        ]
    )
    out_detail = tmp_path / "detail.xlsx"
    create_employee_reports.write_detail_report(detail_df, str(out_detail))
    assert out_detail.exists()

    create_employee_reports.write_employee_reports(pd.DataFrame(), str(tmp_path / "empty.xlsx"))
    create_employee_reports.write_detail_report(pd.DataFrame(), str(tmp_path / "empty_detail.xlsx"))


def test_load_payroll_data_bad_csv(tmp_path, capsys):
    bad_path = tmp_path / "missing.csv"
    df = create_employee_reports.load_payroll_data([str(bad_path)])
    assert df.empty
    captured = capsys.readouterr().out
    assert "Warning: failed to read" in captured


def test_main_paths(tmp_path, monkeypatch, capsys):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    csv_path = input_dir / "data.csv"
    pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane",
                "Date": "01/01/2024",
                "DocumentType": "Salary",
                "BasicSalary": 1000,
                "TotalEarnings": 1200,
                "NetPay": 900,
            }
        ]
    ).to_csv(csv_path, index=False)

    out_summary = tmp_path / "summary.xlsx"
    out_detail = tmp_path / "detail.xlsx"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--input-dir",
            str(input_dir),
            "--out-xlsx",
            str(out_summary),
            "--detail-xlsx",
            str(out_detail),
        ],
    )
    create_employee_reports.main()
    assert out_summary.exists()
    assert out_detail.exists()

    monkeypatch.setattr(sys, "argv", ["prog", "--input-dir", str(tmp_path / "missing")])
    create_employee_reports.main()
    assert "is not a valid directory" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["prog"])
    create_employee_reports.main()
    assert "No CSV files provided" in capsys.readouterr().out
