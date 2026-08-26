## TODO

Everything previously listed here shipped in v3.1.4. See [CHANGELOG.md](CHANGELOG.md)
for the release entry and [CONTRIBUTING.md](CONTRIBUTING.md) for how to extend it.

### Delivered in v3.1.7

- Sub-second native first paint through deferred processing/chart imports,
  lazy screen construction and background database maintenance.
- Active-screen-only filter refresh instead of the previous all-view query
  cascade.
- Modern payroll-specific navigation, typography, light/dark palette and the
  Sources → Check → Reports processing runway.
- ARM64-native execution verification and dedicated performance-architecture
  regression tests.

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

### Helper defects fixed in v3.1.5

- Grid edits now accept stored canonical document types and common lowercase,
  snake-case and hyphenated aliases, then return the canonical stored value.
- Numeric parsing now handles comma thousands separators and mixed European
  thousands/decimal separators without understating values.

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

- [x] Bug 5 — HIGH: colliding ZIP names can duplicate payroll records across a batch
**File:** `versions/v3.1.5/src/process_payroll.py:629`
`rstrip('.zip')` removes any trailing combination of those four characters, so
`pay.zip` and `payz.zip` share one extraction directory. The second archive then
reprocesses the first archive's stale PDF. A synthetic two-ZIP run returned
`['second', 'first']` for the second archive.
> **Tell dev:** "Give every `process_zip` call a fresh extraction directory under the supplied temporary root, use `Path(zip_path).stem` only as a readable prefix, and add a two-archive collision regression."
> **Fixed in v3.1.5:** each archive now gets a unique `mkdtemp` extraction path;
> the two-archive regression and an isolated CLI run both produced exactly one
> record per ZIP.

- [x] Bug 6 — HIGH: next-month receipts do not merge into their payroll-period PDFs
**File:** `versions/v3.1.5/src/process_payroll.py:460`
Receipt parsing retains `payroll_year` and `payroll_month`, but archiving and
lookup use only `paid_date`. A receipt paid in April for March payroll was filed
under April and found no March payment PDF.
> **Tell dev:** "Use one receipt-period helper that prefers parsed payroll year/month and falls back to paid date, then use it for both receipt archiving and monthly-PDF lookup."
> **Fixed in v3.1.5:** archiving and lookup share a payroll-period-first helper;
> a real April-paid March receipt was archived and merged under `2026/03`.

- [x] Bug 7 — MEDIUM: standalone receipt PDFs are archived but never merged
**File:** `versions/v3.1.5/src/process_payroll.py:715`
The ZIP path calls `_merge_receipts_after_archiving`; `process_pdf_file` returns
immediately after archiving a receipt, and the GUI's direct-PDF path similarly
continues at `payroll_gui.py:7729`. Synthetic instrumentation recorded one
receipt and zero merge calls.
> **Tell dev:** "Route ZIP and standalone receipt handling through one archive-and-merge helper and keep the merged/skipped targets in the processing log."
> **Fixed in v3.1.5:** both the engine and direct-PDF GUI path invoke receipt
> merging and report merged/skipped targets in the processing log.

- [x] Bug 8 — HIGH: CLI reports success after deleting its temporary CSVs
**File:** `versions/v3.1.5/src/payroll_cli.py:201`
The CLI writes intermediate CSVs inside `TemporaryDirectory`, exits that
context, and only then loads them at line 248. A valid synthetic payroll row
returned exit code 0, printed `No valid payroll data found`, and created zero
workbooks.
> **Tell dev:** "Load and write the reports before leaving `TemporaryDirectory`, and add an unmocked CSV-lifetime regression that asserts both workbooks and a successful ledger entry exist."
> **Fixed in v3.1.5:** temporary CSVs are loaded inside their lifetime; the
> regression and isolated wrapper run produced both workbooks and a success ledger.

- [x] Bug 9 — HIGH: employee sheet names that differ only by case abort export
**File:** `versions/v3.1.5/src/create_employee_reports.py:142`
The uniqueness set is case-sensitive while Excel sheet names are not. Synthetic
employees `Alice (E1)` and `alice (E1)` reproduced XlsxWriter's
`DuplicateWorksheetName` and aborted the workbook.
> **Tell dev:** "Track sheet-name uniqueness with `casefold()` while preserving the display spelling, and add a case-collision workbook regression."
> **Fixed in v3.1.5:** worksheet names are tracked with `casefold()` and the
> case-collision workbook regression completes successfully.

- [x] Bug 10 — HIGH: rows with a missing employee name vanish from the summary
**File:** `versions/v3.1.5/src/create_employee_reports.py:86`
The parser permits `EmployeeName=None`, but pandas' default groupby drops null
group keys. One otherwise valid synthetic payroll row produced zero summary
rows and therefore no employee sheet.
> **Tell dev:** "Fill a stable employee-name fallback before grouping, or group with `dropna=False`, and assert that a code-only payroll row survives into both summary and detail reports."
> **Fixed in v3.1.5:** blank names receive a stable employee-code label before
> grouping; missing dates are also labelled `Unknown` instead of `NaT`.

- [x] Bug 11 — HIGH: detail workbook crashes on missing numeric values
**File:** `versions/v3.1.5/src/create_employee_reports.py`
Pandas 3.0 can retain missing numeric cells as floats while sizing worksheet
columns. Applying `len()` to those values raised `TypeError` after the summary
workbook had already been created.
> **Fixed in v3.1.5:** display widths now treat missing cells as empty; the real
> multi-ZIP CLI run produced valid summary and detail XLSX files.

- [x] Bug 12 — MEDIUM: employee names containing "Receipt" prevent receipt merge
**File:** `versions/v3.1.5/src/process_payroll.py`
Receipt lookup excluded every filename containing the word `receipt`, including
ordinary payroll PDFs for an employee such as `Receipt Employee`.
> **Fixed in v3.1.5:** lookup excludes the exact archived receipt and generated
> receipt suffix, not arbitrary employee-name text; a real two-page PDF merge passed.

### QA audit — 2026-08-25: further processing and export testing

> **Fixed in v3.1.6:** Bugs 13–28 are covered by dedicated regressions in
> `versions/v3.1.6/tests/test_v316_regressions.py`; the full suite passes with
> 349 tests and 93.26% core coverage.

- [x] Bug 13 — HIGH: corrupt input returns CLI success and a non-error ledger status
**File:** `versions/v3.1.5/src/payroll_cli.py:245`
A deliberately corrupt ZIP raised `File is not a zip file`, but the wrapper
returned exit code 0 and wrote ledger status `no-data`. Automation therefore
cannot distinguish complete processing failure from a successful empty run.
> **Tell dev:** "If every attempted input failed, set ledger status to `error` and return nonzero. Reserve `no-data` for successfully inspected inputs containing no payroll rows, and add a corrupt-ZIP CLI regression."

- [x] Bug 14 — MEDIUM: failed and empty CLI runs advertise reports that do not exist
**File:** `versions/v3.1.5/src/payroll_cli.py:187`
Summary and detail paths are added to the ledger before processing. The corrupt
ZIP run created neither workbook, yet `query outputs` would return both planned
paths as if they were artifacts.
> **Tell dev:** "Only populate `summary_xlsx` and `detail_xlsx` after each workbook is written and validated, or store planned paths separately with an explicit existence/status field."

- [x] Bug 15 — HIGH: concurrent CLI runs collide and can corrupt their workbooks
**File:** `versions/v3.1.5/src/payroll_cli.py:185`
Output names have only second precision. Two isolated runs started together
wrote the same summary/detail paths and both ledgers said `success`; `unzip -t`
then found invalid compressed data in the shared summary workbook.
> **Tell dev:** "Include the unique run id (or a UUID) in report filenames, write each workbook to a run-specific temporary path, atomically publish it, and add a two-process concurrency regression."

- [x] Bug 16 — HIGH: secondary code labels split one payslip into phantom employees
**File:** `versions/v3.1.5/src/process_payroll.py:62`
Every line beginning with `Κωδικός` starts a new slip. One employee followed by
`Κωδικός Ειδικότητας : 123` produced employees `001` and `Ειδικότητας`, splitting
the real employee's amounts across two records.
> **Tell dev:** "Anchor slip boundaries to the exact employee-code label/syntax and add a fixture containing secondary `Κωδικός ...` fields that must produce one complete payroll record."

- [x] Bug 17 — HIGH: namesake employees have their confidential PDFs combined
**File:** `versions/v3.1.5/src/process_payroll.py:424`
Archive directory and filename identity prefer employee name and ignore code.
Two one-page PDFs for codes `001` and `002`, both named `Common Name`, became one
two-page monthly PDF under a shared folder.
> **Tell dev:** "Include the stable employee code in archive directories and filenames, migrate existing paths safely, and assert that namesakes never share or merge payroll PDFs."

- [x] Bug 18 — HIGH: duplicate ZIP member paths silently discard payroll documents
**File:** `versions/v3.1.5/src/process_payroll.py:650`
A ZIP with two distinct PDFs both stored as `same.pdf` had two members, but
`extractall()` overwrote the first and processing returned only the second row.
> **Tell dev:** "Validate normalized member-path uniqueness before extraction; reject duplicates with a clear input error or extract each member under a unique internal path while preserving both records."

- [x] Bug 19 — HIGH: ZIP extraction has no decompression safety limits
**File:** `versions/v3.1.5/src/process_payroll.py:656`
Extraction has no expanded-size, member-count, per-file-size, or compression-ratio
guard. A disposable 8,274-byte archive expanded to 8,388,608 bytes and was accepted.
> **Tell dev:** "Inspect every `ZipInfo` before extraction and reject configurable cumulative size, per-member size, member-count, path-depth, and compression-ratio limits; test a high-ratio archive without fully expanding it."

- [x] Bug 20 — HIGH: leading-zero employee codes collapse during CSV round-trip
**File:** `versions/v3.1.5/src/create_employee_reports.py:39`
`read_csv` infers employee codes as numbers. Codes `001` and `1` both reloaded as
integer `1`, corrupting identity and allowing distinct employees to collapse.
> **Tell dev:** "Load `EmployeeCode` with an explicit string dtype and controlled NA handling, then assert `001` survives the parser/CSV/report pipeline exactly."

- [x] Bug 21 — HIGH: receipt payroll period is inferred from unrelated text
**File:** `versions/v3.1.5/src/process_payroll.py:238`
The parser searches the entire receipt for the first year and any month substring.
Beneficiary `ΜΑΡΤΙΝΟΣ` triggered March, and a January 2024 payment containing `DEC`
was assigned December 2024 instead of December 2023.
> **Tell dev:** "Parse payroll period only from explicitly labelled payment-purpose text; otherwise fall back to paid date. When a labelled month lacks a year, apply a tested year-boundary rule."

- [x] Bug 22 — HIGH: multiple receipts for one employee/month overwrite each other
**File:** `versions/v3.1.5/src/process_payroll.py:477`
Receipt archive names contain no transaction or content identity. Two different
receipts resolved to one path; the second was not copied, then the first archived
receipt was merged again, losing the second receipt and duplicating the first.
> **Tell dev:** "Give receipts a stable transaction/content identity in their archive name, never merge a source that was not archived, and test two distinct same-employee/month receipts end to end."

- [x] Bug 23 — HIGH: reprocessing a payroll PDF duplicates archived pages
**File:** `versions/v3.1.5/src/process_payroll.py:611`
An existing monthly PDF is always merged with the new source without checking
content identity. Processing the same one-page salary PDF twice produced two
identical pages.
> **Tell dev:** "Make payroll archiving content-idempotent using a source checksum/manifest and assert that reprocessing identical input leaves page count and bytes stable."

- [x] Bug 24 — HIGH: dot-decimal amounts are multiplied by 100
**File:** `versions/v3.1.5/src/process_payroll.py:335`
Receipt parsing removes every dot before converting the value. `1234.56` became
`123456.0`, which can prevent payment matching or mark the wrong financial data.
> **Tell dev:** "Use one locale-aware amount parser for receipts and payroll rows; regress `1.234,56`, `1234,56`, `1,234.56`, and `1234.56` with unambiguous expected values."

- [x] Bug 25 — HIGH: detailed Excel reports permit formula injection
**File:** `versions/v3.1.5/src/create_employee_reports.py:202`
Untrusted parsed strings are written with XlsxWriter's formula detection enabled.
An employee name `=1+1` was serialized as an Excel `<f>1+1</f>` formula rather
than literal text; source filenames expose the same path.
> **Tell dev:** "Disable `strings_to_formulas` for exported data or explicitly write all untrusted text cells as strings, and test leading `=`, `+`, `-`, `@`, whitespace, and newline variants."

- [x] Bug 26 — MEDIUM: rows missing employee code still vanish from summaries
**File:** `versions/v3.1.5/src/create_employee_reports.py:73`
The code creates a normalized fallback series but never assigns it to
`df['EmployeeCode']`; the later groupby still drops the null-key row.
> **Tell dev:** "Assign a stable fallback identifier before grouping and add a name-only payroll regression that survives both summary and detail output."

- [x] Bug 27 — MEDIUM: April through December payslip filenames are misclassified
**File:** `versions/v3.1.5/src/process_payroll.py:392`
The classifier documentation promises month-name recognition but implements only
January, February, and March. April through December fall back to `Salary` while
the first three months become `Payslip`, fragmenting filters and summaries.
> **Tell dev:** "Normalize and recognize all twelve supported Greek month names through one table, and parameterize every month in the classifier tests."

- [x] Bug 28 — MEDIUM: invalid insurance months are parsed and archived
**File:** `versions/v3.1.5/src/process_payroll.py:267`
The insurance parser accepts any one- or two-digit month without range validation.
`ΠΕΡΙΟΔΟΣ ΑΠΟ 13/2026` produced `claim_month=13` and archive name
`202613_EFKA_TPTE_RF123456.pdf`.
> **Tell dev:** "Validate month 1–12 before returning, archiving, or storing a claim; reject 0 and 13 with explicit diagnostics and focused parser regressions."

#### Usability Assessment — further processing and exports

- [ ] Show per-file `processed`, `no payroll data`, or `failed` status before presenting an overall batch result.
- [ ] Display employee code alongside name anywhere archive identity or receipt matching is involved.
- [ ] Preview ZIP member count and expanded size, with a clear explanation when safety limits reject an archive.
- [ ] Include a visible run id in report filenames and the Processing log so concurrent or repeated outputs are distinguishable.
