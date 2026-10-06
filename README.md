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
- Signed-document import and archiving, with automatic employer/employee signature flags
- Payment receipts merged into the employee's monthly payment PDF

**Analysis**
- Dashboard with KPIs, alerts, and current-vs-last-month comparisons
- Analytics data grid with multi-term search (AND/OR/NOT), sorting, and inline editing with undo/redo
- Analytics charts: monthly burn, insurance breakdown, cost per employee, document mix, payment heat-map, year-over-year
- Workforce charts: headcount trend with joiners and leavers, median vs average pay with an interquartile band
- Employer cost per euro of take-home pay, tracked over time
- Sudden-jump detection comparing each employee against their own prior month
- Insurance tab comparing calculated against official EFKA/TEKA figures
- Employee workspace with Monthly payroll, Profile and Payment history tabs;
  select a year and month to see totals, payment status, insurance and payslips

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

In **Overview → Alerts**, select reviewed alerts and click **Acknowledge selected**.
They stay hidden after refresh and restart. Enable **Show acknowledged** to review
them again and use **Restore selected** to return them to the active list.
Double-click an alert to open its payroll details.

## Requirements

For the packaged **v3.1.11 app**, PostgreSQL, Python and PDF tools are included.
On a new installation, open the app and it prepares its local database automatically.
No separate database or Homebrew installation is required. The current local build
targets **Apple Silicon and macOS 26+**; other targets require a matching native build.

For development from source:

- macOS compatible with your installed Python, PostgreSQL and PDF tools
- Python 3.9+
- `pdftotext` — `brew install poppler`
- PostgreSQL, if you want database-backed features (the reports work without it)

Python dependencies are installed automatically into a local `.venv` by the
launch scripts. The packaged `.app` bundles everything.

### Included database

The private database lives in `~/.payroll_processor/local-postgres/data`, outside
the app bundle. Its local socket is restricted to the current macOS user, with no
TCP listener. Payroll Processor starts it when needed and stops it after its last
app/CLI client exits. Replacing the app preserves the database; keep normal backups.

Existing saved connections remain in use. This update does not move existing data
into a new database or overwrite disabled/custom settings. **Database Settings**
shows simple local-database information for managed installations and retains
advanced connection settings for external databases. Failed first-run setup offers
Retry. A different PostgreSQL major version requires an explicit upgrade.

Builders need PostgreSQL 18 installed and can set `PAYROLL_PG_CONFIG` to its
`pg_config`. The build copies its runtime and non-system libraries, rewrites library
paths, verifies PostgreSQL's relocated paths, copies available license notices and
signs the result. The build's minimum macOS version follows its bundled runtime.

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
│   ├── v1.0/ … v3.1.6/     # frozen historical releases
│   └── v3.1.11/             # active codebase
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
./bump_version.sh v3.1.11
```

This copies the active tree and repoints the root wrappers, `AGENTS.md`,
`pytest.ini`, and `.coveragerc`. Keep changes inside the active version
directory; older versions are history and should not be edited.

### Tests

```bash
versions/v3.1.11/.venv/bin/python -m pytest -q                                    # 426 unit tests; 16 optional database tests
versions/v3.1.11/.venv/bin/python -m pytest -q --cov --cov-config=.coveragerc     # with the gate
```

The coverage gate is 65%. The full local v3.1.11 suite, including database integration tests, passes with **74.53%**
coverage, including the employee workspace logic:

| Module | Coverage |
|---|---|
| `create_employee_reports.py` | 99% |
| `process_payroll.py` | 95% |
| `payroll_cli.py` | 92% |
| `db_storage.py` | 91% |

`payroll_gui.py` is excluded from the gate — most of it is widget construction
and event wiring that needs a display. Its display-independent logic
(formatters, parsers, validators, the signed-document classifier, export
builders) is covered by `tests/test_payroll_gui_helpers.py`, which drives an
uninitialized instance and needs no window server.

---

## Documentation

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — **start here to branch, extend, or fork this project**
- [`CHANGELOG.md`](CHANGELOG.md) — release history
- [`AGENTS.md`](AGENTS.md) — architecture and data-flow notes for contributors
- [`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md) — feature overview and usage detail
- [`TODO.md`](TODO.md) — roadmap

---

## License

Released under the [MIT License](LICENSE). Copyright © 2026 PanLam.


### Employee management (v3.1.11)

Click the **Code** or **Name** column header to sort; click again to reverse.
Codes sort numerically while preserving leading zeros in employee identities.

The Employees directory fills the view so full names are readable. Click a name
to slide open Monthly payroll, Profile and Payment history. **← Employees**
returns to the directory with your selection intact. ⌘-click selects for merging
without opening the details panel.

The Employees list defaults to **Active**: employment overlaps the selected
filter period, or today when no period is selected. Choose **Inactive**, **All**,
or **Dates not set** to review other employees. Existing employees without
confirmed dates remain visible as **Dates not set**. Payroll dates are not
silently treated as employment dates.

Select an employee and choose **Employment…** to add or edit start/end dates,
including separate periods for rehires. Click either date field to open its calendar,
with month/year navigation and a Today shortcut. End dates are inclusive; choose
**Ongoing** for employment without an end date. Add or update a period in the list, then choose
**Save periods**. Historical payroll remains available under **All**.

⌘-click two employees and choose **Merge…** (enabled only for two selections).
Choose which employee code to keep; the payroll summary loads automatically.
Click the button showing the merge direction to complete the merge. All
payroll rows, payment states, insurance and document references are retained;
matching payslips are flagged and are not automatically deleted. The retained
profile wins conflicting fields, missing fields are filled, and employment
periods are combined. Old codes resolve to the retained employee on later
imports. A database audit retains the prior profiles and moved payroll IDs.
There is no automatic unmerge; take a database backup before merging.

Employee writes require the editor role and an unlocked editing checkbox.
Use **Delete…** for an incorrect OCR-created employee. Review the employee and
linked record counts; if payroll entries exist, explicitly confirm their deletion.
Deleting removes the profile, employment periods and linked payroll/insurance/document
records from the database. Original PDFs remain on disk, and an audit snapshot is
retained in `employee_deletion_history`. There is no automatic undo. Profiles with
merge history or import aliases cannot be deleted. Reimporting the original incorrect
source can create the employee again.

The standard pg_dump backup includes employment periods, aliases, merge audit and deletion snapshots.

Optional database regression tests use a separate disposable local database:

```bash
createdb payroll_employee_qa_3110
PAYROLL_EMPLOYEE_QA=1 PAYROLL_BUNDLED_PG_QA="/absolute/path/to/bundled/postgres" PYTHONPATH=versions/v3.1.11/src versions/v3.1.11/.venv/bin/python -m pytest -q --cov --cov-config=.coveragerc
```

This exercises 442 tests, including real transactions, rollback, alias reimports,
profile conflicts, rehire gaps and stale-preview rejection. The database tests
clear only the explicitly named test database. Set `PAYROLL_BUNDLED_PG_QA` to a runtime produced by the app builder to include the two isolated bundled-database lifecycle tests; they use temporary data directories.
