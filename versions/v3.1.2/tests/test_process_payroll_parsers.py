import datetime
import os

import process_payroll as pp


def test_parse_transfer_receipt_happy_path(monkeypatch):
    sample_text = """\
Κωδικός Συναλλαγής
Κύριος Δικαιούχος: ΝΙΚΟΣ ΠΑΠΑΣ
Ποσό: 1.234,56 EUR
Εκτέλεση Στις 05/02/2025
Προς Λογαριασμό: GR12 3456 7890 1234 5678 9012
ΜΙΣΘΟΔΟΣΙΑ DEC 2024
"""
    monkeypatch.setattr(pp.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    receipt = pp.parse_transfer_receipt("/tmp/receipt.pdf")
    assert receipt["employee_name"] == "ΝΙΚΟΣ ΠΑΠΑΣ"
    assert receipt["amount"] == 1234.56
    assert receipt["paid_date"] == datetime.date(2025, 2, 5)
    assert receipt["iban"].startswith("GR12")
    # Year uses the first year match in the full text (05/02/2025 appears earlier).
    assert receipt["payroll_year"] == 2025
    assert receipt["payroll_month"] == 12


def test_parse_transfer_receipt_rejects_non_receipts(monkeypatch):
    monkeypatch.setattr(pp.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: "Not a receipt")
    assert pp.parse_transfer_receipt("/tmp/other.pdf") is None


def test_parse_insurance_claim_happy_path(monkeypatch):
    sample_text = """\
ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
ΤΕΚΑ
Ημερομηνία Υποβολής 15/03/2024
ΠΕΡΙΟΔΟΣ ΑΠΟ 02/2024
Σύνολο Αποδοχών 1.000,50
Σύνολο Εισφορών 123,45
Τ.Π.Τ.Ε. RF 123 456 789
"""
    monkeypatch.setattr(pp.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    claim = pp.parse_insurance_claim("/tmp/claim.pdf")
    assert claim["claim_type"] == "TEKA"
    assert claim["claim_year"] == 2024
    assert claim["claim_month"] == 2
    assert claim["total_earnings"] == 1000.50
    assert claim["total_contributions"] == 123.45
    assert claim["tpte_code"] == "RF123456789"
    assert claim["submission_date"] == datetime.date(2024, 3, 15)


def test_parse_insurance_claim_rejects_non_claim(monkeypatch):
    monkeypatch.setattr(pp.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: "Some other PDF")
    assert pp.parse_insurance_claim("/tmp/other.pdf") is None


def test_archive_helpers_build_and_copy(tmp_path):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"dummy")

    claim = {
        "claim_year": 2024,
        "claim_month": 1,
        "claim_type": "EFKA",
        "tpte_code": "RF123",
    }
    info = pp._archive_pdf_for_claim(str(archive_root), str(pdf_path), claim)
    assert info["copied"] is True
    assert os.path.exists(info["path"])


def test_build_claim_archive_filename_format():
    claim = {"claim_year": 2024, "claim_month": 12, "claim_type": "TEKA", "tpte_code": "RF 12"}
    name = pp._build_claim_archive_filename(claim)
    assert name.startswith("202412_TEKA_TPTE_RF 12")
    assert name.endswith(".pdf")
