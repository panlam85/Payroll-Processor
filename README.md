# Payroll Processor

A macOS desktop application for processing Greek payroll documents. Drop in the
ZIP archives your accountant sends, and it extracts the PDFs, parses the payroll
and insurance data, stores it in PostgreSQL, and produces Excel and PDF reports.

Built for Greek payroll specifically: it reads `ΑΠΟΔΕΙΞΕΙΣ ΠΛΗΡΩΜΩΝ` payslips,
`ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ` vacation allowances, `ΔΩΡΟ` bonuses, `ΑΠΟΖΗΜΙΩΣΗ` leave
compensation, and EFKA/TEKA insurance claims.

**Engineer:** PanLam
**License:** [MIT](LICENSE)

---

## Features

**Processing**
- Drag-and-drop ZIP or PDF ingestion, plus a file browser
- Greek-language PDF parsing (employee codes, names, salary, net pay, EFKA/TEKA contributions, payment dates)
- Transfer-receipt parsing that marks entries paid by name, IBAN, or amount
- IBAN and beneficiary extraction, auto-linked to employee profiles
- Watch-folder auto-processing on a configurable interval
- Signed-document import and archiving

**Analysis**
- Dashboard with KPIs and alerts
- Analytics data grid with multi-term search (AND/OR/NOT), sorting, and inline editing with undo/redo
- Analytics charts: monthly burn, insurance breakdown, cost per employee, document mix, payment heat-map, year-over-year
- Insurance tab comparing calculated against official EFKA/TEKA figures
- Employee profiles with monthly totals, pay rates, and payment history

**Output**
- Per-employee Excel summary workbook plus an analytical detail workbook
- Per-employee monthly PDF reports
- CSV / XLSX / PDF export from any grid
- Source PDFs archived by year, month, and employee

**Operations**
- Database backup and restore, full backup ZIP with scheduling and verification
- Headless CLI for processing and run-history queries
- Light / dark / auto appearance

---

## Requirements

- macOS 10.12 (Sierra) or later — Intel or Apple Silicon
- Python 3.9+
- `pdftotext` — `brew install poppler`
- PostgreSQL, if you want database-backed features (the reports work without it)

Python dependencies are installed automatically into a local `.venv` by the
launch scripts. The packaged `.app` bundles everything.

---

## Quick start

```bash
git clone https://github.com/panlam85/PayrollProcessor.git
cd PayrollProcessor
./run_dev.sh          # sets up .venv on first run, then launches the GUI
```

Reports are written to `~/Documents/Payroll Processor Reports` by default; you
can change the location in Settings. Per-employee reports land in an
`Employees Reports/` subfolder.

---

## Command line

```bash
# Process archives
./payroll_cli.sh run --zips /path/to/zips --out ~/Documents/Payroll\ Processor\ Reports

# Validate inputs without writing anything
./payroll_cli.sh run --zips /path/to/zips --dry-run

# Inspect past runs
./payroll_cli.sh query latest
./payroll_cli.sh query list --limit 10
./payroll_cli.sh query by-id --id <run_id>
```

Every run is recorded as JSON under
`~/Documents/Payroll Processor Reports/.run_ledger/`, capturing inputs, outputs,
metrics, status, and timestamps.

---

## Building a distributable

```bash
./create_simple_app.py          # builds dist/Payroll Processor.app
./create_simple_installer.sh    # builds releases/<version>/ ZIP + DMG + installer
```

`dist/` and `releases/` are gitignored and absent from a fresh clone.

---

## Development

### Repository layout

This project keeps every release as a frozen directory under `versions/` rather
than relying on git history alone. Root scripts always delegate to the active
version.

```
PayrollProcessor/
├── versions/
│   ├── v1.0/ … v3.1.3/     # frozen historical releases
│   └── v3.1.4/             # active codebase
├── launch_gui.sh           # → versions/<active>/scripts/launch_gui.sh
├── run_dev.sh              # → versions/<active>/scripts/run_dev.sh
├── payroll_cli.sh          # → versions/<active>/scripts/payroll_cli.sh
├── create_simple_app.py    # → app bundle builder
├── create_simple_installer.sh
└── bump_version.sh         # cuts a new version from the active one
```

Core modules live in `versions/<active>/src/`:

| Module | Responsibility |
|---|---|
| `payroll_gui.py` | GUI shell, sidebar views, menus, report orchestration |
| `process_payroll.py` | PDF extraction and payroll/insurance/receipt parsing |
| `db_storage.py` | PostgreSQL schema, migrations, imports, exports, backup/restore |
| `create_employee_reports.py` | Excel summary and detail workbooks |
| `payroll_cli.py` | Headless entry point and run-ledger queries |

### Cutting a new version

```bash
./bump_version.sh v3.1.5
```

This copies the active tree and repoints the root wrappers, `AGENTS.md`,
`pytest.ini`, and `.coveragerc`. Keep changes inside the active version
directory; older versions are history and should not be edited.

### Tests

```bash
versions/v3.1.4/.venv/bin/python -m pytest -q                                    # 236 tests
versions/v3.1.4/.venv/bin/python -m pytest -q --cov --cov-config=.coveragerc     # with the gate
```

The coverage gate is 65%. The parsing, storage, and CLI core currently sits at
**94.7%**:

| Module | Coverage |
|---|---|
| `create_employee_reports.py` | 100% |
| `process_payroll.py` | 99% |
| `payroll_cli.py` | 97% |
| `db_storage.py` | 92% |

`payroll_gui.py` is excluded from the gate — most of it is widget construction
and event wiring that needs a display. Its display-independent logic
(formatters, parsers, validators, the signed-document classifier, export
builders) is covered by `tests/test_payroll_gui_helpers.py`, which drives an
uninitialized instance and needs no window server.

---

## Documentation

- [`CHANGELOG.md`](CHANGELOG.md) — release history
- [`AGENTS.md`](AGENTS.md) — architecture and data-flow notes for contributors
- [`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md) — feature overview and usage detail
- [`TODO.md`](TODO.md) — roadmap

---

## License

Released under the [MIT License](LICENSE). Copyright © 2026 PanLam.
