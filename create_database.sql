-- create_database.sql
-- Schema setup for the Payroll Processor database (PostgreSQL).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payroll_document_type') THEN
        CREATE TYPE payroll_document_type AS ENUM (
            'salary',
            'bonus',
            'vacation_allowance',
            'unused_leave_compensation',
            'other'
        );
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS employees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_code TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    role_title    TEXT,
    iban          TEXT,
    beneficiary_name TEXT,
    first_worked_date DATE,
    last_paid_date DATE,
    pay_rate_monthly NUMERIC(12,2),
    pay_rate_hourly NUMERIC(12,2),
    pay_rate_daily NUMERIC(12,2),
    pay_rate_double NUMERIC(12,2),
    pay_rate_abroad NUMERIC(12,2),
    pay_rate_abroad_double NUMERIC(12,2),
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payroll_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year           INT NOT NULL,
    month          INT NOT NULL CHECK (month BETWEEN 1 AND 12),
    run_date       DATE NOT NULL,
    source_archive TEXT NOT NULL,
    notes          TEXT,
    created_at     TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (year, month, source_archive)
);

CREATE TABLE IF NOT EXISTS payroll_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payroll_run_id UUID NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    employee_id    UUID NOT NULL REFERENCES employees(id),
    document_type  payroll_document_type NOT NULL,
    payment_date   DATE NOT NULL,
    paid_status    BOOLEAN NOT NULL DEFAULT FALSE,
    paid_date DATE,
    basic_salary   NUMERIC(12,2) DEFAULT 0,
    total_earnings NUMERIC(12,2) DEFAULT 0,
    net_pay        NUMERIC(12,2) NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS insurance_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payroll_entry_id UUID NOT NULL REFERENCES payroll_entries(id) ON DELETE CASCADE,
    efka_employee   NUMERIC(12,2) DEFAULT 0,
    efka_employer   NUMERIC(12,2) DEFAULT 0,
    teka_employee   NUMERIC(12,2) DEFAULT 0,
    teka_employer   NUMERIC(12,2) DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (payroll_entry_id)
);

CREATE TABLE IF NOT EXISTS insurance_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_year INT NOT NULL,
    claim_month INT NOT NULL CHECK (claim_month BETWEEN 1 AND 12),
    submission_date DATE,
    total_earnings NUMERIC(12,2) DEFAULT 0,
    total_contributions NUMERIC(12,2) DEFAULT 0,
    tpte_code TEXT,
    claim_type TEXT DEFAULT 'EFKA',
    paid_status BOOLEAN DEFAULT FALSE,
    paid_date DATE,
    source_pdf TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (claim_year, claim_month, tpte_code, source_pdf)
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payroll_entry_id UUID NOT NULL REFERENCES payroll_entries(id) ON DELETE CASCADE,
    source_pdf       TEXT NOT NULL,
    checksum         TEXT,
    imported_at      TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (payroll_entry_id)
);

CREATE INDEX IF NOT EXISTS idx_payroll_entries_employee
    ON payroll_entries(employee_id);

CREATE INDEX IF NOT EXISTS idx_payroll_entries_run
    ON payroll_entries(payroll_run_id);

CREATE INDEX IF NOT EXISTS idx_payroll_entries_date
    ON payroll_entries(payment_date);

CREATE INDEX IF NOT EXISTS idx_documents_source
    ON documents(source_pdf);

CREATE INDEX IF NOT EXISTS idx_insurance_entry
    ON insurance_contributions(payroll_entry_id);

CREATE INDEX IF NOT EXISTS idx_insurance_claims_period
    ON insurance_claims(claim_year, claim_month);

DROP VIEW IF EXISTS v_payroll_costs;
DROP VIEW IF EXISTS v_monthly_payroll_summary;

CREATE VIEW v_payroll_costs AS
SELECT
    e.full_name AS employee_name,
    d.source_pdf,
    pe.net_pay,
    (ic.efka_employer + ic.teka_employer) AS employer_insurance,
    pe.net_pay + (ic.efka_employer + ic.teka_employer) AS employer_cost
FROM payroll_entries pe
JOIN employees e ON e.id = pe.employee_id
JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
JOIN documents d ON d.payroll_entry_id = pe.id;

CREATE VIEW v_monthly_payroll_summary AS
SELECT
    pr.year,
    pr.month,
    e.full_name AS employee_name,
    SUM(pe.net_pay) AS total_net_pay,
    SUM(ic.efka_employee + ic.teka_employee) AS employee_insurance,
    SUM(ic.efka_employer + ic.teka_employer) AS employer_insurance
FROM payroll_runs pr
JOIN payroll_entries pe ON pe.payroll_run_id = pr.id
JOIN employees e ON e.id = pe.employee_id
JOIN insurance_contributions ic ON ic.payroll_entry_id = pe.id
GROUP BY pr.year, pr.month, e.full_name;
