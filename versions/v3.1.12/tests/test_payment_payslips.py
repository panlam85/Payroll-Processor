import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

import db_storage as db
import payment_payslips as slips
from payroll_gui import PayrollProcessorGUI, filedialog, messagebox
from test_employee_management import import_entry, qa, sql


@pytest.fixture
def payment():
    return slips.Payment("entry", "0060", "Example Employee", datetime.date(2026, 6, 1),
                         "salary", Decimal("100"), None)


@pytest.mark.parametrize("answer,chosen,expected", [(False, None, 0), (True, "", 0), (True, "slip.pdf", 1)])
def test_optional_picker(monkeypatch, tmp_path, payment, answer, chosen, expected):
    gui = Mock(db_config={}, archive_dir=tmp_path)
    monkeypatch.setattr(slips, "find_payment", lambda *_: payment)
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: answer)
    picker = Mock(return_value=chosen)
    monkeypatch.setattr(filedialog, "askopenfilename", picker)
    attach = Mock(return_value=tmp_path / "saved.pdf")
    monkeypatch.setattr(slips, "attach", attach)
    PayrollProcessorGUI._offer_payment_payslips(gui, ["entry"])
    assert picker.call_count == int(answer)
    assert attach.call_count == expected
    if expected:
        attach.assert_called_once_with({}, tmp_path, "entry", chosen)
    gui.show_message.assert_not_called()


def test_cancel_remaining_skips_all_attachments(monkeypatch, payment):
    gui = Mock()
    find = Mock(return_value=payment)
    monkeypatch.setattr(slips, "find_payment", find)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *args, **kwargs: None)
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kwargs: pytest.fail("Unexpected picker"))
    PayrollProcessorGUI._offer_payment_payslips(gui, ["first", "second"])
    find.assert_called_once_with(gui.db_config, "first")


def test_payment_archive_and_upgrade(qa, tmp_path):
    import_entry(qa, "0060")
    import_entry(qa, "0060", date="02/06/2026", amount="50")
    import_entry(qa, "60")  # Same name, distinct employee code
    sql(qa, "ALTER TABLE payroll_entries DROP COLUMN payslip_archive_path")
    slips.ensure_schema(qa)
    slips.ensure_schema(qa)
    changed = []
    assert db.mark_entries_paid_for_month(qa, "0060", year=2026, month=6, changed_ids=changed) == 2
    assert db.mark_entries_paid_for_month(qa, "0060", year=2026, month=6, changed_ids=changed) == 0
    assert len(set(changed)) == 2
    assert not db.update_payroll_entry(qa, changed[0], "paid_status", True)
    archive = tmp_path / "Source PDFs"
    pdf = tmp_path / "payslip.pdf"
    pdf.write_bytes(b"Wrong file type")
    with pytest.raises(ValueError, match="PDF"):
        slips.attach(qa, archive, changed[0], pdf)
    assert slips.find_payment(qa, changed[0]).archive_path is None
    pdf.write_bytes(b"%PDF-1.7\nfirst payment")
    first = slips.attach(qa, archive, changed[0], pdf)
    assert first.parent == archive / "2026/06/0060 - Example Employee/Payslips"
    assert first.read_bytes() == pdf.read_bytes()
    pdf.write_bytes(b"%PDF-1.7\nsecond payment")
    second = slips.attach(qa, archive, changed[1], pdf)
    assert second != first and second.read_bytes() == pdf.read_bytes()
    assert slips.attach(qa, archive, changed[0], pdf) == first
    assert first.read_bytes() != pdf.read_bytes()
    assert slips.archive_file(archive, slips.find_payment(qa, changed[0]).archive_path) == first
    others = []
    assert db.mark_paid_by_receipt_total(qa, "Example Employee", 100, datetime.date(2026, 6, 2),
                                         changed_ids=others) == 1
    assert slips.find_payment(qa, others[0]).code == "60"
    assert slips.find_payment(qa, others[0]).archive_path is None
    db.update_payroll_entry(qa, others[0], "paid_status", False)
    with pytest.raises(ValueError, match="no longer marked paid"):
        slips.attach(qa, archive, others[0], pdf)
