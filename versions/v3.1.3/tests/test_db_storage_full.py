import datetime
import json
from pathlib import Path

import pandas as pd

import db_storage


class FakeCursor:
    def __init__(
        self,
        fetchall_sequence=None,
        fetchone_sequence=None,
        rowcount_sequence=None,
        description_sequence=None,
    ):
        self.fetchall_sequence = list(fetchall_sequence or [])
        self.fetchone_sequence = list(fetchone_sequence or [])
        self.rowcount_sequence = list(rowcount_sequence or [])
        self.description_sequence = list(description_sequence or [])
        self.rowcount = 0
        self.description = [("col",)]
        self.queries = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append(query)
        self.params.append(params)
        if self.rowcount_sequence:
            self.rowcount = self.rowcount_sequence.pop(0)
        if self.description_sequence:
            self.description = self.description_sequence.pop(0)

    def fetchall(self):
        if self.fetchall_sequence:
            return self.fetchall_sequence.pop(0)
        return []

    def fetchone(self):
        if self.fetchone_sequence:
            return self.fetchone_sequence.pop(0)
        return None

    def copy_expert(self, sql, handle):
        handle.write("col1,col2\n")
        handle.write("1,2\n")


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


class ConnectionFactory:
    def __init__(self, cursors):
        self._cursors = list(cursors)

    def __call__(self, _config):
        if self._cursors:
            cursor = self._cursors.pop(0)
        else:
            cursor = FakeCursor()
        return FakeConnection(cursor)


def _clear_caches():
    db_storage._PAID_DATE_COLUMN_CACHE.clear()
    db_storage._INSURANCE_CLAIMS_COLUMN_CACHE.clear()
    db_storage._EMPLOYEE_COLUMN_CACHE.clear()


def test_config_and_prefs_roundtrip(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_path = config_dir / "db_config.json"
    prefs_path = config_dir / "ui_prefs.json"
    monkeypatch.setattr(db_storage, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(db_storage, "CONFIG_PATH", config_path)
    monkeypatch.setattr(db_storage, "PREFS_PATH", prefs_path)

    loaded = db_storage.load_db_config()
    assert loaded["host"] == "localhost"

    custom = {"enabled": True, "host": "db.example", "port": 9999}
    db_storage.save_db_config(custom)
    reloaded = db_storage.load_db_config()
    assert reloaded["enabled"] is True
    assert reloaded["host"] == "db.example"

    prefs = {"theme": "dark", "size": 12}
    db_storage.save_ui_prefs(prefs)
    assert db_storage.load_ui_prefs() == prefs


def test_find_pg_tool_and_backup_restore(monkeypatch):
    monkeypatch.setattr(db_storage.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    assert db_storage._find_pg_tool("pg_dump") == "/usr/local/bin/pg_dump"

    calls = []

    def fake_check_call(args, env=None):
        calls.append((args, env))

    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_find_pg_tool", lambda name: f"/bin/{name}")
    monkeypatch.setattr(db_storage.subprocess, "check_call", fake_check_call)

    config = {"host": "db", "port": 5555, "database": "payroll", "user": "me", "password": "secret"}
    db_storage.backup_database(config, "/tmp/backup.dump")
    db_storage.restore_database(config, "/tmp/backup.dump")

    assert len(calls) == 2
    assert calls[0][0][0] == "/bin/pg_dump"
    assert calls[1][0][0] == "/bin/pg_restore"


def test_export_all_tables_to_csv(tmp_path, monkeypatch):
    cursor = FakeCursor()
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))
    db_storage.export_all_tables_to_csv({}, str(tmp_path))
    for table in (
        "employees",
        "payroll_runs",
        "payroll_entries",
        "insurance_contributions",
        "insurance_claims",
        "documents",
    ):
        assert (tmp_path / f"{table}.csv").exists()


def test_migrate_paid_date_column(monkeypatch):
    _clear_caches()
    cursor = FakeCursor(fetchall_sequence=[[('actual_payment_date',)]])
    conn = FakeConnection(cursor)
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: conn)
    assert db_storage.migrate_paid_date_column({}) is True
    assert conn.committed is True


def test_ensure_insurance_claims_table(monkeypatch):
    _clear_caches()
    cursor = FakeCursor(
        fetchall_sequence=[[('claim_year',), ('claim_month',), ('tpte_code',), ('source_pdf',)]],
    )
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))
    db_storage.ensure_insurance_claims_table({})


def test_ensure_employee_profile_columns(monkeypatch):
    _clear_caches()
    cursor = FakeCursor(fetchall_sequence=[[('iban',), ('beneficiary_name',)]])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))
    db_storage.ensure_employee_profile_columns({"host": "h", "port": 1, "database": "d", "user": "u"})


def test_columns_cache(monkeypatch):
    _clear_caches()
    cursor = FakeCursor(fetchall_sequence=[[('iban', 'YES'), ('beneficiary_name', 'NO')]])
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))
    cols = db_storage._insurance_claims_columns({"host": "h", "port": 1, "database": "d", "user": "u"})
    assert cols == {"iban": True, "beneficiary_name": False}
    assert db_storage._insurance_claims_columns({"host": "h", "port": 1, "database": "d", "user": "u"}) == cols


def test_prepare_staging_rows_and_store_payroll_data(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "EmployeeCode": "E1",
                "EmployeeName": "Jane Doe",
                "DocumentType": "Salary",
                "BasicSalary": "1000",
                "TotalEarnings": "1200",
                "NetPay": "900",
                "Date": "01/01/2024",
                "EFKAEmployee": "10",
                "EFKAEmployer": "20",
                "TEKAEmployee": "3",
                "TEKAEmployer": "4",
                "SourcePDF": "file.pdf",
                "SourceArchive": "archive.zip",
            }
        ]
    )
    columns, rows = db_storage._prepare_staging_rows(df)
    assert "employee_code" in columns
    assert rows

    cursor = FakeCursor()
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)

    def fake_execute_values(cur, sql, values, page_size=500):
        assert values

    monkeypatch.setattr(db_storage, "extras", type("Extras", (), {"execute_values": fake_execute_values}))
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))
    assert db_storage.store_payroll_data(df, {}) == 1


def test_store_insurance_claims(monkeypatch):
    claims = [
        {
            "claim_year": 2024,
            "claim_month": 1,
            "submission_date": datetime.date(2024, 2, 5),
            "total_earnings": 1000,
            "total_contributions": 200,
            "tpte_code": "RF123",
            "claim_type": "EFKA",
            "paid_status": True,
            "paid_date": datetime.date(2024, 3, 1),
            "source_pdf": "claim.pdf",
        }
    ]
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(
        db_storage,
        "_insurance_claims_columns",
        lambda config: {
            "claim_year": True,
            "claim_month": True,
            "submission_date": True,
            "total_earnings": True,
            "total_contributions": True,
            "tpte_code": True,
            "claim_type": True,
            "paid_status": True,
            "paid_date": True,
            "source_pdf": True,
        },
    )

    def fake_execute_values(cur, sql, values, page_size=200):
        assert values

    monkeypatch.setattr(db_storage, "extras", type("Extras", (), {"execute_values": fake_execute_values}))
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(FakeCursor()))
    assert db_storage.store_insurance_claims(claims, {}) == 1


def test_fetch_view_rows_and_summary_queries(monkeypatch):
    cursor = FakeCursor(
        fetchall_sequence=[[('row1',)], [('summary',)], [('totals',)]],
        description_sequence=[[('col_a',), ('col_b',)]],
    )
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))

    cols, rows = db_storage.fetch_view_rows({}, "v_monthly_payroll_summary", limit=10)
    assert cols == ["col_a", "col_b"]
    assert rows == [('row1',)]

    assert db_storage.fetch_monthly_summary({}, search="Jane")
    assert db_storage.fetch_monthly_totals({}, document_type="salary")


def test_employee_profile_queries_and_updates(monkeypatch):
    cursor = FakeCursor(fetchall_sequence=[[('E1', 'Jane')]], fetchone_sequence=[('E1', 'Jane')], rowcount_sequence=[1])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))
    monkeypatch.setattr(
        db_storage,
        "_employee_columns",
        lambda config: {
            "iban": True,
            "beneficiary_name": True,
            "first_worked_date": True,
            "last_paid_date": True,
            "pay_rate_monthly": True,
            "pay_rate_hourly": True,
            "pay_rate_daily": True,
            "pay_rate_double": True,
            "pay_rate_abroad": True,
            "pay_rate_abroad_double": True,
        },
    )

    assert db_storage.fetch_employees_list({})
    assert db_storage.fetch_employee_profile({}, "E1")
    db_storage.update_employee_profile({}, "E1", iban="GR123")
    assert db_storage.update_employee_iban_by_name({}, "Jane", "GR123") == 1
    assert db_storage.update_employee_bank_details_by_name({}, "Jane", iban="GR123") == 1


def test_insurance_claims_queries(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_insurance_period_columns", lambda config: ("claim_year", "claim_month"))
    monkeypatch.setattr(db_storage, "_insurance_claims_columns", lambda config: {"claim_type": True, "paid_status": True, "paid_date": True})
    monkeypatch.setattr(db_storage, "extras", type("Extras", (), {"execute_batch": lambda *args, **kwargs: None}))

    cursor1 = FakeCursor(fetchall_sequence=[[('row',)]])
    cursor2 = FakeCursor(fetchall_sequence=[[('row',)]])
    claim_rows = [(1, "EFKA", 100.0, 200.0, None)]
    cursor3 = FakeCursor(fetchall_sequence=[claim_rows])
    cursor4 = FakeCursor()
    cursor5 = FakeCursor(rowcount_sequence=[2])
    factory = ConnectionFactory([cursor1, cursor2, cursor3, cursor4, cursor5])
    monkeypatch.setattr(db_storage, "get_connection", factory)

    assert db_storage.fetch_insurance_comparison({}, start_date=datetime.date(2024, 1, 1))
    assert db_storage.fetch_insurance_claims_for_period({}, 2024, 1) == [('row',)]
    assert db_storage.update_insurance_claims_for_period({}, 2024, 1, 100, 200) == 1
    assert db_storage.delete_insurance_claims_for_period({}, 2024, 1) == 2


def test_metrics_and_analytics_queries(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")
    cursor1 = FakeCursor(fetchall_sequence=[[('month', 1)]])
    cursor2 = FakeCursor(fetchone_sequence=[(0, 0)])
    cursor3 = FakeCursor(fetchone_sequence=[(0, 0, 0, 0)])
    cursor4 = FakeCursor(fetchall_sequence=[[('avg', 1)]])
    cursor5 = FakeCursor(fetchall_sequence=[[('cost', 1)]])
    cursor6 = FakeCursor(fetchall_sequence=[[('doc', 1)]])
    cursor7 = FakeCursor(fetchall_sequence=[[('kpi', 1)]])
    cursor8 = FakeCursor(fetchall_sequence=[[('heat', 1)]])
    cursor9 = FakeCursor(fetchall_sequence=[[(2024,)]])
    cursor10 = FakeCursor(fetchall_sequence=[[(1,)]])
    factory = ConnectionFactory([cursor1, cursor2, cursor3, cursor4, cursor5, cursor6, cursor7, cursor8, cursor9, cursor10])
    monkeypatch.setattr(db_storage, "get_connection", factory)

    assert db_storage.fetch_month_totals_by_year({}, 2024)
    assert db_storage.fetch_paid_unpaid_totals({}, start_date=datetime.date(2024, 1, 1)) == (0, 0)
    assert db_storage.fetch_unpaid_aging_buckets({}, as_of=datetime.date(2024, 1, 1)) == {
        "0_30": 0.0,
        "31_60": 0.0,
        "61_90": 0.0,
        "90_plus": 0.0,
    }
    assert db_storage.fetch_avg_days_to_paid_by_month({}) == [('avg', 1)]
    assert db_storage.fetch_employer_costs_by_employee({})
    assert db_storage.fetch_document_type_breakdown({})
    assert db_storage.fetch_kpi_totals({})
    assert db_storage.fetch_payment_heatmap({}, 2024, 1)
    assert db_storage.fetch_available_years({}) == [2024]
    assert db_storage.fetch_available_months({}, 2024) == [1]


def test_entries_queries_and_updates(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")
    monkeypatch.setattr(db_storage, "_employee_columns", lambda config: {"iban": True, "last_paid_date": True})

    cursor1 = FakeCursor(fetchall_sequence=[[('row',)]], description_sequence=[[('col',)]])
    cursor2 = FakeCursor(fetchall_sequence=[[('dup',)]], description_sequence=[[('col',)]])
    cursor3 = FakeCursor()
    cursor4 = FakeCursor(rowcount_sequence=[0, 1, 1])
    factory = ConnectionFactory([cursor1, cursor2, cursor3, cursor4])
    monkeypatch.setattr(db_storage, "get_connection", factory)

    assert db_storage.fetch_payroll_entries({}, search="Jane")
    assert db_storage.fetch_duplicate_payroll_entries({})[0] == ["col"]
    db_storage.update_payroll_entry({}, 1, "net_pay", 10)

    updated = db_storage.mark_paid_by_receipt(
        {},
        employee_name="Jane",
        amount=10,
        paid_date=datetime.date(2024, 1, 2),
        iban="GR123",
        beneficiary_name="Jane",
        payroll_year=2024,
        payroll_month=1,
    )
    assert updated == 1


def test_mark_paid_by_receipt_total(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")
    monkeypatch.setattr(db_storage, "_employee_columns", lambda config: {"last_paid_date": True})

    cursor = FakeCursor(rowcount_sequence=[1, 1])
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))

    updated = db_storage.mark_paid_by_receipt_total(
        {},
        employee_name="Jane",
        amount=10,
        paid_date=datetime.date(2024, 1, 2),
        beneficiary_name="Jane",
        payroll_year=2024,
        payroll_month=1,
    )
    assert updated == 1


def test_delete_and_counts(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    cursor1 = FakeCursor(rowcount_sequence=[2])
    cursor2 = FakeCursor()
    cursor3 = FakeCursor(fetchone_sequence=[(5,)])
    cursor4 = FakeCursor(fetchone_sequence=[(0,)], rowcount_sequence=[0])
    cursor5 = FakeCursor(rowcount_sequence=[1])
    factory = ConnectionFactory([cursor1, cursor2, cursor3, cursor4, cursor5])
    monkeypatch.setattr(db_storage, "get_connection", factory)

    assert db_storage.delete_payroll_entries({}, [1, 2]) == 2
    db_storage.delete_all_data({})
    assert db_storage.fetch_payroll_entry_count({}) == 5
    assert db_storage.fetch_unpaid_amount({}) == 0.0
    assert db_storage.mark_entries_paid_for_month({}, employee_name="Jane", year=2024, month=1) == 1


def test_dashboard_and_recent_queries(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_paid_date_column", lambda config: "paid_date")

    cursor1 = FakeCursor(fetchall_sequence=[[('row',)]], description_sequence=[[('col',)]])
    cursor2 = FakeCursor(fetchone_sequence=[(0, 0, 0, 0, 0)])
    cursor3 = FakeCursor(fetchall_sequence=[[('anomaly',)]], description_sequence=[[('col',)]])
    cursor4 = FakeCursor(fetchall_sequence=[[('recent',)]], description_sequence=[[('col',)]])
    cursor5 = FakeCursor(fetchall_sequence=[[('export',)]], description_sequence=[[('col',)]])
    cursor6 = FakeCursor(fetchall_sequence=[[('summary',)]], description_sequence=[[('col',)]])
    cursor7 = FakeCursor(fetchall_sequence=[[('monthly',)]], description_sequence=[[('col',)]])
    factory = ConnectionFactory([cursor1, cursor2, cursor3, cursor4, cursor5, cursor6, cursor7])
    monkeypatch.setattr(db_storage, "get_connection", factory)

    columns, rows = db_storage.fetch_employee_entries({}, employee_code="E1")
    assert columns == ["col"]
    assert rows == [('row',)]

    assert db_storage.fetch_dashboard_metrics({})["entry_count"] == 0
    assert db_storage.fetch_anomaly_entries({})[0] == ["col"]
    assert db_storage.fetch_recent_entries({})[0] == ["col"]
    assert db_storage.fetch_export_rows({}, [1])[0] == ["col"]
    assert db_storage.fetch_monthly_employee_summary({})[0] == ["col"]
    assert db_storage.fetch_employee_monthly_entries({}, employee_code="E1", months=[(2024, 1)])[0] == ["col"]


def test_audit_log_and_paid_date_column(tmp_path, monkeypatch):
    _clear_caches()
    monkeypatch.setattr(db_storage, "CONFIG_DIR", tmp_path)

    cursor = FakeCursor(fetchall_sequence=[[('paid_date',)]])
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))

    assert db_storage._paid_date_column({"host": "h", "port": 1, "database": "d", "user": "u"}) == "paid_date"
    db_storage.append_audit_log({}, 1, "net_pay", 1, 2)
    log_path = tmp_path / "audit_log.jsonl"
    assert log_path.exists()
    data = json.loads(log_path.read_text().splitlines()[0])
    assert data["entry_id"] == 1
    assert db_storage._serialize_audit_value(datetime.date(2024, 1, 1)) == "2024-01-01"


def test_update_insurance_claims_paid(monkeypatch):
    cursor = FakeCursor(rowcount_sequence=[3])
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "_insurance_period_columns", lambda config: ("claim_year", "claim_month"))
    monkeypatch.setattr(db_storage, "get_connection", lambda config: FakeConnection(cursor))

    assert db_storage.update_insurance_claims_paid({}, 2024, 1, paid_status=False) == 3


def test_update_insurance_claims_for_period_paid_fields(monkeypatch):
    monkeypatch.setattr(db_storage, "_require_psycopg2", lambda: None)
    monkeypatch.setattr(db_storage, "extras", type("Extras", (), {"execute_batch": lambda *args, **kwargs: None}))
    monkeypatch.setattr(
        db_storage,
        "_insurance_claims_columns",
        lambda config: {"claim_type": True, "paid_status": True, "paid_date": True},
    )
    claim_rows = [(1, "EFKA", 100.0, 200.0, None)]
    cursor1 = FakeCursor(fetchall_sequence=[claim_rows])
    cursor2 = FakeCursor()
    factory = ConnectionFactory([cursor1, cursor2])
    monkeypatch.setattr(db_storage, "get_connection", factory)

    assert (
        db_storage.update_insurance_claims_for_period(
            {},
            2024,
            1,
            efka_total=150,
            teka_total=None,
            total_earnings=500,
            submission_date=datetime.date(2024, 2, 1),
            tpte_code="RF1",
            paid_status=True,
            paid_date=None,
        )
        == 1
    )
