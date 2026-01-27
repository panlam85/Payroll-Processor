import sys
import zipfile

import pandas as pd

import process_payroll as pp


def test_main_accepts_tuple_from_process_zip(tmp_path, monkeypatch):
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
                "NetPay": "900,00",
            }
        ]
    )

    def fake_process_zip(zip_path, tmpdir):
        return (df, [], [])

    monkeypatch.setattr(pp, "process_zip", fake_process_zip)

    out_csv = tmp_path / "out.csv"
    monkeypatch.setattr(sys, "argv", ["process_payroll.py", "--input-dir", str(input_dir), "--out-csv", str(out_csv)])
    pp.main()

    assert out_csv.exists()
    written = pd.read_csv(out_csv)
    assert written.loc[0, "SourceArchive"] == "data.zip"
