# Next Agent Guide

## What the app does
- A macOS GUI that processes payroll ZIP files (PDFs inside), extracts data, and writes Excel reports.
- Output includes two workbooks per run:
  - Summary workbook: one sheet per employee with monthly totals.
  - Detail workbook: every payroll entry in a single table.

## Current active version
- Active code lives in `versions/v3.1.11/`.
- Root scripts (`launch_gui.sh`, `run_dev.sh`, `create_simple_app.py`, `create_simple_installer.sh`) delegate to `versions/v3.1.11`.
- Older versions are kept for history; do not edit them unless asked.

## Key files and responsibilities
- `versions/v3.1.11/src/local_database.py`
  - First-run private PostgreSQL cluster, local socket, process leases and shutdown.
  - Existing connection settings are preserved; data lives outside the app bundle.
- `versions/v3.1.11/scripts/bundle_postgres.py`
  - Copy/relink/sign a PostgreSQL 18 runtime; verify relocated share/lib paths.
- `versions/v3.1.11/src/employee_management.py`
  - Employment intervals, activity filtering, natural sorting, transactional merges and audited deletions.
  - Merged source profiles remain import aliases; payroll IDs/documents are preserved.
- `versions/v3.1.11/src/employee_actions.py`
  - Employment-period editing and reviewed merge dialogs; writes require editor/unlocked state.
- `versions/v3.1.11/src/filter_workspace.py`
  - Sliding filter overlay, readable date/document controls and quick periods.
  - Filter summaries stay visible; persisted month/document values remain compatible.
- `versions/v3.1.11/src/dashboard_alerts.py`
  - Stable alert identities, selection, acknowledgement and restoration controls.
  - Reviewed alerts are saved in the database's `alert_acknowledgements` table.
- `versions/v3.1.11/src/employee_workspace.py`
  - Full-width directory with sliding Monthly payroll, Profile and Payment history details.
  - Queries run asynchronously; monthly totals and detail share the same rows.
- `versions/v3.1.11/src/employee_months.py`
  - Decimal monthly aggregation by payslip date, without row limits.
- `versions/v3.1.11/src/payroll_gui.py`
  - GUI, menus, and report orchestration.
  - Controls save locations and spawns the processing thread.
- `versions/v3.1.11/src/process_payroll.py`
  - Extracts PDFs from ZIPs and parses payroll fields.
  - Document type classifier defaults to "Salary".
- `versions/v3.1.11/src/create_employee_reports.py`
  - Builds summary workbook.
  - Builds detail workbook (every row).
- `versions/v3.1.11/scripts/launch_gui.sh`
  - Production-style launcher; caches pip installs via a requirements hash.
- `versions/v3.1.11/scripts/run_dev.sh`
  - Dev launcher with the same environment setup.

## How the data flows
1. GUI collects ZIP paths.
2. `process_payroll.process_zip()` extracts PDFs and parses entries.
3. Entries are saved to temp CSVs.
4. `create_employee_reports.load_payroll_data()` combines CSVs.
5. Summary workbook is created from grouped data.
6. Detail workbook is created from the flat combined data.

## Reports and output
- Default folder: `~/Documents/Payroll Processor Reports` (user can pick a different one)
- Employee reports are saved under `Employees Reports/` inside the selected output folder.
- Filenames:
  - `employee_reports_<timestamp>_summary.xlsx`
  - `employee_reports_<timestamp>_detail.xlsx`
- Monthly employee reports (from the Monthly Employee Summary tab) are generated as PDFs per employee/month.

## How to run
- Development: `./run_dev.sh`
- Normal launch: `./launch_gui.sh`
- Build app bundle: `./create_simple_app.py`
- Build installer: `./create_simple_installer.sh`

## Coding tips
- Keep changes inside `versions/v3.1.11` unless the user asks for a new version.
- Use `./bump_version.sh vX.Y.Z` to create a new version with real copied tests (no symlinks) and update root wrappers.
- Update the root wrappers if a new version becomes active.
- For GUI tweaks, check macOS menu behavior (`tk::mac::setmenuname` and `tkAboutDialog`).
- Preserve the two-report output behavior unless explicitly asked to change it.
- Monthly Employee Summary supports multi-select and a "Create Monthly Report" button; reports are written using the shared PDF export layout.
