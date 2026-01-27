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
import os
import re
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
        name_match = re.search(r"Ονοματεπώνυμο\s*:?\s*(.+?)\s*(?= Α\.Φ\.Μ\.|\s*$)", flat)
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
    return 'Unknown'


def process_zip(zip_path: str, temp_root: str) -> pd.DataFrame:
    """Extract PDFs from a zip and return parsed records as a DataFrame."""
    records: List[Dict[str, str]] = []
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
                doc_type = classify_document(fname)
                slips = parse_pdf(file_path, doc_type)
                records.extend(slips)
    return pd.DataFrame(records)


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
            df = process_zip(zip_path, tmpdir)
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