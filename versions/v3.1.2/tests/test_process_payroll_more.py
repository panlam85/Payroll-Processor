import datetime

import process_payroll as pp


def test_parse_pdf_extracts_multiple_slips(monkeypatch):
    text = """\
Κωδικός : 001
Ονοματεπώνυμο : ΑΛΦΑ ΒΗΤΑ
ΒΑΣΙΚΟΣ ΜΙΣΘΟΣ : 1.000,00
ΣΥΝΟΛΟ ΑΠΟΔΟΧΩΝ ΠΕΡΙΟΔΟΥ : 1.200,00
ΠΛΗΡΩΤΕΟ : 900,00
ΗΜΕΡ/ ΝΙΑ : 05/01/2024
Κωδικός : 002
Ονοματεπώνυμο : ΓΑΜΜΑ ΔΕΛΤΑ
ΒΑΣΙΚΟΣ ΜΙΣΘΟΣ : 2.000,00
ΣΥΝΟΛΟ ΑΠΟΔΟΧΩΝ ΠΕΡΙΟΔΟΥ : 2.200,00
ΠΛΗΡΩΤΕΟ : 1800,00
ΗΜΕΡ/ ΝΙΑ : 05/01/2024
"""
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: text)
    slips = pp.parse_pdf("/tmp/test.pdf", "Payslip")
    assert len(slips) == 2
    assert slips[0]["EmployeeCode"] == "001"
    assert slips[1]["EmployeeName"].startswith("ΓΑΜΜΑ ΔΕΛΤΑ")


def test_parse_pdf_uses_default_date(monkeypatch):
    text = """\
05/02/2024
Κωδικός : 003
Ονοματεπώνυμο : TEST USER
ΒΑΣΙΚΟΣ ΜΙΣΘΟΣ : 1.000,00
"""
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: text)
    slips = pp.parse_pdf("/tmp/test.pdf", "Payslip")
    assert slips[0]["Date"] == "05/02/2024"


def test_parse_pdf_handles_missing_code(monkeypatch):
    text = """\
Ονοματεπώνυμο : TEST USER
"""
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: text)
    slips = pp.parse_pdf("/tmp/test.pdf", "Payslip")
    assert slips == []


def test_split_pdf_pages_handles_subprocess_error(monkeypatch, tmp_path):
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdfseparate")
    def raise_error(*args, **kwargs):
        raise RuntimeError("fail")
    monkeypatch.setattr(pp.subprocess, "check_call", raise_error)
    pages = pp._split_pdf_pages(str(tmp_path / "file.pdf"), str(tmp_path))
    assert pages == []


def test_merge_pdf_files_handles_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdfunite")
    def raise_error(*args, **kwargs):
        raise RuntimeError("fail")
    monkeypatch.setattr(pp.subprocess, "check_call", raise_error)
    assert pp._merge_pdf_files(str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")) is False


def test_archive_pdf_for_entry_merges_when_exists(monkeypatch, tmp_path):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    file_path = tmp_path / "file.pdf"
    file_path.write_bytes(b"dummy")
    entry = {"EmployeeName": "Alice", "Date": "01/01/2024", "DocumentType": "Payslip"}
    dest_path = archive_root / "24" / "01" / "Alice" / "2401_Alice_Payslip.pdf"
    dest_path.parent.mkdir(parents=True)
    dest_path.write_bytes(b"old")

    monkeypatch.setattr(pp, "_merge_pdf_files", lambda *_: True)
    pp._archive_pdf_for_entry(str(archive_root), str(file_path), entry)
    # If merge succeeds, should not overwrite the existing file.
    assert dest_path.read_bytes() == b"old"


def test_archive_pdf_for_entry_copies_when_missing(monkeypatch, tmp_path):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    file_path = tmp_path / "file.pdf"
    file_path.write_bytes(b"dummy")
    entry = {"EmployeeName": "Alice", "Date": "01/01/2024", "DocumentType": "Payslip"}

    pp._archive_pdf_for_entry(str(archive_root), str(file_path), entry)
    dest_path = archive_root / "2024" / "01" / "Alice" / "2401_Alice_Payslip.pdf"
    assert dest_path.exists()


def test_build_archive_filename_without_doc_type():
    entry = {"EmployeeName": "Alice", "Date": "01/01/2024"}
    name = pp._build_archive_filename(entry, include_doc_type=False)
    assert name.startswith("2401_Alice")
    assert "Payslip" not in name


def test_extract_payroll_period_handles_no_month():
    assert pp._extract_payroll_period("no month here") == (None, None)


def test_parse_transfer_receipt_without_iban(monkeypatch):
    sample_text = """\
Κωδικός Συναλλαγής
Κύριος Δικαιούχος: ΝΙΚΟΣ ΠΑΠΑΣ
Ποσό: 100,00 EUR
Στις 05/02/2025
"""
    monkeypatch.setattr(pp.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    receipt = pp.parse_transfer_receipt("/tmp/receipt.pdf")
    assert receipt["iban"] is None


def test_parse_insurance_claim_requires_fields(monkeypatch):
    sample_text = """\
ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
ΤΕΚΑ
"""
    monkeypatch.setattr(pp.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    assert pp.parse_insurance_claim("/tmp/claim.pdf") is None


def test_parse_pdf_efka_teka_fields(monkeypatch):
    text = """\
Κωδικός : 004
Ονοματεπώνυμο : TEST USER
ΕΙΣΦΟΡΕΣ ΕΦΚΑ ΕΡΓΑΖ.: 12,34
ΕΙΣΦΟΡΕΣ ΕΦΚΑ ΕΡΓΟΔ.: 56,78
ΕΙΣΦΟΡΕΣ TEKA ΕΡΓΑΖ.: 1,23
ΕΙΣΦΟΡΕΣ TEKA ΕΡΓΟΔ.: 4,56
"""
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: text)
    slips = pp.parse_pdf("/tmp/test.pdf", "Payslip")
    slip = slips[0]
    assert slip["EFKAEmployee"] == "12,34"
    assert slip["EFKAEmployer"] == "56,78"
    assert slip["TEKAEmployee"] == "1,23"
    assert slip["TEKAEmployer"] == "4,56"
