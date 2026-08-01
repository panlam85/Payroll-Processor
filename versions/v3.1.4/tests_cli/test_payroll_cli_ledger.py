import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import payroll_cli  # noqa: E402


def test_payroll_cli_dry_run_writes_ledger(tmp_path: Path) -> None:
    test_zip = tmp_path / "sample.zip"
    test_zip.write_bytes(b"")

    args = payroll_cli.build_parser().parse_args(
        [
            "run",
            "--zips",
            str(test_zip),
            "--dry-run",
            "--ledger-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "out"),
        ]
    )

    exit_code = payroll_cli.run_processing(args)
    assert exit_code == 0

    ledger_files = list(tmp_path.glob("run_*.json"))
    assert ledger_files, "Expected a ledger entry to be written"

    payload = json.loads(ledger_files[0].read_text(encoding="utf-8"))
    assert payload["status"] == "dry-run"
    assert payload["inputs"]["files"] == [str(test_zip)]
