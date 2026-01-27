#!/usr/bin/env python3
"""Database storage utilities for Payroll Processor (PostgreSQL)."""

import json
import os
import datetime
import shutil
from pathlib import Path
from typing import Dict, Tuple, Optional

import pandas as pd
import subprocess

try:
    import psycopg2
    from psycopg2 import extras
except ImportError:  # pragma: no cover - handled at runtime
    psycopg2 = None
    extras = None

CONFIG_DIR = Path.home() / ".payroll_processor"
CONFIG_PATH = CONFIG_DIR / "db_config.json"
PREFS_PATH = CONFIG_DIR / "ui_prefs.json"
_PAID_DATE_COLUMN_CACHE: Dict[Tuple[str, str, str, str], str] = {}
_INSURANCE_CLAIMS_COLUMN_CACHE: Dict[Tuple[str, str, str, str], Dict[str, bool]] = {}
_EMPLOYEE_COLUMN_CACHE: Dict[Tuple[str, str, str, str], Dict[str, bool]] = {}

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


def migrate_paid_date_column(config: Dict[str, object]) -> bool:
    """Rename actual_payment_date to paid_date when needed."""
    _require_psycopg2()
    try:
        with get_connection(config) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'payroll_entries';"
                )
                columns = {row[0] for row in cur.fetchall()}
                if "paid_date" in columns:
                    return False
                if "actual_payment_date" in columns:
                    cur.execute("ALTER TABLE payroll_entries RENAME COLUMN actual_payment_date TO paid_date;")
                    conn.commit()
                    return True
    except Exception:
        return False
    return False


def ensure_insurance_claims_table(config: Dict[str, object]) -> None:
    """Create insurance_claims table if it does not exist and add missing columns."""
    _require_psycopg2()
    create_sql = """
        CREATE TABLE IF NOT EXISTS insurance_claims (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_year INT NOT NULL,
            claim_month INT NOT NULL CHECK (claim_month BETWEEN 1 AND 12),
            submission_date DATE,
            total_earnings NUMERIC(12,2) DEFAULT 0,
            total_contributions NUMERIC(12,2) DEFAULT 0,
            tpte_code TEXT,
            source_pdf TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            UNIQUE (claim_year, claim_month, tpte_code, source_pdf)
        );
        CREATE INDEX IF NOT EXISTS idx_insurance_claims_period
            ON insurance_claims (claim_year, claim_month);
    """
    expected_columns = {
        "id",
        "claim_year",
        "claim_month",
        "submission_date",
        "total_earnings",
        "total_contributions",
        "tpte_code",
        "claim_type",
        "paid_status",
        "paid_date",
        "source_pdf",
        "created_at",
    }
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(create_sql)
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'insurance_claims';"
            )
            existing = {row[0] for row in cur.fetchall()}
            missing = expected_columns - existing
            for col in sorted(missing):
                if col == "claim_year":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN claim_year INT;")
                elif col == "claim_month":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN claim_month INT CHECK (claim_month BETWEEN 1 AND 12);")
                elif col == "submission_date":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN submission_date DATE;")
                elif col == "total_earnings":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN total_earnings NUMERIC(12,2) DEFAULT 0;")
                elif col == "total_contributions":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN total_contributions NUMERIC(12,2) DEFAULT 0;")
                elif col == "tpte_code":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN tpte_code TEXT;")
                elif col == "claim_type":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN claim_type TEXT DEFAULT 'EFKA';")
                elif col == "paid_status":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN paid_status BOOLEAN DEFAULT FALSE;")
                elif col == "paid_date":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN paid_date DATE;")
                elif col == "source_pdf":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN source_pdf TEXT;")
                elif col == "created_at":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT now();")
                elif col == "id":
                    cur.execute("ALTER TABLE insurance_claims ADD COLUMN id UUID DEFAULT gen_random_uuid();")
            if {"claim_year", "claim_month", "tpte_code", "source_pdf"}.issubset(existing):
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'insurance_claims_unique'
                              AND conrelid = 'insurance_claims'::regclass
                        ) THEN
                            ALTER TABLE insurance_claims
                                ADD CONSTRAINT insurance_claims_unique
                                UNIQUE (claim_year, claim_month, tpte_code, source_pdf);
                        END IF;
                    END $$;
                    """
                )
        conn.commit()


def ensure_employee_profile_columns(config: Dict[str, object]) -> None:
    """Add employee profile columns when missing."""
    _require_psycopg2()
    expected_columns = {
        "iban",
        "beneficiary_name",
        "first_worked_date",
        "last_paid_date",
        "pay_rate_monthly",
        "pay_rate_hourly",
        "pay_rate_daily",
        "pay_rate_double",
        "pay_rate_abroad",
        "pay_rate_abroad_double",
    }
    key = (
        str(config.get("host")),
        str(config.get("port")),
        str(config.get("database")),
        str(config.get("user")),
    )
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'employees';"
            )
            existing = {row[0] for row in cur.fetchall()}
            missing = expected_columns - existing
            for col in sorted(missing):
                if col == "iban":
                    cur.execute("ALTER TABLE employees ADD COLUMN iban TEXT;")
                elif col == "beneficiary_name":
                    cur.execute("ALTER TABLE employees ADD COLUMN beneficiary_name TEXT;")
                elif col == "first_worked_date":
                    cur.execute("ALTER TABLE employees ADD COLUMN first_worked_date DATE;")
                elif col == "last_paid_date":
                    cur.execute("ALTER TABLE employees ADD COLUMN last_paid_date DATE;")
                else:
                    cur.execute(f"ALTER TABLE employees ADD COLUMN {col} NUMERIC(12,2);")
        conn.commit()
    _EMPLOYEE_COLUMN_CACHE.pop(key, None)


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


def export_all_tables_to_csv(config: Dict[str, object], output_dir: str) -> None:
    """Export core tables to CSV files in the output directory."""
    _require_psycopg2()
    tables = [
        "employees",
        "payroll_runs",
        "payroll_entries",
        "insurance_contributions",
        "insurance_claims",
        "documents",
    ]
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            for table in tables:
                file_path = output_path / f"{table}.csv"
                with file_path.open("w", encoding="utf-8", newline="") as handle:
                    cur.copy_expert(f"COPY {table} TO STDOUT WITH CSV HEADER", handle)


def _find_pg_tool(tool_name: str) -> Optional[str]:
    """Return a pg tool path from PATH or common macOS install locations."""
    tool_path = shutil.which(tool_name)
    if tool_path:
        return tool_path
    candidates = []
    candidates.extend(Path("/Applications/Postgres.app/Contents/Versions").glob("*/bin"))
    candidates.extend(Path("/Library/PostgreSQL").glob("*/bin"))
    for base in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidates.append(Path(base))
    for base in candidates:
        candidate = base / tool_name
        if candidate.exists():
            return str(candidate)
    return None


def backup_database(config: Dict[str, object], backup_path: str) -> None:
    """Create a pg_dump backup to the specified path."""
    _require_psycopg2()
    pg_dump_path = _find_pg_tool("pg_dump")
    if not pg_dump_path:
        raise RuntimeError(
            "pg_dump not found. Install PostgreSQL client tools "
            "or add pg_dump to your PATH (Postgres.app or Homebrew)."
        )
    env = os.environ.copy()
    if config.get("password"):
        env["PGPASSWORD"] = str(config.get("password"))
    args = [
        pg_dump_path,
        "--format=custom",
        "--file",
        backup_path,
        "--host",
        str(config.get("host") or "localhost"),
        "--port",
        str(config.get("port") or 5432),
        "--username",
        str(config.get("user") or "postgres"),
        str(config.get("database") or "payroll"),
    ]
    subprocess.check_call(args, env=env)


def restore_database(config: Dict[str, object], backup_path: str) -> None:
    """Restore a pg_dump custom format backup to the configured database."""
    _require_psycopg2()
    pg_restore_path = _find_pg_tool("pg_restore")
    if not pg_restore_path:
        raise RuntimeError(
            "pg_restore not found. Install PostgreSQL client tools "
            "or add pg_restore to your PATH (Postgres.app or Homebrew)."
        )
    env = os.environ.copy()
    if config.get("password"):
        env["PGPASSWORD"] = str(config.get("password"))
    args = [
        pg_restore_path,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--host",
        str(config.get("host") or "localhost"),
        "--port",
        str(config.get("port") or 5432),
        "--username",
        str(config.get("user") or "postgres"),
        "--dbname",
        str(config.get("database") or "payroll"),
        backup_path,
    ]
    subprocess.check_call(args, env=env)


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


def _append_claim_month_range(conditions, params, start_date=None, end_date=None, year_col="claim_year", month_col="claim_month"):
    if start_date is not None:
        conditions.append(f"({year_col} > %s OR ({year_col} = %s AND {month_col} >= %s))")
        params.extend([start_date.year, start_date.year, start_date.month])
    if end_date is not None:
        conditions.append(f"({year_col} < %s OR ({year_col} = %s AND {month_col} <= %s))")
        params.extend([end_date.year, end_date.year, end_date.month])


def _append_search_conditions(conditions, params, search, fields):
    if not search:
        return
    if isinstance(search, str):
        conditions.append("(" + " OR ".join([f"{field} ILIKE %s" for field in fields]) + ")")
        params.extend([f"%{search}%"] * len(fields))
        return
    if isinstance(search, list):
        parts = []
        for clause in search:
            if not clause:
                continue
            term = str(clause.get("term", "")).strip()
            if not term:
                continue
            op = str(clause.get("op", "AND")).upper()
            sub = "(" + " OR ".join([f"{field} ILIKE %s" for field in fields]) + ")"
            params.extend([f"%{term}%"] * len(fields))
            if op == "NOT":
                connector = "AND" if parts else ""
                expr = f"NOT {sub}"
            else:
                connector = op if parts else ""
                expr = sub
            if connector:
                parts.append(f"{connector} {expr}")
            else:
                parts.append(expr)
    if parts:
        conditions.append("(" + " ".join(parts) + ")")


def _insurance_claims_columns(config: Dict[str, object]) -> Dict[str, bool]:
    key = (
        str(config.get("host")),
        str(config.get("port")),
        str(config.get("database")),
        str(config.get("user")),
    )
    cached = _INSURANCE_CLAIMS_COLUMN_CACHE.get(key)
    if cached is not None:
        return cached
    columns: Dict[str, bool] = {}
    try:
        with get_connection(config) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'insurance_claims';"
                )
                columns = {row[0]: (row[1] == "YES") for row in cur.fetchall()}
    except Exception:
        columns = {}
    _INSURANCE_CLAIMS_COLUMN_CACHE[key] = columns
    return columns


def _employee_columns(config: Dict[str, object]) -> Dict[str, bool]:
    key = (
        str(config.get("host")),
        str(config.get("port")),
        str(config.get("database")),
        str(config.get("user")),
    )
    cached = _EMPLOYEE_COLUMN_CACHE.get(key)
    if cached is not None:
        return cached
    columns: Dict[str, bool] = {}
    try:
        with get_connection(config) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'employees';"
                )
                columns = {row[0]: True for row in cur.fetchall()}
    except Exception:
        columns = {}
    _EMPLOYEE_COLUMN_CACHE[key] = columns
    return columns


def _insurance_period_columns(config: Dict[str, object] = None) -> Tuple[str, str]:
    if config is None:
        return ("claim_year", "claim_month")
    columns = _insurance_claims_columns(config)
    if "period_year" in columns and "period_month" in columns:
        return ("period_year", "period_month")
    return ("claim_year", "claim_month")


def _prepare_staging_rows(df: pd.DataFrame) -> Tuple[list, list]:
    """Normalize DataFrame columns and return rows ready for insertion."""
    data = df.copy()

    if "Date" in data.columns:
        parsed_dates = pd.to_datetime(data["Date"], dayfirst=True, errors="coerce")
        data["date"] = parsed_dates.dt.date
        data["date"] = data["date"].apply(lambda value: value if pd.notna(value) else None)
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

    data["document_type"] = data["document_type"].fillna("").astype(str).str.strip()
    data["employee_code"] = data["employee_code"].fillna("").astype(str).str.strip()
    data["employee_name"] = data["employee_name"].fillna("").astype(str).str.strip()
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
        SELECT DISTINCT ON (sp.employee_code)
            sp.employee_code,
            sp.employee_name AS employee_name,
            TRUE
        FROM staging_payroll sp
        ORDER BY sp.employee_code, sp.employee_name DESC
        ON CONFLICT (employee_code) DO UPDATE
          SET full_name = EXCLUDED.full_name;

        WITH employee_dates AS (
            SELECT
                sp.employee_code,
                MIN(sp.date) AS first_date,
                MAX(sp.date) AS last_date
            FROM staging_payroll sp
            WHERE sp.date IS NOT NULL
            GROUP BY sp.employee_code
        )
        UPDATE employees e
        SET first_worked_date = COALESCE(LEAST(e.first_worked_date, ed.first_date), ed.first_date),
            last_paid_date = COALESCE(GREATEST(e.last_paid_date, ed.last_date), ed.last_date)
        FROM employee_dates ed
        WHERE e.employee_code = ed.employee_code;

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


def store_insurance_claims(claims: list, config: Dict[str, object]) -> int:
    """Insert insurance claim rows into insurance_claims."""
    if not claims:
        return 0
    _require_psycopg2()
    available = _insurance_claims_columns(config)
    columns = []
    if "claim_year" in available and "claim_month" in available:
        columns.extend(["claim_year", "claim_month"])
    if "period_year" in available and "period_month" in available:
        columns.extend(["period_year", "period_month"])
    for col in (
        "submission_date",
        "total_earnings",
        "total_contributions",
        "tpte_code",
        "claim_type",
        "paid_status",
        "paid_date",
        "source_pdf",
    ):
        if col in available:
            columns.append(col)
    rows = []
    for claim in claims:
        claim_year = claim.get("claim_year")
        claim_month = claim.get("claim_month")
        row = []
        for col in columns:
            if col in ("claim_year", "period_year"):
                row.append(claim_year)
            elif col in ("claim_month", "period_month"):
                row.append(claim_month)
            elif col == "submission_date":
                row.append(claim.get("submission_date"))
            elif col == "total_earnings":
                row.append(claim.get("total_earnings"))
            elif col == "total_contributions":
                row.append(claim.get("total_contributions"))
            elif col == "tpte_code":
                row.append(claim.get("tpte_code"))
            elif col == "claim_type":
                row.append(claim.get("claim_type") or "EFKA")
            elif col == "paid_status":
                row.append(claim.get("paid_status"))
            elif col == "paid_date":
                row.append(claim.get("paid_date"))
            elif col == "source_pdf":
                row.append(claim.get("source_pdf"))
        rows.append(tuple(row))

    insert_sql = f"""
        INSERT INTO insurance_claims ({', '.join(columns)})
        VALUES %s
        ON CONFLICT DO NOTHING;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            extras.execute_values(cur, insert_sql, rows, page_size=200)
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
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
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


def fetch_monthly_totals(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return per-month totals for net pay and insurance."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT
            EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
            EXTRACT(MONTH FROM pe.payment_date)::INT AS month,
            SUM(pe.net_pay) AS total_net_pay,
            SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance,
            SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance
        FROM payroll_entries pe
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY year, month
        ORDER BY year, month;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_insurance_comparison(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return per-month calculated vs official insurance totals."""
    _require_psycopg2()
    year_col, month_col = _insurance_period_columns(config)
    claim_columns = _insurance_claims_columns(config)
    claim_type_expr = "claim_type" if "claim_type" in claim_columns else "'EFKA'"
    paid_status_expr = "BOOL_AND(COALESCE(paid_status, FALSE))" if "paid_status" in claim_columns else "NULL::boolean"
    paid_date_expr = "MAX(paid_date)" if "paid_date" in claim_columns else "NULL::date"
    calc_conditions = []
    calc_params = []
    _append_date_range(calc_conditions, calc_params, "pe.payment_date", start_date, end_date)
    if document_type:
        calc_conditions.append("pe.document_type = %s")
        calc_params.append(document_type)
    _append_search_conditions(
        calc_conditions,
        calc_params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    calc_where = f"WHERE {' AND '.join(calc_conditions)}" if calc_conditions else "WHERE TRUE"

    claim_conditions = []
    claim_params = []
    _append_claim_month_range(claim_conditions, claim_params, start_date, end_date, year_col, month_col)
    _append_search_conditions(claim_conditions, claim_params, search, ["source_pdf", "tpte_code"])
    claim_where = f"WHERE {' AND '.join(claim_conditions)}" if claim_conditions else ""

    query = f"""
        WITH calc AS (
            SELECT
                EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
                EXTRACT(MONTH FROM pe.payment_date)::INT AS month,
                SUM(ic.efka_employee + ic.teka_employee + ic.efka_employer + ic.teka_employer) AS calculated_insurance,
                SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance,
                SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance
            FROM payroll_entries pe
            JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
            JOIN employees e ON e.id = pe.employee_id
            LEFT JOIN documents d ON d.payroll_entry_id = pe.id
            {calc_where}
            GROUP BY year, month
        ),
        claims AS (
            SELECT
                {year_col} AS year,
                {month_col} AS month,
                SUM(CASE WHEN COALESCE({claim_type_expr}, 'EFKA') = 'EFKA' THEN total_contributions ELSE 0 END) AS official_efka,
                SUM(CASE WHEN COALESCE({claim_type_expr}, 'EFKA') = 'TEKA' THEN total_contributions ELSE 0 END) AS official_teka,
                SUM(total_contributions) AS official_total,
                SUM(total_earnings) AS official_earnings,
                {paid_status_expr} AS paid_status,
                {paid_date_expr} AS paid_date,
                MAX(submission_date) AS latest_submission_date,
                STRING_AGG(DISTINCT tpte_code, ', ') AS tpte_codes,
                STRING_AGG(DISTINCT source_pdf, ', ') AS source_pdfs
            FROM insurance_claims
            {claim_where}
            GROUP BY {year_col}, {month_col}
        )
        SELECT
            COALESCE(calc.year, claims.year) AS year,
            COALESCE(calc.month, claims.month) AS month,
            calc.calculated_insurance,
            claims.official_efka,
            claims.official_teka,
            claims.official_total,
            COALESCE(claims.official_total, 0) - COALESCE(calc.calculated_insurance, 0) AS variance,
            calc.employee_insurance,
            calc.employer_insurance,
            claims.official_earnings,
            claims.paid_status,
            claims.paid_date,
            claims.latest_submission_date,
            claims.tpte_codes,
            claims.source_pdfs
        FROM calc
        FULL OUTER JOIN claims
            ON calc.year = claims.year AND calc.month = claims.month
        ORDER BY year, month;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, calc_params + claim_params)
            return cur.fetchall()


def fetch_employees_list(config: Dict[str, object], search: str = None):
    """Return basic employee profile details for listing."""
    _require_psycopg2()
    columns = _employee_columns(config)
    iban_col = "e.iban" if "iban" in columns else "NULL::text AS iban"
    beneficiary_col = "e.beneficiary_name" if "beneficiary_name" in columns else "NULL::text AS beneficiary_name"
    first_worked_col = "e.first_worked_date" if "first_worked_date" in columns else "NULL::date AS first_worked_date"
    last_paid_col = "e.last_paid_date" if "last_paid_date" in columns else "NULL::date AS last_paid_date"
    conditions = []
    params = []
    if search:
        conditions.append(
            "(e.full_name ILIKE %s OR e.employee_code ILIKE %s OR COALESCE(e.iban, '') ILIKE %s OR COALESCE(e.beneficiary_name, '') ILIKE %s)"
        )
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT
            e.employee_code,
            e.full_name,
            {iban_col},
            {beneficiary_col},
            {first_worked_col},
            {last_paid_col}
        FROM employees e
        {where_clause}
        ORDER BY e.full_name;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_employee_profile(config: Dict[str, object], employee_code: str):
    """Return extended employee profile details."""
    _require_psycopg2()
    if not employee_code:
        return None
    columns = _employee_columns(config)
    def col(name, fallback):
        return f"e.{name}" if name in columns else fallback
    query = f"""
        SELECT
            e.employee_code,
            e.full_name,
            {col('iban', 'NULL::text AS iban')},
            {col('beneficiary_name', 'NULL::text AS beneficiary_name')},
            {col('first_worked_date', 'NULL::date AS first_worked_date')},
            {col('last_paid_date', 'NULL::date AS last_paid_date')},
            {col('pay_rate_monthly', 'NULL::numeric AS pay_rate_monthly')},
            {col('pay_rate_hourly', 'NULL::numeric AS pay_rate_hourly')},
            {col('pay_rate_daily', 'NULL::numeric AS pay_rate_daily')},
            {col('pay_rate_double', 'NULL::numeric AS pay_rate_double')},
            {col('pay_rate_abroad', 'NULL::numeric AS pay_rate_abroad')},
            {col('pay_rate_abroad_double', 'NULL::numeric AS pay_rate_abroad_double')}
        FROM employees e
        WHERE e.employee_code = %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (employee_code,))
            return cur.fetchone()


def update_employee_profile(
    config: Dict[str, object],
    employee_code: str,
    iban: str = None,
    beneficiary_name: str = None,
    first_worked_date=None,
    last_paid_date=None,
    pay_rate_monthly=None,
    pay_rate_hourly=None,
    pay_rate_daily=None,
    pay_rate_double=None,
    pay_rate_abroad=None,
    pay_rate_abroad_double=None,
) -> None:
    """Update editable employee profile fields."""
    _require_psycopg2()
    if not employee_code:
        return
    columns = _employee_columns(config)
    updates = []
    params = []

    def add_update(column, value):
        if column in columns:
            updates.append(f"{column} = %s")
            params.append(value)

    add_update("iban", iban)
    add_update("beneficiary_name", beneficiary_name)
    add_update("first_worked_date", first_worked_date)
    add_update("last_paid_date", last_paid_date)
    add_update("pay_rate_monthly", pay_rate_monthly)
    add_update("pay_rate_hourly", pay_rate_hourly)
    add_update("pay_rate_daily", pay_rate_daily)
    add_update("pay_rate_double", pay_rate_double)
    add_update("pay_rate_abroad", pay_rate_abroad)
    add_update("pay_rate_abroad_double", pay_rate_abroad_double)

    if not updates:
        return
    query = f"UPDATE employees SET {', '.join(updates)} WHERE employee_code = %s;"
    params.append(employee_code)
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()


def update_employee_iban_by_name(config: Dict[str, object], employee_name: str, iban: str) -> int:
    """Update employee IBAN by fuzzy name match."""
    _require_psycopg2()
    if not employee_name or not iban:
        return 0
    columns = _employee_columns(config)
    if "iban" not in columns:
        return 0
    query = """
        UPDATE employees
        SET iban = %s
        WHERE full_name ILIKE %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (iban, f"%{employee_name}%"))
            return cur.rowcount or 0


def update_employee_bank_details_by_name(
    config: Dict[str, object],
    employee_name: str,
    iban: str = None,
    beneficiary_name: str = None,
) -> int:
    """Update employee IBAN and beneficiary name by fuzzy name match."""
    _require_psycopg2()
    if not employee_name or (iban is None and beneficiary_name is None):
        return 0
    columns = _employee_columns(config)
    updates = []
    params = []
    if iban is not None and "iban" in columns:
        updates.append("iban = %s")
        params.append(iban)
    if beneficiary_name is not None and "beneficiary_name" in columns:
        updates.append("beneficiary_name = %s")
        params.append(beneficiary_name)
    if not updates:
        return 0
    params.append(f"%{employee_name}%")
    query = f"UPDATE employees SET {', '.join(updates)} WHERE full_name ILIKE %s;"
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount or 0


def fetch_employee_monthly_totals(
    config: Dict[str, object],
    employee_code: str,
    start_date=None,
    end_date=None,
):
    """Return per-month totals for a specific employee."""
    _require_psycopg2()
    conditions = ["e.employee_code = %s"]
    params = [employee_code]
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    where_clause = f"WHERE {' AND '.join(conditions)}"
    query = f"""
        SELECT
            EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
            EXTRACT(MONTH FROM pe.payment_date)::INT AS month,
            SUM(pe.net_pay) AS total_net_pay,
            SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance,
            SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance,
            SUM(ic.efka_employee + ic.teka_employee + ic.efka_employer + ic.teka_employer) AS total_insurance
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY year, month
        ORDER BY year, month;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def update_insurance_claims_paid(
    config: Dict[str, object],
    year: int,
    month: int,
    paid_status: bool,
    paid_date=None,
) -> int:
    """Update paid status/date for insurance claims in a given year/month."""
    _require_psycopg2()
    year_col, month_col = _insurance_period_columns(config)
    if paid_status and paid_date is None:
        paid_date = datetime.date.today()
    if not paid_status:
        paid_date = None
    query = f"""
        UPDATE insurance_claims
        SET paid_status = %s,
            paid_date = %s
        WHERE {year_col} = %s
          AND {month_col} = %s;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (paid_status, paid_date, year, month))
            return cur.rowcount or 0


def fetch_insurance_claims_for_period(config: Dict[str, object], year: int, month: int):
    """Return insurance claim rows for a specific year/month."""
    _require_psycopg2()
    year_col, month_col = _insurance_period_columns(config)
    claim_columns = _insurance_claims_columns(config)
    claim_type_select = "claim_type" if "claim_type" in claim_columns else "'EFKA' AS claim_type"
    query = f"""
        SELECT
            id,
            {claim_type_select},
            total_contributions,
            total_earnings,
            submission_date
        FROM insurance_claims
        WHERE {year_col} = %s
          AND {month_col} = %s
        ORDER BY submission_date NULLS LAST, id;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (year, month))
            return cur.fetchall()


def update_insurance_claims_for_period(
    config: Dict[str, object],
    year: int,
    month: int,
    efka_total=None,
    teka_total=None,
    total_earnings=None,
    submission_date=None,
    tpte_code=None,
    paid_status=None,
    paid_date=None,
) -> int:
    """Update insurance claim values for a specific year/month."""
    _require_psycopg2()
    claim_columns = _insurance_claims_columns(config)
    has_claim_type = "claim_type" in claim_columns
    has_paid_status = "paid_status" in claim_columns
    has_paid_date = "paid_date" in claim_columns
    claims = fetch_insurance_claims_for_period(config, year, month)
    if not claims:
        return 0

    updates = []

    def scale_updates(rows, new_total):
        if new_total is None:
            return
        old_total = sum(float(row[2] or 0) for row in rows)
        if old_total:
            factor = float(new_total) / old_total
            for row in rows:
                new_val = round(float(row[2] or 0) * factor, 2)
                updates.append((new_val, row[0]))
        else:
            first = True
            for row in rows:
                new_val = float(new_total) if first else 0.0
                updates.append((new_val, row[0]))
                first = False

    if has_claim_type:
        efka_rows = [row for row in claims if (row[1] or "EFKA") == "EFKA"]
        teka_rows = [row for row in claims if (row[1] or "EFKA") == "TEKA"]
        scale_updates(efka_rows, efka_total)
        scale_updates(teka_rows, teka_total)
    else:
        scale_updates(claims, efka_total)

    with get_connection(config) as conn:
        with conn.cursor() as cur:
            if updates:
                extras.execute_batch(
                    cur,
                    "UPDATE insurance_claims SET total_contributions = %s WHERE id = %s;",
                    updates,
                    page_size=200,
                )
            if total_earnings is not None:
                cur.execute(
                    "UPDATE insurance_claims SET total_earnings = %s WHERE id = ANY(%s);",
                    (total_earnings, [row[0] for row in claims]),
                )
            if submission_date is not None:
                cur.execute(
                    "UPDATE insurance_claims SET submission_date = %s WHERE id = ANY(%s);",
                    (submission_date, [row[0] for row in claims]),
                )
            if tpte_code is not None:
                cur.execute(
                    "UPDATE insurance_claims SET tpte_code = %s WHERE id = ANY(%s);",
                    (tpte_code, [row[0] for row in claims]),
                )
            if paid_status is not None and has_paid_status:
                if paid_status and paid_date is None and has_paid_date:
                    paid_date = datetime.date.today()
                if not paid_status:
                    paid_date = None
                cur.execute(
                    "UPDATE insurance_claims SET paid_status = %s WHERE id = ANY(%s);",
                    (paid_status, [row[0] for row in claims]),
                )
                if has_paid_date:
                    cur.execute(
                        "UPDATE insurance_claims SET paid_date = %s WHERE id = ANY(%s);",
                        (paid_date, [row[0] for row in claims]),
                    )
        conn.commit()
    return len(claims)


def delete_insurance_claims_for_period(config: Dict[str, object], year: int, month: int) -> int:
    """Delete insurance claims for a specific year/month."""
    _require_psycopg2()
    year_col, month_col = _insurance_period_columns(config)
    query = f"DELETE FROM insurance_claims WHERE {year_col} = %s AND {month_col} = %s;"
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (year, month))
            return cur.rowcount or 0


def fetch_month_totals_by_year(
    config: Dict[str, object],
    month: int,
    document_type: str = None,
    search: str = None,
):
    """Return totals for a specific month across years."""
    _require_psycopg2()
    conditions = ["EXTRACT(MONTH FROM pe.payment_date) = %s"]
    params = [month]
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    where_clause = f"WHERE {' AND '.join(conditions)}"
    query = f"""
        SELECT
            EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
            SUM(pe.net_pay) AS total_net_pay,
            SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance,
            SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance
        FROM payroll_entries pe
        JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY year
        ORDER BY year;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_paid_unpaid_totals(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return total paid and unpaid net pay amounts."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT
            COALESCE(SUM(CASE WHEN pe.paid_status IS TRUE THEN pe.net_pay ELSE 0 END), 0) AS paid_total,
            COALESCE(SUM(CASE WHEN pe.paid_status IS NULL OR pe.paid_status = FALSE THEN pe.net_pay ELSE 0 END), 0) AS unpaid_total
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause};
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone() or (0, 0)
    return float(row[0] or 0), float(row[1] or 0)


def fetch_unpaid_aging_buckets(
    config: Dict[str, object],
    as_of: datetime.date,
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return unpaid totals split by aging buckets."""
    _require_psycopg2()
    conditions = ["(pe.paid_status IS NULL OR pe.paid_status = FALSE)"]
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    where_clause = f"WHERE {' AND '.join(conditions)}"
    query = f"""
        SELECT
            COALESCE(SUM(CASE WHEN (%s - pe.payment_date) BETWEEN 0 AND 30 THEN pe.net_pay ELSE 0 END), 0) AS bucket_0_30,
            COALESCE(SUM(CASE WHEN (%s - pe.payment_date) BETWEEN 31 AND 60 THEN pe.net_pay ELSE 0 END), 0) AS bucket_31_60,
            COALESCE(SUM(CASE WHEN (%s - pe.payment_date) BETWEEN 61 AND 90 THEN pe.net_pay ELSE 0 END), 0) AS bucket_61_90,
            COALESCE(SUM(CASE WHEN (%s - pe.payment_date) > 90 THEN pe.net_pay ELSE 0 END), 0) AS bucket_90_plus
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause};
    """
    params = [as_of, as_of, as_of, as_of] + params
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone() or (0, 0, 0, 0)
    return {
        "0_30": float(row[0] or 0),
        "31_60": float(row[1] or 0),
        "61_90": float(row[2] or 0),
        "90_plus": float(row[3] or 0),
    }


def fetch_avg_days_to_paid_by_month(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return average days to paid per month."""
    _require_psycopg2()
    paid_date_col = _paid_date_column(config)
    conditions = [f"pe.{paid_date_col} IS NOT NULL", "pe.paid_status IS TRUE"]
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    where_clause = f"WHERE {' AND '.join(conditions)}"
    query = f"""
        SELECT
            EXTRACT(YEAR FROM pe.payment_date)::INT AS year,
            EXTRACT(MONTH FROM pe.payment_date)::INT AS month,
            AVG(pe.{paid_date_col} - pe.payment_date) AS avg_days
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        {where_clause}
        GROUP BY year, month
        ORDER BY year, month;
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
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
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
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
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
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
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
    search_conditions = []
    search_params = []
    _append_search_conditions(
        search_conditions,
        search_params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    if search_conditions:
        where_extra += " AND " + " AND ".join(search_conditions)
        params.extend(search_params)
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
    paid_date_col = _paid_date_column(config)
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "d.source_pdf"],
    )
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
            pe.{paid_date_col} AS paid_date,
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


def fetch_duplicate_payroll_entries(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return payroll entries that share duplicate name/date/type/amount."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "d.source_pdf"],
    )
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        WITH dup_keys AS (
            SELECT
                e.full_name AS employee_name,
                pe.payment_date,
                pe.document_type,
                pe.net_pay
            FROM payroll_entries pe
            JOIN employees e ON e.id = pe.employee_id
            JOIN documents d ON d.payroll_entry_id = pe.id
            JOIN payroll_runs pr ON pr.id = pe.payroll_run_id
            {where_clause}
            GROUP BY e.full_name, pe.payment_date, pe.document_type, pe.net_pay
            HAVING COUNT(*) > 1
        )
        SELECT
            pe.id AS entry_id,
            e.employee_code,
            e.full_name AS employee_name,
            pe.document_type,
            pe.payment_date,
            pe.net_pay,
            d.source_pdf,
            pr.source_archive
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        JOIN documents d ON d.payroll_entry_id = pe.id
        JOIN payroll_runs pr ON pr.id = pe.payroll_run_id
        JOIN dup_keys dk
          ON dk.employee_name = e.full_name
         AND dk.payment_date = pe.payment_date
         AND dk.document_type = pe.document_type
         AND dk.net_pay = pe.net_pay
        {where_clause}
        ORDER BY e.full_name, pe.payment_date, pe.document_type, pe.net_pay, pe.id;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params + params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows


def update_payroll_entry(config: Dict[str, object], entry_id, field: str, value):
    """Update a single editable payroll entry field."""
    _require_psycopg2()
    paid_date_col = _paid_date_column(config)
    field_map = {
        "document_type": "document_type",
        "payment_date": "payment_date",
        "paid_status": "paid_status",
        "actual_payment_date": paid_date_col,
        "paid_date": paid_date_col,
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


def mark_paid_by_receipt(
    config: Dict[str, object],
    employee_name: str,
    amount: float,
    paid_date: datetime.date,
    iban: str = None,
    beneficiary_name: str = None,
    payroll_year: int = None,
    payroll_month: int = None,
) -> int:
    """Mark payroll entries as paid based on transfer receipt details."""
    _require_psycopg2()
    paid_date_col = _paid_date_column(config)
    employee_columns = _employee_columns(config)
    if not employee_name or paid_date is None:
        return 0
    updated = 0
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            target_year = payroll_year or paid_date.year
            target_month = payroll_month or paid_date.month
            if iban and "iban" in employee_columns:
                query = f"""
                    UPDATE payroll_entries pe
                    SET paid_status = TRUE,
                        {paid_date_col} = %s
                    FROM employees e
                    WHERE pe.employee_id = e.id
                      AND e.iban = %s
                      AND ABS(pe.net_pay - %s) <= 0.05
                      AND EXTRACT(YEAR FROM pe.payment_date) = %s
                      AND EXTRACT(MONTH FROM pe.payment_date) = %s
                      AND (pe.paid_status IS NULL OR pe.paid_status = FALSE)
                    RETURNING pe.id;
                """
                params = [
                    paid_date,
                    iban,
                    amount,
                    target_year,
                    target_month,
                ]
                cur.execute(query, params)
                updated = cur.rowcount or 0
            if not updated:
                name_key = beneficiary_name or employee_name
                query = f"""
                    UPDATE payroll_entries pe
                    SET paid_status = TRUE,
                        {paid_date_col} = %s
                    FROM employees e
                    WHERE pe.employee_id = e.id
                      AND e.full_name ILIKE %s
                      AND ABS(pe.net_pay - %s) <= 0.05
                      AND EXTRACT(YEAR FROM pe.payment_date) = %s
                      AND EXTRACT(MONTH FROM pe.payment_date) = %s
                      AND (pe.paid_status IS NULL OR pe.paid_status = FALSE)
                    RETURNING pe.id;
                """
                params = [
                    paid_date,
                    f"%{name_key}%",
                    amount,
                    target_year,
                    target_month,
                ]
                cur.execute(query, params)
                updated = cur.rowcount or 0
            if updated and "last_paid_date" in employee_columns:
                cur.execute(
                    "UPDATE employees SET last_paid_date = GREATEST(last_paid_date, %s) "
                    "WHERE full_name ILIKE %s;",
                    (paid_date, f"%{beneficiary_name or employee_name}%"),
                )
        conn.commit()
    return updated


def mark_paid_by_receipt_total(
    config: Dict[str, object],
    employee_name: str,
    amount: float,
    paid_date: datetime.date,
    iban: str = None,
    beneficiary_name: str = None,
    payroll_year: int = None,
    payroll_month: int = None,
) -> int:
    """Mark all payroll entries as paid when the month total matches a receipt."""
    _require_psycopg2()
    paid_date_col = _paid_date_column(config)
    employee_columns = _employee_columns(config)
    if not employee_name or paid_date is None:
        return 0
    target_year = payroll_year or paid_date.year
    target_month = payroll_month or paid_date.month
    updated = 0
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            if iban and "iban" in employee_columns:
                query = f"""
                    WITH matched AS (
                        SELECT pe.id,
                               SUM(pe.net_pay) OVER (PARTITION BY pe.employee_id) AS month_total
                        FROM payroll_entries pe
                        JOIN employees e ON e.id = pe.employee_id
                        WHERE e.iban = %s
                          AND EXTRACT(YEAR FROM pe.payment_date) = %s
                          AND EXTRACT(MONTH FROM pe.payment_date) = %s
                          AND (pe.paid_status IS NULL OR pe.paid_status = FALSE)
                    )
                    UPDATE payroll_entries pe
                    SET paid_status = TRUE,
                        {paid_date_col} = %s
                    FROM matched m
                    WHERE pe.id = m.id
                      AND ABS(m.month_total - %s) <= 0.05
                    RETURNING pe.id;
                """
                params = [iban, target_year, target_month, paid_date, amount]
                cur.execute(query, params)
                updated = cur.rowcount or 0
            if not updated:
                name_key = beneficiary_name or employee_name
                query = f"""
                    WITH matched AS (
                        SELECT pe.id,
                               SUM(pe.net_pay) OVER (PARTITION BY pe.employee_id) AS month_total
                        FROM payroll_entries pe
                        JOIN employees e ON e.id = pe.employee_id
                        WHERE e.full_name ILIKE %s
                          AND EXTRACT(YEAR FROM pe.payment_date) = %s
                          AND EXTRACT(MONTH FROM pe.payment_date) = %s
                          AND (pe.paid_status IS NULL OR pe.paid_status = FALSE)
                    )
                    UPDATE payroll_entries pe
                    SET paid_status = TRUE,
                        {paid_date_col} = %s
                    FROM matched m
                    WHERE pe.id = m.id
                      AND ABS(m.month_total - %s) <= 0.05
                    RETURNING pe.id;
                """
                params = [f"%{name_key}%", target_year, target_month, paid_date, amount]
                cur.execute(query, params)
                updated = cur.rowcount or 0
            if updated and "last_paid_date" in employee_columns:
                cur.execute(
                    "UPDATE employees SET last_paid_date = GREATEST(last_paid_date, %s) "
                    "WHERE full_name ILIKE %s;",
                    (paid_date, f"%{beneficiary_name or employee_name}%"),
                )
        conn.commit()
    return updated


def append_audit_log(config: Dict[str, object], entry_id: int, field: str, old_value, new_value):
    """Append a local audit log entry for edits."""
    user = str(config.get("audit_user") or os.environ.get("USER") or "unknown")
    if user == "unknown":
        try:
            user = os.getlogin()
        except OSError:
            user = "unknown"
    old_value = _serialize_audit_value(old_value)
    new_value = _serialize_audit_value(new_value)
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


def _serialize_audit_value(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _paid_date_column(config: Dict[str, object]) -> str:
    key = (
        str(config.get("host", "")),
        str(config.get("port", "")),
        str(config.get("database", "")),
        str(config.get("user", "")),
    )
    cached = _PAID_DATE_COLUMN_CACHE.get(key)
    if cached:
        return cached
    column = "paid_date"
    try:
        with get_connection(config) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'payroll_entries';"
                )
                columns = {row[0] for row in cur.fetchall()}
        if "paid_date" in columns:
            column = "paid_date"
        elif "actual_payment_date" in columns:
            column = "actual_payment_date"
    except Exception:
        column = "paid_date"
    _PAID_DATE_COLUMN_CACHE[key] = column
    return column


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


def delete_all_data(config: Dict[str, object]) -> None:
    """Delete all payroll data from the database."""
    _require_psycopg2()
    query = """
        TRUNCATE TABLE
            documents,
            insurance_contributions,
            insurance_claims,
            payroll_entries,
            payroll_runs,
            employees
        RESTART IDENTITY
        CASCADE;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
        conn.commit()


def fetch_payroll_entry_count(
    config: Dict[str, object],
    start_date=None,
    end_date=None,
    document_type: str = None,
    search: str = None,
):
    """Return total payroll entry count for pagination."""
    _require_psycopg2()
    conditions = []
    params = []
    _append_date_range(conditions, params, "pe.payment_date", start_date, end_date)
    if document_type:
        conditions.append("pe.document_type = %s")
        params.append(document_type)
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else "WHERE TRUE"
    query = f"""
        SELECT COUNT(*)
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
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
    paid_date_col = _paid_date_column(config)
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
            pe.{paid_date_col} AS paid_date,
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
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
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
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
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
    _append_search_conditions(
        conditions,
        params,
        search,
        ["e.full_name", "e.employee_code", "pe.document_type::TEXT", "d.source_pdf"],
    )
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
            BOOL_AND(COALESCE(pe.paid_status, false)) AS paid,
            MAX(pe.paid_date) AS paid_date,
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


def fetch_employee_monthly_entries(
    config: Dict[str, object],
    employee_code: str = None,
    employee_name: str = None,
    months: list = None,
):
    """Return detailed payroll entries for an employee across selected months."""
    _require_psycopg2()
    if not months:
        return [], []
    conditions = []
    params = []
    if employee_code:
        conditions.append("e.employee_code = %s")
        params.append(employee_code)
    if employee_name:
        conditions.append("e.full_name = %s")
        params.append(employee_name)
    month_clauses = []
    for year, month in months:
        month_clauses.append(
            "(EXTRACT(YEAR FROM pe.payment_date)::INT = %s AND EXTRACT(MONTH FROM pe.payment_date)::INT = %s)"
        )
        params.extend([int(year), int(month)])
    conditions.append("(" + " OR ".join(month_clauses) + ")")
    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    query = f"""
        SELECT
            pe.payment_date AS payment_date,
            COALESCE(pe.paid_status, false) AS paid_status,
            pe.document_type AS document_type,
            pe.net_pay AS net_pay,
            d.source_pdf AS source_pdf,
            pr.source_archive AS source_archive
        FROM payroll_entries pe
        JOIN employees e ON e.id = pe.employee_id
        LEFT JOIN documents d ON d.payroll_entry_id = pe.id
        LEFT JOIN payroll_runs pr ON pr.id = pe.payroll_run_id
        WHERE {where_clause}
        ORDER BY pe.payment_date, pe.document_type;
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    return columns, rows


def mark_entries_paid_for_month(
    config: Dict[str, object],
    employee_code: str = None,
    employee_name: str = None,
    year: int = None,
    month: int = None,
) -> int:
    """Mark all payroll entries for an employee in a specific month as paid."""
    _require_psycopg2()
    if not year or not month:
        raise ValueError("year and month are required")
    if not employee_code and not employee_name:
        raise ValueError("employee_code or employee_name is required")
    conditions = [
        "EXTRACT(YEAR FROM pe.payment_date) = %s",
        "EXTRACT(MONTH FROM pe.payment_date) = %s",
    ]
    params = [year, month]
    if employee_code:
        conditions.append("e.employee_code = %s")
        params.append(employee_code)
    else:
        conditions.append("e.full_name = %s")
        params.append(employee_name)
    where_clause = " AND ".join(conditions)
    query = f"""
        UPDATE payroll_entries pe
        SET paid_status = TRUE,
            paid_date = COALESCE(paid_date, CURRENT_DATE)
        FROM employees e
        WHERE pe.employee_id = e.id
          AND {where_clause};
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount
