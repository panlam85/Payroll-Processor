import argparse
import datetime
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

import create_employee_reports
import payroll_cli
import process_payroll


def _cli_args(tmp_path, source, run_id):
    return argparse.Namespace(
        zips=[str(source)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=False,
        no_open=True,
        run_id=run_id,
        notes="",
    )


def _payroll_frame(code="E1"):
    return pd.DataFrame(
        [
            {
                "EmployeeCode": code,
                "EmployeeName": "Test Employee",
                "Date": "01/01/2026",
                "DocumentType": "Salary",
                "BasicSalary": "1234.56",
                "TotalEarnings": "1234.56",
                "NetPay": "1000.00",
            }
        ]
    )


def test_bug_13_corrupt_zip_is_error_and_returns_nonzero(tmp_path):
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"not a zip")

    assert payroll_cli.run_processing(_cli_args(tmp_path, corrupt, "corrupt")) == 1
    ledger = json.loads((tmp_path / "ledger" / "run_corrupt.json").read_text(encoding="utf-8"))
    assert ledger["status"] == "error"
    assert ledger["errors"]


def test_bug_14_failed_run_does_not_advertise_nonexistent_workbooks(tmp_path):
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"not a zip")

    payroll_cli.run_processing(_cli_args(tmp_path, corrupt, "no-outputs"))
    ledger = json.loads((tmp_path / "ledger" / "run_no-outputs.json").read_text(encoding="utf-8"))
    assert "summary_xlsx" not in ledger["outputs"]
    assert "detail_xlsx" not in ledger["outputs"]


def test_bug_15_runs_in_same_second_get_distinct_output_paths(tmp_path, monkeypatch):
    source = tmp_path / "payroll.pdf"
    source.write_bytes(b"pdf")
    frame = _payroll_frame()
    monkeypatch.setattr(
        payroll_cli.process_payroll,
        "process_pdf_file",
        lambda *args, **kwargs: (frame.copy(), [], []),
    )
    monkeypatch.setattr(
        payroll_cli.create_employee_reports,
        "load_payroll_data",
        lambda paths: frame.copy(),
    )

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 8, 25, 10, 11, 12)
            return value.replace(tzinfo=tz) if tz else value

    monkeypatch.setattr(payroll_cli.dt, "datetime", FixedDateTime)
    assert payroll_cli.run_processing(_cli_args(tmp_path, source, "run-A")) == 0
    assert payroll_cli.run_processing(_cli_args(tmp_path, source, "run-B")) == 0
    ledger_a = json.loads((tmp_path / "ledger" / "run_run-A.json").read_text(encoding="utf-8"))
    ledger_b = json.loads((tmp_path / "ledger" / "run_run-B.json").read_text(encoding="utf-8"))
    assert ledger_a["outputs"]["summary_xlsx"] != ledger_b["outputs"]["summary_xlsx"]
    assert ledger_a["outputs"]["detail_xlsx"] != ledger_b["outputs"]["detail_xlsx"]


def test_bug_16_secondary_code_label_does_not_create_phantom_slip(tmp_path, monkeypatch):
    text = """
    Κωδικός : 001
    Ονοματεπώνυμο : Real Employee
    Διεύθυνση : Athens
    Κωδικός Ειδικότητας : 1234
    ΠΛΗΡΩΤΕΟ : 900,00
    """
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)
    source = tmp_path / "slip.pdf"
    source.write_bytes(b"pdf")

    slips = process_payroll.parse_pdf(str(source), "Salary")
    assert [slip["EmployeeCode"] for slip in slips] == ["001"]


def test_bug_17_namesakes_use_employee_code_in_archive_identity(tmp_path):
    first = {"EmployeeCode": "001", "EmployeeName": "Same Name", "Date": "01/03/2026"}
    second = {"EmployeeCode": "002", "EmployeeName": "Same Name", "Date": "01/03/2026"}

    assert process_payroll._derive_archive_dir(str(tmp_path), first) != process_payroll._derive_archive_dir(
        str(tmp_path), second
    )
    assert process_payroll._build_archive_filename(first) != process_payroll._build_archive_filename(second)

    first_dir = Path(process_payroll._derive_archive_dir(str(tmp_path), first))
    second_dir = Path(process_payroll._derive_archive_dir(str(tmp_path), second))
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    (first_dir / process_payroll._build_archive_filename(first)).write_bytes(b"first")
    (second_dir / process_payroll._build_archive_filename(second)).write_bytes(b"second")
    receipt = {"employee_name": "Same Name", "paid_date": datetime.date(2026, 3, 5)}
    assert process_payroll.find_monthly_payment_pdfs(str(tmp_path), receipt) == []


def test_bug_18_duplicate_zip_member_paths_are_rejected(tmp_path):
    archive = tmp_path / "duplicates.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("employee.pdf", b"first")
        zf.writestr("employee.pdf", b"second")

    with pytest.raises(ValueError, match="Duplicate ZIP member"):
        process_payroll.process_zip(str(archive), str(tmp_path))


def test_bug_19_suspicious_zip_compression_ratio_is_rejected(tmp_path, monkeypatch):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("employee.pdf", b"A" * 100_000)
    monkeypatch.setattr(process_payroll, "MAX_ZIP_COMPRESSION_RATIO", 2)

    with pytest.raises(ValueError, match="compression ratio"):
        process_payroll.process_zip(str(archive), str(tmp_path))

    monkeypatch.setattr(process_payroll, "MAX_ZIP_COMPRESSION_RATIO", 1_000_000)
    monkeypatch.setattr(process_payroll, "MAX_ZIP_MEMBERS", 1)
    member_archive = tmp_path / "members.zip"
    with zipfile.ZipFile(member_archive, "w") as zf:
        zf.writestr("one.pdf", b"one")
        zf.writestr("two.pdf", b"two")
    with pytest.raises(ValueError, match="too many members"):
        process_payroll.process_zip(str(member_archive), str(tmp_path))

    monkeypatch.setattr(process_payroll, "MAX_ZIP_MEMBERS", 100)
    monkeypatch.setattr(process_payroll, "MAX_ZIP_MEMBER_SIZE", 3)
    size_archive = tmp_path / "member-size.zip"
    with zipfile.ZipFile(size_archive, "w") as zf:
        zf.writestr("large.pdf", b"four")
    with pytest.raises(ValueError, match="member is too large"):
        process_payroll.process_zip(str(size_archive), str(tmp_path))

    monkeypatch.setattr(process_payroll, "MAX_ZIP_MEMBER_SIZE", 100)
    monkeypatch.setattr(process_payroll, "MAX_ZIP_TOTAL_SIZE", 5)
    total_archive = tmp_path / "total-size.zip"
    with zipfile.ZipFile(total_archive, "w") as zf:
        zf.writestr("one.pdf", b"one")
        zf.writestr("two.pdf", b"two")
    with pytest.raises(ValueError, match="expanded size"):
        process_payroll.process_zip(str(total_archive), str(tmp_path))

    monkeypatch.setattr(process_payroll, "MAX_ZIP_TOTAL_SIZE", 100)
    monkeypatch.setattr(process_payroll, "MAX_ZIP_PATH_DEPTH", 2)
    depth_archive = tmp_path / "depth.zip"
    with zipfile.ZipFile(depth_archive, "w") as zf:
        zf.writestr("one/two/three.pdf", b"pdf")
    with pytest.raises(ValueError, match="path is too deep"):
        process_payroll.process_zip(str(depth_archive), str(tmp_path))


def test_bug_20_employee_codes_round_trip_as_exact_strings(tmp_path):
    csv_path = tmp_path / "codes.csv"
    csv_path.write_text("EmployeeCode,EmployeeName\n001,First\n1,Second\n", encoding="utf-8")

    loaded = create_employee_reports.load_payroll_data([str(csv_path)])
    assert loaded["EmployeeCode"].tolist() == ["001", "1"]


def test_bug_21_period_parser_ignores_names_and_transaction_date_year():
    assert process_payroll._extract_payroll_period("Employee ΜΑΡΤΙΝΟΣ\nΣτις 05/04/2026") == (None, None)
    paid = datetime.date(2026, 1, 5)
    assert process_payroll._extract_payroll_period("Στις 05/01/2026\nDEC", paid_date=paid) == (2025, 12)


def test_bug_22_two_receipts_for_same_employee_and_month_get_unique_paths(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"receipt one")
    second.write_bytes(b"receipt two")
    receipt = {
        "employee_name": "Same Employee",
        "paid_date": datetime.date(2026, 3, 5),
        "payroll_year": 2026,
        "payroll_month": 3,
    }

    first_info = process_payroll._archive_pdf_for_receipt(str(tmp_path / "archive"), str(first), receipt)
    second_info = process_payroll._archive_pdf_for_receipt(str(tmp_path / "archive"), str(second), receipt)
    assert first_info["path"] != second_info["path"]
    assert Path(first_info["path"]).read_bytes() == b"receipt one"
    assert Path(second_info["path"]).read_bytes() == b"receipt two"


def test_bug_23_reprocessing_identical_payroll_pdf_does_not_merge_again(tmp_path, monkeypatch):
    source = tmp_path / "salary.pdf"
    source.write_bytes(b"same payroll bytes")
    entry = {
        "EmployeeCode": "001",
        "EmployeeName": "Employee",
        "Date": "01/03/2026",
        "DocumentType": "Salary",
    }
    merge_calls = []
    monkeypatch.setattr(
        process_payroll,
        "_merge_pdf_files",
        lambda *args: merge_calls.append(args) or True,
    )

    process_payroll._archive_pdf_for_entry(str(tmp_path / "archive"), str(source), entry)
    process_payroll._archive_pdf_for_entry(str(tmp_path / "archive"), str(source), entry)
    assert merge_calls == []


def test_bug_24_dot_decimal_receipt_amount_stays_decimal(tmp_path, monkeypatch):
    source = tmp_path / "receipt.pdf"
    source.write_bytes(b"pdf")
    text = """
    Κωδικός Συναλλαγής
    Ποσό: 1234.56
    Στις 05/03/2026
    MAR 2026
    Ονοματεπώνυμο/ Επωνυμία Δικαιούχου: Employee Name
    """
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)

    assert process_payroll.parse_transfer_receipt(str(source))["amount"] == 1234.56


def test_bug_25_detail_workbook_does_not_convert_strings_to_formulas(tmp_path, monkeypatch):
    output = tmp_path / "detail.xlsx"
    payloads = ["=1+1", "+1+1", "-1+1", "@SUM(A1:A2)", " =1+1", "\n=1+1"]
    detail = pd.concat([_payroll_frame() for _ in payloads], ignore_index=True)
    detail["EmployeeName"] = payloads
    create_employee_reports.write_detail_report(detail, str(output))

    with zipfile.ZipFile(output) as workbook:
        worksheet_xml = workbook.read("xl/worksheets/sheet1.xml")
    assert b"<f>1+1</f>" not in worksheet_xml

    import payroll_gui

    grid_output = tmp_path / "grid.xlsx"
    gui = payroll_gui.PayrollProcessorGUI.__new__(payroll_gui.PayrollProcessorGUI)
    gui._prepare_export_payload = lambda tree: (["EmployeeName"], [["=2+2"]], [], None)
    gui.show_toast = lambda *args, **kwargs: None
    gui.show_message = lambda *args, **kwargs: pytest.fail(f"grid export failed: {args}")
    monkeypatch.setattr(payroll_gui.filedialog, "asksaveasfilename", lambda **kwargs: str(grid_output))
    gui._export_tree_xlsx(object())
    with zipfile.ZipFile(grid_output) as workbook:
        grid_xml = workbook.read("xl/worksheets/sheet1.xml")
    assert b"<f>2+2</f>" not in grid_xml


def test_bug_26_missing_employee_code_is_retained_with_unknown_label():
    frame = _payroll_frame()
    frame.loc[0, "EmployeeCode"] = None

    summary = create_employee_reports.prepare_summary(frame)
    assert len(summary) == 2
    assert set(summary["EmployeeCode"]) == {"Unknown"}


@pytest.mark.parametrize(
    "month_name",
    [
        "ΑΠΡΙΛΙΟΣ",
        "ΜΑΪΟΣ",
        "ΙΟΥΝΙΟΣ",
        "ΙΟΥΛΙΟΣ",
        "ΑΥΓΟΥΣΤΟΣ",
        "ΣΕΠΤΕΜΒΡΙΟΣ",
        "ΟΚΤΩΒΡΙΟΣ",
        "ΝΟΕΜΒΡΙΟΣ",
        "ΔΕΚΕΜΒΡΙΟΣ",
    ],
)
def test_bug_27_all_greek_month_filenames_are_payslips(month_name):
    assert process_payroll.classify_document(f"{month_name}_2026.pdf") == "Payslip"


def test_bug_28_invalid_insurance_month_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "claim.pdf"
    source.write_bytes(b"pdf")
    text = """
    ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
    Ημερομηνία Υποβολής 05/01/2026
    ΠΕΡΙΟΔΟΣ ΑΠΟ 13/2026
    Σύνολο Εισφορών 100,00
    """
    monkeypatch.setattr(process_payroll.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)

    assert process_payroll.parse_insurance_claim(str(source)) is None
