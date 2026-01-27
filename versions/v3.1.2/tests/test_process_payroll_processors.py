import zipfile

import pandas as pd

import process_payroll as pp


def test_process_zip_with_receipt(monkeypatch, tmp_path):
    zip_path = tmp_path / "data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("receipt.pdf", b"dummy")

    temp_root = tmp_path / "temp"
    archive_root = tmp_path / "archive"
    temp_root.mkdir()
    archive_root.mkdir()

    receipt = {"employee_name": "Alice"}
    monkeypatch.setattr(pp, "parse_insurance_claim", lambda *_: None)
    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda *_: receipt)

    def fake_archive(*_):
        return {"path": "/tmp/archived.pdf", "copied": True}

    monkeypatch.setattr(pp, "_archive_pdf_for_receipt", fake_archive)

    df, receipts, claims = pp.process_zip(str(zip_path), str(temp_root), archive_root=str(archive_root))
    assert df.empty
    assert claims == []
    assert receipts[0]["archive_path"] == "/tmp/archived.pdf"
    assert receipts[0]["archive_copied"] is True


def test_process_zip_with_claim(monkeypatch, tmp_path):
    zip_path = tmp_path / "data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("claim.pdf", b"dummy")

    temp_root = tmp_path / "temp"
    archive_root = tmp_path / "archive"
    temp_root.mkdir()
    archive_root.mkdir()

    claim = {"claim_year": 2024}
    monkeypatch.setattr(pp, "parse_insurance_claim", lambda *_: claim)

    def fake_archive(*_):
        return {"path": "/tmp/claim.pdf", "copied": False}

    monkeypatch.setattr(pp, "_archive_pdf_for_claim", fake_archive)

    df, receipts, claims = pp.process_zip(str(zip_path), str(temp_root), archive_root=str(archive_root))
    assert df.empty
    assert receipts == []
    assert claims[0]["archive_path"] == "/tmp/claim.pdf"
    assert claims[0]["archive_copied"] is False


def test_process_pdf_file_archives_single_slip(monkeypatch, tmp_path):
    pdf_path = tmp_path / "slip.pdf"
    pdf_path.write_bytes(b"dummy")

    slip = {"EmployeeCode": "1", "EmployeeName": "Alice", "Date": "01/01/2024"}
    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda *_: None)
    monkeypatch.setattr(pp, "parse_insurance_claim", lambda *_: None)
    monkeypatch.setattr(pp, "classify_document", lambda *_: "Payslip")
    monkeypatch.setattr(pp, "parse_pdf", lambda *_: [slip])

    calls = []

    def record_archive(archive_root_value, file_path, entry, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(pp, "_archive_pdf_for_entry", record_archive)

    df, claims, receipts = pp.process_pdf_file(str(pdf_path), str(tmp_path), archive_root=str(tmp_path))
    assert len(df) == 1
    assert claims == []
    assert receipts == []
    assert calls and calls[0].get("include_doc_type") is False


def test_process_pdf_file_archives_split_pages(monkeypatch, tmp_path):
    pdf_path = tmp_path / "slip.pdf"
    pdf_path.write_bytes(b"dummy")

    slips = [
        {"EmployeeCode": "1", "EmployeeName": "Alice", "Date": "01/01/2024"},
        {"EmployeeCode": "2", "EmployeeName": "Bob", "Date": "01/01/2024"},
    ]
    pages = [str(tmp_path / "page-1.pdf"), str(tmp_path / "page-2.pdf")]

    monkeypatch.setattr(pp, "parse_transfer_receipt", lambda *_: None)
    monkeypatch.setattr(pp, "parse_insurance_claim", lambda *_: None)
    monkeypatch.setattr(pp, "classify_document", lambda *_: "Payslip")
    monkeypatch.setattr(pp, "parse_pdf", lambda *_: slips)
    monkeypatch.setattr(pp, "_split_pdf_pages", lambda *_: pages)

    calls = []

    def record_archive(archive_root_value, file_path, entry, **kwargs):
        calls.append((file_path, kwargs))

    monkeypatch.setattr(pp, "_archive_pdf_for_entry", record_archive)

    df, claims, receipts = pp.process_pdf_file(str(pdf_path), str(tmp_path), archive_root=str(tmp_path))
    assert len(df) == 2
    assert [call[0] for call in calls] == pages
    assert calls[0][1].get("merge_if_exists") is True
