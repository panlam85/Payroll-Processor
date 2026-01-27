import datetime
import os

import process_payroll as pp


def test_build_archive_filename_defaults_to_salary():
    entry = {"EmployeeName": "Alice", "Date": "01/01/2024", "DocumentType": None}
    name = pp._build_archive_filename(entry)
    assert "Salary" in name


def test_build_archive_filename_invalid_date():
    entry = {"EmployeeName": "Alice", "Date": "bad"}
    name = pp._build_archive_filename(entry)
    assert name.startswith("unknown_Alice")


def test_derive_archive_dir_unknown_date():
    entry = {"EmployeeName": "Alice", "Date": None}
    path = pp._derive_archive_dir("/tmp/archive", entry)
    assert path.endswith(os.path.join("unknown", "unknown", "Alice"))


def test_archive_pdf_for_claim_skips_existing(tmp_path):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    pdf_path = tmp_path / "claim.pdf"
    pdf_path.write_bytes(b"dummy")
    claim = {"claim_year": 2024, "claim_month": 1, "claim_type": "EFKA", "tpte_code": "RF1"}
    first = pp._archive_pdf_for_claim(str(archive_root), str(pdf_path), claim)
    assert first["copied"] is True
    second = pp._archive_pdf_for_claim(str(archive_root), str(pdf_path), claim)
    assert second["copied"] is False


def test_archive_pdf_for_receipt_with_date(tmp_path):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    pdf_path = tmp_path / "receipt.pdf"
    pdf_path.write_bytes(b"dummy")
    receipt = {
        "employee_name": "Alice",
        "paid_date": datetime.date(2024, 1, 5),
    }
    info = pp._archive_pdf_for_receipt(str(archive_root), str(pdf_path), receipt)
    assert info["copied"] is True
    assert os.path.exists(info["path"])
    assert os.path.join("2024", "01", "Alice") in info["path"]


def test_parse_transfer_receipt_alt_amount_patterns(monkeypatch):
    sample_text = """\
Κωδικός Συναλλαγής
Κύριος Δικαιούχος: ΝΙΚΟΣ ΠΑΠΑΣ
Ποσό συναλλαγής 1.000,50
Στις 05/02/2025
"""
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    receipt = pp.parse_transfer_receipt("/tmp/receipt.pdf")
    assert receipt["amount"] == 1000.50


def test_parse_transfer_receipt_amount_eur(monkeypatch):
    sample_text = """\
Μεταφορά σε IBAN
Κύριος Δικαιούχος: ΝΙΚΟΣ ΠΑΠΑΣ
100,00 EUR
Στις 05/02/2025
"""
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    receipt = pp.parse_transfer_receipt("/tmp/receipt.pdf")
    assert receipt["amount"] == 100.0


def test_parse_insurance_claim_detects_efka(monkeypatch):
    sample_text = """\
ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
Ημερομηνία Υποβολής 15/03/2024
ΠΕΡΙΟΔΟΣ ΑΠΟ 02/2024
Σύνολο Εισφορών 123,45
"""
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    claim = pp.parse_insurance_claim("/tmp/claim.pdf")
    assert claim["claim_type"] == "EFKA"


def test_parse_transfer_receipt_rejects_bad_amount(monkeypatch):
    sample_text = """\
Κωδικός Συναλλαγής
Κύριος Δικαιούχος: ΝΙΚΟΣ ΠΑΠΑΣ
Ποσό: bad EUR
Στις 05/02/2025
"""
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    assert pp.parse_transfer_receipt("/tmp/receipt.pdf") is None
