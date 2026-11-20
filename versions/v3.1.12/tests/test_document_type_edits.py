import pytest

import db_storage as db
from payroll_gui import PayrollProcessorGUI
from test_employee_management import qa, sql, import_entry


@pytest.mark.parametrize('value, expected', [
    ('UnusedLeaveCompensation', 'unused_leave_compensation'),
    ('unused_leave_compensation', 'unused_leave_compensation'),
    ('Unused Leave Compensation', 'unused_leave_compensation'),
    (' vacation-allowance ', 'vacation_allowance'),
    ('Payslip', 'salary'),
])
def test_document_type_normalization_uses_enum_values(value, expected):
    assert db.normalize_document_type(value) == expected


def test_unknown_document_type_is_rejected_before_database_access(monkeypatch):
    monkeypatch.setattr(db, 'get_connection', lambda _config: pytest.fail('Unexpected database access'))
    with pytest.raises(ValueError, match='Document type must be one of'):
        db.update_payroll_entry({}, 'entry', 'document_type', 'Commission')


def test_every_grid_document_type_saves_and_can_be_reverted(qa):
    import_entry(qa, 'TEST')
    entry_id, old_type, original_pay = sql(qa, 'SELECT id, document_type, net_pay FROM payroll_entries')[0]
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    for choice in db.DOCUMENT_TYPES:
        valid, normalized, message = gui._validate_grid_edit('document_type', choice)
        assert valid, message
        assert normalized == choice
        db.update_payroll_entry(qa, entry_id, 'document_type', normalized)
        assert sql(qa, 'SELECT document_type,net_pay FROM payroll_entries WHERE id=%s', (entry_id,)) == [(choice, original_pay)]
        db.update_payroll_entry(qa, entry_id, 'document_type', old_type)
        assert sql(qa, 'SELECT document_type FROM payroll_entries WHERE id=%s', (entry_id,)) == [(old_type,)]
    # Older undo histories can contain display spellings; storage handles these too.
    db.update_payroll_entry(qa, entry_id, 'document_type', 'UnusedLeaveCompensation')
    assert sql(qa, 'SELECT document_type FROM payroll_entries WHERE id=%s', (entry_id,)) == [('unused_leave_compensation',)]
