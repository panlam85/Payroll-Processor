"""PDF attachments for individual paid payroll entries in the employee archive."""

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import db_storage


@dataclass(frozen=True)
class Payment:
    id: str
    code: str
    name: str
    date: date
    document: str
    net_pay: Decimal
    archive_path: str | None

    @property
    def label(self):
        return (f"{self.name} ({self.code}) · {self.date:%d/%m/%Y}\n"
                f"{self.document.replace('_', ' ').title()} · €{self.net_pay:,.2f}")


def ensure_schema(config):
    with db_storage.get_connection(config) as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE payroll_entries ADD COLUMN IF NOT EXISTS payslip_archive_path TEXT")


def _payment(cur, entry_id, *, lock=False):
    query = """
        SELECT pe.id::text, e.employee_code, e.full_name, pe.payment_date,
               pe.document_type, pe.net_pay, pe.payslip_archive_path
        FROM payroll_entries pe JOIN employees e ON e.id = pe.employee_id
        WHERE pe.id = %s AND pe.paid_status
    """
    cur.execute(query + (" FOR UPDATE OF pe" if lock else ""), (entry_id,))
    row = cur.fetchone()
    return Payment(*row) if row else None


def find_payment(config, entry_id):
    with db_storage.get_connection(config) as conn, conn.cursor() as cur:
        return _payment(cur, entry_id)


def archive_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError("The payslip path is outside the employee archive.")
    return path


def attach(config, root, entry_id, source):
    if str(config.get("role", "editor")).lower() != "editor":
        raise PermissionError("Enable editing to add a payslip.")
    from process_payroll import _derive_archive_dir

    with db_storage.get_connection(config) as conn, conn.cursor() as cur:
        payment = _payment(cur, entry_id, lock=True)
        if not payment:
            raise ValueError("This payment is no longer marked paid.")
        if payment.archive_path:
            destination = archive_file(root, payment.archive_path)
            if destination.is_file():
                return destination
        else:
            entry = {"EmployeeCode": payment.code, "EmployeeName": payment.name,
                     "Date": payment.date.strftime("%d/%m/%Y")}
            folder = Path(_derive_archive_dir("", entry))
            relative = folder / "Payslips" / f"{payment.date:%Y-%m-%d}_{payment.id}.pdf"
            destination = archive_file(root, relative)

        with Path(source).open("rb") as pdf:
            if pdf.read(5) != b"%PDF-":
                raise ValueError("Choose a PDF payslip.")
            pdf.seek(0)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Publish only a complete file, even if copying fails or is interrupted.
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staged:
                temp_path = Path(staged.name)
                try:
                    shutil.copyfileobj(pdf, staged)
                    staged.flush()
                    cur.execute("UPDATE payroll_entries SET payslip_archive_path = %s WHERE id = %s",
                                (str(destination.relative_to(Path(root).resolve())), payment.id))
                    os.replace(temp_path, destination)
                finally:
                    temp_path.unlink(missing_ok=True)
    return destination
