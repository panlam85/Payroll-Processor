import datetime

import process_payroll


def test_parse_insurance_claim_detects_claim(monkeypatch):
    marker = "\u0391\u039d\u03a4\u0399\u0393\u03a1\u0391\u03a6\u039f \u0391\u03a0\u039f\u0394\u0395\u0399\u039a\u03a4\u0399\u039a\u039f\u03a5 \u03a5\u03a0\u039f\u0392\u039f\u039b\u0397\u03a3"
    text = (
        f"{marker}\n"
        "\u0397\u03bc\u03b5\u03c1\u03bf\u03bc\u03b7\u03bd\u03af\u03b1 \u03a5\u03c0\u03bf\u03b2\u03bf\u03bb\u03ae\u03c2 12/03/2024\n"
        "\u03a0\u0395\u03a1\u0399\u039f\u0394\u039f\u03a3 \u0391\u03a0\u039f 3 / 2024\n"
        "\u03a3\u03cd\u03bd\u03bf\u03bb\u03bf \u0395\u03b9\u03c3\u03c6\u03bf\u03c1\u03ce\u03bd 100,50\n"
        "\u03a3\u03cd\u03bd\u03bf\u03bb\u03bf \u0391\u03c0\u03bf\u03b4\u03bf\u03c7\u03ce\u03bd 500,00\n"
        "\u03a4.\u03a0.\u03a4.\u0395. RF 1234"
    )

    monkeypatch.setattr(process_payroll.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)

    result = process_payroll.parse_insurance_claim("dummy.pdf")
    assert result is not None
    assert result["claim_year"] == 2024
    assert result["claim_month"] == 3
    assert result["total_contributions"] == 100.5
    assert result["total_earnings"] == 500.0
    assert result["tpte_code"].startswith("RF")


def test_parse_transfer_receipt(monkeypatch):
    marker = "\u039a\u03c9\u03b4\u03b9\u03ba\u03cc\u03c2 \u03a3\u03c5\u03bd\u03b1\u03bb\u03bb\u03b1\u03b3\u03ae\u03c2"
    beneficiary = "\u039a\u03cd\u03c1\u03b9\u03bf\u03c2 \u0394\u03b9\u03ba\u03b1\u03b9\u03bf\u03cd\u03c7\u03bf\u03c2: JOHN DOE"
    text = (
        f"{marker}\n"
        f"{beneficiary}\n"
        "\u03a0\u03bf\u03c3\u03cc: 1.234,56 EUR\n"
        "\u0395\u03ba\u03c4\u03ad\u03bb\u03b5\u03c3\u03b7 \u03a3\u03c4\u03b9\u03c2 05/02/2024\n"
        "IBAN GR12 3456 7890 1234 5678 9012 345\n"
        "\u039c\u0399\u03a3\u0398\u039f\u0394\u039f\u03a3\u0399\u0391 \u0399\u0391\u039d\u039f\u03a5\u0391\u03a1\u0399\u039f\u03a3 2024\n"
    )

    monkeypatch.setattr(process_payroll.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(process_payroll.subprocess, "check_output", lambda *args, **kwargs: text)

    result = process_payroll.parse_transfer_receipt("receipt.pdf")
    assert result is not None
    assert result["employee_name"] == "JOHN DOE"
    assert result["amount"] == 1234.56
    assert result["paid_date"] == datetime.date(2024, 2, 5)
    assert result["payroll_year"] == 2024
    assert result["payroll_month"] == 1
