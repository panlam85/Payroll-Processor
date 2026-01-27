import os
import sys
import zipfile

import pandas as pd

import process_payroll as pp


def test_main_no_zip_files(tmp_path, capsys, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    out_csv = tmp_path / "out.csv"

    monkeypatch.setattr(sys, "argv", ["process_payroll.py", "--input-dir", str(input_dir), "--out-csv", str(out_csv)])
    pp.main()
    captured = capsys.readouterr()
    assert "No payroll records found" in captured.out
    assert not out_csv.exists()


def test_main_writes_csv_and_normalizes(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    zip_path = input_dir / "data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("dummy.pdf", b"dummy")

    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "1",
                "EmployeeName": "Alice",
                "Date": "01/01/2024",
                "BasicSalary": "1.000,00",
                "TotalEarnings": "1.200,00",
                "NetPay": "900,00",
                "EFKAEmployee": "10,00",
                "EFKAEmployer": "20,00",
                "TEKAEmployee": "1,00",
                "TEKAEmployer": "2,00",
            }
        ]
    )

    def fake_process_zip(zip_path, tmpdir):
        return df

    monkeypatch.setattr(pp, "process_zip", fake_process_zip)

    out_csv = tmp_path / "out.csv"
    monkeypatch.setattr(sys, "argv", ["process_payroll.py", "--input-dir", str(input_dir), "--out-csv", str(out_csv)])
    pp.main()

    assert out_csv.exists()
    written = pd.read_csv(out_csv)
    assert written.loc[0, "BasicSalary"] == 1000.0
    assert written.loc[0, "NetPay"] == 900.0
    assert written.loc[0, "SourceArchive"] == "data.zip"


def test_process_pdf_file_unsplit_fallback(monkeypatch, tmp_path):
    pdf_path = tmp_path / "slip.pdf"
    pdf_path.write_bytes(b"dummy")

    slips = [
        {"EmployeeCode": "1", "EmployeeName": "Alice", "Date": "01/01/2024"},
        {"EmployeeCode": "2", "EmployeeName": "Bob", "Date": "01/01/2024"},
    ]

    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda *_: None)
    monkeypatch.setattr(pp, "parse_insurance_claim", lambda *_: None)
    monkeypatch.setattr(pp, "classify_document", lambda *_: "Payslip")
    monkeypatch.setattr(pp, "parse_pdf", lambda *_: slips)
    monkeypatch.setattr(pp, "_split_pdf_pages", lambda *_: [])

    calls = []

    def record_archive(archive_root_value, file_path, entry, **kwargs):
        calls.append((file_path, kwargs))

    monkeypatch.setattr(pp, "_archive_pdf_for_entry", record_archive)

    df, claims, receipts = pp.process_pdf_file(str(pdf_path), str(tmp_path), archive_root=str(tmp_path))
    assert len(df) == 2
    assert len(calls) == 1
    assert calls[0][1].get("merge_if_exists") is True
