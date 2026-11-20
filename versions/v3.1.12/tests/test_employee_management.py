import datetime as dt
import os
from decimal import Decimal
from pathlib import Path

import pytest

import db_storage as db
import employee_management as management


def test_code_sort_is_numeric_without_conflating_zero_padded_identities():
    rows = [('60', 'Gamma'), ('0060', 'Gamma'), ('9', 'Beta'), ('100', 'Alpha'), ('ABC', 'Zeta')]
    assert [r[0] for r in management.sort_employees(rows, 'code')] == ['9', '0060', '60', '100', 'ABC']
    assert [r[0] for r in management.sort_employees(rows, 'code', True)] == ['ABC', '100', '60', '0060', '9']
    assert [r[0] for r in management.sort_employees(rows, 'name')] == ['100', '9', '0060', '60', 'ABC']
    assert len(rows) == 5


def test_name_sort_ignores_greek_case_and_accents():
    rows = [('2', 'ΒΗΤΑ'), ('1', 'άλφα'), ('3', 'ΑΛΦΑ')]
    assert [r[0] for r in management.sort_employees(rows)] == ['1', '3', '2']


def test_periods_keep_rehire_gaps_but_combine_overlaps():
    assert management.normalize_periods([('2024-01-01', '2024-02-29'), ('2024-02-01', '2024-03-01'),
                                         ('2026-01-01', '')]) == [(dt.date(2024, 1, 1), dt.date(2024, 3, 1)), (dt.date(2026, 1, 1), None)]
    assert management.activity_label([(dt.date(2024, 1, 1), dt.date(2024, 2, 29))], True,
                                     dt.date(2024, 2, 29), dt.date(2024, 2, 29)) == 'Active'
    assert management.activity_label([(dt.date(2024, 1, 1), dt.date(2024, 2, 29))], True,
                                     dt.date(2024, 3, 1), dt.date(2024, 3, 31)) == 'Inactive'
    assert management.activity_label([], True) == 'Dates not set'
    assert management.activity_label([], False) == 'Inactive'


@pytest.mark.parametrize('period', [('', ''), ('2026-02-30', ''), ('2026-07-02', '2026-07-01')])
def test_invalid_employment_dates_are_rejected(period):
    with pytest.raises(ValueError):
        management.normalize_periods([period])


def test_read_only_role_cannot_merge_or_change_dates():
    with pytest.raises(PermissionError):
        management.merge_employees({'role': 'viewer'}, '60', '0060', 'revision')
    with pytest.raises(PermissionError):
        management.save_periods({'role': 'viewer'}, '60', [])


@pytest.fixture
def qa():
    if os.environ.get('PAYROLL_EMPLOYEE_QA') != '1':
        pytest.skip('Set PAYROLL_EMPLOYEE_QA=1 to use the isolated payroll_employee_qa_3110 database.')
    config = dict(host='localhost', port=5432, database='payroll_employee_qa_3110', user=os.environ.get('PGUSER') or os.environ.get('USER', 'postgres'), role='editor')
    # This fixed disposable database is never the production payroll database.
    assert config['database'] == 'payroll_employee_qa_3110'
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(Path(__file__).resolve().parents[3].joinpath('create_database.sql').read_text())
            cur.execute('TRUNCATE employees, payroll_runs, insurance_claims, alert_acknowledgements, employee_deletion_history CASCADE')
    yield config


def sql(config, statement, params=()):
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(statement, params)
            return cur.fetchall() if cur.description else []


def import_entry(config, code, name='Example Employee', amount='100', date='01/06/2026', source=None):
    import pandas as pd
    source = source or f'{code}-{date}.pdf'
    frame = pd.DataFrame([dict(EmployeeCode=code, EmployeeName=name, DocumentType='salary',
                               Date=date, BasicSalary=amount, TotalEarnings=amount, NetPay=amount,
                               EFKAEmployee='10', EFKAEmployer='20', TEKAEmployee='1', TEKAEmployer='2',
                               SourcePDF=source, SourceArchive='qa.zip')])
    db.store_payroll_data(frame, config)
    return frame


def merge(config, source='0060', target='60'):
    preview = management.preview_merge(config, source, target)
    return management.merge_employees(config, source, target, preview['revision'])


def test_merge_keeps_ids_documents_insurance_and_payment_state(qa):
    import_entry(qa, '60', amount='100.10')
    import_entry(qa, '0060', amount='200.20')
    sql(qa, "UPDATE payroll_entries SET paid_status=TRUE,paid_date='2026-07-01' WHERE net_pay=200.20")
    entries = sql(qa, 'SELECT id,net_pay,paid_status,paid_date FROM payroll_entries ORDER BY id')
    docs = sql(qa, 'SELECT * FROM documents ORDER BY id')
    insurance = sql(qa, 'SELECT * FROM insurance_contributions ORDER BY id')
    result = merge(qa)
    assert result['combined_net'] == Decimal('300.30')
    assert sql(qa, 'SELECT id,net_pay,paid_status,paid_date FROM payroll_entries ORDER BY id') == entries
    assert sql(qa, 'SELECT * FROM documents ORDER BY id') == docs
    assert sql(qa, 'SELECT * FROM insurance_contributions ORDER BY id') == insurance
    assert sql(qa, 'SELECT DISTINCT e.employee_code FROM payroll_entries p JOIN employees e ON e.id=p.employee_id') == [('60',)]
    assert [r[0] for r in management.fetch_directory(qa, status='All')] == ['60']
    assert sql(qa, 'SELECT count(*) FROM employee_merge_history') == [(1,)]


def test_old_code_reimports_into_survivor_without_recreating_duplicate(qa):
    import_entry(qa, '60')
    original = import_entry(qa, '0060', amount='200')
    merge(qa)
    db.store_payroll_data(original, qa)
    assert sql(qa, 'SELECT count(*) FROM payroll_entries') == [(2,)]
    import_entry(qa, '0060', amount='300', date='01/07/2026')
    assert sql(qa, 'SELECT count(*) FROM payroll_entries') == [(3,)]
    assert sql(qa, 'SELECT DISTINCT e.employee_code FROM payroll_entries p JOIN employees e ON e.id=p.employee_id') == [('60',)]
    report = management.canonicalize_payroll_frame(original, qa)
    assert report.iloc[0]['EmployeeCode'] == '60'
    assert report.iloc[0]['SourcePDF'] == original.iloc[0]['SourcePDF']
    assert original.iloc[0]['EmployeeCode'] == '0060'


def test_merge_conflicts_overlap_warning_and_combined_employment(qa):
    import_entry(qa, '60')
    import_entry(qa, '0060')
    sql(qa, "UPDATE employees SET iban=CASE employee_code WHEN '60' THEN 'KEEP' ELSE 'OLD' END")
    management.save_periods(qa, '60', [('2026-01-01', '2026-03-31')])
    management.save_periods(qa, '0060', [('2026-03-01', '2026-06-30'), ('2026-09-01', '')])
    preview = management.preview_merge(qa, '0060', '60')
    assert preview['overlaps'] == 1
    assert 'iban' in preview['conflicts']
    management.merge_employees(qa, '0060', '60', preview['revision'])
    assert sql(qa, "SELECT iban FROM employees WHERE employee_code='60'") == [('KEEP',)]
    assert sql(qa, "SELECT iban FROM employees WHERE employee_code='0060'") == [('OLD',)]
    assert management.fetch_periods(qa, '60')['periods'] == [(dt.date(2026, 1, 1), dt.date(2026, 6, 30)), (dt.date(2026, 9, 1), None)]
    assert sql(qa, 'SELECT count(*) FROM payroll_entries') == [(2,)]


def test_stale_merge_preview_cannot_apply_after_payroll_changes(qa):
    import_entry(qa, '60')
    import_entry(qa, '0060')
    preview = management.preview_merge(qa, '0060', '60')
    sql(qa, 'UPDATE payroll_entries SET paid_status=TRUE')
    with pytest.raises(ValueError, match='changed after'):
        management.merge_employees(qa, '0060', '60', preview['revision'])
    assert sql(qa, 'SELECT count(*) FROM employees WHERE merged_into IS NULL') == [(2,)]
    assert sql(qa, 'SELECT count(*) FROM employee_merge_history') == [(0,)]


def test_merge_chain_flattens_aliases_and_rejects_same_or_already_merged(qa):
    for code in ['60', '0060', '99']:
        import_entry(qa, code)
    merge(qa)
    merge(qa, '60', '99')
    import_entry(qa, '0060', date='01/07/2026')
    assert sql(qa, 'SELECT DISTINCT e.employee_code FROM payroll_entries p JOIN employees e ON e.id=p.employee_id') == [('99',)]
    with pytest.raises(ValueError):
        management.preview_merge(qa, '99', '99')
    with pytest.raises(ValueError):
        management.preview_merge(qa, '0060', '99')


def test_active_directory_respects_period_end_rehire_gaps_and_unknown_dates(qa):
    for code in ['60', '0060']:
        import_entry(qa, code)
    management.save_periods(qa, '60', [('2024-01-01', '2024-02-29'), ('2026-09-01', '')])
    def codes(start, end, status='Active'):
        return {r[0] for r in management.fetch_directory(qa, status=status, start=dt.date.fromisoformat(start), end=dt.date.fromisoformat(end))}
    assert codes('2024-02-29', '2024-02-29') == {'60', '0060'}
    assert codes('2024-03-01', '2024-03-31') == {'0060'}
    assert codes('2026-09-01', '2026-09-30') == {'60', '0060'}
    assert codes('2024-03-01', '2024-03-31', 'Inactive') == {'60'}
    assert codes('2024-03-01', '2024-03-31', 'Dates not set') == {'0060'}
    management.save_periods(qa, '0060', [], False)
    assert codes('2024-03-01', '2024-03-31') == set()
    assert sql(qa, 'SELECT count(*) FROM payroll_entries') == [(2,)]


def test_stale_or_invalid_employment_edit_keeps_saved_periods(qa):
    import_entry(qa, '60')
    original = management.fetch_periods(qa, '60')
    management.save_periods(qa, '60', [('2026-01-01', '')], expected_revision=original['revision'])
    with pytest.raises(ValueError, match='changed'):
        management.save_periods(qa, '60', [], expected_revision=original['revision'])
    with pytest.raises(ValueError):
        management.save_periods(qa, '60', [('2026-10-01', '2026-09-01')])
    assert management.fetch_periods(qa, '60')['periods'] == [(dt.date(2026, 1, 1), None)]


def test_failure_mid_merge_rolls_back_employee_and_payroll_changes(qa):
    import psycopg2
    import_entry(qa, '60')
    import_entry(qa, '0060')
    before = sql(qa, 'SELECT id,employee_id FROM payroll_entries ORDER BY id')
    sql(qa, """CREATE OR REPLACE FUNCTION qa_reject_merge() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'intentional QA failure'; END; $$;
        CREATE TRIGGER qa_reject BEFORE INSERT ON employee_merge_history FOR EACH ROW EXECUTE FUNCTION qa_reject_merge();""")
    try:
        with pytest.raises(psycopg2.Error, match='intentional QA failure'):
            merge(qa)
        assert sql(qa, 'SELECT id,employee_id FROM payroll_entries ORDER BY id') == before
        assert sql(qa, 'SELECT count(*) FROM employees WHERE merged_into IS NULL') == [(2,)]
    finally:
        sql(qa, 'DROP TRIGGER qa_reject ON employee_merge_history; DROP FUNCTION qa_reject_merge()')


def test_delete_empty_ocr_employee_keeps_unrelated_employees(qa):
    sql(qa, "INSERT INTO employees(employee_code,full_name) VALUES ('OCR',''), ('REAL','Real Employee')")
    preview = management.preview_delete_employee(qa, 'OCR')
    assert preview['payroll_count'] == preview['document_count'] == 0
    assert management.delete_employee(qa, 'OCR', preview['revision']) == 0
    assert sql(qa, 'SELECT employee_code FROM employees') == [('REAL',)]
    snapshot, = sql(qa, "SELECT snapshot FROM employee_deletion_history WHERE employee_code='OCR'")[0]
    assert snapshot['employee']['employee_code'] == 'OCR'


def test_delete_linked_payroll_requires_consent_and_preserves_audit_and_files(qa, tmp_path):
    source = tmp_path / 'original.pdf'
    source.write_bytes(b'original evidence')
    import_entry(qa, 'OCR', source=str(source))
    import_entry(qa, 'REAL', amount='200')
    management.save_periods(qa, 'OCR', [('2024-01-01', '')])
    sql(qa, "UPDATE payroll_entries SET paid_status=TRUE WHERE employee_id=(SELECT id FROM employees WHERE employee_code='OCR')")
    preview = management.preview_delete_employee(qa, 'OCR')
    assert preview['payroll_count'] == preview['paid_count'] == preview['document_count'] == 1
    assert preview['net_pay'] == Decimal('100')
    with pytest.raises(ValueError, match='Confirm deletion'):
        management.delete_employee(qa, 'OCR', preview['revision'])
    assert management.delete_employee(qa, 'OCR', preview['revision'], include_payroll=True) == 1
    assert sql(qa, 'SELECT count(*),sum(net_pay) FROM payroll_entries') == [(1, Decimal('200'))]
    assert sql(qa, 'SELECT count(*) FROM documents') == [(1,)]
    assert sql(qa, 'SELECT count(*) FROM insurance_contributions') == [(1,)]
    snapshot = sql(qa, "SELECT snapshot FROM employee_deletion_history WHERE employee_code='OCR'")[0][0]
    assert snapshot['payroll_entries'][0]['paid_status'] is True
    assert len(snapshot['documents']) == len(snapshot['insurance_contributions']) == len(snapshot['employee_employment_periods']) == 1
    assert source.read_bytes() == b'original evidence'


def test_delete_rejects_stale_preview_and_viewer(qa):
    import_entry(qa, 'OCR')
    preview = management.preview_delete_employee(qa, 'OCR')
    with pytest.raises(PermissionError):
        management.delete_employee(dict(qa, role='viewer'), 'OCR', preview['revision'], include_payroll=True)
    sql(qa, 'UPDATE payroll_entries SET paid_status=TRUE')
    with pytest.raises(ValueError, match='changed'):
        management.delete_employee(qa, 'OCR', preview['revision'], include_payroll=True)
    assert sql(qa, 'SELECT count(*) FROM payroll_entries') == [(1,)]


def test_delete_protects_merged_profiles_and_aliases(qa):
    import_entry(qa, '0060')
    import_entry(qa, '60')
    merge(qa)
    for code in ('60', '0060'):
        with pytest.raises(ValueError, match='merge history'):
            management.preview_delete_employee(qa, code)
    assert sql(qa, 'SELECT count(*) FROM payroll_entries') == [(2,)]


def test_delete_rolls_back_audit_and_children_when_employee_delete_fails(qa):
    import_entry(qa, 'OCR')
    preview = management.preview_delete_employee(qa, 'OCR')
    sql(qa, """CREATE OR REPLACE FUNCTION reject_employee_delete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'test rejection'; END $$;
        CREATE TRIGGER reject_employee_delete BEFORE DELETE ON employees FOR EACH ROW EXECUTE FUNCTION reject_employee_delete()""")
    try:
        with pytest.raises(Exception, match='test rejection'):
            management.delete_employee(qa, 'OCR', preview['revision'], include_payroll=True)
        for table in ('employees', 'payroll_entries', 'documents', 'insurance_contributions'):
            assert sql(qa, f'SELECT count(*) FROM {table}') == [(1,)]
        assert sql(qa, 'SELECT count(*) FROM employee_deletion_history') == [(0,)]
    finally:
        sql(qa, 'DROP TRIGGER reject_employee_delete ON employees; DROP FUNCTION reject_employee_delete()')
