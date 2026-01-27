import os

import process_payroll as pp


def test_extract_iban_empty_returns_none():
    assert pp._extract_iban("") is None


def test_extract_beneficiary_name_rejects_non_letters():
    text = """\
Κύριος Δικαιούχος: 12345
"""
    assert pp._extract_beneficiary_name(text) is None


def test_extract_payroll_period_with_year_in_text():
    year, month = pp._extract_payroll_period("Payroll MAR 2023")
    assert (year, month) == (2023, 3)


def test_classify_document_url_encoded_variants():
    assert pp.classify_document("#U0395#U03A0#U0399.pdf") == "VacationAllowance"
    assert pp.classify_document("#U0391#U03A0#U0396.pdf") == "UnusedLeaveCompensation"
    assert pp.classify_document("#U0391#U03A0#U0394.pdf") == "Payslip"


def test_sanitize_segment_none():
    assert pp._sanitize_segment(None) == "unknown"


def test_derive_claim_archive_dir_unknown_year():
    path = pp._derive_claim_archive_dir("/tmp/archive", {"claim_year": "bad"})
    assert path.endswith(os.path.join("unknown", "Insurance"))


def test_archive_pdf_for_entry_no_merge_when_exists(tmp_path):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    entry = {"EmployeeName": "Alice", "Date": "01/01/2024", "DocumentType": "Payslip"}
    dest_dir = archive_root / "2024" / "01" / "Alice"
    dest_dir.mkdir(parents=True)
    dest_path = dest_dir / "2401_Alice_Payslip.pdf"
    dest_path.write_bytes(b"old")

    file_path = tmp_path / "file.pdf"
    file_path.write_bytes(b"new")

    pp._archive_pdf_for_entry(str(archive_root), str(file_path), entry, merge_if_exists=False)
    assert dest_path.read_bytes() == b"old"


def test_merge_pdf_files_removes_temp_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdfunite")
    dest = tmp_path / "dest.pdf"
    new = tmp_path / "new.pdf"
    temp_path = tmp_path / "dest.pdf.tmp"
    temp_path.write_bytes(b"temp")

    def raise_error(*args, **kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr(pp.subprocess, "check_call", raise_error)
    assert pp._merge_pdf_files(str(dest), str(new)) is False
    assert not temp_path.exists()


def test_parse_insurance_claim_no_pdftotext(monkeypatch):
    monkeypatch.setattr(pp.shutil, "which", lambda *_: None)
    assert pp.parse_insurance_claim("/tmp/claim.pdf") is None


def test_parse_transfer_receipt_no_pdftotext(monkeypatch):
    monkeypatch.setattr(pp.shutil, "which", lambda *_: None)
    assert pp.parse_transfer_receipt("/tmp/receipt.pdf") is None
