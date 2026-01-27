import datetime

import process_payroll as pp


def test_parse_amount_handles_commas_and_dots():
    assert pp._parse_amount("1.234,56") == 1234.56
    assert pp._parse_amount("123,45") == 123.45
    assert pp._parse_amount("123.45") == 123.45
    assert pp._parse_amount("bad") is None
    assert pp._parse_amount(None) is None


def test_extract_iban_from_label_line():
    text = """\
Προς Λογαριασμό: GR12 3456 7890 1234 5678 9012
"""
    assert pp._extract_iban(text) == "GR1234567890123456789012"


def test_extract_iban_from_next_line():
    text = """\
IBAN
GR98 7654 3210 9876 5432 1098
"""
    assert pp._extract_iban(text) == "GR9876543210987654321098"


def test_extract_iban_from_compact_text():
    text = "Some text GR1234567890123456789012345 more text"
    assert pp._extract_iban(text) == "GR1234567890123456789012345"


def test_extract_beneficiary_name_inline_label():
    text = """\
Κύριος Δικαιούχος: ΝΙΚΟΣ ΠΑΠΑΣ
"""
    assert pp._extract_beneficiary_name(text) == "ΝΙΚΟΣ ΠΑΠΑΣ"


def test_extract_beneficiary_name_next_line():
    text = """\
Ονοματεπώνυμο / Επωνυμία Δικαιούχου -
ΜΑΡΙΑ ΚΑΡΑ
"""
    assert pp._extract_beneficiary_name(text) == "ΜΑΡΙΑ ΚΑΡΑ"


def test_extract_beneficiary_name_ignores_noise():
    text = """\
Κύριος Δικαιούχος:
Πληροφορίες
"""
    assert pp._extract_beneficiary_name(text) is None


def test_extract_payroll_period_with_year():
    year, month = pp._extract_payroll_period("ΜΙΣΘΟΔΟΣΙΑ ΙΟΥΛ 2024")
    assert (year, month) == (2024, 7)


def test_extract_payroll_period_infers_year_from_paid_date():
    paid_date = datetime.date(2025, 1, 10)
    year, month = pp._extract_payroll_period("Payroll DEC", paid_date=paid_date)
    assert (year, month) == (2024, 12)


def test_classify_document_greek_and_encoded():
    assert pp.classify_document("ΔΩΡΟ ΧΡΙΣΤΟΥΓΕΝΝΩΝ.pdf") == "Bonus"
    assert pp.classify_document("ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ.pdf") == "VacationAllowance"
    assert pp.classify_document("ΑΠΟΖΗΜΙΩΣΗ ΑΔΕΙΑΣ.pdf") == "UnusedLeaveCompensation"
    assert pp.classify_document("ΑΠΟΔΕΙΞΕΙΣ ΠΛΗΡΩΜΩΝ.pdf") == "Payslip"
    assert pp.classify_document("#U0394#U03A9#U03A1.pdf") == "Bonus"


def test_sanitize_segment_replaces_invalid_chars():
    assert pp._sanitize_segment("John/Smith") == "John_Smith"
    assert pp._sanitize_segment(" ") == "unknown"


def test_build_archive_filename_includes_doc_type_and_date():
    entry = {
        "Date": "15/03/2024",
        "EmployeeName": "Ana Maria",
        "DocumentType": "Payslip",
    }
    filename = pp._build_archive_filename(entry)
    assert filename.startswith("2403_Ana_Maria_Payslip")
    assert filename.endswith(".pdf")
