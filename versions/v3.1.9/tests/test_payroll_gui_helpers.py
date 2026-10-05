"""Tests for the display-independent helpers on PayrollProcessorGUI.

payroll_gui.py is a 6,340-line Tkinter module excluded from the coverage
gate, but a large share of its logic needs no display: formatters,
parsers, validators, the signed-document classifier, and the export-table
builders.

These tests drive an *uninitialized* instance (`PayrollProcessorGUI.__new__`),
which gives real bound methods without running `__init__` — so no Tk root,
no widgets, no database, no window server. Matplotlib is pinned to the Agg
backend before import so the module's top-level `backend_tkagg` import is
safe headlessly.
"""

import datetime

import matplotlib

matplotlib.use("Agg")

import pytest

from payroll_gui import PayrollProcessorGUI


@pytest.fixture
def gui():
    """A PayrollProcessorGUI with bound methods but no widgets."""
    return PayrollProcessorGUI.__new__(PayrollProcessorGUI)


# --------------------------------------------------------------------------
# Date arithmetic
# --------------------------------------------------------------------------


def test_month_start_and_end(gui):
    d = datetime.date(2026, 2, 17)
    assert gui._month_start(d) == datetime.date(2026, 2, 1)
    assert gui._month_end(d) == datetime.date(2026, 2, 28)


def test_month_end_handles_leap_year(gui):
    assert gui._month_end(datetime.date(2024, 2, 5)) == datetime.date(2024, 2, 29)


@pytest.mark.parametrize(
    "start,months,expected",
    [
        (datetime.date(2026, 1, 15), 1, datetime.date(2026, 2, 15)),
        (datetime.date(2026, 1, 15), -1, datetime.date(2025, 12, 15)),
        (datetime.date(2026, 1, 15), 12, datetime.date(2027, 1, 15)),
        (datetime.date(2026, 1, 15), 0, datetime.date(2026, 1, 15)),
        # Day is clamped to the target month's length.
        (datetime.date(2026, 1, 31), 1, datetime.date(2026, 2, 28)),
        (datetime.date(2026, 3, 31), -1, datetime.date(2026, 2, 28)),
        (datetime.date(2024, 1, 31), 1, datetime.date(2024, 2, 29)),
        # Crossing a year boundary backwards.
        (datetime.date(2026, 2, 10), -14, datetime.date(2024, 12, 10)),
    ],
)
def test_add_months(gui, start, months, expected):
    assert gui._add_months(start, months) == expected


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def test_format_currency(gui):
    assert gui._format_currency(1234.5) == "€ 1,234.50"
    assert gui._format_currency(0) == "€ 0.00"
    assert gui._format_currency(-50.125) == "€ -50.12"


def test_format_currency_falls_back_on_bad_input(gui):
    assert gui._format_currency("not a number") == "€ 0.00"
    assert gui._format_currency(None) == "€ 0.00"


def test_format_value_for_edit(gui):
    assert gui._format_value_for_edit(12) == "12.00"
    assert gui._format_value_for_edit("3.456") == "3.46"
    assert gui._format_value_for_edit(None) == ""
    assert gui._format_value_for_edit("abc") == ""


def test_normalize_text_strips_accents_and_casefolds(gui):
    # Greek accented text is a core case for this app.
    assert gui._normalize_text("ΆΝΝΑ") == "αννα"
    assert gui._normalize_text("Café") == "cafe"
    assert gui._normalize_text(None) == ""
    assert gui._normalize_text(42) == "42"


# --------------------------------------------------------------------------
# Numeric parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", [None, "", "   ", "—", "-", "None"])
def test_parse_numeric_treats_blanks_as_none(gui, blank):
    assert gui._parse_numeric(blank) is None


def test_parse_numeric_strips_currency_and_spaces(gui):
    assert gui._parse_numeric("€ 1,234.56") == pytest.approx(1234.56)
    assert gui._parse_numeric("  42.5  ") == pytest.approx(42.5)
    assert gui._parse_numeric("$1,000.00") == pytest.approx(1000.0)


def test_parse_numeric_reads_comma_as_decimal_when_no_dot(gui):
    """With no dot present, a comma is the decimal separator (EU format)."""
    assert gui._parse_numeric("1,50") == pytest.approx(1.5)


def test_parse_numeric_reads_thousands_separator_without_decimals(gui):
    assert gui._parse_numeric("1,000") == pytest.approx(1000.0)
    assert gui._parse_numeric("1,000.00") == pytest.approx(1000.0)


def test_parse_numeric_reads_european_thousands_and_decimal_separators(gui):
    assert gui._parse_numeric("1.234,56") == pytest.approx(1234.56)


def test_parse_numeric_returns_none_for_garbage(gui):
    assert gui._parse_numeric("abc") is None
    assert gui._parse_numeric("1.2.3.4") is None


def test_currency_format_parse_roundtrip(gui):
    """The app's own display format must survive a parse back to a number."""
    for value in (0.0, 5.5, 1234.56, 1_000_000.99):
        assert gui._parse_numeric(gui._format_currency(value)) == pytest.approx(value)


# --------------------------------------------------------------------------
# Boolean / date normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("truthy", [True, "1", "true", "TRUE", "Yes", "paid", " PAID "])
def test_normalize_paid_status_truthy(gui, truthy):
    assert gui._normalize_paid_status(truthy) is True


@pytest.mark.parametrize("falsy", [False, "0", "false", "No", "unpaid", "", "garbage"])
def test_normalize_paid_status_falsy(gui, falsy):
    assert gui._normalize_paid_status(falsy) is False


def test_format_paid_status_uses_normalizer(gui):
    assert gui._format_paid_status("yes") == "Yes"
    assert gui._format_paid_status(True) == "Yes"
    assert gui._format_paid_status(None) == "No"
    assert gui._format_paid_status("unpaid") == "No"


@pytest.mark.parametrize("empty", [None, "", "  ", "none", "NaT", "null", "NONE"])
def test_is_empty_date(gui, empty):
    assert gui._is_empty_date(empty) is True


def test_is_empty_date_rejects_real_values(gui):
    assert gui._is_empty_date("2026-01-01") is False
    assert gui._is_empty_date(datetime.date(2026, 1, 1)) is False


@pytest.mark.parametrize(
    "value,default,expected",
    [
        (True, False, True),
        (False, True, False),
        ("yes", False, True),
        ("on", False, True),
        ("  TRUE ", False, True),
        ("no", True, False),
        ("", True, False),
        (None, True, True),
        (None, False, False),
        (1, False, True),
        (0, True, False),
    ],
)
def test_normalize_pref_bool(gui, value, default, expected):
    assert gui._normalize_pref_bool(value, default) is expected


# --------------------------------------------------------------------------
# Grid edit validation
# --------------------------------------------------------------------------


def test_validate_grid_edit_requires_a_value(gui):
    ok, _, message = gui._validate_grid_edit("net_pay", "")
    assert ok is False
    assert "required" in message.lower()


@pytest.mark.parametrize("column", ["basic_salary", "total_earnings", "net_pay"])
def test_validate_grid_edit_parses_amounts(gui, column):
    ok, value, message = gui._validate_grid_edit(column, "1,234.567")
    assert ok is True
    assert value == pytest.approx(1234.57)  # rounded to 2dp
    assert message == ""


def test_validate_grid_edit_rejects_bad_amount(gui):
    ok, value, message = gui._validate_grid_edit("net_pay", "abc")
    assert ok is False
    assert value == "abc"
    assert "valid number" in message


def test_validate_grid_edit_accepts_slash_dates(gui):
    ok, value, _ = gui._validate_grid_edit("payment_date", "2026/03/04")
    assert ok is True
    assert value == datetime.date(2026, 3, 4)


def test_validate_grid_edit_rejects_bad_date(gui):
    ok, _, message = gui._validate_grid_edit("paid_date", "04-03-2026")
    assert ok is False
    assert "YYYY-MM-DD" in message


@pytest.mark.parametrize("word", ["yes", "TRUE", "1", "paid"])
def test_validate_grid_edit_paid_status_truthy(gui, word):
    ok, value, _ = gui._validate_grid_edit("paid_status", word)
    assert ok is True
    assert value is True


@pytest.mark.parametrize("word", ["no", "false", "0", "unpaid"])
def test_validate_grid_edit_paid_status_falsy(gui, word):
    ok, value, _ = gui._validate_grid_edit("paid_status", word)
    assert ok is True
    assert value is False


def test_validate_grid_edit_rejects_bad_paid_status(gui):
    ok, _, message = gui._validate_grid_edit("paid_status", "maybe")
    assert ok is False
    assert "Yes or No" in message


def test_validate_grid_edit_rejects_uneditable_column(gui):
    ok, _, message = gui._validate_grid_edit("employee_code", "EMP-1")
    assert ok is False
    assert "cannot be edited" in message


def test_validate_grid_edit_document_type_accepts_lowercase_vocabulary(gui):
    ok, value, _ = gui._validate_grid_edit("document_type", "salary")
    assert ok is True
    assert value == "Salary"


@pytest.mark.parametrize(
    "entered,canonical",
    [
        ("Salary", "Salary"),
        ("Bonus", "Bonus"),
        ("VacationAllowance", "VacationAllowance"),
        ("vacation_allowance", "VacationAllowance"),
        ("UnusedLeaveCompensation", "UnusedLeaveCompensation"),
        ("unused_leave_compensation", "UnusedLeaveCompensation"),
        ("Payslip", "Payslip"),
        ("other", "Other"),
    ],
)
def test_validate_grid_edit_document_type_accepts_canonical_and_aliases(gui, entered, canonical):
    ok, value, message = gui._validate_grid_edit("document_type", entered)
    assert ok is True
    assert value == canonical
    assert message == ""


def test_validate_grid_edit_document_type_rejects_unknown_value(gui):
    ok, value, message = gui._validate_grid_edit("document_type", "Commission")
    assert ok is False
    assert value == "Commission"
    assert "Document type must be one of" in message


# --------------------------------------------------------------------------
# Filenames and signed-document classification
# --------------------------------------------------------------------------


def test_sanitize_filename_handles_greek_and_punctuation(gui):
    assert gui._sanitize_filename("ΆΝΝΑ ΠΑΠΑ/2026") == "ΑΝΝΑ_ΠΑΠΑ2026"
    assert gui._sanitize_filename("report: final*") == "report_final"


def test_sanitize_filename_falls_back_to_default(gui):
    assert gui._sanitize_filename(None) == "report"
    assert gui._sanitize_filename("   ") == "report"
    assert gui._sanitize_filename("***") == "report"


def test_sanitize_filename_trims_underscores(gui):
    assert gui._sanitize_filename("  spaced name  ") == "spaced_name"


@pytest.mark.parametrize(
    "filename,expected_type",
    [
        ("E9 Some Employee.pdf", "E9"),
        ("ΠΡΟΣΛΗΨΗ Employee.pdf", "ΠΡΟΣΛΗΨΗ"),
        ("entypo3_form.pdf", "ΕΝΤΥΠΟ3"),
        ("govgr_document_1234.pdf", "GOVGR"),
        ("contract_signed.pdf", "SIGNED"),
        ("ypograf_final.pdf", "ΥΠΟΓΡΑΦΕΣ"),
        ("random_document.pdf", "Signed"),
    ],
)
def test_classify_signed_doc_types(gui, filename, expected_type):
    doc_type, _ = gui._classify_signed_doc(filename)
    assert doc_type == expected_type


def test_classify_signed_doc_extracts_employee_name(gui):
    _, employee = gui._classify_signed_doc("/tmp/E9 Some Employee.pdf")
    assert employee == "Some Employee"


def test_classify_signed_doc_strips_copy_suffix(gui):
    _, employee = gui._classify_signed_doc("E9 Some Employee copy.pdf")
    assert employee == "Some Employee"


def test_classify_signed_doc_without_employee(gui):
    doc_type, employee = gui._classify_signed_doc("govgr_document_1.pdf")
    assert doc_type == "GOVGR"
    assert employee is None


def test_classify_signed_doc_ignores_directory_and_extension(gui):
    """Only the filename stem is inspected, not the enclosing path."""
    doc_type, _ = gui._classify_signed_doc("/signed/E9/plain_name.pdf")
    assert doc_type == "Signed"


# --------------------------------------------------------------------------
# Export helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column", ["payment_date", "paid_date", "entry_id", "employee_code", "full_name"]
)
def test_should_total_column_skips_non_numeric(gui, column):
    assert gui._should_total_column(column) is False


@pytest.mark.parametrize("column", ["net_pay", "total_earnings", "efka_employer"])
def test_should_total_column_accepts_amounts(gui, column):
    assert gui._should_total_column(column) is True


def test_should_total_column_skips_basic_salary_explicitly(gui):
    """basic_salary is an explicit skip token even though it is an amount."""
    assert gui._should_total_column("basic_salary") is False


def test_get_grid_value_reads_by_column_name(gui):
    columns = ["entry_id", "net_pay", "paid_status"]
    values = ("abc-123", "1500.00", "Yes")
    assert gui._get_grid_value(values, columns, "net_pay") == "1500.00"


def test_get_grid_value_handles_missing_and_short_rows(gui):
    columns = ["entry_id", "net_pay"]
    assert gui._get_grid_value(("a", "b"), columns, "nope") is None
    assert gui._get_grid_value(("a",), columns, "net_pay") is None
    assert gui._get_grid_value(("a",), [], "net_pay") is None


def test_get_label_from_event_maps_x_to_label(gui):
    labels = ["Jan", "Feb", "Mar"]
    assert gui._get_label_from_event(labels, 1.4) == "Feb"
    assert gui._get_label_from_event(labels, 0) == "Jan"


def test_get_label_from_event_guards_out_of_range(gui):
    labels = ["Jan", "Feb"]
    assert gui._get_label_from_event(labels, None) is None
    assert gui._get_label_from_event(labels, -1) is None
    assert gui._get_label_from_event(labels, 5) is None
    assert gui._get_label_from_event([], 0) is None


def test_filter_view_columns_keeps_requested_order(gui):
    columns = ["a", "b", "c"]
    rows = [(1, 2, 3), (4, 5, 6)]
    kept_cols, kept_rows = gui._filter_view_columns(columns, rows, ["c", "a"])
    assert kept_cols == ["c", "a"]
    assert kept_rows == [(3, 1), (6, 4)]


def test_filter_view_columns_ignores_unknown_names(gui):
    columns = ["a", "b"]
    rows = [(1, 2)]
    kept_cols, kept_rows = gui._filter_view_columns(columns, rows, ["b", "zzz"])
    assert kept_cols == ["b"]
    assert kept_rows == [(2,)]


def test_filter_view_columns_passes_through_empty(gui):
    assert gui._filter_view_columns([], [], ["a"]) == ([], [])


def test_build_export_totals_sums_numeric_columns(gui):
    columns = ["employee_code", "net_pay", "total_earnings"]
    rows = [("EMP-1", "€ 1,000.00", "1200"), ("EMP-2", "€ 500.50", "600")]
    totals = gui._build_export_totals(columns, rows)
    assert totals[0] == "TOTAL"
    assert totals[1] == "1500.50"
    assert totals[2] == "1800.00"


def test_build_export_totals_ignores_unparseable_cells(gui):
    columns = ["employee_code", "net_pay"]
    rows = [("EMP-1", "€ 100.00"), ("EMP-2", "—"), ("EMP-3", "n/a")]
    totals = gui._build_export_totals(columns, rows)
    assert totals[1] == "100.00"


def test_build_export_totals_returns_none_without_data(gui):
    assert gui._build_export_totals(["net_pay"], []) is None
    assert gui._build_export_totals([], [("x",)]) is None


def test_build_export_totals_returns_none_when_nothing_is_totalable(gui):
    columns = ["employee_code", "payment_date"]
    rows = [("EMP-1", "2026-01-01")]
    assert gui._build_export_totals(columns, rows) is None


def test_build_export_totals_label_is_overwritten_when_first_column_totals(gui):
    """The TOTAL label lands in column 0, then a total may overwrite it."""
    columns = ["net_pay", "employee_code"]
    rows = [("100.00", "EMP-1")]
    totals = gui._build_export_totals(columns, rows)
    assert totals[0] == "100.00"  # not "TOTAL"


def test_wrap_export_table_wraps_long_cells(gui):
    columns = ["employee_name", "note"]
    long_value = "Employee " + "Name " * 60  # comfortably past the 140-char budget
    rows = [(long_value, "short")]
    headers, wrapped_rows, widths = gui._wrap_export_table(columns, rows)

    assert len(headers) == 2
    assert len(wrapped_rows) == 1
    # Widths are proportions of the table and sum to 1.
    assert sum(widths) == pytest.approx(1.0)
    assert "\n" in wrapped_rows[0][0]


def test_wrap_export_table_leaves_short_cells_alone(gui):
    headers, rows, _ = gui._wrap_export_table(["a", "b"], [("short", "also short")])
    assert "\n" not in rows[0][0]
    assert "\n" not in rows[0][1]


def test_wrap_export_table_handles_no_rows(gui):
    headers, rows, widths = gui._wrap_export_table(["a", "b"], [])
    assert headers == ["a", "b"]
    assert rows == []
    assert sum(widths) == pytest.approx(1.0)


def test_wrap_export_table_tolerates_ragged_rows(gui):
    """A row shorter than the header list must not raise."""
    headers, rows, _ = gui._wrap_export_table(["a", "b", "c"], [("only-one",)])
    assert len(headers) == 3
    assert len(rows) == 1
