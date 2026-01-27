#!/usr/bin/env python3
"""Database storage utilities for Payroll Processor (PostgreSQL)."""

import json
import os
import datetime
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

try:
    import psycopg2
    from psycopg2 import extras
except ImportError:  # pragma: no cover - handled at runtime
    psycopg2 = None
    extras = None

CONFIG_DIR = Path.home() / ".payroll_processor"
CONFIG_PATH = CONFIG_DIR / "db_config.json"
PREFS_PATH = CONFIG_DIR / "ui_prefs.json"

DEFAULT_CONFIG: Dict[str, object] = {
    "enabled": False,
    "host": "localhost",
    "port": 5432,
    "database": "payroll",
    "user": "postgres",
    "password": "",
    "sslmode": "prefer",
    "role": "editor",
    "audit_user": "",
}


def load_db_config() -> Dict[str, object]:
    """Load database config from disk, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text())
            if isinstance(stored, dict):
                config.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_db_config(config: Dict[str, object]) -> None:
    """Persist database config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True))


def load_ui_prefs() -> Dict[str, object]:
    """Load UI preferences from disk."""
    if PREFS_PATH.exists():
        try:
            stored = json.loads(PREFS_PATH.read_text())
            if isinstance(stored, dict):
                return stored
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_ui_prefs(prefs: Dict[str, object]) -> None:
    """Persist UI preferences to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(json.dumps(prefs, indent=2, sort_keys=True))


def _require_psycopg2() -> None:
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for database storage. Install psycopg2-binary.")


def get_connection(config: Dict[str, object]):
    """Create a psycopg2 connection using the provided config."""
    _require_psycopg2()
    return psycopg2.connect(
        host=config.get("host"),
        port=config.get("port"),
        dbname=config.get("database"),
        user=config.get("user"),
        password=config.get("password"),
        sslmode=config.get("sslmode"),
    )


def test_connection(config: Dict[str, object]) -> Tuple[bool, str]:
    """Attempt a simple connection check."""
    try:
        with get_connection(config) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return True, "Connection successful."
    except Exception as exc:
        return False, f"Connection failed: {exc}"


def _append_date_range(conditions, params, field, start_date=None, end_date=None):
    if start_date is not None:
        conditions.append(f"{field} >= %s")
        params.append(start_date)
    if end_date is not None:
        conditions.append(f"{field} <= %s")
        params.append(end_date)


def _prepare_staging_rows(df: pd.DataFrame) -> Tuple[list, list]:
    """Normalize DataFrame columns and return rows ready for insertion."""
    data = df.copy()

    if "Date" in data.columns:
        parsed_dates = pd.to_datetime(data["Date"], dayfirst=True, errors="coerce")
        data["date"] = parsed_dates.dt.date
        data["date"] = data["date"].where(pd.notna(data["date"]), None)
    else:
        data["date"] = None

    rename_map = {
        "EmployeeCode": "employee_code",
        "EmployeeName": "employee_name",
        "DocumentType": "document_type",
        "BasicSalary": "basic_salary",
        "TotalEarnings": "total_earnings",
        "NetPay": "net_pay",
        "EFKAEmployee": "efka_employee",
        "EFKAEmployer": "efka_employer",
        "TEKAEmployee": "teka_employee",
        "TEKAEmployer": "teka_employer",
        "SourcePDF": "source_pdf",
        "SourceArchive": "source_archive",
    }

    for source, target in rename_map.items():
        if source in data.columns:
            data[target] = data[source]
        elif target not in data.columns:
            data[target] = None

    numeric_cols = [
        "basic_salary",
        "total_earnings",
        "net_pay",
        "efka_employee",
        "efka_employer",
        "teka_employee",
        "teka_employer",
    ]
    for col in numeric_cols:
        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0)

    data["document_type"] = data["document_type"].fillna("").astype(str)
    data["employee_code"] = data["employee_code"].fillna("").astype(str)
    data["employee_name"] = data["employee_name"].fillna("").astype(str)
    data["source_pdf"] = data["source_pdf"].fillna("").astype(str)
    data["source_archive"] = data["source_archive"].fillna("").astype(str)

    columns = [
        "employee_code",
        "employee_name",
        "document_type",
        "basic_salary",
        "total_earnings",
        "net_pay",
        "date",
        "efka_employee",
        "efka_employer",
        "teka_employee",
        "teka_employer",
        "source_pdf",
        "source_archive",
    ]

    rows = list(data[columns].itertuples(index=False, name=None))
    return columns, rows


def store_payroll_data(df: pd.DataFrame, config: Dict[str, object]) -> int:
    """Insert payroll data into the normalized schema via a staging table."""
    if df.empty:
        return 0

    _require_psycopg2()
    columns, rows = _prepare_staging_rows(df)

    staging_sql = """
        CREATE TEMP TABLE staging_payroll (
            employee_code   TEXT,
            employee_name   TEXT,
            document_type   TEXT,
            basic_salary    NUMERIC,
            total_earnings  NUMERIC,
            net_pay         NUMERIC,
            date            DATE,
            efka_employee   NUMERIC,
            efka_employer   NUMERIC,
            teka_employee   NUMERIC,
            teka_employer   NUMERIC,
            source_pdf      TEXT,
            source_archive  TEXT
        );
    """

    import_sql = """
        INSERT INTO employees (employee_code, full_name, active)
        SELECT DISTINCT sp.employee_code,
               sp.employee_name,
               TRUE
        FROM staging_payroll sp
        ON CONFLICT (employee_code) DO UPDATE
          SET full_name = EXCLUDED.full_name;

        INSERT INTO payroll_runs (year, month, run_date, source_archive)
        SELECT
            EXTRACT(YEAR FROM sp.date)::INT    AS year,
            EXTRACT(MONTH FROM sp.date)::INT   AS month,
            MIN(sp.date)                       AS run_date,
            sp.source_archive
        FROM staging_payroll sp
        GROUP BY
            EXTRACT(YEAR FROM sp.date),
            EXTRACT(MONTH FROM sp.date),
            sp.source_archive
        ON CONFLICT (year, month, source_archive) DO NOTHING;

        WITH row_data AS (
            SELECT
                sp.*,
                e.id AS employee_id,
                pr.id AS payroll_run_id,
                COALESCE(sp.basic_salary, 0) AS basic_salary_norm,
                COALESCE(sp.total_earnings, 0) AS total_earnings_norm,
                COALESCE(sp.net_pay, 0) AS net_pay_norm,
                CASE
                    WHEN LOWER(BTRIM(sp.document_type)) IN ('salary', 'payslip', 'unknown') THEN 'salary'
                    WHEN LOWER(BTRIM(sp.document_type)) IN ('bonus') THEN 'bonus'
                    WHEN LOWER(BTRIM(sp.document_type)) IN ('vacationallowance', 'vacation_allowance', 'vacation allowance') THEN 'vacation_allowance'
                    WHEN LOWER(BTRIM(sp.document_type)) IN ('unusedleavecompensation', 'unused_leave_compensation', 'unused leave compensation') THEN 'unused_leave_compensation'
                    ELSE 'other'
                END::payroll_document_type AS document_type_norm
            FROM staging_payroll sp
            JOIN employees e ON e.employee_code = sp.employee_code
            JOIN payroll_runs pr
              ON pr.year = EXTRACT(YEAR FROM sp.date)
             AND pr.month = EXTRACT(MONTH FROM sp.date)
             AND pr.source_archive = sp.source_archive
        ),
        inserted AS (
            INSERT INTO payroll_entries (
                payroll_run_id,
                employee_id,
                document_type,
                payment_date,
                basic_salary,
                total_earnings,
                net_pay
            )
            SELECT
                rd.payroll_run_id,
                rd.employee_id,
                rd.document_type_norm,
                rd.date,
                rd.basic_salary_norm,
                rd.total_earnings_norm,
                rd.net_pay_norm
            FROM row_data rd
            WHERE NOT EXISTS (
                SELECT 1
                FROM payroll_entries pe2
                JOIN documents d2 ON d2.payroll_entry_id = pe2.id
                WHERE pe2.payroll_run_id = rd.payroll_run_id
                  AND pe2.employee_id = rd.employee_id
                  AND pe2.document_type = rd.document_type_norm
                  AND pe2.payment_date = rd.date
                  AND pe2.basic_salary = rd.basic_salary_norm
                  AND pe2.total_earnings = rd.total_earnings_norm
                  AND pe2.net_pay = rd.net_pay_norm
                  AND d2.source_pdf = rd.source_pdf
            )
            RETURNING
                id,
                payroll_run_id,
                employee_id,
                document_type,
                payment_date,
                basic_salary,
                total_earnings,
                net_pay
        ),
        insurance_insert AS (
            INSERT INTO insurance_contributions (
                payroll_entry_id,
                efka_employee,
                efka_employer,
                teka_employee,
                teka_employer
            )
            SELECT
                i.id AS payroll_entry_id,
                COALESCE(rd.efka_employee, 0),
                COALESCE(rd.efka_employer, 0),
                COALESCE(rd.teka_employee, 0),
                COALESCE(rd.teka_employer, 0)
            FROM inserted i
            JOIN row_data rd
              ON rd.payroll_run_id = i.payroll_run_id
             AND rd.employee_id = i.employee_id
             AND rd.document_type_norm = i.document_type
             AND rd.date = i.payment_date
             AND rd.basic_salary_norm = i.basic_salary
             AND rd.total_earnings_norm = i.total_earnings
             AND rd.net_pay_norm = i.net_pay
            ON CONFLICT (payroll_entry_id) DO NOTHING
            RETURNING payroll_entry_id
        )
        INSERT INTO documents (
            payroll_entry_id,
            source_pdf,
            checksum,
            imported_at
        )
        SELECT
            i.id AS payroll_entry_id,
            rd.source_pdf,
            NULL,
            NOW()
        FROM inserted i
        JOIN row_data rd
          ON rd.payroll_run_id = i.payroll_run_id
         AND rd.employee_id = i.employee_id
         AND rd.document_type_norm = i.document_type
         AND rd.date = i.payment_date
         AND rd.basic_salary_norm = i.basic_salary
         AND rd.total_earnings_norm = i.total_earnings
         AND rd.net_pay_norm = i.net_pay
        ON CONFLICT (payroll_entry_id) DO NOTHING;
    """

    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(staging_sql)
            extras.execute_values(
                cur,
                f"INSERT INTO staging_payroll ({', '.join(columns)}) VALUES %s",
                rows,
                page_size=500,
            )
            cur.execute(import_sql)
    return len(rows)


ALLOWED_VIEWS = {
    "v_monthly_payroll_summary",
    "v_payroll_costs",
}


def fetch_view_rows(config: Dict[str, object], view_name: str, limit: int = 500):
    """Fetch rows from a whitelisted view for display."""
    _require_psycopg2()
    if view_name not in ALLOWED_VIEWS:
        raise ValueError(f"View {view_name} is not allowed.")
    if limit is None or limit <= 0:
        limit_clause = ""
    else:
        limit_clause = f" LIMIT {int(limit)}"
    query = f"SELECT * FROM {view_name}{limit_clause};"
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows


def fetch_monthly_summary(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return monthly summary rows ordered by year/month/employee."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT
            EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
            EXTRACT(MONTH FROM pe.payment_date)::INT AS month,
            e.full_name AS employee_name,
            SUM(pe.net_pay) AS total_net_pay,
            SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance,
            SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY year, month, employee_name
        ORDER BY year, month, employee_name;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_employer_costs_by_employee(
    config: Dict[str, object],
    limit: int = 20,
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return total employer cost per employee."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    params.append(limit)
    query = f"""
        SELECT
            e.full_name AS employee_name,
            SUM(pe.net_pay + ic.efka_employer + ic.teka_employer) AS employer_cost
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY e.full_name
        ORDER BY employer_cost DESC
        LIMIT %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_document_type_breakdown(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return monthly net pay totals by document category."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT
            EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
            EXTRACT(MONTH FROM pe.payment_date)::INT AS month,
            CASE
                WHEN pe.document_type = 'salary' THEN 'Salary'
                WHEN pe.document_type = 'bonus' THEN 'Bonus'
                WHEN pe.document_type IN ('vacation_allowance', 'unused_leave_compensation') THEN 'Allowance'
                ELSE 'Other'
            END AS category,
            SUM(pe.net_pay) AS total_net_pay
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY year, month, category
        ORDER BY year, month, category;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_kpi_totals(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    employee_code: str = None,
    employee_name: str = None,
    search: str = None,
):
    """Return KPI totals scoped by optional date, document type, and employee."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if employee_code:
        conditions.append("e.employee_code = %s")
        params.append(employee_code)
    elif employee_name:
        conditions.append("e.full_name = %s")
        params.append(employee_name)
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT
            COALESCE(SUM(pe.net_pay), 0) AS total_net_pay,
            COALESCE(SUM(ic.efka_employee + ic.teka_employee), 0) AS employee_insurance,
            COALESCE(SUM(ic.efka_employer + ic.teka_employer), 0) AS employer_insurance
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause};
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone() or (0, 0, 0)
    return tuple(float(value or 0) for value in row)

def fetch_payment_heatmap(
    config: Dict[str, object],
    year: int,
    month: int,
    limit: int = 20,
    document_type: str = None,
    search: str = None,
):
    """Return net pay by employee and payment date for heatmap display."""
    _require_psycopg2()
    where_extra = ""
    params = [year, month]
    if document_type:
        where_extra = " AND pe.document_type = %s"
        params.append(document_type)
    if search:
        where_extra += " AND (e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        params.extend([f"%{search}%"] * 4)
    params.append(limit)
    query = f"""
        WITH filtered AS (
            SELECT
                pe.employee_id,
                e.full_name AS employee_name,
                pe.payment_date,
                pe.net_pay
            FROM payroll_entries pe
            JOIN employees e ON e.id = pe.employee_id
            LEFT JOIN documents d ON d.payroll_entry_id = pe.id
            WHERE EXTRACT(YEAR FROM pe.payment_date) = %s
              AND EXTRACT(MONTH FROM pe.payment_date) = %s
              {where_extra}
        ),
        top_employees AS (
            SELECT employee_id, employee_name, SUM(net_pay) AS total_net
            FROM filtered
            GROUP BY employee_id, employee_name
            ORDER BY total_net DESC
            LIMIT %s
        )
        SELECT
            f.employee_name,
            f.payment_date,
            SUM(f.net_pay) AS total_net_pay
        FROM filtered f
        JOIN top_employees t ON t.employee_id = f.employee_id
        GROUP BY f.employee_name, f.payment_date
        ORDER BY f.employee_name, f.payment_date;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_available_years(config: Dict[str, object]):
    """Return distinct years present in payroll entries."""
    _require_psycopg2()
    query = """
        SELECT DISTINCT EXTRACT(YEAR FROM payment_date)::INT AS year
        FROM payroll_entries
        ORDER BY year;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return [row[0] for row in cur.fetchall()]


def fetch_available_months(config: Dict[str, object], year: int):
    """Return distinct months present in a year."""
    _require_psycopg2()
    query = """
        SELECT DISTINCT EXTRACT(MONTH FROM payment_date)::INT AS month
        FROM payroll_entries
        WHERE EXTRACT(YEAR FROM payment_date) = %s
        ORDER BY month;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (year,))
            return [row[0] for row in cur.fetchall()]


def fetch_payroll_entries(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
    limit: int = 500,
    offset: int = 0,
):
    """Return payroll entries for the analytics data grid."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if search:
        conditions.append("(e.full_name ILIKE %s OR d.source_pdf ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    params.extend([limit, offset])
    query = f"""
        SELECT
            pe.id AS entry_id,
            e.employee_code,
            e.full_name AS employee_name,
            pe.document_type,
            pe.payment_date,
            pe.paid_status,
            pe.actual_payment_date,
            pe.basic_salary,
            pe.total_earnings,
            pe.net_pay,
            d.source_pdf,
            pr.source_archive
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN documents d ON d.payroll_entry_id = pe.id
        JOIN payroll_runs pr ON pr.id = pe.payroll_run_id
        {where_clause}
        ORDER BY pe.payment_date DESC, e.full_name
        LIMIT %s
        OFFSET %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows


def update_payroll_entry(config: Dict[str, object], entry_id, field: str, value):
    """Update a single editable payroll entry field."""
    _require_psycopg2()
    field_map = {
        "document_type": "document_type",
        "payment_date": "payment_date",
        "paid_status": "paid_status",
        "actual_payment_date": "actual_payment_date",
        "basic_salary": "basic_salary",
        "total_earnings": "total_earnings",
        "net_pay": "net_pay",
    }
    column = field_map.get(field)
    if not column:
        raise ValueError(f"Field {field} is not editable.")
    query = f"UPDATE payroll_entries SET {column} = %s WHERE id = %s;"
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (value, entry_id))
        conn.commit()


def append_audit_log(config: Dict[str, object], entry_id: int, field: str, old_value, new_value):
    """Append a local audit log entry for edits."""
    user = str(config.get("audit_user") or os.environ.get("USER") or "unknown")
    if user == "unknown":
        try:
            user = os.getlogin()
        except OSError:
            user = "unknown"
    record = {
        "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        "entry_id": entry_id,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "user": user,
    }
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = CONFIG_DIR / "audit_log.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def delete_payroll_entries(config: Dict[str, object], entry_ids: list) -> int:
    """Delete payroll entries by id (cascades to related records)."""
    _require_psycopg2()
    if not entry_ids:
        return 0
    placeholders = ", ".join(["%s"] * len(entry_ids))
    query = f"DELETE FROM payroll_entries WHERE id IN ({placeholders});"
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, entry_ids)
            deleted = cur.rowcount or 0
    return deleted


def fetch_payroll_entry_count(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
):
    """Return total payroll entry count for pagination."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT COUNT(*)
        FROM payroll_entries pe
        {where_clause};
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return int(cur.fetchone()[0])


def fetch_employee_entries(
    config: Dict[str, object],
    employee_code: str = None,
    employee_name: str = None,
    start_date=None,
    end_date=None,
    document_type: str = None,
    limit: int = 500,
):
    """Return detailed entries for a specific employee."""
    _require_psycopg2()
    conditions = []
    params = []
    if employee_code:
        conditions.append("e.employee_code = %s")
        params.append(employee_code)
    if employee_name and not employee_code:
        conditions.append("e.full_name = %s")
        params.append(employee_name)
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    params.append(limit)
    query = f"""
        SELECT
            pe.payment_date,
            pe.paid_status,
            pe.actual_payment_date,
            pe.document_type,
            pe.basic_salary,
            pe.total_earnings,
            pe.net_pay,
            d.source_pdf,
            pr.source_archive
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN documents d ON d.payroll_entry_id = pe.id
        JOIN payroll_runs pr ON pr.id = pe.payroll_run_id
        {where_clause}
        ORDER BY pe.payment_date DESC
        LIMIT %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows


def fetch_dashboard_metrics(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return high-level KPI metrics for the dashboard."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT
            COUNT(DISTINCT pe.employee_id) AS employee_count,
            COUNT(*) AS entry_count,
            SUM(pe.net_pay) AS total_net_pay,
            SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance,
            SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance
        FROM payroll_entries pe
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause};
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone() or (0, 0, 0, 0, 0)
    return {
        "employee_count": row[0] or 0,
        "entry_count": row[1] or 0,
        "total_net_pay": float(row[2] or 0),
        "employee_insurance": float(row[3] or 0),
        "employer_insurance": float(row[4] or 0),
    }


def fetch_unpaid_amount(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
):
    """Return total net pay for unpaid entries in a date window."""
    _require_psycopg2()
    conditions = ["(pe.paid_status IS NULL OR pe.paid_status = FALSE)"]
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    where_clause = f"WHERE {' AND '.join(conditions)}"
    query = f"""
        SELECT COALESCE(SUM(pe.net_pay), 0)
        FROM payroll_entries pe
        {where_clause};
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
    return float(row[0] or 0)


def fetch_anomaly_entries(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
    limit: int = 20,
):
    """Return alert-style anomalies for dashboard attention."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    base_params = list(params)
    params = base_params + base_params + [limit]
    query = f"""
        WITH stats AS (
            SELECT
                AVG(pe.net_pay) AS avg_net_pay,
                AVG(ic.efka_employee + ic.teka_employee + ic.efka_employer + ic.teka_employer) AS avg_total_insurance
            FROM payroll_entries pe
            JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
            JOIN employees e ON e.id = pe.employee_id
            LEFT JOIN documents d ON d.payroll_entry_id = pe.id
            {where_clause}
        )
        SELECT
            CASE
                WHEN stats.avg_net_pay IS NOT NULL AND pe.net_pay >= stats.avg_net_pay * 1.5 THEN 'High Net Pay'
                WHEN stats.avg_total_insurance IS NOT NULL
                     AND (ic.efka_employee + ic.teka_employee + ic.efka_employer + ic.teka_employer) >= stats.avg_total_insurance * 1.5
                THEN 'High Insurance'
                ELSE 'Unusual Entry'
            END AS alert,
            e.full_name AS employee_name,
            pe.payment_date,
            pe.document_type,
            pe.net_pay,
            (ic.efka_employee + ic.teka_employee + ic.efka_employer + ic.teka_employer) AS total_insurance
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        CROSS JOIN stats
        {where_clause}
        AND (
            (stats.avg_net_pay IS NOT NULL AND pe.net_pay >= stats.avg_net_pay * 1.5)
            OR (
                stats.avg_total_insurance IS NOT NULL
                AND (ic.efka_employee + ic.teka_employee + ic.efka_employer + ic.teka_employer) >= stats.avg_total_insurance * 1.5
            )
        )
        ORDER BY pe.net_pay DESC
        LIMIT %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows


def fetch_recent_entries(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
    limit: int = 20,
):
    """Return most recent payroll entries for dashboard."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR pe.document_type::TEXT ILIKE %s OR d.source_pdf ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    query = f"""
        SELECT
            e.full_name AS employee_name,
            pe.payment_date,
            pe.document_type,
            pe.net_pay
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause}
        ORDER BY pe.payment_date DESC, e.full_name
        LIMIT %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows

def fetch_export_rows(
    config: Dict[str, object],
    entry_ids: list,
):
    """Return rows formatted for Excel export for selected entry ids."""
    _require_psycopg2()
    if not entry_ids:
        return [], []
    placeholders = ", ".join(["%s"] * len(entry_ids))
    query = f"""
        SELECT
            e.employee_code AS "EmployeeCode",
            e.full_name AS "EmployeeName",
            pe.document_type AS "DocumentType",
            pe.basic_salary AS "BasicSalary",
            pe.total_earnings AS "TotalEarnings",
            pe.net_pay AS "NetPay",
            pe.payment_date AS "Date",
            ic.efka_employee AS "EFKAEmployee",
            ic.efka_employer AS "EFKAEmployer",
            ic.teka_employee AS "TEKAEmployee",
            ic.teka_employer AS "TEKAEmployer",
            d.source_pdf AS "SourcePDF",
            pr.source_archive AS "SourceArchive"
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        LEFT JOIN payroll_runs pr ON pr.id = pe.payroll_run_id
        WHERE pe.id IN ({placeholders})
        ORDER BY pe.payment_date, e.full_name;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, entry_ids)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows

def fetch_monthly_employee_summary(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    limit: int = 500,
):
    """Return per-month, per-employee payment and insurance totals."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    query = f"""
        SELECT
            EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
            EXTRACT(MONTH FROM pe.payment_date)::INT AS month,
            e.employee_code,
            e.full_name AS employee_name,
            SUM(pe.net_pay) AS total_net_pay,
            SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance,
            SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance,
            SUM(ic.efka_employee + ic.teka_employee + ic.efka_employer + ic.teka_employer) AS total_insurance
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY year, month, e.employee_code, e.full_name
        ORDER BY year DESC, month DESC, e.full_name
        LIMIT %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows
