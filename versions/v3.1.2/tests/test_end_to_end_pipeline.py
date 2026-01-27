import zipfile

import pandas as pd

import create_employee_reports as cer
import process_payroll as pp


def test_end_to_end_zip_to_reports(tmp_path, monkeypatch):
    zip_path = tmp_path / "input.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("payroll1.pdf", b"dummy")
        zf.writestr("payroll2.pdf", b"dummy")

    sample_text = """\
Κωδικός : 001
Ονοματεπώνυμο : ALICE TEST
ΒΑΣΙΚΟΣ ΜΙΣΘΟΣ : 1.000,00
ΣΥΝΟΛΟ ΑΠΟΔΟΧΩΝ ΠΕΡΙΟΔΟΥ : 1.200,00
ΠΛΗΡΩΤΕΟ : 900,00
ΗΜΕΡ/ ΝΙΑ : 05/01/2024
"""

    def fake_check_output(args, **_kwargs):
        assert args[0] == "pdftotext"
        return sample_text

    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(pp, "parse_insurance_claim", lambda *_: None)
    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda *_: None)

    df, receipts, claims = pp.process_zip(str(zip_path), str(tmp_path))
    assert receipts == []
    assert claims == []
    assert not df.empty

    csv_path = tmp_path / "data.csv"
    df.to_csv(csv_path, index=False)

    combined = cer.load_payroll_data([str(csv_path)])
    summary = cer.prepare_summary(combined)

    out_summary = tmp_path / "summary.xlsx"
    out_detail = tmp_path / "detail.xlsx"
    cer.write_employee_reports(summary, str(out_summary))
    cer.write_detail_report(combined, str(out_detail))

    assert out_summary.exists()
    assert out_summary.stat().st_size > 0
    assert out_detail.exists()
    assert out_detail.stat().st_size > 0
