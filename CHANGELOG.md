# Changelog

All notable changes to this project are documented here. Newer entries go to the top.

## v3.1.7 — 2026-08-26

**Fast startup and responsive navigation**
- Deferred pandas, payroll parsing and Matplotlib until their features are
  opened. A clean import now takes about 0.09 seconds instead of 3–8 seconds.
- Built only the Processing screen at startup and lazy-loaded the seven
  secondary views. Repeat native first-paint measurements fell from roughly
  10–12 seconds to 0.45–0.51 seconds.
- Removed synchronous database migrations from startup, added a short database
  connection timeout, and moved schema maintenance and available-year lookups
  to background workers.
- Filter and search changes now refresh only the visible screen instead of
  triggering every dashboard, chart, grid, insurance and employee query.
- Kept charts on demand: opening all fourteen analytics charts adds about 0.6
  seconds once, rather than charging that cost on every app launch.

**Modern payroll workspace**
- Replaced the boxed legacy navigation with a flat 224px navy rail, grouped as
  Primary, Records, Insights and System, with a persistent version marker.
- Made Process Payroll the default workspace and introduced a three-stage
  `Sources → Check → Reports` run rail that tracks the real report workflow.
- Rebuilt the source-document area, readiness banner, run status and progress
  surfaces around a restrained payroll palette: ink navy, ledger teal,
  approval mint and warning amber.
- Standardized SF Pro Display/Text/Mono typography, larger page hierarchy,
  taller controls and tables, cleaner inputs, subtle borders and consistent
  light/dark surfaces. Global filters now stay out of Processing and Settings.
- Removed startup decoding of the old raster navigation icon set; the branded
  app icon is applied after first paint.

**Release and regression safety**
- Added architecture regressions for deferred imports, one-time view building,
  active-view-only refresh and database connection timeout.
- Kept v3.1.6 frozen and preserved the opt-in isolated QA data root for
  side-by-side testing with older installed versions.
- Verified the development runtime executes natively as ARM64 on Apple silicon;
  the distributable remains Universal for ARM64 and Intel Macs.
- Verified 352 passing tests across processing, storage, CLI, exports, GUI
  helpers and release scripts.

## v3.1.6 — 2026-08-25

**Processing correctness and identity**
- Tightened payslip boundary detection so secondary labels such as `Κωδικός
  Ειδικότητας` cannot create phantom employees.
- Preserved employee codes as strings through CSV/report generation, retained
  missing-code rows under a stable `Unknown` label, and included employee code
  in archive directories and filenames so namesakes remain isolated.
- Unified Greek/US amount parsing across receipts, CLI rows and standalone
  processing; dot-decimal values such as `1234.56` are no longer multiplied by
  100.
- Recognized all twelve Greek month names, parsed receipt payroll periods only
  from complete month tokens on the same line as an optional year, and rejected
  insurance periods outside months 1–12.

**Safe archives and idempotent receipts**
- Replaced bulk ZIP extraction with validated PDF-member extraction. Duplicate
  normalized paths, traversal, excessive member counts/sizes, total expanded
  size and suspicious compression ratios are rejected before expansion.
- Added employee-code-qualified payroll paths and fail-closed namesake receipt
  lookup. Receipts now carry a source-content digest in their archive filename.
- Added source-checksum manifests so reprocessing an identical payroll PDF or
  receipt does not append duplicate pages, while distinct same-month receipts
  remain separate and merge once.

**Truthful, isolated exports**
- Corrupt/all-failed CLI batches now return nonzero with ledger status `error`;
  genuine empty inputs retain `no-data`.
- Workbook paths are recorded only after both reports are written successfully.
  Filenames contain run identity plus a unique suffix, and workbooks publish
  atomically from run-specific temporary files to prevent concurrent corruption.
- Disabled XlsxWriter formula and URL inference for report data, preventing
  parsed values such as `=1+1` from becoming active spreadsheet formulas.
- Bundles and installers now advertise the complete `3.1.6` version.

**Self-contained macOS release**
- Corrected Python framework relinking so every embedded dependency keeps its
  actual path instead of being redirected to the framework executable.
- Made the builder compatible with the macOS system `rsync`, removed build-only
  framework metadata and eliminated the slow per-file quarantine cleanup pass.
- Set the bundled framework as `PYTHONHOME`; the running app now loads Python,
  Tcl and Tk exclusively from inside `Payroll Processor.app`.

**Verification**
- Added focused regressions for audit Bugs 13–28 and verified 349 passing tests.
  Core coverage is 93.26% against the enforced 65% gate. Isolated CLI, receipt,
  concurrent-export and signed-bundle GUI smoke tests also pass.

## v3.1.5 — 2026-08-25

**Release reliability**
- Added a Tk-aware Python selector for clean GUI and development launches, and
  made the CLI share the same requirement-hashed runtime cache. This avoids the
  local Homebrew Python installation that has no `_tkinter` or app dependencies.
- Installer versioning now derives from the selected version directory. Bundles
  carry an `APP_VERSION` resource for the About dialog, reject build Pythons
  without Tk, and are rebuilt fresh instead of silently reusing an older
  `dist/Payroll Processor.app`.

**Processing and exports**
- Isolated every ZIP extraction in a fresh directory, preventing similarly
  named archives such as `pay.zip` and `payz.zip` from duplicating records.
- Kept CLI intermediate payroll data alive long enough to generate both Excel
  reports and a truthful success ledger.
- Filed and matched receipts by their parsed payroll period, with paid date as
  a fallback, and merged standalone receipt PDFs as well as ZIP-contained ones.
- Fixed receipt lookup for employees whose names contain "Receipt".
- Preserved payroll rows that have an employee code but no name, labelled
  missing dates as `Unknown`, handled missing numeric values in detail exports,
  and made worksheet-name uniqueness match Excel's case-insensitive rules.
- Accepted canonical and common alias document types in grid edits, and fixed
  numeric parsing for both `1,000` and European values such as `1.234,56`.
- Added regressions for every processing/export defect and verified the suite
  at 322 passing tests, plus isolated multi-ZIP and real-PDF receipt runs.

**Side-by-side QA safety**
- Added `PAYROLL_PROCESSOR_DATA_ROOT` so a source build can keep its database
  configuration, preferences, reports, archives, watch folder and backups
  separate from an older installed version. Normal launches keep the legacy
  paths when the variable is unset.
- Added path-isolation and database-off navigation regression coverage.

**Notifications**
- Added non-blocking toasts (bottom right, stacked, auto-dismissing, optional
  action such as "Show in Finder") and moved every guidance, confirmation and
  completion message onto them. Errors that need a decision are still dialogs.
- Replaced the fifteen "Database Disabled" modal warnings: refreshing a view now
  shows an inline panel with an "Open Database Settings…" button, and actions
  that need storage raise a toast rather than a dialog per attempt.
- Dropped the modal that fired on every edit-lock toggle; the existing lock
  indicator and a toast carry it.

**Charts**
- All fourteen analytics charts plus the dashboard trend now follow the light /
  dark theme: figure and axes backgrounds, grid, spines, tick and title colours,
  legend frame. Previously every figure stayed white in dark mode.
- Added a shared series palette in `theme_config`, euro-formatted axes
  (`€ 1.2k`, `€ 3.4M`), percentage and day suffixes, `tight_layout` so rotated
  month labels are no longer clipped, and a titled "no data" placeholder.
- Grouped the fourteen chart tabs into five by question — Spend, Trends,
  Insurance, Payments, Workforce — as cards in a grid, with an expand control
  that fills the tab and reveals the matplotlib toolbar on demand.

**Responsiveness**
- Dashboard and analytics refreshes now run their queries on a worker thread and
  render on the UI thread, with a generation counter so a superseded refresh is
  discarded. Filter changes no longer freeze the window.
- Only the visible chart group is drawn on refresh; the others are marked stale
  and drawn when their tab is opened.
- Quitting with auto backup on shows a progress sheet instead of freezing, and
  "Run Backup Now" runs in the background.

**Navigation and layout**
- Fixed the Data Grid showing Monthly Summary's storage-disabled explanation;
  only the selected analytics subtab now refreshes its notice.
- Removed the duplicate Analytics status label.
- Fixed database-off Insurance and Employees views rendering as blank pages;
  both retain their layouts and show a working database-settings notice.
- Fixed inline notice placement by using Tk's `grid_size()` column/row order,
  and made notice removal respect the widget's active geometry manager.
- Filter bar grouped into Period / Document / Search, with the applied filters
  shown as removable chips, a "Clear all" button, and a search group that wraps
  to its own line at narrow widths.
- Sidebar gained a filled active state and ⌘1–⌘8 shortcuts.
- Settings scrolls, so the Backups and Appearance groups are reachable at the
  900×600 minimum window size.
- Month-over-month KPI cards split into a large value and a delta line coloured
  by direction.
- Processing view rebuilt: left-aligned header, a setup banner for missing
  dependencies or disabled storage, a file counter, and a collapsible live log.
- Defined `Accent.TButton` (it was referenced but never configured, so the
  primary action looked like every other button) and `Danger.TButton` for
  "Delete All Data…".
- Appearance changes now repaint the listbox, log pane, lock canvas, settings
  canvas and figures instead of leaving a half-themed window until restart.
- Fixed the Processing header reading "Payment Processor" and removed the
  leftover `DEBUG:` prints from the file and report actions.
- Made `_find_pg_tool`'s two tests hermetic; they searched the real
  `/Library/PostgreSQL` and failed on any machine with PostgreSQL installed.

## v3.1.4
- Promoted v3.1.4 as active version and updated root launch/build scripts.
- Added README.md, CONTRIBUTING.md and an MIT LICENSE; project engineered by PanLam.
- Added current-vs-last-month comparison KPIs (net pay, employer cost, insurance, employee count) to the dashboard.
- Added signed_employer/signed_employee/signed_date columns with an automatic startup migration.
- Added signed-flag updates by entry id and by employee month, with independent employer/employee sides.
- Signed-document import now auto-flags the matching employee month; government filings evidence the employer side only.
- Added a per-month signed / partially signed / unsigned summary.
- Payment receipts are now merged into the employee's monthly payment PDFs after archiving.
- Added "Employer Cost vs Net Pay" chart showing cost per euro of take-home pay.
- Added "Headcount Trend" chart with joiners and leavers, using all-history first/last payment dates.
- Added "Median vs Average Pay" chart with an interquartile band, aggregated per employee month.
- Added sudden-jump detection comparing each employee against their own prior month, surfaced in dashboard alerts.
- Added `tests/test_payroll_gui_helpers.py` covering the display-independent
  helpers on `PayrollProcessorGUI` (117 tests, no Tk root required).
- Added `tests/test_db_storage_gaps.py`, `tests/test_db_storage_filters.py` and
  `tests/test_todo_features.py`; `db_storage` coverage rose from 85% to 92% and
  the suite from 95 to 283 tests.
- Fixed the coverage gate: `.coveragerc` pointed at a nonexistent `src`, so it
  reported 0% and failed despite a fully passing suite.
- Fixed `bump_version.sh`: it recreated symlinked source directories instead of
  copying through them, never repointed the root `.coveragerc`, skipped
  `tests_cli` when copying, and contained a no-op string replacement.
- Removed a stray duplicate `versions/v3.1.3/v3.1.2/tools/create_icon.py`.
- Refreshed PROJECT_SUMMARY.md, which still described v1.3 as current.

## v3.1.3
- Promoted v3.1.3 as active version and updated root launch/build scripts.
- Added `payroll_cli` entry point with `run` and `query` subcommands and a `payroll_cli.sh` wrapper.
- Added `--dry-run` input validation mode to the CLI `run` command.
- Added a JSON run ledger under `~/Documents/Payroll Processor Reports/.run_ledger/` recording inputs, outputs, metrics, status, and timestamps.
- Added `query latest`, `query list --limit`, and `query by-id --id` for inspecting past runs.
- Consolidated the test suite and added dedicated CLI/ledger tests under `tests_cli/`.
- Refreshed database, export, and refresh icon assets.

## v3.1.2
- Promoted v3.1.2 as active version and updated root launch/build scripts.
- Added signed document import workflow with tidy storage and naming.
- Added signed-document archiving from the /Signed folder with tidy naming.

## v3.1.1
- Promoted v3.1.1 as active version and updated root launch/build scripts.
- Added Employees tab with profiles, monthly totals, and payment lists.
- Added employee profile fields (IBAN, first/last paid, pay rates) with edit support.
- Added IBAN and beneficiary extraction from payment receipts and auto-linking to employees.
- Added receipt archiving into employee year/month folders and improved receipt parsing.

## v3.1.0
- Promoted v3.1.0 as active version and updated root launch/build scripts.
- Added EFKA insurance claim parsing and database storage.
- Added TEKA insurance claim parsing and EFKA/TEKA split in Insurance summary.
- Added Insurance tab with monthly calculated vs official insurance comparison.
- Added paid toggle and paid date tracking for insurance claims.
- Added right-click edit and delete actions for insurance claim values.
- Added insurance claims to database exports and backup verification.

## v3.0.2
- Promoted v3.0.2 as active version and updated root launch/build scripts.
- Added paid and paid date columns to Monthly Employee Summary.
- Added Monthly Employee Summary action to generate per-employee monthly PDF reports.
- Reports now save under an "Employees Reports" subfolder of the selected output folder.
- Added duplicate cleanup modal in the Analytics Data Grid with grouped review and delete actions.
- Added duplicate scan using name/date/document type/amount keys for database entries.
- Sanitized per-employee sheet names to avoid invalid Excel characters.
- Normalized database staging inserts to handle NaT dates and reduce duplicate employee upserts.

## v3.0.1
- Bundled new app icon/logo and button icons; wired icon assets in the GUI and app bundle.
- Improved embedded app launcher and venv handling for macOS arm64 builds.
- Added pg_dump/pg_restore path discovery and corrected missing Optional import.

## v3.0.0
- Promoted v3.0.0 as active version and updated root launch/build scripts.
- Added paid_date migration for existing databases.
- Added transfer receipt parsing (PDF) to mark entries paid by name/amount/date.

## v2.2.9
- Increased default window size and minimum dimensions.
- Added paid status toggle with auto-fill for actual payment date.
- Added paid status + actual payment date fields to analytics grid and employee detail.
- Fixed UUID edits in the data grid and invalid-date DB inserts.
- Fixed dashboard alerts and employee detail queries (parameter handling).
- Added PDF option to analytics export dropdown.
- Improved horizontal scrolling behavior in analytics and dashboard tables.
- Persist window size/position between launches.
- Added column selector for Employee Detail and Monthly Summary tables.
- Added PDF archive folder picker in Settings and persisted archive location.
- Added option to move existing archived PDFs when changing archive folder.
- Archived PDFs now use default naming: YYMM_Name_DocumentType.pdf.
- Added database backup/restore and CSV export tools in Settings.
- Added Settings tab in sidebar and consolidated settings screens.
- Added total backup ZIP with PDFs + database export, auto-backup scheduling, and backup verification.
- Renamed actual payment date field to paid date with backward-compatible DB mapping.
- Added PDF export metadata + totals row and improved A4 landscape layout with wrapping.
- Added watch folder auto-processing for new ZIP/PDF files (configurable interval).
- Fixed Database tab visibility toggle persistence and re-added control in Settings.
- Added Delete All Data action with double confirmation.
- Added multi-term search filters with AND/OR/NOT and +/- controls.
- Added processing log output and auto-close timer for success dialog.
- Listed keyboard shortcuts in Help dialog.

## v2.2.8
- Sidebar order updated and analytics split into graphs vs data grid views.
- Added alerts panel on the dashboard with drill-down behavior.
- Added dashboard unpaid amount KPIs (last month, current month, current year).
- Added horizontal scrollbars to dashboard alerts/latest tables.
- Added delete entry action in analytics grid context menu.
- Added paid status + actual payment date fields for payroll entries (grid + modal edit).
- Added auto-refresh when switching tabs and sub-tabs.
- Added Settings toggle to show/hide the Database tab.
- Added export dropdown (CSV/XLSX/PDF) for analytics data grids.
- Added icon assets and tooltips for key controls.
- Fixed DB import handling of invalid dates and UUID edits.
- Enabled sorting by column headers in database views and analytics detail tables.
- Menu bar title updated to Payment Processor.
- Added appearance settings (auto/light/dark) in Settings menu.

## v2.2.7
- Processing accepts ZIP or PDF files (drag/drop and browse).
- Moved output folder selection into Settings menu.

## v2.2.6
- Added view dropdown and hid main tab bar to free horizontal space for charts.

## v2.2.5
- Analytics KPI cards now respect the global search filter.
- Added analytics Back button to return to prior drill-down state.
- Analytics and dashboard charts now respect the global search filter.

## v2.2.4
- Added Edit menu with undo/redo and global edit lock.
- Added redo stack for grid edits and Cmd+Shift+Z shortcut.
- Started Phase E: added keyboard shortcuts (refresh/search/copy) and saved UI preferences for filters/columns/edit lock.

## v2.2
- Added unified filter bar with smart defaults and debounced search.

## v2.1.1
- Centralized UI theme tokens and updated styling to use shared config.

## v2.1
- Added Dashboard tab with current metrics and monthly employee summary.
- Added monthly per-employee payment/insurance view in Analytics.

## v2.0.3
- Added analytics data grid with sorting/search and filters.

## v2.0.2
- Simplified analytics charts into dedicated tabs with zoom/pan controls.
- Added document-type filtering and interactive series toggles.

## v2.0.1
- Added KPI cards and cohesive typography/palette for the analytics dashboard.

## v1.9
- Fixed name parsing to stop before "Διεύθυνση".
- Improved source PDF archiving with per-employee assignment and page splitting when available.
- Merged archived PDF pages per employee when possible to avoid single-page outputs.

## v1.8
- Bumped active version to v1.8.
- Added analytics filters for year/month and new charts (document mix and payment heat-map).

## v1.7
- Added analytics tab with monthly burn, insurance breakdown, and cost per employee charts.
- Added matplotlib dependency for chart rendering.
- Added source PDF archiving by year/month/employee.
- Added deduplication protections for database imports.
- Updated build scripts to default to v1.7.0.

## v1.6
- Promoted v1.6 as the active version and updated root launch/build wrappers.
- Refreshed the payroll schema guide and improved import script normalization.
- Added PostgreSQL schema DDL and database storage integration with GUI settings.
- Added a database views tab that renders normalized view data.
- Updated database views to show employee names and source PDFs.
- Added database tab filters, limits, and column selectors.

## v1.5
- Embedded Python venv and bundled pdftotext into the app bundle (build-time).
- Installer README updated to reflect bundled dependencies.

## v1.4
- Added output folder picker in the GUI.
- Added “Show in Finder” prompt after report generation.
- Simplified DMG to drag-and-drop (app + Applications link) and added User Agreement file.

## v1.3
- Added dual Excel outputs per run: per-employee summary + analytical detail list.
- Auto-save now names files with `_summary.xlsx` and `_detail.xlsx`.
- Added app menu with About and How-To, author credited as panlam.
- macOS app name now shows as "Payroll Processor" (not Python).
- Renamed document type `Unknown` to `Salary`.

## v1.2
- Auto-saves reports to `~/Documents/Payroll Processor Reports`.
- GUI shows output location and last saved file.
- Launch scripts cache dependency installs to speed startup.

## v1.1
- Reorganized repository into versioned folders (`versions/v1.1` active).
- Added app bundle creation and installer tooling.
- Improved GUI status/progress handling and dependency checks.

## v1.0
- Initial working GUI and payroll processing pipeline.
- Core PDF parsing and report generation scripts.

## v0.9
- Initial payroll processing pipeline.
 
