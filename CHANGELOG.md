# Changelog

All notable changes to this project are documented here. Newer entries go to the top.

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
 
