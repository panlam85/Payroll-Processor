# Contributing to Payroll Processor

A guide for anyone who wants to fork this, branch from it, or build something
of their own on top. It explains the conventions that are not obvious from the
code, and the traps that will bite you if you ignore them.

Engineer: **PanLam** · License: [MIT](LICENSE)

---

## 1. Get it running

```bash
git clone https://github.com/panlam85/PayrollProcessor.git
cd PayrollProcessor
brew install poppler          # provides pdftotext, pdfunite, pdfseparate
./run_dev.sh                  # creates .venv on first run, then launches the GUI
```

The first run installs dependencies into `versions/<active>/.venv` and takes a
minute. Later runs reuse it. `launch_gui.sh` is the same thing with less debug
output.

You do **not** need PostgreSQL to start. Without it the app still parses PDFs
and writes Excel reports; the Dashboard, Analytics, Insurance, Employees and
Database views need a database and will tell you so.

To use a database, create one with `create_database.sql`, then point the app at
it in **Settings → Database**. Migrations run automatically at startup.

---

## 2. The one convention that will confuse you

**This project keeps every release as a frozen directory under `versions/`.**

```
versions/v1.0/  v1.1/  …  v3.1.5/  v3.1.6/   ← each a complete copy of the app
```

Git history exists, but the `versions/` folders are the project's real record of
how it evolved. Consequences:

- **Only the active version is live.** Root scripts (`run_dev.sh`,
  `launch_gui.sh`, `payroll_cli.sh`, `create_simple_app.py`,
  `create_simple_installer.sh`) all delegate to it.
- **Do not edit older version directories.** They are history. Changing
  `versions/v3.1.2/` changes the record of what v3.1.2 was.
- **`AGENTS.md` is the source of truth** for which version is active.
  `bump_version.sh` reads it to decide what to copy.

Find the active version:

```bash
grep -m1 -o 'versions/v[0-9.]*' AGENTS.md
```

### Cutting a new version

```bash
./bump_version.sh v3.1.7
```

That copies the active tree and repoints `AGENTS.md`, the root wrappers,
`create_simple_app.py`, `pytest.ini`, `.coveragerc`, `README.md` and
`PROJECT_SUMMARY.md`. Add a `CHANGELOG.md` entry yourself — the script does not
write prose.

Bump when you ship something you want frozen. Ordinary work goes in the active
version directory on a branch; you do not need a new version per change.

> If you add a new top-level directory inside a version, the script picks it up
> automatically — it copies every real directory rather than a hard-coded list.
> That was a bug once: `tests_cli` was silently dropped on every bump, and
> because pytest ignores a missing testpath the only symptom was the suite
> quietly shrinking. If your test count drops after a bump, look here first.

---

## 3. Layout

```
versions/<active>/
├── src/
│   ├── payroll_gui.py            # GUI shell, views, menus, orchestration
│   ├── process_payroll.py        # PDF extraction and parsing
│   ├── db_storage.py             # schema, migrations, queries, backup/restore
│   ├── create_employee_reports.py# Excel workbooks
│   ├── payroll_cli.py            # headless entry point + run ledger
│   └── theme_config.py           # shared UI tokens
├── tests/                        # unit tests
├── tests_cli/                    # CLI and run-ledger tests
├── scripts/                      # launchers and builders
├── assets/ resources/ docs/ tools/
```

### How data flows

```
ZIP/PDF
  └─ process_payroll.process_zip()
       ├─ parse_insurance_claim()    → EFKA/TEKA claims
       ├─ parse_transfer_receipt()   → payment receipts (IBAN, beneficiary)
       ├─ classify_document()        → Salary | Bonus | VacationAllowance | …
       ├─ parse_pdf()                → payroll entries
       ├─ archives source PDFs to    archive_root/YYYY/MM/Employee/
       └─ merges receipts into that month's payment PDFs
  └─ db_storage.store_payroll_data() / store_insurance_claims()
  └─ create_employee_reports.*       → summary + detail workbooks
```

Reports default to `~/Documents/Payroll Processor Reports`; per-employee reports
go to an `Employees Reports/` subfolder.

---

## 4. Tests

```bash
V=$(grep -m1 -o 'versions/v[0-9.]*' AGENTS.md)
PYTHONPATH=$V/src $V/.venv/bin/python -m pytest -q
PYTHONPATH=$V/src $V/.venv/bin/python -m pytest -q --cov --cov-config=.coveragerc
```

`PYTHONPATH` matters — the modules import each other by bare name
(`import db_storage`), so `src/` must be on the path.

The gate is 65%; the parsing, storage and CLI core sits around 94%.

### Writing tests without a database

There is no test database. Everything is mocked through fakes defined in
`tests/test_db_storage_full.py`, which other test modules import:

```python
from test_db_storage_full import ConnectionFactory, FakeCursor, _clear_caches

def test_something(monkeypatch):
    _clear_caches()                                    # column probes are cached
    cursor = FakeCursor(fetchall_sequence=[[(1, 2)]])  # queued results
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", ConnectionFactory([cursor]))

    db_storage.fetch_something(CONFIG)

    assert "WHERE" in cursor.queries[0]      # inspect generated SQL
    assert cursor.params[0] == [...]         # and bound parameters
```

`FakeCursor` takes `fetchall_sequence`, `fetchone_sequence`, `rowcount_sequence`
and `description_sequence`, each popped per call.

**Always `_clear_caches()` first.** `db_storage` caches which optional columns
exist (`_EMPLOYEE_COLUMN_CACHE`, `_SIGNED_COLUMN_CACHE`, and friends) keyed by
connection target. A stale cache makes tests pass or fail depending on order.

### Writing tests for the GUI

`payroll_gui.py` is excluded from the coverage gate — most of it is widget
construction that needs a display. Its logic is still testable, because many
methods declare `self` without using it:

```python
import matplotlib
matplotlib.use("Agg")          # before importing payroll_gui

from payroll_gui import PayrollProcessorGUI

@pytest.fixture
def gui():
    return PayrollProcessorGUI.__new__(PayrollProcessorGUI)   # no __init__

def test_formatter(gui):
    assert gui._format_currency(1234.5) == "€ 1,234.50"
```

`__new__` skips `__init__`, so no Tk root is created and no widgets are built,
but methods are properly bound. If a method needs one attribute, set it on the
instance (`gui.db_config = {"enabled": True}`) rather than constructing the app.

Pin `matplotlib` to `Agg` **before** the import — `payroll_gui` imports
`backend_tkagg` at module level.

### Make sure your tests actually bite

If a new test passes on the first run, prove it can fail. Break the code it
covers, confirm the failure, then restore:

```bash
# temporarily change `if document_type:` to `if False:` and re-run
```

This repo has already shipped a test suite that reported 0% coverage while
passing, and a bump script that silently dropped a test directory. Green is not
the same as correct.

---

## 5. Extending it

### Adding an analytics query

Put it in `db_storage.py`, following the existing shape:

```python
def fetch_my_metric(config, start_date=None, end_date=None,
                    document_type=None, search=None):
    """One line on what it returns, and any non-obvious choice."""
    _require_psycopg2()
    conditions, params = [], []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(conditions, params, search,
                              ["e.full_name", "e.employee_code"])
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""SELECT … {where_clause} …"""
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()
```

Accept `start_date`, `end_date`, `document_type` and `search` even if you do not
need them all — the global filter bar passes them to everything, and a query
that ignores them will silently disagree with the rest of the screen.

Guard every division with `NULLIF(x, 0)`. A month with no payroll is normal.

### Adding a chart

1. Add `("my_key", "My Chart Title")` to the tuple in `create_analytics_tab`.
2. Write `_plot_my_chart(self, rows)` using
   `self.analytics_charts["my_key"]["ax"]`. Clear the axis first and handle the
   empty case with `ax.text(0.5, 0.5, "No data", ha="center", va="center")`.
3. Fetch the rows in `refresh_analytics` and call your plot method there.

Canvases are redrawn in one pass at the end of `refresh_analytics`; do not call
`draw()` yourself.

### Adding a column to an existing table

Never assume a column exists. Users upgrade from old databases. Follow the
migration pattern:

```python
def migrate_my_column(config) -> bool:
    _require_psycopg2()
    try:
        with get_connection(config) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'payroll_entries';")
                columns = {row[0] for row in cur.fetchall()}
                if "my_column" in columns:
                    return False
                cur.execute("ALTER TABLE payroll_entries ADD COLUMN my_column TEXT;")
                conn.commit()
                return True
    except Exception:
        return False          # must never break startup
```

Call it alongside the others in `PayrollProcessorGUI.__init__`, and have readers
degrade gracefully when the column is absent — see `_signed_columns` and
`fetch_signed_status_summary`, which return an empty result rather than raising
on an un-migrated database.

### Adding a parser for a new document type

`process_payroll.py` tries parsers in order inside `process_zip`: insurance
claim, then transfer receipt, then payslip. Each returns falsy when the document
is not its kind. Add yours in the same style, and remember the file is Greek —
normalise accents before matching (`unicodedata.normalize("NFKD", …)`).

---

## 6. Branching and forking

Work on a branch off `main`, in the active version directory:

```bash
git checkout -b feature/my-thing
# edit versions/<active>/src/…
# add tests in versions/<active>/tests/
PYTHONPATH=$V/src $V/.venv/bin/python -m pytest -q
git commit
gh pr create --base main
```

Before opening a PR:

- The suite passes and the coverage gate is green.
- New behaviour has tests, and you have confirmed they can fail.
- `CHANGELOG.md` has an entry if you shipped something user-visible.
- You did not edit an older `versions/` directory.

**Forking for a different payroll system.** The parsing in
`process_payroll.py` is specific to Greek payslips — the document classifier,
the field labels, and the accent handling all assume it. The rest is generic:
`db_storage.py`, the report builders, the CLI and the whole GUI care about
entries, employees and amounts, not about language. Replacing `parse_pdf`,
`classify_document` and `parse_insurance_claim` is the bulk of porting it.

**Licensing.** MIT. Use it, change it, ship it commercially, keep your changes
closed if you like. Keep the copyright notice. Attribution beyond that is
appreciated but not required.

---

## 7. Things that will trip you up

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError: db_storage` | `PYTHONPATH` is not set to the active `src/` |
| Coverage reports 0% with tests passing | `.coveragerc` `source` points at the wrong path |
| Test count drops after `bump_version.sh` | a test directory was not carried forward |
| Tests pass alone, fail in a suite | a column cache was not cleared |
| `RuntimeError` about Tk / no display | `payroll_gui` imported without `matplotlib.use("Agg")` |
| Receipts not merging into monthly PDFs | poppler's `pdfunite` is not installed |
| Edits to the app do nothing | you edited a frozen version, not the active one |
| Greek names not matching | text not accent-normalised before comparison |
