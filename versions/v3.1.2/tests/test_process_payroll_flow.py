import os
import zipfile

import pandas as pd

import process_payroll as pp


def _write_zip_with_pdf(zip_path, pdf_name="sample.pdf"):
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(pdf_name, b"dummy")


def test_process_zip_with_multiple_slips_and_split(monkeypatch, tmp_path):
    zip_path = tmp_path / "data.zip"
    _write_zip_with_pdf(zip_path)
    temp_root = tmp_path / "temp"
    archive_root = tmp_path / "archive"
    temp_root.mkdir()
    archive_root.mkdir()

    monkeypatch.setattr(pp, "parse_insurance_claim", lambda _: None)
    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda _: None)
    monkeypatch.setattr(pp, "classify_document", lambda _: "Payslip")
    slips = [
        {"EmployeeCode": "1", "EmployeeName": "Alice", "Date": "01/01/2024"},
        {"EmployeeCode": "2", "EmployeeName": "Bob", "Date": "01/01/2024"},
    ]
    monkeypatch.setattr(pp, "parse_pdf", lambda *_: slips)

    split_pages = [str(tmp_path / "page-1.pdf"), str(tmp_path / "page-2.pdf")]
    monkeypatch.setattr(pp, "_split_pdf_pages", lambda *_: split_pages)

    calls = []

    def record_archive(archive_root_value, file_path, entry, **kwargs):
        calls.append((archive_root_value, file_path, entry, kwargs))

    monkeypatch.setattr(pp, "_archive_pdf_for_entry", record_archive)

    df, receipts, claims = pp.process_zip(str(zip_path), str(temp_root), archive_root=str(archive_root))
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert receipts == []
    assert claims == []
    assert [call[1] for call in calls] == split_pages


def test_process_zip_with_unsplit_fallback(monkeypatch, tmp_path):
    zip_path = tmp_path / "data.zip"
    _write_zip_with_pdf(zip_path)
    temp_root = tmp_path / "temp"
    archive_root = tmp_path / "archive"
    temp_root.mkdir()
    archive_root.mkdir()

    monkeypatch.setattr(pp, "parse_insurance_claim", lambda _: None)
    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda _: None)
    monkeypatch.setattr(pp, "classify_document", lambda _: "Payslip")
    slips = [
        {"EmployeeCode": "1", "EmployeeName": "Alice", "Date": "01/01/2024"},
        {"EmployeeCode": "2", "EmployeeName": "Bob", "Date": "01/01/2024"},
    ]
    monkeypatch.setattr(pp, "parse_pdf", lambda *_: slips)
    monkeypatch.setattr(pp, "_split_pdf_pages", lambda *_: [])

    calls = []

    def record_archive(archive_root_value, file_path, entry, **kwargs):
        calls.append((archive_root_value, file_path, entry, kwargs))

    monkeypatch.setattr(pp, "_archive_pdf_for_entry", record_archive)

    df, receipts, claims = pp.process_zip(str(zip_path), str(temp_root), archive_root=str(archive_root))
    assert len(df) == 2
    assert len(calls) == 1
    assert calls[0][2]["EmployeeCode"] == "1"


def test_process_pdf_file_receipt_short_circuit(monkeypatch, tmp_path):
    pdf_path = tmp_path / "receipt.pdf"
    pdf_path.write_bytes(b"dummy")

    receipt = {"employee_name": "Test"}
    called = {"claim": False, "pdf": False}

    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda _: receipt)

    def claim_called(_):
        called["claim"] = True
        return None

    def pdf_called(*_):
        called["pdf"] = True
        return []

    monkeypatch.setattr(pp, "parse_insurance_claim", claim_called)
    monkeypatch.setattr(pp, "parse_pdf", pdf_called)

    df, claims, receipts = pp.process_pdf_file(str(pdf_path), str(tmp_path))
    assert df.empty
    assert claims == []
    assert receipts == [receipt]
    assert called["claim"] is False
    assert called["pdf"] is False


def test_process_pdf_file_claim_short_circuit(monkeypatch, tmp_path):
    pdf_path = tmp_path / "claim.pdf"
    pdf_path.write_bytes(b"dummy")

    claim = {"claim_year": 2024}
    called = {"pdf": False}

    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda _: None)
    monkeypatch.setattr(pp, "parse_insurance_claim", lambda _: claim)

    def pdf_called(*_):
        called["pdf"] = True
        return []

    monkeypatch.setattr(pp, "parse_pdf", pdf_called)

    df, claims, receipts = pp.process_pdf_file(str(pdf_path), str(tmp_path))
    assert df.empty
    assert claims == [claim]
    assert receipts == []
    assert called["pdf"] is False


def test_split_pdf_pages_no_pdfseparate(monkeypatch, tmp_path):
    monkeypatch.setattr(pp.shutil, "which", lambda _: None)
    assert pp._split_pdf_pages(str(tmp_path / "file.pdf"), str(tmp_path)) == []


def test_merge_pdf_files_no_pdfunite(monkeypatch, tmp_path):
    monkeypatch.setattr(pp.shutil, "which", lambda _: None)
    assert pp._merge_pdf_files(str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")) is False
