/*
 * import_payroll.sql
 *
 * SQL script to import raw payroll data from a staging table into the
 * normalized payroll schema.  This script assumes that you have created
 * a table called `staging_payroll` with columns matching the payroll
 * CSV export produced by the PayrollProcessor application.  The normalized
 * tables (`employees`, `payroll_runs`, `payroll_entries`,
 * `insurance_contributions`, `documents`) and the enum type
 * `payroll_document_type` must already exist.
 *
 * The staging table should contain at least the following columns:
 *   employee_code      TEXT
 *   employee_name      TEXT
 *   document_type      TEXT
 *   basic_salary       NUMERIC
 *   total_earnings     NUMERIC
 *   net_pay            NUMERIC
 *   date               DATE        -- parsed from DD/MM/YYYY format
 *   efka_employee      NUMERIC
 *   efka_employer      NUMERIC
 *   teka_employee      NUMERIC
 *   teka_employer      NUMERIC
 *   source_pdf         TEXT
 *   source_archive     TEXT
 *
 * To use this script:
 *  1. Create the `staging_payroll` table (temporary or permanent) with
 *     the columns shown above.
 *  2. Load your CSV data into `staging_payroll` using COPY, e.g.:
 *        \copy staging_payroll FROM '/path/to/extracted.csv' WITH CSV HEADER;
 *  3. Execute this script.  It will populate the normalized tables and
 *     leave the staging table intact (no deletes performed).
 */

BEGIN;

-- 1. Insert or update employees.
--    The employees table stores one row per person.  We use the
--    external `employee_code` as the natural key and update the name
--    if it has changed.
INSERT INTO employees (employee_code, full_name, active)
SELECT DISTINCT sp.employee_code,
       sp.employee_name,
       TRUE
FROM staging_payroll sp
ON CONFLICT (employee_code) DO UPDATE
  SET full_name = EXCLUDED.full_name;

-- 2. Insert or update payroll runs.
--    Each run corresponds to a unique combination of year, month
--    and source_archive (the ZIP file).  The run_date is set to
--    the minimum payment date for that run.  If a run already
--    exists, nothing is done.
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

-- 3. Insert payroll entries and collect data for insurance and documents.
--    We first compute the foreign keys for each row (employee_id and
--    payroll_run_id) and then insert the main payroll entry.  The
--    RETURNING clause exposes the inserted entry IDs along with the
--    insurance values and PDF information. Document types are trimmed,
--    lowercased, and mapped to enum values.
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
-- 4. Insert document records for each payroll entry. We set
--    `checksum` to NULL; you may compute a real checksum later.
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

COMMIT;
