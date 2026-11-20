"""Employment periods and explicit, audited employee identity merges."""

import datetime
import hashlib
import json
import re
import unicodedata

import db_storage as db


SCHEMA_SQL = """
ALTER TABLE employees ADD COLUMN IF NOT EXISTS merged_into UUID REFERENCES employees(id);
CREATE TABLE IF NOT EXISTS employee_employment_periods (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id),
    start_date DATE NOT NULL,
    end_date DATE,
    CHECK (end_date IS NULL OR end_date >= start_date),
    UNIQUE (employee_id, start_date)
);
CREATE INDEX IF NOT EXISTS idx_employee_periods ON employee_employment_periods(employee_id);
CREATE TABLE IF NOT EXISTS employee_merge_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_employee_id UUID NOT NULL REFERENCES employees(id),
    target_employee_id UUID NOT NULL REFERENCES employees(id),
    snapshot JSONB NOT NULL,
    merged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    merged_by TEXT
);
CREATE TABLE IF NOT EXISTS employee_deletion_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_code TEXT NOT NULL,
    snapshot JSONB NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_by TEXT
);
"""
LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('payroll-employee-management'));"


def ensure_schema(config):
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)


def _editable(config):
    if str(config.get('role', 'editor')).lower() != 'editor':
        raise PermissionError('Employee changes require the editor role.')


def sort_employees(rows, column='name', descending=False):
    def name_key(value):
        return ''.join(c for c in unicodedata.normalize('NFD', str(value or '').casefold())
                       if not unicodedata.combining(c))

    def key(row):
        code = str(row[0] or '')
        # Sort numerical codes by value without changing their stored identity.
        code_key = (0, int(code), code) if re.fullmatch(r'[0-9]+', code) else (1, name_key(code), code)
        return (code_key, name_key(row[1])) if column == 'code' else (name_key(row[1]), code_key)
    return sorted(rows, key=key, reverse=descending)


def normalize_periods(periods):
    result = []
    for start, end in periods:
        if isinstance(start, str):
            start = datetime.date.fromisoformat(start.strip())
        if isinstance(end, str):
            end = datetime.date.fromisoformat(end.strip()) if end.strip() else None
        if not isinstance(start, datetime.date) or (end is not None and not isinstance(end, datetime.date)):
            raise ValueError('Every employment period needs a start date (YYYY-MM-DD).')
        if end is not None and end < start:
            raise ValueError('The end date must be on or after the start date.')
        result.append((start, end))
    merged = []
    for start, end in sorted(result, key=lambda period: period[0]):
        if merged and (merged[-1][1] is None or start <= merged[-1][1]):
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, None if previous_end is None or end is None else max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def activity_label(periods, fallback_active, start=None, end=None):
    if not periods:
        return 'Dates not set' if fallback_active else 'Inactive'
    today = datetime.date.today()
    start, end = start or today, end or today
    return 'Active' if any(a <= end and (b is None or b >= start) for a, b in periods) else 'Inactive'


def fetch_directory(config, search=None, status='Active', start=None, end=None):
    ensure_schema(config)
    today = datetime.date.today()
    start, end = start or today, end or today
    active = """(EXISTS (SELECT 1 FROM employee_employment_periods p
        WHERE p.employee_id=e.id AND p.start_date <= %s AND (p.end_date IS NULL OR p.end_date >= %s))
        OR (NOT EXISTS (SELECT 1 FROM employee_employment_periods p WHERE p.employee_id=e.id) AND e.active))"""
    sql = f"""SELECT e.employee_code, e.full_name, e.active,
        EXISTS (SELECT 1 FROM employee_employment_periods p WHERE p.employee_id=e.id) AS dates_set,
        {active} AS in_period
        FROM employees e WHERE e.merged_into IS NULL"""
    params = [end, start]
    if search:
        sql += " AND (e.employee_code ILIKE %s OR e.full_name ILIKE %s OR e.iban ILIKE %s OR e.beneficiary_name ILIKE %s)"
        params.extend([f'%{search}%'] * 4)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    if status == 'Active':
        rows = [row for row in rows if row[4]]
    elif status == 'Inactive':
        rows = [row for row in rows if not row[4]]
    elif status == 'Dates not set':
        rows = [row for row in rows if not row[3]]
    return rows


def fetch_periods(config, code):
    ensure_schema(config)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id, full_name, active FROM employees WHERE employee_code=%s AND merged_into IS NULL', (code,))
            employee = cur.fetchone()
            if not employee:
                raise ValueError('This employee no longer exists as a separate profile. Refresh the list.')
            cur.execute('SELECT start_date, end_date FROM employee_employment_periods WHERE employee_id=%s ORDER BY start_date', (employee[0],))
            periods = cur.fetchall()
    return {'code': code, 'name': employee[1], 'active': employee[2], 'periods': periods,
            'revision': _digest([employee, periods])}


def save_periods(config, code, periods, fallback_active=True, expected_revision=None):
    _editable(config)
    periods = normalize_periods(periods)
    ensure_schema(config)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(LOCK_SQL)
            cur.execute('SELECT id, full_name, active FROM employees WHERE employee_code=%s AND merged_into IS NULL FOR UPDATE', (code,))
            employee = cur.fetchone()
            if not employee:
                raise ValueError('Employee was merged or removed. Refresh before editing.')
            cur.execute('SELECT start_date, end_date FROM employee_employment_periods WHERE employee_id=%s ORDER BY start_date', (employee[0],))
            previous = cur.fetchall()
            if expected_revision is not None and _digest([employee, previous]) != expected_revision:
                raise ValueError('Employment details changed. Reopen the editor before saving.')
            cur.execute('DELETE FROM employee_employment_periods WHERE employee_id=%s', (employee[0],))
            for start, end in periods:
                cur.execute('INSERT INTO employee_employment_periods (employee_id,start_date,end_date) VALUES (%s,%s,%s)', (employee[0], start, end))
            cur.execute('UPDATE employees SET active=%s, updated_at=now() WHERE id=%s', (bool(fallback_active), employee[0]))


def _digest(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


def _deletion_snapshot(cur, code):
    cur.execute('SELECT * FROM employees WHERE employee_code=%s FOR UPDATE', (code,))
    columns = [c[0] for c in cur.description]
    row = cur.fetchone()
    if not row:
        raise ValueError('Employee no longer exists. Refresh the list.')
    employee = dict(zip(columns, row))
    cur.execute('''SELECT EXISTS(SELECT 1 FROM employee_merge_history WHERE source_employee_id=%s OR target_employee_id=%s)
        OR EXISTS(SELECT 1 FROM employees WHERE merged_into=%s)''', (employee['id'],) * 3)
    if employee['merged_into'] or cur.fetchone()[0]:
        raise ValueError('This profile has merge history or import aliases and cannot be deleted. Its linked history must be retained.')
    snapshot = {'employee': employee}
    for table in ('payroll_entries', 'employee_employment_periods'):
        cur.execute(f'SELECT * FROM {table} WHERE employee_id=%s ORDER BY id FOR UPDATE', (employee['id'],))
        columns = [c[0] for c in cur.description]
        snapshot[table] = [dict(zip(columns, row)) for row in cur.fetchall()]
    for table in ('documents', 'insurance_contributions'):
        cur.execute(f'''SELECT * FROM {table} WHERE payroll_entry_id IN
            (SELECT id FROM payroll_entries WHERE employee_id=%s) ORDER BY id FOR UPDATE''', (employee['id'],))
        columns = [c[0] for c in cur.description]
        snapshot[table] = [dict(zip(columns, row)) for row in cur.fetchall()]
    return snapshot


def preview_delete_employee(config, code):
    ensure_schema(config)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(LOCK_SQL)
            snapshot = _deletion_snapshot(cur, code)
    return {'code': code, 'name': snapshot['employee']['full_name'],
            'payroll_count': len(snapshot['payroll_entries']),
            'paid_count': sum(bool(row.get('paid_status')) for row in snapshot['payroll_entries']),
            'net_pay': sum(row.get('net_pay') or 0 for row in snapshot['payroll_entries']),
            'document_count': len(snapshot['documents']), 'revision': _digest(snapshot)}


def delete_employee(config, code, expected_revision, *, include_payroll=False):
    _editable(config)
    if not expected_revision:
        raise ValueError('Review this employee before deleting.')
    ensure_schema(config)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(LOCK_SQL)
            snapshot = _deletion_snapshot(cur, code)
            if _digest(snapshot) != expected_revision:
                raise ValueError('Employee data changed. Review the deletion again.')
            if snapshot['payroll_entries'] and not include_payroll:
                raise ValueError('Confirm deletion of linked payroll entries.')
            cur.execute('INSERT INTO employee_deletion_history(employee_code,snapshot,deleted_by) VALUES (%s,%s::jsonb,%s)',
                        (code, json.dumps(snapshot, default=str), str(config.get('audit_user') or config.get('user') or '')))
            employee_id = snapshot['employee']['id']
            cur.execute('DELETE FROM payroll_entries WHERE employee_id=%s', (employee_id,))
            cur.execute('DELETE FROM employee_employment_periods WHERE employee_id=%s', (employee_id,))
            cur.execute('DELETE FROM employees WHERE id=%s', (employee_id,))
    return len(snapshot['payroll_entries'])


def _merge_snapshot(cur, source_code, target_code):
    if not source_code or not target_code or source_code == target_code:
        raise ValueError('Choose two different employees.')
    cur.execute('SELECT * FROM employees WHERE employee_code IN (%s,%s) ORDER BY id FOR UPDATE', (source_code, target_code))
    columns = [c[0] for c in cur.description]
    employees = {row[columns.index('employee_code')]: dict(zip(columns, row)) for row in cur.fetchall()}
    if len(employees) != 2 or any(e['merged_into'] is not None for e in employees.values()):
        raise ValueError('One of these employees has already been merged. Refresh the list.')
    source, target = employees[source_code], employees[target_code]
    ids = [source['id'], target['id']]
    # Lock payroll while capturing the confirmation revision, including payment state.
    cur.execute('SELECT * FROM payroll_entries WHERE employee_id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE', (ids,))
    columns = [c[0] for c in cur.description]
    entries = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.execute('SELECT employee_id,start_date,end_date FROM employee_employment_periods WHERE employee_id=ANY(%s::uuid[]) ORDER BY employee_id,start_date', (ids,))
    periods = cur.fetchall()
    return {'source': source, 'target': target, 'entries': entries, 'periods': periods}


def preview_merge(config, source_code, target_code):
    ensure_schema(config)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(LOCK_SQL)
            snapshot = _merge_snapshot(cur, source_code, target_code)
    return _merge_summary(snapshot)


def _merge_summary(snapshot):
    source, target = snapshot['source'], snapshot['target']
    source_entries = [e for e in snapshot['entries'] if e['employee_id'] == source['id']]
    target_entries = [e for e in snapshot['entries'] if e['employee_id'] == target['id']]
    def signature(e):
        return (e['payment_date'], e['document_type'], e['net_pay'], e['total_earnings'], e['basic_salary'])
    target_signatures = {signature(e) for e in target_entries}
    overlaps = sum(signature(e) in target_signatures for e in source_entries)
    fields = ['iban', 'beneficiary_name', 'role_title', 'pay_rate_monthly', 'pay_rate_hourly',
              'pay_rate_daily', 'pay_rate_double', 'pay_rate_abroad', 'pay_rate_abroad_double']
    conflicts = [f for f in fields if source.get(f) is not None and target.get(f) is not None and source[f] != target[f]]
    return {'revision': _digest(snapshot), 'source_code': source['employee_code'], 'target_code': target['employee_code'],
            'source_name': source['full_name'], 'target_name': target['full_name'],
            'source_count': len(source_entries), 'target_count': len(target_entries), 'overlaps': overlaps,
            'conflicts': conflicts,
            'combined_net': sum((e['net_pay'] for e in snapshot['entries']), 0)}


def merge_employees(config, source_code, target_code, expected_revision):
    """Move entries atomically; retain the old profile as an import alias and audit."""
    _editable(config)
    if not expected_revision:
        raise ValueError('Review the merge preview before confirming.')
    ensure_schema(config)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(LOCK_SQL)
            snapshot = _merge_snapshot(cur, source_code, target_code)
            if _digest(snapshot) != expected_revision:
                raise ValueError('These employees changed after the preview. Review a fresh preview.')
            source, target = snapshot['source'], snapshot['target']
            cur.execute('UPDATE payroll_entries SET employee_id=%s WHERE employee_id=%s', (target['id'], source['id']))
            cur.execute('UPDATE employees SET merged_into=%s, active=FALSE, updated_at=now() WHERE id=%s OR merged_into=%s', (target['id'], source['id'], source['id']))
            # Keep the survivor's conflicting values; fill only its missing fields.
            fields = ['iban', 'beneficiary_name', 'role_title', 'pay_rate_monthly', 'pay_rate_hourly',
                      'pay_rate_daily', 'pay_rate_double', 'pay_rate_abroad', 'pay_rate_abroad_double']
            assignments = ', '.join(f'{f}=COALESCE(t.{f},s.{f})' for f in fields)
            cur.execute(f'''UPDATE employees t SET {assignments},
                first_worked_date=LEAST(t.first_worked_date,s.first_worked_date),
                last_paid_date=GREATEST(t.last_paid_date,s.last_paid_date), updated_at=now()
                FROM employees s WHERE t.id=%s AND s.id=%s''', (target['id'], source['id']))
            combined_periods = normalize_periods([(p[1], p[2]) for p in snapshot['periods']])
            cur.execute('DELETE FROM employee_employment_periods WHERE employee_id=ANY(%s::uuid[])', ([source['id'], target['id']],))
            for start, end in combined_periods:
                cur.execute('INSERT INTO employee_employment_periods (employee_id,start_date,end_date) VALUES (%s,%s,%s)', (target['id'], start, end))
            cur.execute('INSERT INTO employee_merge_history (source_employee_id,target_employee_id,snapshot,merged_by) VALUES (%s,%s,%s::jsonb,%s)',
                        (source['id'], target['id'], json.dumps(snapshot, default=str), config.get('audit_user') or config.get('user')))
    return _merge_summary(snapshot)


def canonicalize_payroll_frame(frame, config):
    """Use confirmed aliases in newly generated reports, retaining source paths."""
    if frame.empty or 'EmployeeCode' not in frame.columns:
        return frame
    ensure_schema(config)
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT a.employee_code, t.employee_code, t.full_name FROM employees a JOIN employees t ON t.id=a.merged_into')
            aliases = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    result = frame.copy()
    codes = result['EmployeeCode'].astype(str).str.strip()
    for alias, (code, name) in aliases.items():
        mask = codes == alias
        result.loc[mask, 'EmployeeCode'] = code
        result.loc[mask, 'EmployeeName'] = name
    return result
