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
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import Dict, List

import pandas as pd


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
    slip_indices = [idx for idx, line in enumerate(lines) if line.strip().startswith("Κωδικός")]
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
    cleaned = value.strip()
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
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
        "ΙΑΝΟΥΑΡΙ": 1,
        "ΦΕΒΡΟΥΑΡ": 2,
        "ΜΑΡΤΙ": 3,
        "ΑΠΡΙΛ": 4,
        "ΜΑΪ": 5,
        "ΜΑΙ": 5,
        "ΙΟΥΝ": 6,
        "ΙΟΥΛ": 7,
        "ΑΥΓ": 8,
        "ΣΕΠΤ": 9,
        "ΟΚΤ": 10,
        "ΝΟΕ": 11,
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
    upper = text.upper()
    year_match = re.search(r"\b(20\d{2})\b", upper)
    year = int(year_match.group(1)) if year_match else None
    month = None
    for key, month_num in month_map.items():
        if key in upper:
            month = month_num
            break
    if month is None:
        return None, None
    if year is None and paid_date:
        year = paid_date.year
        if paid_date.month < month:
            year -= 1
    return year, month


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
    amount_text = amount_match.group(1).strip().replace(".", "").replace(",", ".")
    try:
        amount = float(amount_text)
    except ValueError:
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
    if 'ΑΠΟΔΕΙΞΕΙΣ' in name or 'ΙΑΝΟΥΑΡΙΟΣ' in name or 'ΦΕΒΡΟΥΑΡΙΟΣ' in name or 'ΜΑΡΤΙΟΣ' in name:
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
    employee_name = entry.get("EmployeeName") or entry.get("EmployeeCode") or "unknown"
    employee_dir = _sanitize_segment(employee_name)
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


def _archive_pdf_for_receipt(archive_root: str, file_path: str, receipt: Dict[str, object]) -> Dict[str, object]:
    entry = {
        "EmployeeName": receipt.get("employee_name"),
        "EmployeeCode": None,
        "Date": receipt.get("paid_date").strftime("%d/%m/%Y") if receipt.get("paid_date") else None,
        "DocumentType": "Receipt",
    }
    archive_dir = _derive_archive_dir(archive_root, entry)
    os.makedirs(archive_dir, exist_ok=True)
    dest_name = _build_archive_filename(entry, suffix="receipt", merge_if_exists=False, include_doc_type=True)
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
    paid_date = receipt.get("paid_date")
    if not paid_date:
        return []
    entry = {
        "EmployeeName": receipt.get("employee_name"),
        "EmployeeCode": None,
        "Date": paid_date.strftime("%d/%m/%Y"),
        "DocumentType": "Receipt",
    }
    archive_dir = _derive_archive_dir(archive_root, entry)
    if not os.path.isdir(archive_dir):
        return []
    matches = []
    for fname in sorted(os.listdir(archive_dir)):
        if not fname.lower().endswith(".pdf"):
            continue
        lowered = fname.lower()
        if "_receipt" in lowered or "receipt" in lowered:
            continue
        matches.append(os.path.join(archive_dir, fname))
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
        if _merge_pdf_files(target, receipt_path):
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
        if _merge_pdf_files(dest_path, file_path):
            return
    if not os.path.exists(dest_path):
        shutil.copy2(file_path, dest_path)


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
    employee_name = entry.get("EmployeeName") or entry.get("EmployeeCode") or "unknown"
    name_part = _sanitize_segment(employee_name).replace(" ", "_")
    base = f"{date_part}_{name_part}"
    if include_doc_type:
        doc_type = entry.get("DocumentType") or entry.get("document_type") or "Salary"
        doc_part = _sanitize_segment(str(doc_type)).replace(" ", "_")
        base = f"{base}_{doc_part}"
    file_suffix = f"_{suffix}" if suffix else ""
    if merge_if_exists:
        return f"{base}{file_suffix}.pdf"
    return f"{base}{file_suffix}.pdf"


def process_zip(zip_path: str, temp_root: str, archive_root: str = None):
    """Extract PDFs from a zip and return parsed records and receipts."""
    records: List[Dict[str, str]] = []
    receipts: List[Dict[str, object]] = []
    claims: List[Dict[str, object]] = []
    archived_keys = set()
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Extract into a temporary directory
        extract_dir = os.path.join(temp_root, os.path.basename(zip_path).rstrip('.zip'))
        zf.extractall(extract_dir)
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
                # Remove thousands separator dots and replace decimal commas with dots
                combined[col] = combined[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                combined[col] = pd.to_numeric(combined[col], errors='coerce')
        combined.to_csv(csv_path, index=False)
        print(f"Wrote {len(combined)} records to {csv_path}")


if __name__ == "__main__":
    main()
