#!/usr/bin/env python3
"""Process payroll files contained in zipped archives.

This script recursively walks through any ZIP files in a specified
directory, extracts PDFs, identifies the type of payroll document
(e.g. regular payslip, unused‑leave compensation, vacation bonus,
Easter/Christmas bonus) based on the filename, and then parses
each pay slip to extract core information about the employee and
payment amounts.  A simple regular‑expression based parser is
employed to pick up fields such as employee code, full name,
basic salary, total earnings and net pay.  Parsed records are
accumulated into a pandas DataFrame and written to a CSV.

Usage:
    python process_payroll.py --input-dir /path/to/zips --out-csv results.csv
"""

import argparse
import datetime
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import PurePosixPath
from typing import Dict, List

import pandas as pd


MAX_ZIP_MEMBERS = 2_000
MAX_ZIP_MEMBER_SIZE = 256 * 1024 * 1024
MAX_ZIP_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200
MAX_ZIP_PATH_DEPTH = 20


def parse_pdf(file_path: str, allowance_type: str) -> List[Dict[str, str]]:
    """Parse a payroll PDF and return a list of dictionaries for each slip.

    Each slip in the PDF is identified by a line starting with
    "Κωδικός :".  Within each slip the parser looks for the
    employee code, full name, basic salary, total earnings and net pay.

    Args:
        file_path: Path to the PDF to parse.
        allowance_type: A label describing the type of document (e.g.
            "Misthodosia", "Apozimiosi Adeias", "Epidoma Adeias", "Doro").

    Returns:
        A list of dictionaries containing parsed fields for each slip.
    """
    entries: List[Dict[str, str]] = []
    try:
        # Use pdftotext to extract text; the dash outputs to stdout
        text = subprocess.check_output(["pdftotext", file_path, "-"], universal_newlines=True)
    except Exception as exc:  # pragma: no cover - external utility error
        print(f"Failed to parse {file_path}: {exc}")
        return entries
    # Split the text into lines for locating individual slips.  Each slip
    # begins with a line starting with "Κωδικός".  Some PDFs include
    # only one date at the top of the document; extract it here as a
    # fallback for any slips that do not include their own date.
    lines = text.split("\n")
    # Capture the first date in the entire document (format dd/mm/yyyy)
    doc_date_match = re.search(r"([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    default_date = doc_date_match.group(1) if doc_date_match else None
    # Find indices where a new slip begins
    slip_header = re.compile(r"^\s*Κωδικός\s*:\s*\S+")
    slip_indices = [idx for idx, line in enumerate(lines) if slip_header.match(line)]
    if not slip_indices:
        # No slips found, return empty list
        return entries
    slip_indices.append(len(lines))
    for start, end in zip(slip_indices, slip_indices[1:]):
        segment = "\n".join(lines[start:end])
        if not segment.strip():
            continue
        # Flatten whitespace to ease regex matching across line breaks
        flat = re.sub(r"\s+", " ", segment)
        # Extract fields using regular expressions.  Allow colon to be
        # optional to accommodate slight variations.
        code_match = re.search(r"Κωδικός\s*:?\s*(\S+)", flat)
        if not code_match:
            continue
        name_match = re.search(
            r"Ονοματεπώνυμο\s*:?\s*(.+?)(?=\s+Διεύθυνση\s*:|\s+Α\.Φ\.Μ\.|\s*$)",
            flat,
            re.IGNORECASE,
        )
        basic_match = re.search(r"ΒΑΣΙΚΟΣ\s+ΜΙΣΘΟΣ\s*:?\s*([0-9.,]+)", flat)
        total_match = re.search(r"ΣΥΝΟΛ[ΟΟ]\s+ΑΠΟΔΟΧΩΝ\s+ΠΕΡΙΟΔΟΥ\s*:?\s*([0-9.,]+)", flat)
        # Net pay sometimes appears on a separate line labelled "ΠΛΗΡΩΤΕΟ"
        net_match = re.search(r"ΠΛΗΡΩΤΕΟ\s*:?\s*([0-9.,]+)", flat)
        # Extract date within the slip if available; else use default_date
        date_match = re.search(r"ΗΜΕΡ/\s*ΝΙΑ\s*:?\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", flat)
        # Extract contributions for EFKA and TEKA (employee and employer)
        efka_emp_match = re.search(r"ΕΙΣΦΟΡΕΣ\s+ΕΦΚΑ\s+ΕΡΓΑΖ\.?:\s*([0-9.,]+)", flat)
        efka_ergo_match = re.search(r"ΕΙΣΦΟΡΕΣ\s+ΕΦΚΑ\s+ΕΡΓΟΔ\.?:\s*([0-9.,]+)", flat)
        teka_emp_match = re.search(r"ΕΙΣΦΟΡΕΣ\s+TEKA\s+ΕΡΓΑΖ\.?:\s*([0-9.,]+)", flat)
        teka_ergo_match = re.search(r"ΕΙΣΦΟΡΕΣ\s+TEKA\s+ΕΡΓΟΔ\.?:\s*([0-9.,]+)", flat)
        entry: Dict[str, str] = {
            "DocumentType": allowance_type,
            "EmployeeCode": code_match.group(1),
            "EmployeeName": name_match.group(1).strip() if name_match else None,
            "BasicSalary": basic_match.group(1) if basic_match else None,
            "TotalEarnings": total_match.group(1) if total_match else None,
            "NetPay": net_match.group(1) if net_match else None,
            "Date": date_match.group(1) if date_match else default_date,
            "EFKAEmployee": efka_emp_match.group(1) if efka_emp_match else None,
            "EFKAEmployer": efka_ergo_match.group(1) if efka_ergo_match else None,
            "TEKAEmployee": teka_emp_match.group(1) if teka_emp_match else None,
            "TEKAEmployer": teka_ergo_match.group(1) if teka_ergo_match else None,
            "SourcePDF": os.path.basename(file_path),
        }
        entries.append(entry)
    return entries


def _parse_amount(value: str):
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9,\.\-+]", "", str(value).strip())
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        decimal_separator = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        cleaned = cleaned.replace(thousands_separator, "")
        if decimal_separator == ",":
            cleaned = cleaned.replace(",", ".")
    else:
        separator = "," if "," in cleaned else "." if "." in cleaned else None
        if separator:
            parts = cleaned.split(separator)
            if len(parts) > 2:
                grouping_parts = [part.lstrip("+-") for part in parts[1:-1]]
                if len(parts[-1]) in (1, 2) and all(len(part) == 3 for part in grouping_parts):
                    cleaned = "".join(parts[:-1]) + "." + parts[-1]
                elif len(parts[-1]) == 3 and all(len(part) == 3 for part in parts[1:]):
                    cleaned = "".join(parts)
                else:
                    return None
            elif len(parts) == 2:
                whole, fractional = parts
                if len(fractional) == 3 and len(whole.lstrip("+-")) <= 3:
                    cleaned = whole + fractional
                else:
                    cleaned = whole + "." + fractional
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_iban(text: str):
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    iban_regex = re.compile(r"GR\s?\d{2}(?:\s?\d{4}){5,6}")
    label_keywords = ("Προς Λογαριασμό", "IBAN", "Προς Λογαριασμό:", "Προς Λογαριασμό :")
    for idx, line in enumerate(lines):
        if any(key in line for key in label_keywords):
            match = iban_regex.search(line)
            if match:
                return re.sub(r"\s+", "", match.group(0)).upper()
            if idx + 1 < len(lines):
                match = iban_regex.search(lines[idx + 1])
                if match:
                    return re.sub(r"\s+", "", match.group(0)).upper()
    compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    match = re.search(r"GR[0-9]{25}", compact)
    if match:
        return match.group(0)
    return None


def _extract_beneficiary_name(text: str):
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines()]
    labels = {
        "Κύριος Δικαιούχος": True,
        "Ονοματεπώνυμο/ Επωνυμία Δικαιούχου": True,
        "Ονοματεπώνυμο / Επωνυμία Δικαιούχου": True,
        "Ονοματεπώνυμο / Επωνυμία Δικαιούχου -": True,
        "Ονοματεπώνυμο / Επωνυμία Δικαιούχου - ": True,
        "Ονοματεπώνυμο/ Επωνυμία Δικαιούχου -": True,
    }
    ignore_keywords = (
        "Τράπεζα",
        "Αντιστοιχία",
        "Δικαιούχου",
        "Πληροφορίες",
        "Συνδικαιούχοι",
        "Τρόπος επαλήθευσης",
        "Αποτέλεσμα επαλήθευσης",
    )

    def is_label(line):
        base = line.split(":")[0].strip()
        return base in labels

    def is_valid_candidate(value):
        if not value:
            return False
        if any(key in value for key in ignore_keywords):
            return False
        if not re.search(r"[Α-ΩΆΈΉΊΌΎΏA-Z]", value, re.IGNORECASE):
            return False
        return True
    for idx, line in enumerate(lines):
        if is_label(line) or line.startswith("Κύριος Δικαιούχος"):
            parts = line.split(":", 1)
            if len(parts) > 1 and parts[1].strip():
                candidate = parts[1].strip()
            else:
                candidate = ""
                for next_idx in range(idx + 1, min(idx + 3, len(lines))):
                    if lines[next_idx]:
                        candidate = lines[next_idx]
                        break
            candidate = candidate.strip()
            if is_valid_candidate(candidate):
                return candidate
    return None


def _extract_payroll_period(text: str, paid_date: datetime.date = None):
    if not text:
        return None, None
    month_map = {
        "ΙΑΝΟΥΑΡΙΟΣ": 1,
        "ΙΑΝΟΥΑΡΙΟΥ": 1,
        "ΙΑΝ": 1,
        "ΦΕΒΡΟΥΑΡΙΟΣ": 2,
        "ΦΕΒΡΟΥΑΡΙΟΥ": 2,
        "ΦΕΒ": 2,
        "ΜΑΡΤΙΟΣ": 3,
        "ΜΑΡΤΙΟΥ": 3,
        "ΜΑΡ": 3,
        "ΑΠΡΙΛΙΟΣ": 4,
        "ΑΠΡΙΛΙΟΥ": 4,
        "ΑΠΡ": 4,
        "ΜΑΪΟΣ": 5,
        "ΜΑΙΟΣ": 5,
        "ΜΑΪΟΥ": 5,
        "ΜΑΙΟΥ": 5,
        "ΙΟΥΝΙΟΣ": 6,
        "ΙΟΥΝΙΟΥ": 6,
        "ΙΟΥΝ": 6,
        "ΙΟΥΛΙΟΣ": 7,
        "ΙΟΥΛΙΟΥ": 7,
        "ΙΟΥΛ": 7,
        "ΑΥΓΟΥΣΤΟΣ": 8,
        "ΑΥΓΟΥΣΤΟΥ": 8,
        "ΑΥΓ": 8,
        "ΣΕΠΤΕΜΒΡΙΟΣ": 9,
        "ΣΕΠΤΕΜΒΡΙΟΥ": 9,
        "ΣΕΠ": 9,
        "ΟΚΤΩΒΡΙΟΣ": 10,
        "ΟΚΤΩΒΡΙΟΥ": 10,
        "ΟΚΤ": 10,
        "ΝΟΕΜΒΡΙΟΣ": 11,
        "ΝΟΕΜΒΡΙΟΥ": 11,
        "ΝΟΕ": 11,
        "ΔΕΚΕΜΒΡΙΟΣ": 12,
        "ΔΕΚΕΜΒΡΙΟΥ": 12,
        "ΔΕΚ": 12,
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
        "DEK": 12,
        "DEKEM": 12,
        "NOEM": 11,
        "OKT": 10,
        "SEPTEM": 9,
        "AUGOU": 8,
        "IOUL": 7,
        "IOUN": 6,
    }
    for line in text.upper().splitlines():
        for key in sorted(month_map, key=len, reverse=True):
            if not re.search(rf"(?<!\w){re.escape(key)}(?!\w)", line):
                continue
            year_match = re.search(r"(?<!/)\b(20\d{2})\b", line)
            year = int(year_match.group(1)) if year_match else None
            month = month_map[key]
            if year is None and paid_date:
                year = paid_date.year
                if paid_date.month < month:
                    year -= 1
            return year, month
    return None, None


def parse_insurance_claim(pdf_path: str):
    """Parse an EFKA/TEKA insurance claim PDF and return claim details if detected."""
    if not shutil.which("pdftotext"):
        return None
    try:
        text = subprocess.check_output(["pdftotext", pdf_path, "-"], universal_newlines=True)
    except Exception:
        return None
    if "ΑΝΤΙΓΡΑΦΟ ΑΠΟΔΕΙΚΤΙΚΟΥ ΥΠΟΒΟΛΗΣ" not in text:
        return None
    claim_type = "TEKA" if "ΤΕΚΑ" in text or "TEKA" in text else "EFKA"
    flat = re.sub(r"\s+", " ", text)
    submission_match = re.search(r"Ημερομηνία\s+Υποβολής\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", flat)
    period_match = re.search(r"ΠΕΡΙΟΔΟΣ\s+ΑΠΟ\s*([0-9]{1,2})\s*/\s*([0-9]{4})", flat)
    total_earnings_match = re.search(r"Σύνολο\s+Αποδοχών\s*([0-9.,]+)", flat)
    total_contrib_match = re.search(r"Σύνολο\s+Εισφ[oο]ρών\s*([0-9.,]+)", flat, re.IGNORECASE)
    if not total_contrib_match:
        total_contrib_match = re.search(r"Καταβλητέες\s+Εισφ[oο]ρ(?:ές|ες)\s*([0-9.,]+)", flat, re.IGNORECASE)
    tpte_match = re.search(r"Τ\.Π\.Τ\.Ε\.?\s*(RF\s*[0-9 ]+|[0-9 ]+)", flat)
    if not tpte_match:
        tpte_match = re.search(r"Ταυτότητα\s+Πληρωμής\s*(RF\s*[0-9 ]+|[0-9 ]+)", flat)
    if not tpte_match:
        tpte_match = re.search(
            r"Κωδικός\s+Ηλεκτρονικής\s+Πληρωμής\s*\(RF\):?\s*(RF\s*[0-9 ]+|[0-9 ]+)",
            flat,
        )

    if not (submission_match and period_match and total_contrib_match):
        return None

    try:
        day, month, year = [int(part) for part in submission_match.group(1).split("/")]
        submission_date = datetime.date(year, month, day)
    except Exception:
        submission_date = None

    claim_month = int(period_match.group(1))
    claim_year = int(period_match.group(2))
    if not 1 <= claim_month <= 12:
        return None
    total_earnings = _parse_amount(total_earnings_match.group(1)) if total_earnings_match else None
    total_contributions = _parse_amount(total_contrib_match.group(1))
    tpte_code = re.sub(r"\s+", "", tpte_match.group(1)).strip() if tpte_match else None

    return {
        "claim_year": claim_year,
        "claim_month": claim_month,
        "submission_date": submission_date,
        "total_earnings": total_earnings,
        "total_contributions": total_contributions,
        "tpte_code": tpte_code,
        "claim_type": claim_type,
        "source_pdf": os.path.basename(pdf_path),
    }


def parse_transfer_receipt(pdf_path: str):
    """Parse a bank transfer receipt PDF and return receipt details if detected."""
    if not shutil.which("pdftotext"):
        return None
    try:
        text = subprocess.check_output(["pdftotext", pdf_path, "-"], universal_newlines=True)
    except Exception:
        return None
    if (
        "Κωδικός Συναλλαγής" not in text
        and "Μεταφορά σε τρίτο" not in text
        and "Μεταφορά σε IBAN" not in text
        and "Λεπτομέρειες Συναλλαγής" not in text
    ):
        return None
    name = _extract_beneficiary_name(text)
    amount_match = re.search(r"Ποσό:\s*([0-9\.,]+)", text, re.S)
    if not amount_match:
        amount_match = re.search(r"Ποσό\s+συναλλαγής\s*([0-9\.,]+)", text, re.S)
    if not amount_match:
        amount_match = re.search(r"([0-9\.,]+)\s*EUR", text)
    date_match = re.search(r"(?:Εκτέλεση\s+Στις|Στις)\s*(\d{1,2}/\d{1,2}/\d{4})", text)
    if not date_match:
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    if not (name and amount_match and date_match):
        return None
    name = name.strip()
    amount = _parse_amount(amount_match.group(1))
    if amount is None:
        return None
    try:
        day, month, year = [int(part) for part in date_match.group(1).split("/")]
        paid_date = datetime.date(year, month, day)
    except Exception:
        return None
    iban = _extract_iban(text)
    payroll_year, payroll_month = _extract_payroll_period(text, paid_date=paid_date)
    return {
        "employee_name": name,
        "amount": amount,
        "paid_date": paid_date,
        "iban": iban,
        "beneficiary_name": name,
        "payroll_year": payroll_year,
        "payroll_month": payroll_month,
    }


def classify_document(filename: str) -> str:
    """Classify a payroll document based on its filename.

    Filenames provided by the accountant can either be plain Greek
    (e.g. ``"ΑΠΟΔΕΙΞΕΙΣ ΠΛΗΡΩΜΩΝ.pdf"``) or URL‑encoded (e.g.
    ``"#U0394#U03a9#U03a1…"``).  To keep the classification logic
    robust, this function normalises the filename to uppercase and
    searches for distinctive substrings that correspond to the
    document’s purpose:

    * ``ΔΩΡΟ`` → Bonus (Easter/Christmas gift)
    * ``ΕΠΙΔΟΜΑ`` and ``ΑΔΕΙΑ`` → Vacation allowance
    * ``ΑΠΟΖΗΜΙΩΣΗ`` → Compensation for unused leave
    * ``ΑΠΟΔΕΙΞΕΙΣ`` or month names (``ΙΑΝΟΥΑΡΙΟΣ``, ``ΦΕΒΡΟΥΑΡΙΟΣ``
      etc.) → Regular payslip

    When dealing with URL‑encoded names, the encoded values for Greek
    characters start with ``U0``, so we additionally check for the
    presence of certain codepoints to approximate the same matches.

    Args:
        filename: Basename of the PDF file.

    Returns:
        A short label representing the document type.
    """
    name = filename.upper()
    # Check for plain Greek substrings
    if 'ΔΩΡΟ' in name:
        return 'Bonus'
    if 'ΕΠΙΔΟΜΑ' in name and ('ΑΔΕΙΑ' in name or 'ΑΔΕΙΑΣ' in name):
        return 'VacationAllowance'
    if 'ΑΠΟΖΗΜΙΩΣΗ' in name:
        return 'UnusedLeaveCompensation'
    greek_months = (
        'ΙΑΝΟΥΑΡΙΟΣ', 'ΦΕΒΡΟΥΑΡΙΟΣ', 'ΜΑΡΤΙΟΣ', 'ΑΠΡΙΛΙΟΣ', 'ΜΑΪΟΣ',
        'ΜΑΙΟΣ', 'ΙΟΥΝΙΟΣ', 'ΙΟΥΛΙΟΣ', 'ΑΥΓΟΥΣΤΟΣ', 'ΣΕΠΤΕΜΒΡΙΟΣ',
        'ΟΚΤΩΒΡΙΟΣ', 'ΝΟΕΜΒΡΙΟΣ', 'ΔΕΚΕΜΒΡΙΟΣ',
    )
    if 'ΑΠΟΔΕΙΞΕΙΣ' in name or any(month in name for month in greek_months):
        return 'Payslip'
    # Fallback for URL‑encoded names using common codepoints
    if 'U0394' in name and 'U03A9' in name and 'U03A1' in name:
        return 'Bonus'
    if 'U0395' in name and 'U03A0' in name and 'U0399' in name:
        return 'VacationAllowance'
    if 'U0391' in name and 'U03A0' in name and 'U0396' in name:
        return 'UnusedLeaveCompensation'
    if 'U0391' in name and 'U03A0' in name and 'U0394' in name:
        return 'Payslip'
    return 'Salary'


def _sanitize_segment(value: str) -> str:
    if not value:
        return "unknown"
    cleaned = re.sub(r'[\\\\/:*?"<>|]', "_", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "unknown"


def _employee_archive_segment(entry: Dict[str, str]) -> str:
    employee_code = str(entry.get("EmployeeCode") or "").strip()
    employee_name = str(entry.get("EmployeeName") or "").strip()
    if employee_code and employee_name:
        return _sanitize_segment(f"{employee_code} - {employee_name}")
    return _sanitize_segment(employee_code or employee_name or "unknown")


def _derive_archive_dir(archive_root: str, entry: Dict[str, str]) -> str:
    date_str = entry.get("Date") or ""
    year = "unknown"
    month = "unknown"
    try:
        parsed = datetime.datetime.strptime(date_str, "%d/%m/%Y")
        year = str(parsed.year)
        month = f"{parsed.month:02d}"
    except ValueError:
        pass
    employee_dir = _employee_archive_segment(entry)
    return os.path.join(archive_root, year, month, employee_dir)


def _derive_claim_archive_dir(archive_root: str, claim: Dict[str, object]) -> str:
    year = claim.get("claim_year")
    year_part = str(year) if isinstance(year, int) else "unknown"
    return os.path.join(archive_root, year_part, "Insurance")


def _build_claim_archive_filename(claim: Dict[str, object]) -> str:
    year = claim.get("claim_year")
    month = claim.get("claim_month")
    period_part = "unknown"
    if isinstance(year, int) and isinstance(month, int):
        period_part = f"{year:04d}{month:02d}"
    claim_type = claim.get("claim_type") or "EFKA"
    claim_type_part = _sanitize_segment(str(claim_type)).upper()
    tpte = claim.get("tpte_code") or ""
    tpte_part = _sanitize_segment(str(tpte)) if tpte else "unknown"
    return f"{period_part}_{claim_type_part}_TPTE_{tpte_part}.pdf"


def _archive_pdf_for_claim(archive_root: str, file_path: str, claim: Dict[str, object]) -> Dict[str, object]:
    archive_dir = _derive_claim_archive_dir(archive_root, claim)
    os.makedirs(archive_dir, exist_ok=True)
    dest_name = _build_claim_archive_filename(claim)
    dest_path = os.path.join(archive_dir, dest_name)
    copied = False
    if not os.path.exists(dest_path):
        shutil.copy2(file_path, dest_path)
        copied = True
    return {"path": dest_path, "copied": copied}


def _receipt_period_date(receipt: Dict[str, object]):
    """Return the payroll-period date for a receipt, falling back to its paid date."""
    year = receipt.get("payroll_year")
    month = receipt.get("payroll_month")
    if isinstance(year, int) and isinstance(month, int):
        try:
            return datetime.date(year, month, 1)
        except ValueError:
            pass
    paid_date = receipt.get("paid_date")
    if isinstance(paid_date, datetime.datetime):
        return paid_date.date()
    if isinstance(paid_date, datetime.date):
        return paid_date
    return None


def _archive_pdf_for_receipt(archive_root: str, file_path: str, receipt: Dict[str, object]) -> Dict[str, object]:
    period_date = _receipt_period_date(receipt)
    entry = {
        "EmployeeName": receipt.get("employee_name"),
        "EmployeeCode": None,
        "Date": period_date.strftime("%d/%m/%Y") if period_date else None,
        "DocumentType": "Receipt",
    }
    archive_dir = _derive_archive_dir(archive_root, entry)
    os.makedirs(archive_dir, exist_ok=True)
    source_digest = _sha256_file(file_path)
    dest_name = _build_archive_filename(
        entry,
        suffix=f"receipt_{source_digest[:12]}",
        merge_if_exists=False,
        include_doc_type=True,
    )
    dest_path = os.path.join(archive_dir, dest_name)
    copied = False
    if not os.path.exists(dest_path):
        shutil.copy2(file_path, dest_path)
        copied = True
    return {"path": dest_path, "copied": copied}


def find_monthly_payment_pdfs(archive_root: str, receipt: Dict[str, object]) -> List[str]:
    """Return the archived payment PDFs for a receipt's employee and month.

    Receipt archives live alongside the payment PDFs in
    ``archive_root/YYYY/MM/Employee/``. Anything already carrying the receipt
    suffix or document type is skipped so a receipt is never merged into
    another receipt.
    """
    period_date = _receipt_period_date(receipt)
    if not period_date:
        return []
    employee_name = _sanitize_segment(str(receipt.get("employee_name") or "unknown"))
    month_dir = os.path.join(archive_root, str(period_date.year), f"{period_date.month:02d}")
    if not os.path.isdir(month_dir):
        return []
    exact_dir = os.path.join(month_dir, employee_name)
    coded_suffix = f" - {employee_name}".casefold()
    coded_dirs = []
    for child in sorted(os.listdir(month_dir)):
        candidate_dir = os.path.join(month_dir, child)
        if os.path.isdir(candidate_dir) and child.casefold().endswith(coded_suffix):
            coded_dirs.append(candidate_dir)
    # A receipt does not carry an employee code. If multiple code-qualified
    # namesakes exist, merging would risk attaching confidential data to the
    # wrong person, so leave the receipt separate for manual reconciliation.
    if len(coded_dirs) > 1:
        return []
    archive_dirs = []
    if os.path.isdir(exact_dir):
        archive_dirs.append(exact_dir)
    archive_dirs.extend(path for path in coded_dirs if path not in archive_dirs)
    if not archive_dirs:
        return []
    archived_receipt = receipt.get("archive_path")
    archived_receipt = os.path.abspath(archived_receipt) if archived_receipt else None
    matches = []
    for archive_dir in archive_dirs:
        for fname in sorted(os.listdir(archive_dir)):
            if not fname.lower().endswith(".pdf"):
                continue
            candidate = os.path.join(archive_dir, fname)
            if archived_receipt and os.path.abspath(candidate) == archived_receipt:
                continue
            if "_receipt_receipt" in fname.lower():
                continue
            matches.append(candidate)
    return matches


def merge_receipt_into_monthly_pdf(
    archive_root: str,
    receipt_path: str,
    receipt: Dict[str, object],
) -> Dict[str, object]:
    """Append a payment receipt to that employee's monthly payment PDFs.

    Returns ``{"merged": [...], "skipped": [...]}``. Merging needs poppler's
    ``pdfunite``; without it every target lands in ``skipped`` and the receipt
    remains archived as its own file, so nothing is lost either way.
    """
    result = {"merged": [], "skipped": []}
    if not receipt_path or not os.path.exists(receipt_path):
        return result
    targets = find_monthly_payment_pdfs(archive_root, receipt)
    for target in targets:
        if os.path.abspath(target) == os.path.abspath(receipt_path):
            continue
        receipt_digest = _sha256_file(receipt_path)
        if receipt_digest in _load_source_manifest(target):
            result["skipped"].append(target)
        elif _merge_pdf_files(target, receipt_path):
            _record_archived_source(target, receipt_digest)
            result["merged"].append(target)
        else:
            result["skipped"].append(target)
    return result


def _split_pdf_pages(file_path: str, temp_dir: str) -> List[str]:
    if not shutil.which("pdfseparate"):
        return []
    pattern = os.path.join(temp_dir, "page-%d.pdf")
    try:
        subprocess.check_call(["pdfseparate", file_path, pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    pages = []
    for fname in os.listdir(temp_dir):
        if fname.startswith("page-") and fname.endswith(".pdf"):
            pages.append(fname)
    def page_index(name: str) -> int:
        match = re.search(r"page-(\d+)\.pdf$", name)
        return int(match.group(1)) if match else 0
    pages.sort(key=page_index)
    return [os.path.join(temp_dir, name) for name in pages]


def _merge_pdf_files(dest_path: str, new_path: str) -> bool:
    if not shutil.which("pdfunite"):
        return False
    temp_path = f"{dest_path}.tmp"
    try:
        subprocess.check_call(
            ["pdfunite", dest_path, new_path, temp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.replace(temp_path, dest_path)
        return True
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


def _sha256_file(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest_path(dest_path: str) -> str:
    return f"{dest_path}.sources.json"


def _load_source_manifest(dest_path: str) -> set:
    manifest_path = _source_manifest_path(dest_path)
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return set()
    sources = payload.get("sha256", []) if isinstance(payload, dict) else []
    return {str(item) for item in sources}


def _record_archived_source(dest_path: str, source_digest: str) -> None:
    sources = _load_source_manifest(dest_path)
    sources.add(source_digest)
    manifest_path = _source_manifest_path(dest_path)
    directory = os.path.dirname(manifest_path)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".sources_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"sha256": sorted(sources)}, handle, indent=2)
        os.replace(temp_path, manifest_path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def _source_already_archived(dest_path: str, source_path: str) -> bool:
    source_digest = _sha256_file(source_path)
    if source_digest in _load_source_manifest(dest_path):
        return True
    if os.path.exists(dest_path) and _sha256_file(dest_path) == source_digest:
        _record_archived_source(dest_path, source_digest)
        return True
    return False


def _archive_pdf_for_entry(
    archive_root: str,
    file_path: str,
    entry: Dict[str, str],
    suffix: str = "",
    merge_if_exists: bool = True,
    include_doc_type: bool = True,
) -> None:
    archive_dir = _derive_archive_dir(archive_root, entry)
    os.makedirs(archive_dir, exist_ok=True)
    dest_name = _build_archive_filename(
        entry,
        suffix=suffix,
        merge_if_exists=merge_if_exists,
        include_doc_type=include_doc_type,
    )
    dest_path = os.path.join(archive_dir, dest_name)
    if os.path.exists(dest_path) and merge_if_exists:
        if _source_already_archived(dest_path, file_path):
            return
        if _merge_pdf_files(dest_path, file_path):
            _record_archived_source(dest_path, _sha256_file(file_path))
            return
    if not os.path.exists(dest_path):
        shutil.copy2(file_path, dest_path)
        _record_archived_source(dest_path, _sha256_file(file_path))


def _build_archive_filename(
    entry: Dict[str, str],
    suffix: str = "",
    merge_if_exists: bool = True,
    include_doc_type: bool = True,
) -> str:
    date_str = entry.get("Date") or ""
    date_part = "unknown"
    try:
        parsed = datetime.datetime.strptime(date_str, "%d/%m/%Y")
        date_part = parsed.strftime("%y%m")
    except ValueError:
        pass
    name_part = _employee_archive_segment(entry).replace(" ", "_")
    base = f"{date_part}_{name_part}"
    if include_doc_type:
        doc_type = entry.get("DocumentType") or entry.get("document_type") or "Salary"
        doc_part = _sanitize_segment(str(doc_type)).replace(" ", "_")
        base = f"{base}_{doc_part}"
    file_suffix = f"_{suffix}" if suffix else ""
    if merge_if_exists:
        return f"{base}{file_suffix}.pdf"
    return f"{base}{file_suffix}.pdf"


def _validated_zip_members(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise ValueError(f"ZIP contains too many members ({len(infos)} > {MAX_ZIP_MEMBERS})")
    seen = set()
    total_size = 0
    pdf_members = []
    for info in infos:
        normalized = posixpath.normpath(info.filename.replace("\\", "/"))
        path = PurePosixPath(normalized)
        if normalized.startswith("/") or ".." in path.parts:
            raise ValueError(f"Unsafe ZIP member path: {info.filename}")
        if len(path.parts) > MAX_ZIP_PATH_DEPTH:
            raise ValueError(f"ZIP member path is too deep: {info.filename}")
        if info.is_dir():
            continue
        member_key = normalized.casefold()
        if member_key in seen:
            raise ValueError(f"Duplicate ZIP member path: {info.filename}")
        seen.add(member_key)
        if info.file_size > MAX_ZIP_MEMBER_SIZE:
            raise ValueError(f"ZIP member is too large: {info.filename}")
        total_size += info.file_size
        if total_size > MAX_ZIP_TOTAL_SIZE:
            raise ValueError("ZIP expanded size exceeds the safety limit")
        if info.file_size:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_ZIP_COMPRESSION_RATIO:
                raise ValueError(f"ZIP member compression ratio is suspicious: {info.filename}")
        if normalized.lower().endswith(".pdf"):
            pdf_members.append(info)
    return pdf_members


def _extract_pdf_members(zf: zipfile.ZipFile, members: List[zipfile.ZipInfo], extract_dir: str) -> None:
    for info in members:
        normalized = posixpath.normpath(info.filename.replace("\\", "/"))
        destination = os.path.join(extract_dir, *PurePosixPath(normalized).parts)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with zf.open(info, "r") as source, open(destination, "wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)


def process_zip(zip_path: str, temp_root: str, archive_root: str = None):
    """Extract PDFs from a zip and return parsed records and receipts."""
    records: List[Dict[str, str]] = []
    receipts: List[Dict[str, object]] = []
    claims: List[Dict[str, object]] = []
    archived_keys = set()
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Every archive gets a fresh directory. Reusing a basename-derived path
        # can leave PDFs from an earlier archive in the next archive's walk.
        archive_stem = os.path.splitext(os.path.basename(zip_path))[0]
        safe_stem = _sanitize_segment(archive_stem).replace(" ", "_")
        extract_dir = tempfile.mkdtemp(prefix=f"{safe_stem}_", dir=temp_root)
        members = _validated_zip_members(zf)
        _extract_pdf_members(zf, members, extract_dir)
        # Walk through all PDFs in the extracted directory
        for root, _, files in os.walk(extract_dir):
            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue
                file_path = os.path.join(root, fname)
                claim = parse_insurance_claim(file_path)
                if claim:
                    if archive_root:
                        archive_info = _archive_pdf_for_claim(archive_root, file_path, claim)
                        claim["archive_path"] = archive_info["path"]
                        claim["archive_copied"] = archive_info["copied"]
                    claims.append(claim)
                    continue
                receipt = parse_transfer_receipt(file_path)
                if receipt:
                    if archive_root:
                        archive_info = _archive_pdf_for_receipt(archive_root, file_path, receipt)
                        receipt["archive_path"] = archive_info["path"]
                        receipt["archive_copied"] = archive_info["copied"]
                    receipts.append(receipt)
                    continue
                doc_type = classify_document(fname)
                slips = parse_pdf(file_path, doc_type)
                if archive_root and slips:
                    if len(slips) == 1:
                        key = (file_path, slips[0].get("EmployeeCode") or slips[0].get("EmployeeName"), "single")
                        if key not in archived_keys:
                            _archive_pdf_for_entry(archive_root, file_path, slips[0], include_doc_type=False)
                            archived_keys.add(key)
                    else:
                        split_dir = tempfile.mkdtemp(prefix="pages_", dir=temp_root)
                        page_files = _split_pdf_pages(file_path, split_dir)
                        if page_files and len(page_files) >= len(slips):
                            for index, entry in enumerate(slips):
                                key = (file_path, entry.get("EmployeeCode") or entry.get("EmployeeName"), f"page{index + 1}")
                                if key in archived_keys:
                                    continue
                                _archive_pdf_for_entry(
                                    archive_root,
                                    page_files[index],
                                    entry,
                                    merge_if_exists=True,
                                    include_doc_type=False,
                                )
                                archived_keys.add(key)
                        else:
                            # If splitting isn't available, avoid duplicating the full PDF per entry.
                            entry = slips[0]
                            key = (file_path, entry.get("EmployeeCode") or entry.get("EmployeeName"), "unsplit")
                            if key not in archived_keys:
                                _archive_pdf_for_entry(
                                    archive_root,
                                    file_path,
                                    entry,
                                    merge_if_exists=True,
                                    include_doc_type=False,
                                )
                                archived_keys.add(key)
                records.extend(slips)
    # Merge receipts only after the walk, because a receipt is usually read
    # before the payment PDFs it belongs to have been archived.
    if archive_root:
        _merge_receipts_after_archiving(archive_root, receipts)
    return pd.DataFrame(records), receipts, claims


def _merge_receipts_after_archiving(archive_root: str, receipts: List[Dict[str, object]]) -> None:
    """Append each archived receipt to its employee's monthly payment PDFs."""
    for receipt in receipts:
        receipt_path = receipt.get("archive_path")
        if not receipt_path:
            continue
        outcome = merge_receipt_into_monthly_pdf(archive_root, receipt_path, receipt)
        receipt["merged_into"] = outcome["merged"]
        receipt["merge_skipped"] = outcome["skipped"]


def process_pdf_file(pdf_path: str, temp_root: str, archive_root: str = None):
    """Parse a single PDF and return extracted records plus insurance claims."""
    records: List[Dict[str, str]] = []
    archived_keys = set()
    claims: List[Dict[str, object]] = []
    receipts: List[Dict[str, object]] = []
    receipt = parse_transfer_receipt(pdf_path)
    if receipt:
        if archive_root:
            archive_info = _archive_pdf_for_receipt(archive_root, pdf_path, receipt)
            receipt["archive_path"] = archive_info["path"]
            receipt["archive_copied"] = archive_info["copied"]
        receipts.append(receipt)
        if archive_root:
            _merge_receipts_after_archiving(archive_root, receipts)
        return pd.DataFrame(records), claims, receipts
    claim = parse_insurance_claim(pdf_path)
    if claim:
        if archive_root:
            archive_info = _archive_pdf_for_claim(archive_root, pdf_path, claim)
            claim["archive_path"] = archive_info["path"]
            claim["archive_copied"] = archive_info["copied"]
        claims.append(claim)
        return pd.DataFrame(records), claims, receipts
    doc_type = classify_document(os.path.basename(pdf_path))
    slips = parse_pdf(pdf_path, doc_type)
    if archive_root and slips:
        if len(slips) == 1:
            key = (pdf_path, slips[0].get("EmployeeCode") or slips[0].get("EmployeeName"), "single")
            if key not in archived_keys:
                _archive_pdf_for_entry(archive_root, pdf_path, slips[0], include_doc_type=False)
                archived_keys.add(key)
        else:
            split_dir = tempfile.mkdtemp(prefix="pages_", dir=temp_root)
            page_files = _split_pdf_pages(pdf_path, split_dir)
            if page_files and len(page_files) >= len(slips):
                for index, entry in enumerate(slips):
                    key = (pdf_path, entry.get("EmployeeCode") or entry.get("EmployeeName"), f"page{index + 1}")
                    if key in archived_keys:
                        continue
                    _archive_pdf_for_entry(
                        archive_root,
                        page_files[index],
                        entry,
                        merge_if_exists=True,
                        include_doc_type=False,
                    )
                    archived_keys.add(key)
            else:
                # If splitting isn't available, avoid duplicating the full PDF per entry.
                entry = slips[0]
                key = (pdf_path, entry.get("EmployeeCode") or entry.get("EmployeeName"), "unsplit")
                if key not in archived_keys:
                    _archive_pdf_for_entry(
                        archive_root,
                        pdf_path,
                        entry,
                        merge_if_exists=True,
                        include_doc_type=False,
                    )
                    archived_keys.add(key)
    records.extend(slips)
    return pd.DataFrame(records), claims, receipts


def main() -> None:
    parser = argparse.ArgumentParser(description="Process payroll ZIP archives.")
    parser.add_argument("--input-dir", required=True, help="Directory containing ZIP files")
    parser.add_argument("--out-csv", default="payroll_results.csv", help="Path to write CSV output")
    args = parser.parse_args()

    input_dir = args.input_dir
    csv_path = args.out_csv

    # Create temporary directory for extraction
    with tempfile.TemporaryDirectory() as tmpdir:
        all_frames = []
        for fname in sorted(os.listdir(input_dir)):
            if not fname.lower().endswith(".zip"):
                continue
            zip_path = os.path.join(input_dir, fname)
            print(f"Processing {zip_path}…")
            zip_result = process_zip(zip_path, tmpdir)
            if isinstance(zip_result, tuple):
                df = zip_result[0]
            else:
                df = zip_result
            if not df.empty:
                df["SourceArchive"] = fname
                all_frames.append(df)

        if not all_frames:
            print("No payroll records found.")
            return
        combined = pd.concat(all_frames, ignore_index=True)
        # Normalise numeric fields: convert commas to dots, strip thousands separators and cast to float.
        numeric_cols = [
            "BasicSalary",
            "TotalEarnings",
            "NetPay",
            "EFKAEmployee",
            "EFKAEmployer",
            "TEKAEmployee",
            "TEKAEmployer",
        ]
        for col in numeric_cols:
            if col in combined.columns:
                combined[col] = combined[col].map(_parse_amount)
        combined.to_csv(csv_path, index=False)
        print(f"Wrote {len(combined)} records to {csv_path}")


if __name__ == "__main__":
    main()
