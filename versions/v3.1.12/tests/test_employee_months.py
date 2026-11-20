import datetime
from decimal import Decimal
from unittest.mock import Mock

import db_storage
from employee_months import build_monthly_ledger
from payroll_gui import PayrollProcessorGUI


COLUMNS = ['entry_id', 'payment_date', 'document_type', 'basic_salary',
           'total_earnings', 'net_pay', 'paid_status', 'paid_date',
           'employee_insurance', 'employer_insurance', 'source_pdf', 'source_archive']


def entry(id, date, net, paid=False, employee_ins='0', employer_ins='0'):
    return (id, date, 'salary', Decimal(net), Decimal(net), Decimal(net), paid,
            date if paid else None, Decimal(employee_ins), Decimal(employer_ins),
            f'{id}.pdf', 'archive.zip')


def test_monthly_totals_keep_every_payslip_and_exact_cents():
    rows = [entry('one', datetime.date(2026, 7, 1), '0.10', True, '0.03', '0.02'),
            entry('two', datetime.date(2026, 7, 31), '0.20', False, '0.01', '0.04'),
            entry('older', datetime.date(2025, 7, 15), '100')]
    months = build_monthly_ledger(COLUMNS, rows)
    assert [m['period'] for m in months] == [(2026, 7), (2025, 7)]
    latest = months[0]
    assert latest['net_pay'] == Decimal('0.30')
    assert latest['paid'] == Decimal('0.10')
    assert latest['due'] == Decimal('0.20')
    assert latest['employee_insurance'] == Decimal('0.04')
    assert latest['employer_insurance'] == Decimal('0.06')
    assert latest['entries'] == rows[:2]
    assert all(month['paid'] + month['due'] == month['net_pay'] for month in months)


def test_monthly_ledger_does_not_truncate_large_history_or_lose_adjustments():
    date = datetime.date(2026, 1, 1)
    rows = [entry(str(index), date, '1.00', index % 2 == 0) for index in range(501)]
    rows.append(entry('correction', date, '-0.50', True))
    month, = build_monthly_ledger(COLUMNS, rows)
    assert len(month['entries']) == 502
    assert month['net_pay'] == Decimal('500.50')
    assert month['paid'] == Decimal('250.50')
    assert month['due'] == Decimal('250.00')
    assert build_monthly_ledger([], []) == []


def test_empty_employee_cannot_fetch_other_peoples_payroll(monkeypatch):
    connect = Mock(side_effect=AssertionError('Should not connect without an employee'))
    monkeypatch.setattr(db_storage, 'get_connection', connect)
    assert db_storage.fetch_employee_payroll_detail({}, '') == ([], [])
    connect.assert_not_called()


class Variable:
    def __init__(self, value=''):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class Tree:
    def __init__(self):
        self.rows = {}
        self.selected = ()

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *items):
        for item in items:
            self.rows.pop(item, None)

    def insert(self, _parent, _position, iid=None, values=(), **_kwargs):
        iid = iid or str(len(self.rows))
        self.rows[iid] = values
        return iid

    def selection_set(self, item):
        self.selected = (item,)

    def selection(self):
        return self.selected

    def focus(self, _item):
        pass

    def see(self, _item):
        pass


def monthly_gui(rows):
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    gui.employee_entry_columns = COLUMNS
    gui.employee_months = {m['period']: m for m in build_monthly_ledger(COLUMNS, rows)}
    gui.employee_selected_period = None
    gui.employee_year_var = Variable('All years')
    gui.employee_monthly_tree = Tree()
    gui.employee_month_entries_tree = Tree()
    gui.employee_month_title_var = Variable()
    gui.employee_month_kpis = {key: Variable() for key in ['net_pay', 'paid', 'due', 'insurance']}
    return gui


def test_selecting_month_and_year_keeps_totals_and_details_in_sync():
    rows = [entry('july', datetime.date(2026, 7, 1), '100', True),
            entry('june', datetime.date(2026, 6, 1), '200'),
            entry('old-july', datetime.date(2025, 7, 1), '300')]
    gui = monthly_gui(rows)
    gui._render_employee_months()
    assert gui.employee_selected_period == (2026, 7)
    assert gui.employee_month_kpis['paid'].get() == gui._format_currency(100)
    gui.employee_monthly_tree.selection_set('2026-06')
    gui._on_employee_month_select()
    assert gui.employee_selected_period == (2026, 6)
    assert gui.employee_month_kpis['due'].get() == gui._format_currency(200)
    assert [values[-1] for values in gui.employee_month_entries_tree.rows.values()] == ['june.pdf']
    gui.employee_year_var.set('2025')
    gui._render_employee_months()
    assert tuple(gui.employee_monthly_tree.rows) == ('2025-07',)
    assert gui.employee_selected_period == (2025, 7)
    assert [values[-1] for values in gui.employee_month_entries_tree.rows.values()] == ['old-july.pdf']
    gui.employee_year_var.set('2024')
    gui._render_employee_months()
    assert gui.employee_selected_period is None
    assert gui.employee_month_entries_tree.rows == {}
    assert all(variable.get() == '—' for variable in gui.employee_month_kpis.values())


def test_switching_employees_clears_old_month_and_ignores_late_profile(monkeypatch):
    gui = monthly_gui([entry('old', datetime.date(2026, 7, 1), '100')])
    gui.employee_selected_code = 'OLD'
    gui.employee_selected_period = (2026, 7)
    gui.employee_profile_vars = {'name': Variable('Old Employee')}
    gui.employee_heading_var = Variable('Old Employee')
    gui.employee_due_tree = Tree()
    gui.employee_paid_tree = Tree()
    gui._async_tokens = {}
    gui.db_config = {'enabled': True}
    gui._get_global_filters = lambda: (None, None, None, None)
    requests = []
    gui._run_async = lambda name, work, done, error: requests.append((work, done))
    gui._apply_employee_profile = Mock()
    gui._load_employee_profile('NEW')
    assert gui.employee_selected_period is None
    assert gui.employee_months == {}
    assert gui.employee_profile_vars['name'].get() == '—'
    gui._load_employee_profile('NEWER')
    requests[0][1]((('NEW', 'New Employee'), [], [], []))
    gui._apply_employee_profile.assert_not_called()
    assert gui.employee_selected_code == 'NEWER'
