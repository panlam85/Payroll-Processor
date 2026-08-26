import datetime
import os

import process_payroll


def test_parse_amount_handles_commas_and_thousands():
    assert process_payroll._parse_amount("1.234,56") == 1234.56
    assert process_payroll._parse_amount("1234,56") == 1234.56
    assert process_payroll._parse_amount("1234.56") == 1234.56
    assert process_payroll._parse_amount("bad") is None
    assert process_payroll._parse_amount(None) is None


def test_extract_iban_from_label_line():
    text = "Pros Logariasmo: GR12 3456 7890 1234 5678 9012 345"
    assert process_payroll._extract_iban(text) == "GR1234567890123456789012345"


def test_extract_iban_from_compact_text():
    text = "Random GR1234567890123456789012345 data"
    assert process_payroll._extract_iban(text) == "GR1234567890123456789012345"


def test_extract_beneficiary_name_from_label():
    label = "\u039a\u03cd\u03c1\u03b9\u03bf\u03c2 \u0394\u03b9\u03ba\u03b1\u03b9\u03bf\u03cd\u03c7\u03bf\u03c2"
    text = f"{label}: JOHN DOE\nTrapeza XYZ"
    assert process_payroll._extract_beneficiary_name(text) == "JOHN DOE"


def test_extract_payroll_period_with_year():
    text = "Payroll JAN 2024"
    assert process_payroll._extract_payroll_period(text) == (2024, 1)


def test_extract_payroll_period_infers_year_from_paid_date():
    text = "DEK"
    paid_date = datetime.date(2025, 1, 5)
    assert process_payroll._extract_payroll_period(text, paid_date=paid_date) == (2024, 12)


def test_classify_document_examples():
    assert process_payroll.classify_document("\u0394\u03a9\u03a1\u039f_2024.pdf") == "Bonus"
    assert process_payroll.classify_document("\u0395\u03a0\u0399\u0394\u039f\u039c\u0391_\u0391\u0394\u0395\u0399\u0391.pdf") == "VacationAllowance"
    assert process_payroll.classify_document("\u0391\u03a0\u039f\u0396\u0397\u039c\u0399\u03a9\u03a3\u0397.pdf") == "UnusedLeaveCompensation"
    assert process_payroll.classify_document("\u0391\u03a0\u039f\u0394\u0395\u0399\u039e\u0395\u0399\u03a3_2024.pdf") == "Payslip"


def test_sanitize_segment_removes_invalid_chars():
    assert process_payroll._sanitize_segment("Name:/\\*") == "Name____"
    assert process_payroll._sanitize_segment("") == "unknown"


def test_derive_archive_dir_uses_date_and_employee():
    entry = {
        "EmployeeName": "John / Doe",
        "EmployeeCode": "E1",
        "Date": "05/02/2024",
        "DocumentType": "Payslip",
    }
    base = "/tmp/archive"
    result = process_payroll._derive_archive_dir(base, entry)
    assert result == os.path.join(base, "2024", "02", "E1 - John _ Doe")


def test_build_claim_archive_filename():
    claim = {"claim_year": 2024, "claim_month": 3, "claim_type": "EFKA", "tpte_code": "RF 12 34"}
    name = process_payroll._build_claim_archive_filename(claim)
    assert name.startswith("202403_EFKA_TPTE_RF 12 34")
