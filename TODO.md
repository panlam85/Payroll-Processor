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

Both are pinned in `versions/v3.1.4/tests/test_payroll_gui_helpers.py` with
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
