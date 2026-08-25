## TODO

Everything previously listed here shipped in v3.1.4. See [CHANGELOG.md](CHANGELOG.md)
for the release entry and [CONTRIBUTING.md](CONTRIBUTING.md) for how to extend it.

### Delivered in v3.1.4

**Time comparisons**
- Current month vs last month — net pay, employer cost, insurance, entry and
  employee counts. `db_storage.fetch_period_comparison`, shown as a third row of
  dashboard KPI cards.
- Employer cost vs net pay ratio over time.
  `db_storage.fetch_employer_cost_ratio_by_month`, "Employer Cost vs Net Pay" chart.

**Workforce**
- Headcount trend with joiners and leavers. `db_storage.fetch_headcount_trend`,
  "Headcount Trend" chart. First/last payment dates are computed across all
  history so an employee who predates the filter window is not miscounted.
- Median vs average net pay with an interquartile band.
  `db_storage.fetch_net_pay_distribution`, "Median vs Average Pay" chart.
  Aggregated per employee-month, so a salary plus a bonus counts once.

**Payment status**
- Sudden jumps per employee and document type.
  `db_storage.fetch_entry_jumps` compares each employee against their own prior
  month rather than a global average, and requires both a percentage and an
  absolute threshold. Surfaced in the dashboard alerts table.

**Receipts & signatures**
- `signed_employer`, `signed_employee` and `signed_date` columns on
  `payroll_entries`, added by `db_storage.migrate_signed_flags` on startup.
- `update_signed_flags` (by entry id) and `mark_signed_for_period` (by employee
  and month). Either signature can be set independently.
- Auto-detection: importing a signed document flags the matching employee-month.
  Government filings evidence the employer side only; documents explicitly
  marked as signatures evidence both.
- Payment receipts are merged into the employee's monthly payment PDFs after
  archiving, via poppler's `pdfunite`. Without it the receipt stays a separate
  archived file, so nothing is lost.
- `fetch_signed_status_summary` reports fully / partially / unsigned per month.

### Known defects, pinned by tests but not yet fixed

Both are pinned in `versions/v3.1.5/tests/test_payroll_gui_helpers.py` with
`KNOWN DEFECT` docstrings, so fixing either will deliberately fail its test.

- `_validate_grid_edit` accepts only a lowercase `document_type` vocabulary and
  never case-folds, while `process_payroll` writes `Salary`, `Bonus` and
  `VacationAllowance`. Retyping the value the grid displays is rejected.
- `_parse_numeric` treats a comma as a decimal separator whenever no dot is
  present, so `"1,000"` parses as `1.0`. The app's own formatter always emits
  two decimals and round-trips safely; the exposure is externally formatted
  text reaching `_build_export_totals`.

### Not started

- Bring `payroll_gui.py` widget and event code under test. Its
  display-independent helpers are covered; the rest needs a Tk harness.
- Code signing and notarisation for distribution.

### QA audit — 2026-08-25: startup and navigation

- [x] Bug 1 — MEDIUM: Data Grid shows the Monthly Summary database-off message
**File:** `versions/v3.1.4/src/payroll_gui.py:4052`
Opening Analytics Data Grid with storage disabled calls both grid refresh methods against one shared notice panel. The second call overwrites the visible Data Grid explanation with “The monthly summary is built…”, even while the Data Grid subtab is selected.
> **Tell dev:** "Give each Analytics Data Grid subtab its own database-off notice container, or update only the notice for the selected subtab. Add a Tk navigation test that selects Data Grid while storage is disabled and asserts that the visible notice describes stored payroll entries, not Monthly Summary."

- [x] Bug 2 — LOW: Analytics renders the disabled-status message twice
**File:** `versions/v3.1.4/src/payroll_gui.py:1149`
The same `analytics_status_var` is bound to labels at both column 5 and column 8 of the Analytics header. When storage is disabled, the UI visibly reads “Database storage is disabled. Database storage is disabled.”
> **Tell dev:** "Remove the duplicate `ttk.Label` at line 1165 and keep one status label in the Analytics header. Add a widget-construction assertion that `analytics_status_var` has exactly one visible label consumer."

- [x] Bug 3 — MEDIUM: Employees becomes a completely blank page when storage is off
**File:** `versions/v3.1.4/src/payroll_gui.py:2319`
In a clean v3.1.4 profile with database storage disabled, navigating to Employees produces an empty content pane with no header, table, explanation, or recovery action. `refresh_employees_tab` returns immediately and, unlike the other database-backed views, never creates a database-off notice.
> **Tell dev:** "On the disabled branch of `refresh_employees_tab`, render `_database_notice(self.employees_tab, ...)` with an Open Database Settings action, and clear it on the enabled branch. Add a Tk smoke test that switches to Employees with storage disabled and verifies the header and notice are mapped."

- [x] Bug 4 — MEDIUM: Insurance database-off notice fails and the page renders blank
**File:** `versions/v3.1.4/src/payroll_gui.py:2095`
The Insurance disabled branch calls `_database_notice`, but the live v3.1.4 page still renders as an entirely empty pane. Users get no explanation or route to enable storage, despite the code intending to provide one.
> **Tell dev:** "Add a Tk regression test for the disabled Insurance view, then repair `_database_notice` placement so the Insurance header and inline notice remain mapped. Verify the helper uses the correct row count returned by `grid_size()` and does not overlap the table row."

#### Usability Assessment

- [x] The Processing page's database-off banner is clear and correctly explains that report generation still works.
- [ ] Disable Backup, Restore, Export, Delete All Data, Run Backup, and Verify Backup controls while database storage is off, or explain their disabled state inline.
- [ ] Keep the explicit QA data paths visible in Settings; they make it easy to verify that a test run is isolated from a production profile.
- [ ] Add a persistent version indicator somewhere in the main window so side-by-side testing does not depend on opening About.

### QA audit — 2026-08-25: processing and exports

- [ ] Bug 5 — HIGH: colliding ZIP names can duplicate payroll records across a batch
**File:** `versions/v3.1.5/src/process_payroll.py:629`
`rstrip('.zip')` removes any trailing combination of those four characters, so
`pay.zip` and `payz.zip` share one extraction directory. The second archive then
reprocesses the first archive's stale PDF. A synthetic two-ZIP run returned
`['second', 'first']` for the second archive.
> **Tell dev:** "Give every `process_zip` call a fresh extraction directory under the supplied temporary root, use `Path(zip_path).stem` only as a readable prefix, and add a two-archive collision regression."

- [ ] Bug 6 — HIGH: next-month receipts do not merge into their payroll-period PDFs
**File:** `versions/v3.1.5/src/process_payroll.py:460`
Receipt parsing retains `payroll_year` and `payroll_month`, but archiving and
lookup use only `paid_date`. A receipt paid in April for March payroll was filed
under April and found no March payment PDF.
> **Tell dev:** "Use one receipt-period helper that prefers parsed payroll year/month and falls back to paid date, then use it for both receipt archiving and monthly-PDF lookup."

- [ ] Bug 7 — MEDIUM: standalone receipt PDFs are archived but never merged
**File:** `versions/v3.1.5/src/process_payroll.py:715`
The ZIP path calls `_merge_receipts_after_archiving`; `process_pdf_file` returns
immediately after archiving a receipt, and the GUI's direct-PDF path similarly
continues at `payroll_gui.py:7729`. Synthetic instrumentation recorded one
receipt and zero merge calls.
> **Tell dev:** "Route ZIP and standalone receipt handling through one archive-and-merge helper and keep the merged/skipped targets in the processing log."

- [ ] Bug 8 — HIGH: CLI reports success after deleting its temporary CSVs
**File:** `versions/v3.1.5/src/payroll_cli.py:201`
The CLI writes intermediate CSVs inside `TemporaryDirectory`, exits that
context, and only then loads them at line 248. A valid synthetic payroll row
returned exit code 0, printed `No valid payroll data found`, and created zero
workbooks.
> **Tell dev:** "Load and write the reports before leaving `TemporaryDirectory`, and add an unmocked CSV-lifetime regression that asserts both workbooks and a successful ledger entry exist."

- [ ] Bug 9 — HIGH: employee sheet names that differ only by case abort export
**File:** `versions/v3.1.5/src/create_employee_reports.py:142`
The uniqueness set is case-sensitive while Excel sheet names are not. Synthetic
employees `Alice (E1)` and `alice (E1)` reproduced XlsxWriter's
`DuplicateWorksheetName` and aborted the workbook.
> **Tell dev:** "Track sheet-name uniqueness with `casefold()` while preserving the display spelling, and add a case-collision workbook regression."

- [ ] Bug 10 — HIGH: rows with a missing employee name vanish from the summary
**File:** `versions/v3.1.5/src/create_employee_reports.py:86`
The parser permits `EmployeeName=None`, but pandas' default groupby drops null
group keys. One otherwise valid synthetic payroll row produced zero summary
rows and therefore no employee sheet.
> **Tell dev:** "Fill a stable employee-name fallback before grouping, or group with `dropna=False`, and assert that a code-only payroll row survives into both summary and detail reports."
