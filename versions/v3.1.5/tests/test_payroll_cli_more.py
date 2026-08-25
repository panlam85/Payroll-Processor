import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

import pandas as pd

import payroll_cli


def test_parse_inputs(tmp_path):
    pdf = tmp_path / "one.pdf"
    zipf = tmp_path / "two.zip"
    txt = tmp_path / "ignore.txt"
    pdf.write_text("pdf")
    zipf.write_text("zip")
    txt.write_text("txt")

    result = payroll_cli._parse_inputs([str(tmp_path)])
    assert str(pdf) in result["files"]
    assert str(zipf) in result["files"]
    assert not result["errors"]

    result = payroll_cli._parse_inputs([str(txt)])
    assert result["errors"]


def test_normalize_numeric_fields():
    df = pd.DataFrame(
        [
            {
                "BasicSalary": "1.000,50",
                "TotalEarnings": "2.000,00",
                "NetPay": "900,00",
            }
        ]
    )
    payroll_cli._normalize_numeric_fields(df)
    assert float(df.loc[0, "BasicSalary"]) == 1000.5


def test_run_id_and_ledger(tmp_path):
    run_id = payroll_cli._build_run_id("custom")
    assert run_id == "custom"
    run_id = payroll_cli._build_run_id(None)
    assert "_" in run_id

    entry = {"run_id": "abc", "started_at_epoch": 1}
    ledger_path = payroll_cli._write_ledger(entry, tmp_path)
    assert ledger_path.exists()

    entries = payroll_cli._load_ledgers(tmp_path)
    assert entries[0]["run_id"] == "abc"

    now = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    assert payroll_cli._isoformat(now).endswith("Z")


def test_run_processing_dry_run(tmp_path, capsys):
    pdf = tmp_path / "one.pdf"
    pdf.write_text("pdf")

    args = argparse.Namespace(
        zips=[str(pdf)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=True,
        no_open=True,
        run_id="run123",
        notes="",
    )
    code = payroll_cli.run_processing(args)
    assert code == 0
    captured = capsys.readouterr().out
    assert "Dry run validated inputs" in captured


def test_run_processing_missing_inputs(tmp_path, capsys):
    args = argparse.Namespace(
        zips=[str(tmp_path / "missing.pdf")],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=True,
        no_open=True,
        run_id="run123",
        notes="",
    )
    code = payroll_cli.run_processing(args)
    assert code == 1
    captured = capsys.readouterr().out
    assert "Errors:" in captured


def test_run_query_actions(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    entry = {
        "run_id": "run1",
        "started_at_epoch": 1.0,
        "started_at": "2024-01-01T00:00:00Z",
        "status": "success",
        "outputs": {"summary_xlsx": "a", "detail_xlsx": "b", "output_dir": "c"},
        "metrics": {"records": 1, "employees": 1, "receipts": 0, "claims": 0},
    }
    (ledger_dir / "run_run1.json").write_text(json.dumps(entry))

    args = argparse.Namespace(action="latest", format="text", ledger_dir=str(ledger_dir), id=None, limit=None)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="latest", format="json", ledger_dir=str(ledger_dir), id=None, limit=None)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="list", format="json", ledger_dir=str(ledger_dir), id=None, limit=1)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="list", format="text", ledger_dir=str(ledger_dir), id=None, limit=1)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="by-id", format="text", ledger_dir=str(ledger_dir), id="run1", limit=None)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="outputs", format="text", ledger_dir=str(ledger_dir), id="run1", limit=None)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="stats", format="text", ledger_dir=str(ledger_dir), id="run1", limit=None)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="outputs", format="json", ledger_dir=str(ledger_dir), id="run1", limit=None)
    assert payroll_cli.run_query(args) == 0

    args = argparse.Namespace(action="stats", format="json", ledger_dir=str(ledger_dir), id="run1", limit=None)
    assert payroll_cli.run_query(args) == 0


def test_run_processing_full_flow(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "one.pdf"
    pdf.write_text("pdf")

    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane",
                "Date": "01/01/2024",
                "DocumentType": "Salary",
                "BasicSalary": 1000,
                "TotalEarnings": 1200,
                "NetPay": 900,
            }
        ]
    )

    monkeypatch.setattr(
        payroll_cli.process_payroll,
        "process_pdf_file",
        lambda *args, **kwargs: (df, [{"claim_year": 2024}], [{"amount": 1}]),
    )
    monkeypatch.setattr(
        payroll_cli.process_payroll,
        "process_zip",
        lambda *args, **kwargs: (df, [], []),
    )
    monkeypatch.setattr(payroll_cli.create_employee_reports, "load_payroll_data", lambda paths: df)

    args = argparse.Namespace(
        zips=[str(pdf)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=False,
        no_open=False,
        run_id="runfull",
        notes="",
    )
    monkeypatch.setattr(payroll_cli.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")))
    code = payroll_cli.run_processing(args)
    assert code == 0
    output_dir = Path(args.out)
    assert list(output_dir.glob("*_summary.xlsx"))
    assert list(output_dir.glob("*_detail.xlsx"))
    assert list(Path(args.ledger_dir).glob("run_*.json"))


def test_run_processing_loads_temporary_csvs_before_cleanup(tmp_path, monkeypatch):
    pdf = tmp_path / "one.pdf"
    pdf.write_text("pdf")
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Synthetic Employee",
                "Date": "01/01/2026",
                "DocumentType": "Salary",
                "BasicSalary": 1000,
                "TotalEarnings": 1200,
                "NetPay": 900,
            }
        ]
    )
    monkeypatch.setattr(
        payroll_cli.process_payroll,
        "process_pdf_file",
        lambda *args, **kwargs: (df, [], []),
    )
    args = argparse.Namespace(
        zips=[str(pdf)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=False,
        no_open=True,
        run_id="temp-lifetime",
        notes="",
    )

    assert payroll_cli.run_processing(args) == 0
    assert len(list((tmp_path / "out").glob("*_summary.xlsx"))) == 1
    assert len(list((tmp_path / "out").glob("*_detail.xlsx"))) == 1
    ledger = json.loads((tmp_path / "ledger" / "run_temp-lifetime.json").read_text(encoding="utf-8"))
    assert ledger["status"] == "success"
    assert ledger["metrics"]["records"] == 1


def test_run_processing_zip_branch(tmp_path, monkeypatch):
    zip_path = tmp_path / "files.zip"
    zip_path.write_text("zip")

    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane",
                "Date": "01/01/2024",
                "DocumentType": "Salary",
                "BasicSalary": 1000,
                "TotalEarnings": 1200,
                "NetPay": 900,
            }
        ]
    )

    monkeypatch.setattr(payroll_cli.process_payroll, "process_zip", lambda *args, **kwargs: (df, [], []))
    monkeypatch.setattr(payroll_cli.create_employee_reports, "load_payroll_data", lambda paths: df)

    args = argparse.Namespace(
        zips=[str(zip_path)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=False,
        no_open=True,
        run_id="runzip",
        notes="",
    )
    assert payroll_cli.run_processing(args) == 0


def test_run_processing_no_data(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "one.pdf"
    pdf.write_text("pdf")

    monkeypatch.setattr(
        payroll_cli.process_payroll,
        "process_pdf_file",
        lambda *args, **kwargs: (pd.DataFrame(), [], []),
    )

    args = argparse.Namespace(
        zips=[str(pdf)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=False,
        no_open=True,
        run_id="runempty",
        notes="",
    )
    code = payroll_cli.run_processing(args)
    assert code == 0
    assert "No payroll data extracted" in capsys.readouterr().out


def test_run_processing_no_valid_csvs(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "one.pdf"
    pdf.write_text("pdf")

    monkeypatch.setattr(
        payroll_cli.process_payroll,
        "process_pdf_file",
        lambda *args, **kwargs: (pd.DataFrame([{"EmployeeCode": "E1"}]), [], []),
    )
    monkeypatch.setattr(payroll_cli.create_employee_reports, "load_payroll_data", lambda paths: pd.DataFrame())

    args = argparse.Namespace(
        zips=[str(pdf)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=False,
        no_open=True,
        run_id="runemptycsv",
        notes="",
    )
    code = payroll_cli.run_processing(args)
    assert code == 0
    assert "No valid payroll data found in CSVs." in capsys.readouterr().out


def test_run_processing_exception(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "one.pdf"
    pdf.write_text("pdf")

    def boom(*args, **kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr(payroll_cli.process_payroll, "process_pdf_file", boom)
    args = argparse.Namespace(
        zips=[str(pdf)],
        out=str(tmp_path / "out"),
        report_prefix="employee_reports",
        ledger_dir=str(tmp_path / "ledger"),
        archive_root=None,
        dry_run=False,
        no_open=False,
        run_id="runerr",
        notes="",
    )
    monkeypatch.setattr(payroll_cli.subprocess, "run", lambda *args, **kwargs: None)
    code = payroll_cli.run_processing(args)
    assert code == 0


def test_run_query_no_entries(tmp_path, capsys):
    args = argparse.Namespace(action="latest", format="text", ledger_dir=str(tmp_path), id=None, limit=None)
    assert payroll_cli.run_query(args) == 1
    assert "No run ledger entries found" in capsys.readouterr().out


def test_main_requires_id(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "query", "by-id"])
    with pytest.raises(SystemExit):
        payroll_cli.main()


def test_run_query_missing_id(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    entry = {"run_id": "run1", "started_at_epoch": 1.0}
    (ledger_dir / "run_run1.json").write_text(json.dumps(entry))
    args = argparse.Namespace(action="by-id", format="text", ledger_dir=str(ledger_dir), id="missing", limit=None)
    assert payroll_cli.run_query(args) == 1


def test_load_ledgers_missing_dir(tmp_path):
    missing = tmp_path / "missing"
    assert payroll_cli._load_ledgers(missing) == []


def test_load_ledgers_bad_json(tmp_path):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    (ledger_dir / "run_bad.json").write_text("{bad json")
    entries = payroll_cli._load_ledgers(ledger_dir)
    assert entries == []


def test_run_query_unknown_action(tmp_path, capsys):
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    entry = {"run_id": "run1", "started_at_epoch": 1.0}
    (ledger_dir / "run_run1.json").write_text(json.dumps(entry))
    args = argparse.Namespace(action="unknown", format="text", ledger_dir=str(ledger_dir), id=None, limit=None)
    assert payroll_cli.run_query(args) == 1
