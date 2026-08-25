#!/usr/bin/env python3
"""CLI wrapper to run payroll processing and query past runs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

import create_employee_reports
import process_payroll
from app_paths import DEFAULT_REPORT_DIR


DEFAULT_LEDGER_DIR = DEFAULT_REPORT_DIR / ".run_ledger"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _isoformat(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_inputs(paths: List[str]) -> Dict[str, object]:
    files: List[str] = []
    errors: List[str] = []
    seen = set()
    for raw in paths:
        candidate = Path(raw).expanduser()
        if not candidate.exists():
            errors.append(f"Missing path: {candidate}")
            continue
        if candidate.is_dir():
            for child in sorted(candidate.iterdir()):
                if not child.is_file():
                    continue
                if child.suffix.lower() not in (".zip", ".pdf"):
                    continue
                if str(child) not in seen:
                    files.append(str(child))
                    seen.add(str(child))
        elif candidate.is_file():
            if candidate.suffix.lower() not in (".zip", ".pdf"):
                errors.append(f"Unsupported file: {candidate}")
                continue
            if str(candidate) not in seen:
                files.append(str(candidate))
                seen.add(str(candidate))
        else:
            errors.append(f"Unsupported path: {candidate}")
    return {"files": files, "errors": errors}


def _normalize_numeric_fields(df: pd.DataFrame) -> None:
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
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")


def _build_run_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    ts = _isoformat(_utc_now()).replace(":", "").replace("Z", "Z")
    suffix = uuid.uuid4().hex[:8]
    return f"{ts}_{suffix}"


def _write_ledger(entry: Dict[str, object], ledger_dir: Path) -> Path:
    _ensure_dir(ledger_dir)
    run_id = entry.get("run_id", "unknown")
    ledger_path = ledger_dir / f"run_{run_id}.json"
    with ledger_path.open("w", encoding="utf-8") as handle:
        json.dump(entry, handle, indent=2, sort_keys=True)
    return ledger_path


def _load_ledgers(ledger_dir: Path) -> List[Dict[str, object]]:
    if not ledger_dir.exists():
        return []
    entries: List[Dict[str, object]] = []
    for path in sorted(ledger_dir.glob("run_*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                entry = json.load(handle)
            entry["_ledger_path"] = str(path)
            entries.append(entry)
        except (OSError, json.JSONDecodeError):
            continue
    entries.sort(key=lambda item: float(item.get("started_at_epoch", 0.0)), reverse=True)
    return entries


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _print_run_summary(entry: Dict[str, object]) -> None:
    outputs = entry.get("outputs", {})
    metrics = entry.get("metrics", {})
    print(f"Run ID: {entry.get('run_id')}")
    print(f"Started: {entry.get('started_at')}")
    print(f"Status: {entry.get('status')}")
    print(f"Records: {metrics.get('records', 0)}")
    print(f"Employees: {metrics.get('employees', 0)}")
    print(f"Summary: {outputs.get('summary_xlsx')}")
    print(f"Detail: {outputs.get('detail_xlsx')}")


def run_processing(args: argparse.Namespace) -> int:
    started = _utc_now()
    run_id = _build_run_id(args.run_id)
    input_result = _parse_inputs(args.zips)
    file_paths = input_result["files"]
    errors = input_result["errors"]
    if not file_paths:
        errors.append("No ZIP or PDF files found to process.")

    ledger_entry: Dict[str, object] = {
        "run_id": run_id,
        "started_at": _isoformat(started),
        "started_at_epoch": started.timestamp(),
        "status": "error" if errors else "running",
        "dry_run": bool(args.dry_run),
        "inputs": {
            "paths": args.zips,
            "files": file_paths,
        },
        "outputs": {},
        "metrics": {
            "records": 0,
            "employees": 0,
            "receipts": 0,
            "claims": 0,
        },
        "errors": errors,
        "notes": args.notes or "",
    }

    output_dir = Path(args.out) if args.out else DEFAULT_REPORT_DIR / "Employees Reports"
    output_dir = output_dir.expanduser()
    ledger_entry["outputs"]["output_dir"] = str(output_dir)
    _ensure_dir(output_dir)

    if args.dry_run or errors:
        ledger_entry["status"] = "dry-run" if args.dry_run else "error"
        finished = _utc_now()
        ledger_entry["finished_at"] = _isoformat(finished)
        ledger_entry["finished_at_epoch"] = finished.timestamp()
        _write_ledger(ledger_entry, Path(args.ledger_dir) if args.ledger_dir else DEFAULT_LEDGER_DIR)
        if errors:
            print("Errors:")
            for err in errors:
                print(f"- {err}")
            return 1
        print("Dry run validated inputs:")
        for path in file_paths:
            print(f"- {path}")
        return 0

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_output = output_dir / f"{args.report_prefix}_{timestamp}_summary.xlsx"
    detail_output = output_dir / f"{args.report_prefix}_{timestamp}_detail.xlsx"

    ledger_entry["outputs"].update(
        {
            "summary_xlsx": str(summary_output),
            "detail_xlsx": str(detail_output),
        }
    )

    csv_files: List[str] = []
    receipt_count = 0
    claim_count = 0
    file_results: List[Dict[str, object]] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        for index, file_path in enumerate(file_paths):
            result: Dict[str, object] = {"file": file_path, "records": 0, "receipts": 0, "claims": 0}
            try:
                if file_path.lower().endswith(".zip"):
                    df, receipts, claims = process_payroll.process_zip(
                        file_path,
                        temp_dir,
                        archive_root=args.archive_root,
                    )
                else:
                    df, claims, receipts = process_payroll.process_pdf_file(
                        file_path,
                        temp_dir,
                        archive_root=args.archive_root,
                    )
                receipt_count += len(receipts)
                claim_count += len(claims)
                result["receipts"] = len(receipts)
                result["claims"] = len(claims)

                if not df.empty:
                    df["SourceArchive"] = os.path.basename(file_path)
                    _normalize_numeric_fields(df)
                    csv_path = os.path.join(temp_dir, f"temp_payroll_{index}.csv")
                    df.to_csv(csv_path, index=False)
                    csv_files.append(csv_path)
                    result["records"] = len(df)
            except Exception as exc:
                error_msg = f"{file_path}: {exc}"
                ledger_entry["errors"].append(error_msg)
                result["error"] = str(exc)
            file_results.append(result)

    ledger_entry["metrics"]["receipts"] = receipt_count
    ledger_entry["metrics"]["claims"] = claim_count
    ledger_entry["inputs"]["file_results"] = file_results

    if not csv_files:
        finished = _utc_now()
        ledger_entry["status"] = "no-data"
        ledger_entry["finished_at"] = _isoformat(finished)
        ledger_entry["finished_at_epoch"] = finished.timestamp()
        _write_ledger(ledger_entry, Path(args.ledger_dir) if args.ledger_dir else DEFAULT_LEDGER_DIR)
        print("No payroll data extracted. Outputs were not generated.")
        return 0

    combined_df = create_employee_reports.load_payroll_data(csv_files)
    if combined_df.empty:
        finished = _utc_now()
        ledger_entry["status"] = "no-data"
        ledger_entry["finished_at"] = _isoformat(finished)
        ledger_entry["finished_at_epoch"] = finished.timestamp()
        _write_ledger(ledger_entry, Path(args.ledger_dir) if args.ledger_dir else DEFAULT_LEDGER_DIR)
        print("No valid payroll data found in CSVs.")
        return 0

    summary_df = create_employee_reports.prepare_summary(combined_df)
    create_employee_reports.write_employee_reports(summary_df, str(summary_output))
    create_employee_reports.write_detail_report(combined_df, str(detail_output))

    ledger_entry["metrics"]["records"] = len(combined_df)
    if "EmployeeCode" in combined_df.columns:
        ledger_entry["metrics"]["employees"] = combined_df["EmployeeCode"].nunique()
    else:
        ledger_entry["metrics"]["employees"] = 0

    finished = _utc_now()
    ledger_entry["status"] = "success" if not ledger_entry["errors"] else "partial"
    ledger_entry["finished_at"] = _isoformat(finished)
    ledger_entry["finished_at_epoch"] = finished.timestamp()

    ledger_path = _write_ledger(ledger_entry, Path(args.ledger_dir) if args.ledger_dir else DEFAULT_LEDGER_DIR)

    print(f"Summary report: {summary_output}")
    print(f"Detail report: {detail_output}")
    print(f"Ledger entry: {ledger_path}")

    if not args.no_open:
        try:
            subprocess.run(["open", str(output_dir)], check=False)
        except OSError:
            pass

    return 0


def run_query(args: argparse.Namespace) -> int:
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else DEFAULT_LEDGER_DIR
    entries = _load_ledgers(ledger_dir)
    if not entries:
        print(f"No run ledger entries found in {ledger_dir}")
        return 1

    if args.action == "latest":
        entry = entries[0]
        if args.format == "json":
            _print_json(entry)
        else:
            _print_run_summary(entry)
        return 0

    if args.action == "list":
        limit = args.limit or 10
        payload = entries[:limit]
        if args.format == "json":
            _print_json(payload)
        else:
            for entry in payload:
                _print_run_summary(entry)
                print("")
        return 0

    if args.action == "by-id":
        match = next((entry for entry in entries if entry.get("run_id") == args.id), None)
        if not match:
            print(f"No run found with ID {args.id}")
            return 1
        if args.format == "json":
            _print_json(match)
        else:
            _print_run_summary(match)
        return 0

    if args.action == "outputs":
        match = next((entry for entry in entries if entry.get("run_id") == args.id), None)
        if not match:
            print(f"No run found with ID {args.id}")
            return 1
        outputs = match.get("outputs", {})
        if args.format == "json":
            _print_json(outputs)
        else:
            print(f"Summary: {outputs.get('summary_xlsx')}")
            print(f"Detail: {outputs.get('detail_xlsx')}")
            print(f"Output dir: {outputs.get('output_dir')}")
        return 0

    if args.action == "stats":
        match = next((entry for entry in entries if entry.get("run_id") == args.id), None)
        if not match:
            print(f"No run found with ID {args.id}")
            return 1
        metrics = match.get("metrics", {})
        if args.format == "json":
            _print_json(metrics)
        else:
            print(f"Records: {metrics.get('records', 0)}")
            print(f"Employees: {metrics.get('employees', 0)}")
            print(f"Receipts: {metrics.get('receipts', 0)}")
            print(f"Claims: {metrics.get('claims', 0)}")
        return 0

    print(f"Unknown query action: {args.action}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Payroll Processor CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Process ZIP/PDF files and generate reports")
    run_parser.add_argument("--zips", nargs="+", required=True, help="ZIP/PDF paths or directories to scan")
    run_parser.add_argument("--out", help="Output folder for reports")
    run_parser.add_argument("--report-prefix", default="employee_reports", help="Base filename prefix for reports")
    run_parser.add_argument("--ledger-dir", help="Override run ledger directory")
    run_parser.add_argument("--archive-root", help="Optional archive root for storing PDFs")
    run_parser.add_argument("--dry-run", action="store_true", help="Validate inputs without processing")
    run_parser.add_argument("--no-open", action="store_true", help="Do not open the output folder on completion")
    run_parser.add_argument("--run-id", help="Override run ID")
    run_parser.add_argument("--notes", help="Optional notes stored with the run")
    run_parser.set_defaults(func=run_processing)

    query_parser = subparsers.add_parser("query", help="Query past run ledger entries")
    query_parser.add_argument("action", choices=["latest", "list", "by-id", "outputs", "stats"])
    query_parser.add_argument("--id", help="Run ID for by-id/outputs/stats")
    query_parser.add_argument("--limit", type=int, help="Limit list output")
    query_parser.add_argument("--format", choices=["text", "json"], default="text")
    query_parser.add_argument("--ledger-dir", help="Override run ledger directory")
    query_parser.set_defaults(func=run_query)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "query" and args.action in ("by-id", "outputs", "stats") and not args.id:
        parser.error("--id is required for by-id, outputs, and stats actions")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
