import os

import process_payroll as pp


def test_parse_pdf_subprocess_error(monkeypatch):
    def raise_error(*args, **kwargs):
        raise RuntimeError("fail")
    monkeypatch.setattr(pp.subprocess, "check_output", raise_error)
    slips = pp.parse_pdf("/tmp/test.pdf", "Payslip")
    assert slips == []


def test_split_pdf_pages_success(monkeypatch, tmp_path):
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdfseparate")

    def fake_call(args, stdout=None, stderr=None):
        (tmp_path / "page-2.pdf").write_bytes(b"b")
        (tmp_path / "page-1.pdf").write_bytes(b"a")

    monkeypatch.setattr(pp.subprocess, "check_call", fake_call)
    pages = pp._split_pdf_pages(str(tmp_path / "file.pdf"), str(tmp_path))
    assert pages == [str(tmp_path / "page-1.pdf"), str(tmp_path / "page-2.pdf")]


def test_merge_pdf_files_success(monkeypatch, tmp_path):
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdfunite")
    dest = tmp_path / "dest.pdf"
    new = tmp_path / "new.pdf"
    dest.write_bytes(b"old")
    new.write_bytes(b"new")

    def fake_call(args, stdout=None, stderr=None):
        temp_path = f"{dest}.tmp"
        with open(temp_path, "wb") as handle:
            handle.write(b"merged")

    monkeypatch.setattr(pp.subprocess, "check_call", fake_call)
    assert pp._merge_pdf_files(str(dest), str(new)) is True
    assert dest.read_bytes() == b"merged"


def test_archive_pdf_for_receipt_copies(tmp_path):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    pdf_path = tmp_path / "receipt.pdf"
    pdf_path.write_bytes(b"dummy")
    receipt = {
        "employee_name": "Alice",
        "paid_date": None,
    }
    info = pp._archive_pdf_for_receipt(str(archive_root), str(pdf_path), receipt)
    assert info["copied"] is True
    assert os.path.exists(info["path"])


def test_process_zip_single_slip_archive(monkeypatch, tmp_path):
    zip_path = tmp_path / "data.zip"
    with zip_path.open("wb") as handle:
        import zipfile
        with zipfile.ZipFile(handle, "w") as zf:
            zf.writestr("sample.pdf", b"dummy")

    temp_root = tmp_path / "temp"
    archive_root = tmp_path / "archive"
    temp_root.mkdir()
    archive_root.mkdir()

    monkeypatch.setattr(pp, "parse_insurance_claim", lambda *_: None)
    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda *_: None)
    monkeypatch.setattr(pp, "classify_document", lambda *_: "Payslip")
    slip = {"EmployeeCode": "1", "EmployeeName": "Alice", "Date": "01/01/2024"}
    monkeypatch.setattr(pp, "parse_pdf", lambda *_: [slip])

    calls = []

    def record_archive(archive_root_value, file_path, entry, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(pp, "_archive_pdf_for_entry", record_archive)

    df, receipts, claims = pp.process_zip(str(zip_path), str(temp_root), archive_root=str(archive_root))
    assert len(df) == 1
    assert receipts == []
    assert claims == []
    assert calls and calls[0].get("include_doc_type") is False


def test_parse_insurance_claim_alt_patterns(monkeypatch):
    sample_text = """\
ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
Ημερομηνία Υποβολής 15/03/2024
ΠΕΡΙΟΔΟΣ ΑΠΟ 02/2024
Καταβλητέες Εισφορές 99,99
Ταυτότητα Πληρωμής RF 123 456
"""
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    claim = pp.parse_insurance_claim("/tmp/claim.pdf")
    assert claim is not None
    assert claim["total_contributions"] == 99.99
    assert claim["tpte_code"] == "RF123456"


def test_parse_transfer_receipt_missing_date(monkeypatch):
    sample_text = """\
Κωδικός Συναλλαγής
Κύριος Δικαιούχος: ΝΙΚΟΣ ΠΑΠΑΣ
Ποσό: 100,00 EUR
"""
    monkeypatch.setattr(pp.shutil, "which", lambda *_: "/usr/bin/pdftotext")
    monkeypatch.setattr(pp.subprocess, "check_output", lambda *args, **kwargs: sample_text)
    assert pp.parse_transfer_receipt("/tmp/receipt.pdf") is None
