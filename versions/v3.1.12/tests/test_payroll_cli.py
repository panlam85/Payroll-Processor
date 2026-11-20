import argparse
import json
from pathlib import Path

import pandas as pd

import payroll_cli


def test_parse_inputs_collects_files(tmp_path: Path):
    (tmp_path / "a.zip").write_bytes(b"")
    (tmp_path / "b.pdf").write_bytes(b"")
    (tmp_path / "c.txt").write_text("skip")

    result = payroll_cli._parse_inputs([str(tmp_path)])
    assert str(tmp_path / "a.zip") in result["files"]
    assert str(tmp_path / "b.pdf") in result["files"]
    assert any("Unsupported" in err for err in result["errors"]) is False


def test_normalize_numeric_fields():
    df = pd.DataFrame({"BasicSalary": ["1.234,50"], "TotalEarnings": ["200"]})
    payroll_cli._normalize_numeric_fields(df)
    assert df.loc[0, "BasicSalary"] == 1234.50
    assert df.loc[0, "TotalEarnings"] == 200


def test_run_processing_dry_run_writes_ledger(tmp_path: Path):
    test_zip = tmp_path / "sample.zip"
    test_zip.write_bytes(b"")
    args = argparse.Namespace(
        zips=[str(test_zip)],
        out=str(tmp_path / "out"),
        ledger_dir=str(tmp_path / "ledger"),
        dry_run=True,
        run_id=None,
        notes="",
        report_prefix="employee_reports",
        archive_root=None,
    )
    exit_code = payroll_cli.run_processing(args)
    assert exit_code == 0
    ledger_files = list((tmp_path / "ledger").glob("run_*.json"))
    assert ledger_files
    payload = json.loads(ledger_files[0].read_text(encoding="utf-8"))
    assert payload["status"] == "dry-run"


def test_run_processing_errors_on_missing_files(tmp_path: Path):
    args = argparse.Namespace(
        zips=[str(tmp_path / "missing.zip")],
        out=str(tmp_path / "out"),
        ledger_dir=str(tmp_path / "ledger"),
        dry_run=False,
        run_id=None,
        notes="",
        report_prefix="employee_reports",
        archive_root=None,
    )
    exit_code = payroll_cli.run_processing(args)
    assert exit_code == 1
