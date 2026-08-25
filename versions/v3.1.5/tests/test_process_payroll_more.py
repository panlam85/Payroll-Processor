import datetime
import os
import sys
import zipfile
from pathlib import Path

import process_payroll


def test_parse_pdf_parses_slips(monkeypatch, tmp_path):
    text = """
    01/01/2024
    Κωδικός : 001
    Ονοματεπώνυμο : John Doe
    Διεύθυνση :
    ΒΑΣΙΚΟΣ ΜΙΣΘΟΣ : 1.000,00
    ΣΥΝΟΛΟ ΑΠΟΔΟΧΩΝ ΠΕΡΙΟΔΟΥ : 1.200,00
    ΠΛΗΡΩΤΕΟ : 900,00
    ΗΜΕΡ/ΝΙΑ : 01/01/2024
    ΕΙΣΦΟΡΕΣ ΕΦΚΑ ΕΡΓΑΖ.: 10,00
    ΕΙΣΦΟΡΕΣ ΕΦΚΑ ΕΡΓΟΔ.: 20,00
    Κωδικός : 002
    Ονοματεπώνυμο : Jane Roe
    Διεύθυνση :
    ΒΑΣΙΚΟΣ ΜΙΣΘΟΣ : 2.000,00
    ΣΥΝΟΛΟ ΑΠΟΔΟΧΩΝ ΠΕΡΙΟΔΟΥ : 2.200,00
    ΠΛΗΡΩΤΕΟ : 1.900,00
    """
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_text("pdf")
    entries = process_payroll.parse_pdf(str(pdf_path), "Salary")
    assert len(entries) == 2
    assert entries[0]["EmployeeCode"] == "001"
    assert entries[1]["EmployeeName"] == "Jane Roe"


def test_parse_pdf_missing_code(monkeypatch, tmp_path):
    text = "Κωδικός"
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_text("pdf")
    assert process_payroll.parse_pdf(str(pdf_path), "Salary") == []


def test_parse_pdf_no_slips(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: "No slips")
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_text("pdf")
    assert process_payroll.parse_pdf(str(pdf_path), "Salary") == []


def test_parse_amount():
    assert process_payroll._parse_amount("1.234,56") == 1234.56
    assert process_payroll._parse_amount("1,50") == 1.5
    assert process_payroll._parse_amount("bad") is None
    assert process_payroll._parse_amount(None) is None


def test_extract_iban():
    text = """Προς Λογαριασμό:
    GR12 1234 1234 1234 1234 1234 123
    """
    assert process_payroll._extract_iban(text).startswith("GR12")
    compact = "iban GR1212341234123412341234123"
    assert process_payroll._extract_iban(compact).startswith("GR12")
    assert process_payroll._extract_iban("") is None


def test_extract_beneficiary_name():
    text = """Ονοματεπώνυμο/ Επωνυμία Δικαιούχου:
    John Doe
    """
    assert process_payroll._extract_beneficiary_name(text) == "John Doe"
    assert process_payroll._extract_beneficiary_name("Κύριος Δικαιούχος:\nΤράπεζα") is None
    assert process_payroll._extract_beneficiary_name("") is None
    assert process_payroll._extract_beneficiary_name("Ονοματεπώνυμο/ Επωνυμία Δικαιούχου:\n12345") is None
    assert process_payroll._extract_beneficiary_name("Ονοματεπώνυμο/ Επωνυμία Δικαιούχου:\n\n") is None


def test_extract_payroll_period():
    assert process_payroll._extract_payroll_period("ΜΑΡΤΙΟΣ 2024") == (2024, 3)
    paid_date = datetime.date(2024, 1, 15)
    assert process_payroll._extract_payroll_period("DEC", paid_date=paid_date) == (2023, 12)
    assert process_payroll._extract_payroll_period("no month") == (None, None)
    assert process_payroll._extract_payroll_period(None) == (None, None)


def test_parse_insurance_claim(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdftotext")
    text = """
    ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
    Ημερομηνία Υποβολής 05/01/2024
    ΠΕΡΙΟΔΟΣ ΑΠΟ 1/2024
    Σύνολο Αποδοχών 1.000,00
    Σύνολο Εισφορών 250,00
    Τ.Π.Τ.Ε. RF 123 456
    """
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    pdf_path = tmp_path / "claim.pdf"
    pdf_path.write_text("pdf")
    claim = process_payroll.parse_insurance_claim(str(pdf_path))
    assert claim["claim_year"] == 2024
    assert claim["claim_month"] == 1
    assert claim["claim_type"] == "EFKA"
    text_teka = text + "\nTEKA\n"
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text_teka)
    claim = process_payroll.parse_insurance_claim(str(pdf_path))
    assert claim["claim_type"] == "TEKA"


def test_parse_insurance_claim_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    pdf_path = tmp_path / "claim.pdf"
    pdf_path.write_text("pdf")
    assert process_payroll.parse_insurance_claim(str(pdf_path)) is None

    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: "no claim here")
    assert process_payroll.parse_insurance_claim(str(pdf_path)) is None

    text = "ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ"
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    assert process_payroll.parse_insurance_claim(str(pdf_path)) is None

    text = """
    ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
    Ημερομηνία Υποβολής 32/13/2024
    ΠΕΡΙΟΔΟΣ ΑΠΟ 1/2024
    Καταβλητέες Εισφορές 100,00
    Ταυτότητα Πληρωμής RF 1
    """
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    claim = process_payroll.parse_insurance_claim(str(pdf_path))
    assert claim["submission_date"] is None

    text = """
    ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
    Ημερομηνία Υποβολής 05/01/2024
    ΠΕΡΙΟΔΟΣ ΑΠΟ 1/2024
    Καταβλητέες Εισφορές 100,00
    Ταυτότητα Πληρωμής RF 999
    """
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    claim = process_payroll.parse_insurance_claim(str(pdf_path))
    assert claim["tpte_code"] == "RF999"


def test_parse_transfer_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdftotext")
    text = """
    Κωδικός Συναλλαγής
    Ποσό: 1.234,50
    Στις 05/01/2024
    JAN
    Ονοματεπώνυμο/ Επωνυμία Δικαιούχου: John Doe
    IBAN GR12 1234 1234 1234 1234 1234 123
    """
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    pdf_path = tmp_path / "receipt.pdf"
    pdf_path.write_text("pdf")
    receipt = process_payroll.parse_transfer_receipt(str(pdf_path))
    assert receipt["employee_name"] == "John Doe"
    assert receipt["amount"] == 1234.5
    assert receipt["payroll_month"] == 1
    monkeypatch.setattr(
        process_payroll.subprocess,
        "check_output",
        lambda *args, **kwargs: "Κωδικός Συναλλαγής EUR 100,00 05/01/2024 Ονοματεπώνυμο/ Επωνυμία Δικαιούχου: John Doe",
    )
    assert process_payroll.parse_transfer_receipt(str(pdf_path)) is None


def test_parse_transfer_receipt_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: None)
    pdf_path = tmp_path / "receipt.pdf"
    pdf_path.write_text("pdf")
    assert process_payroll.parse_transfer_receipt(str(pdf_path)) is None

    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdftotext")
    text = "Κωδικός Συναλλαγής\n100,00 EUR\n05/01/2024\nΟνοματεπώνυμο/ Επωνυμία Δικαιούχου: John Doe"
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    receipt = process_payroll.parse_transfer_receipt(str(pdf_path))
    assert receipt["amount"] == 100.0

    text = "Κωδικός Συναλλαγής\nΠοσό: 100,00,00\nΣτις 05/01/2024\nΟνοματεπώνυμο/ Επωνυμία Δικαιούχου: John Doe"
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    assert process_payroll.parse_transfer_receipt(str(pdf_path)) is None

    text = "Κωδικός Συναλλαγής\n10,00 EUR\n99/99/9999\nΟνοματεπώνυμο/ Επωνυμία Δικαιούχου: John Doe"
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    assert process_payroll.parse_transfer_receipt(str(pdf_path)) is None


def test_parse_insurance_claim_missing_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: None)
    pdf_path = tmp_path / "claim.pdf"
    pdf_path.write_text("pdf")
    assert process_payroll.parse_insurance_claim(str(pdf_path)) is None


def test_parse_transfer_receipt_incomplete(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: "Κωδικός Συναλλαγής")
    pdf_path = tmp_path / "receipt.pdf"
    pdf_path.write_text("pdf")
    assert process_payroll.parse_transfer_receipt(str(pdf_path)) is None

    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert process_payroll.parse_transfer_receipt(str(pdf_path)) is None

    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: "no keywords")
    assert process_payroll.parse_transfer_receipt(str(pdf_path)) is None


def test_classify_document():
    assert process_payroll.classify_document("ΔΩΡΟ.pdf") == "Bonus"
    assert process_payroll.classify_document("ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ.pdf") == "VacationAllowance"
    assert process_payroll.classify_document("ΑΠΟΖΗΜΙΩΣΗ.pdf") == "UnusedLeaveCompensation"
    assert process_payroll.classify_document("ΑΠΟΔΕΙΞΕΙΣ.pdf") == "Payslip"
    assert process_payroll.classify_document("U0394U03A9U03A1.pdf") == "Bonus"
    assert process_payroll.classify_document("U0395U03A0U0399.pdf") == "VacationAllowance"
    assert process_payroll.classify_document("U0391U03A0U0396.pdf") == "UnusedLeaveCompensation"
    assert process_payroll.classify_document("U0391U03A0U0394.pdf") == "Payslip"


def test_sanitize_and_archive_helpers(tmp_path, monkeypatch):
    entry = {
        "EmployeeName": "Jane Doe",
        "EmployeeCode": "E1",
        "DocumentType": "Salary",
        "Date": "01/01/2024",
    }
    archive_root = tmp_path / "archive"
    path = process_payroll._derive_archive_dir(str(archive_root), entry)
    assert str(archive_root) in path
    filename = process_payroll._build_archive_filename(entry)
    assert filename.endswith(".pdf")
    assert process_payroll._sanitize_segment("") == "unknown"

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    process_payroll._archive_pdf_for_entry(str(archive_root), str(pdf_path), entry, merge_if_exists=False)
    assert list(Path(archive_root).rglob("*.pdf"))

    def fake_merge(*args, **kwargs):
        return True
    monkeypatch.setattr(process_payroll, "_merge_pdf_files", fake_merge)
    process_payroll._archive_pdf_for_entry(str(archive_root), str(pdf_path), entry, merge_if_exists=True)

    claim = {"claim_year": 2024, "claim_month": 1, "tpte_code": "RF1"}
    claim_dir = process_payroll._derive_claim_archive_dir(str(archive_root), claim)
    assert str(archive_root) in claim_dir
    claim_name = process_payroll._build_claim_archive_filename(claim)
    assert claim_name.endswith(".pdf")

    bad_entry = {"EmployeeName": "Jane", "Date": "bad"}
    assert process_payroll._derive_archive_dir(str(archive_root), bad_entry)
    assert process_payroll._build_archive_filename(bad_entry).endswith(".pdf")

    claim_path = tmp_path / "claim.pdf"
    claim_path.write_text("pdf")
    info = process_payroll._archive_pdf_for_claim(str(archive_root), str(claim_path), claim)
    assert info["path"].endswith(".pdf")

    receipt = {"employee_name": "Jane Doe", "paid_date": datetime.date(2024, 1, 2)}
    receipt_path = tmp_path / "receipt.pdf"
    receipt_path.write_text("pdf")
    info = process_payroll._archive_pdf_for_receipt(str(archive_root), str(receipt_path), receipt)
    assert info["path"].endswith(".pdf")


def test_split_and_merge_pdf_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdfseparate")

    def fake_check_call(args, stdout=None, stderr=None):
        pattern = args[2]
        for idx in range(1, 3):
            path = pattern.replace("%d", str(idx))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("page")

    monkeypatch.setattr(process_payroll.subprocess, "check_call", fake_check_call)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    pages = process_payroll._split_pdf_pages(str(pdf_path), str(tmp_path))
    assert len(pages) == 2

    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdfunite")

    def fake_unite(args, stdout=None, stderr=None):
        temp_path = args[-1]
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write("merged")

    monkeypatch.setattr(process_payroll.subprocess, "check_call", fake_unite)
    dest_path = tmp_path / "dest.pdf"
    new_path = tmp_path / "new.pdf"
    dest_path.write_text("old")
    new_path.write_text("new")
    assert process_payroll._merge_pdf_files(str(dest_path), str(new_path)) is True

    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: None)
    assert process_payroll._split_pdf_pages(str(dest_path), str(tmp_path)) == []
    assert process_payroll._merge_pdf_files(str(dest_path), str(new_path)) is False

    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdfunite")

    def failing_unite(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(process_payroll.subprocess, "check_call", failing_unite)
    assert process_payroll._merge_pdf_files(str(dest_path), str(new_path)) is False

    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdfseparate")
    monkeypatch.setattr(process_payroll.subprocess, "check_call", failing_unite)
    assert process_payroll._split_pdf_pages(str(dest_path), str(tmp_path)) == []

    temp_path = str(dest_path) + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write("tmp")
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdfunite")
    assert process_payroll._merge_pdf_files(str(dest_path), str(new_path)) is False


def test_process_zip_and_pdf(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(pdf_file, arcname="file.pdf")

    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_pdf", lambda path, doc: [{"EmployeeCode": "E1", "EmployeeName": "Jane"}])
    monkeypatch.setattr(process_payroll, "_archive_pdf_for_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(process_payroll, "_split_pdf_pages", lambda *args, **kwargs: [])

    records, receipts, claims = process_payroll.process_zip(str(zip_path), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert len(records) == 1
    assert receipts == []
    assert claims == []

    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: {"claim_year": 2024, "claim_month": 1})
    records, claims, receipts = process_payroll.process_pdf_file(str(pdf_file), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert claims


def test_process_zip_split_pages(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(pdf_file, arcname="file.pdf")

    slip1 = {"EmployeeCode": "E1", "EmployeeName": "Jane"}
    slip2 = {"EmployeeCode": "E2", "EmployeeName": "John"}
    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_pdf", lambda path, doc: [slip1, slip2])

    page1 = tmp_path / "page-1.pdf"
    page2 = tmp_path / "page-2.pdf"
    page1.write_text("page1")
    page2.write_text("page2")
    monkeypatch.setattr(process_payroll, "_split_pdf_pages", lambda *args, **kwargs: [str(page1), str(page2)])

    archived = []

    def fake_archive(*args, **kwargs):
        archived.append(args[1])

    monkeypatch.setattr(process_payroll, "_archive_pdf_for_entry", fake_archive)
    process_payroll.process_zip(str(zip_path), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert len(archived) == 2


def test_process_zip_unsplit(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(pdf_file, arcname="file.pdf")

    slip = {"EmployeeCode": "E1", "EmployeeName": "Jane"}
    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_pdf", lambda path, doc: [slip, slip])
    monkeypatch.setattr(process_payroll, "_split_pdf_pages", lambda *args, **kwargs: [])

    archived = []
    monkeypatch.setattr(process_payroll, "_archive_pdf_for_entry", lambda *args, **kwargs: archived.append(args[1]))
    process_payroll.process_zip(str(zip_path), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert archived[0].endswith("file.pdf")


def test_process_zip_claim_and_receipt(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(pdf_file, arcname="file.pdf")

    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: {"claim_year": 2024, "claim_month": 1})
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    records, receipts, claims = process_payroll.process_zip(str(zip_path), str(tmp_path), archive_root=None)
    assert claims

    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: {"employee_name": "Jane", "paid_date": datetime.date(2024, 1, 1)})
    records, receipts, claims = process_payroll.process_zip(str(zip_path), str(tmp_path), archive_root=None)
    assert receipts


def test_process_zip_with_archive(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(pdf_file, arcname="file.pdf")
        zf.writestr("note.txt", "skip")

    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: {"claim_year": 2024, "claim_month": 1})
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    monkeypatch.setattr(process_payroll, "_archive_pdf_for_claim", lambda *args, **kwargs: {"path": "claim.pdf", "copied": True})
    monkeypatch.setattr(process_payroll, "_archive_pdf_for_receipt", lambda *args, **kwargs: {"path": "receipt.pdf", "copied": True})

    records, receipts, claims = process_payroll.process_zip(str(zip_path), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert claims[0]["archive_path"] == "claim.pdf"

    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: {"employee_name": "Jane", "paid_date": datetime.date(2024, 1, 1)})
    records, receipts, claims = process_payroll.process_zip(str(zip_path), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert receipts[0]["archive_path"] == "receipt.pdf"


def test_process_pdf_file_receipt(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")

    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: {"employee_name": "Jane", "paid_date": datetime.date(2024, 1, 1)})
    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    records, claims, receipts = process_payroll.process_pdf_file(str(pdf_file), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert receipts


def test_process_pdf_file_unsplit(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")

    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_pdf", lambda path, doc: [{"EmployeeCode": "E1"}, {"EmployeeCode": "E2"}])
    monkeypatch.setattr(process_payroll, "_split_pdf_pages", lambda *args, **kwargs: [])

    archived = []
    monkeypatch.setattr(process_payroll, "_archive_pdf_for_entry", lambda *args, **kwargs: archived.append(args[1]))
    process_payroll.process_pdf_file(str(pdf_file), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert archived


def test_process_pdf_file_archive_paths(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")

    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_pdf", lambda path, doc: [{"EmployeeCode": "E1", "EmployeeName": "Jane"}])
    archived = []
    monkeypatch.setattr(process_payroll, "_archive_pdf_for_entry", lambda *args, **kwargs: archived.append(args[1]))
    process_payroll.process_pdf_file(str(pdf_file), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert archived


def test_process_pdf_file_split_pages(monkeypatch, tmp_path):
    pdf_file = tmp_path / "file.pdf"
    pdf_file.write_text("pdf")

    slips = [{"EmployeeCode": "E1"}, {"EmployeeCode": "E2"}]
    monkeypatch.setattr(process_payroll, "parse_transfer_receipt", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_insurance_claim", lambda path: None)
    monkeypatch.setattr(process_payroll, "parse_pdf", lambda path, doc: slips)
    page1 = tmp_path / "page-1.pdf"
    page2 = tmp_path / "page-2.pdf"
    page1.write_text("page1")
    page2.write_text("page2")
    monkeypatch.setattr(process_payroll, "_split_pdf_pages", lambda *args, **kwargs: [str(page1), str(page2)])
    archived = []
    monkeypatch.setattr(process_payroll, "_archive_pdf_for_entry", lambda *args, **kwargs: archived.append(args[1]))
    process_payroll.process_pdf_file(str(pdf_file), str(tmp_path), archive_root=str(tmp_path / "archive"))
    assert len(archived) == 2




def test_main_process_zip(monkeypatch, tmp_path):
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("file.pdf", "pdf")

    df = process_payroll.pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane",
                "BasicSalary": "1000,00",
                "TotalEarnings": "1200,00",
                "NetPay": "900,00",
            }
        ]
    )
    monkeypatch.setattr(process_payroll, "process_zip", lambda *args, **kwargs: df)
    out_csv = tmp_path / "out.csv"
    monkeypatch.setattr(sys, "argv", ["prog", "--input-dir", str(tmp_path), "--out-csv", str(out_csv)])
    process_payroll.main()
    assert out_csv.exists()


def test_main_no_records(monkeypatch, tmp_path, capsys):
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("file.pdf", "pdf")

    monkeypatch.setattr(process_payroll, "process_zip", lambda *args, **kwargs: process_payroll.pd.DataFrame())
    out_csv = tmp_path / "out.csv"
    monkeypatch.setattr(sys, "argv", ["prog", "--input-dir", str(tmp_path), "--out-csv", str(out_csv)])
    process_payroll.main()
    assert "No payroll records found." in capsys.readouterr().out


def test_main_with_tuple_return(monkeypatch, tmp_path, capsys):
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("file.pdf", "pdf")
    (tmp_path / "note.txt").write_text("skip")

    df = process_payroll.pd.DataFrame([{"EmployeeCode": "E1", "EmployeeName": "Jane"}])
    monkeypatch.setattr(process_payroll, "process_zip", lambda *args, **kwargs: (df, [], []))
    out_csv = tmp_path / "out.csv"
    monkeypatch.setattr(sys, "argv", ["prog", "--input-dir", str(tmp_path), "--out-csv", str(out_csv)])
    process_payroll.main()
    assert out_csv.exists()
