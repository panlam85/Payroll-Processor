import datetime
import unicodedata
import zipfile

import pytest

import process_payroll


SUBMISSION = """
Ημερομηνία : 24/07/2026
ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ
Ημερομηνία Υποβολής
24/07/2026
Περίοδος Από
6/2026
Περίοδος Έως
6/2026
Σύνολο Ημερών Ασφάλισης 38
Σύνολο Αποδοχών 1.234,56
Σύνολο Εισφoρών 432,10
RF
RF123456789 000000123 45678
Σύνολο Επιδοτήσεων 0,00
Καταβλητέες Εισφορές 432,10
"""


@pytest.mark.parametrize("transform", [lambda s: s, str.upper, str.lower,
                                      lambda s: unicodedata.normalize("NFD", s),
                                      lambda s: s.replace("Υποβολής\n", "Υποβολής: ").replace("Από\n", "Από: ")])
def test_submission_labels_and_bare_rf_are_recognized(monkeypatch, transform):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda _: "pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *a, **k: transform(SUBMISSION))
    claim = process_payroll.parse_insurance_claim("ΕΙΣΦΟΡΕΣ ΕΦΚΑ 6.2026  .pdf")
    assert claim is not None
    assert (claim["claim_year"], claim["claim_month"]) == (2026, 6)
    assert claim["submission_date"] == datetime.date(2026, 7, 24)
    assert claim["total_earnings"] == 1234.56
    assert claim["total_contributions"] == 432.10
    assert claim["tpte_code"] == "RF12345678900000012345678"
    assert claim["claim_type"] == "EFKA"


def test_bare_rf_and_payable_fallback_do_not_require_total_contributions(monkeypatch):
    text = SUBMISSION.replace("Σύνολο Εισφoρών 432,10", "").replace("RF\nRF", "RF: RF") + "\nΤέκα\n"
    monkeypatch.setattr(process_payroll.shutil, "which", lambda _: "pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *a, **k: text)
    claim = process_payroll.parse_insurance_claim("claim.pdf")
    assert claim["total_contributions"] == 432.10
    assert claim["claim_type"] == "TEKA"
    assert claim["tpte_code"] == "RF12345678900000012345678"


@pytest.mark.parametrize("archive", [False, True])
def test_submission_routes_to_insurance_in_pdf_and_zip_imports(tmp_path, monkeypatch, archive):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda _: "pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *a, **k: SUBMISSION)
    source = tmp_path / "ΕΙΣΦΟΡΕΣ ΕΦΚΑ 6.2026  .pdf"
    source.write_bytes(b"synthetic test input")
    if archive:
        zip_path = tmp_path / "insurance.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(source, source.name)
        records, receipts, claims = process_payroll.process_zip(str(zip_path), str(tmp_path))
    else:
        records, claims, receipts = process_payroll.process_pdf_file(str(source), str(tmp_path))
    assert records.empty
    assert receipts == []
    assert len(claims) == 1
    assert claims[0]["claim_month"] == 6
    assert claims[0]["tpte_code"] == "RF12345678900000012345678"


def test_filename_alone_cannot_turn_a_payslip_into_insurance(monkeypatch):
    monkeypatch.setattr(process_payroll.shutil, "which", lambda _: "pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *a, **k: "ΑΠΟΔΕΙΞΗ ΠΛΗΡΩΜΗΣ\nΕΙΣΦΟΡΕΣ ΕΦΚΑ ΕΡΓΑΖ.: 25,00")
    assert process_payroll.parse_insurance_claim("ΕΙΣΦΟΡΕΣ ΕΦΚΑ 6.2026  .pdf") is None
