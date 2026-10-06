"""Exact monthly totals and drill-down rows for a single employee."""

from decimal import Decimal


def build_monthly_ledger(columns, rows):
    """Group by payslip date and keep every entry behind its monthly total."""
    indexes = {column: index for index, column in enumerate(columns)}
    months = {}
    for row in rows:
        date = row[indexes['payment_date']]
        period = (date.year, date.month)
        if period not in months:
            months[period] = {
                'period': period, 'entries': [],
                'net_pay': Decimal('0'), 'paid': Decimal('0'), 'due': Decimal('0'),
                'employee_insurance': Decimal('0'), 'employer_insurance': Decimal('0'),
            }
        month = months[period]
        month['entries'].append(row)
        for field in ('net_pay', 'employee_insurance', 'employer_insurance'):
            value = row[indexes[field]]
            month[field] += Decimal(str(value)) if value is not None else Decimal('0')
        net_pay = row[indexes['net_pay']]
        payment_bucket = 'paid' if row[indexes['paid_status']] else 'due'
        month[payment_bucket] += Decimal(str(net_pay)) if net_pay is not None else Decimal('0')
    return [months[period] for period in sorted(months, reverse=True)]
