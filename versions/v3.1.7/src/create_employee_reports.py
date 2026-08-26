#!/usr/bin/env python3
"""Combine payroll CSVs and generate per‑employee Excel reports.

This script reads one or more CSV files produced by `process_payroll.py`,
concatenates them into a single DataFrame, groups the data by employee
and month, and produces an Excel workbook containing one sheet per
employee.  Each sheet lists the pay components for that employee
broken down by month and document type (e.g. payslip, vacation
allowance, bonus) and includes monthly totals across all document
types.  Summations of EFKA/TEKA contributions are provided for both
employee and employer contributions.

Usage:
    python create_employee_reports.py --input-dir /path/to/csvs --out-xlsx payroll_reports.xlsx

You can also specify individual CSV files with repeated --csv-file
options instead of --input-dir.
"""

import argparse
import os
from typing import List

import pandas as pd


def load_payroll_data(csv_files: List[str]) -> pd.DataFrame:
    """Load and concatenate payroll CSV files into a single DataFrame.

    Args:
        csv_files: List of CSV file paths to read.

    Returns:
        A pandas DataFrame with concatenated payroll data.
    """
    frames = []
    for csv_path in csv_files:
        try:
            # Employee codes are identifiers, not numbers. Explicit string
            # loading preserves significant leading zeroes such as ``001``.
            df = pd.read_csv(
                csv_path,
                dtype={"EmployeeCode": "string"},
                keep_default_na=False,
            )
        except Exception as exc:
            print(f"Warning: failed to read {csv_path}: {exc}")
            continue
        # Ensure expected columns exist; missing numeric columns will be created as NaN
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined


def prepare_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare a summary DataFrame grouped by employee, month and document type.

    The function converts the `Date` column to a month key of the form
    `YYYY-MM`, replaces missing numeric values with zero, and aggregates
    numeric columns by summing.  It also computes per‑month totals
    across document types.

    Args:
        df: DataFrame containing payroll records.

    Returns:
        A DataFrame suitable for writing to Excel, with a multi‑index
        on (EmployeeCode, EmployeeName, Month, DocumentType) and
        aggregated numeric columns.
    """
    if df.empty:
        return df
    df = df.copy()
    # A parser can recover the employee code even when the name is absent.
    # Keep that valid payroll row and give it a stable workbook label instead
    # of letting pandas groupby silently drop its null key.
    employee_codes = df['EmployeeCode'].fillna('Unknown').astype(str).str.strip()
    employee_codes = employee_codes.mask(employee_codes == '', 'Unknown')
    df['EmployeeCode'] = employee_codes
    if 'EmployeeName' not in df.columns:
        df['EmployeeName'] = ''
    employee_names = df['EmployeeName'].fillna('').astype(str).str.strip()
    df['EmployeeName'] = employee_names.mask(
        employee_names == '',
        'Employee ' + employee_codes,
    )
    # Make sure Date is parsed and month extracted
    # Some dates may be missing; coerce errors to NaT
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df['Month'] = df['Date'].dt.to_period('M').astype('string')
    # For rows with no date, assign 'Unknown'
    df['Month'] = df['Month'].fillna('Unknown')
    # Ensure numeric fields exist and fill NaN with zero
    numeric_cols = ['BasicSalary', 'TotalEarnings', 'NetPay',
                    'EFKAEmployee', 'EFKAEmployer', 'TEKAEmployee', 'TEKAEmployer']
    for col in numeric_cols:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    # Replace missing DocumentType with 'Salary' and normalize legacy labels
    df['DocumentType'] = df['DocumentType'].fillna('Salary')
    df['DocumentType'] = df['DocumentType'].replace({'Unknown': 'Salary'})
    # Aggregate by employee, month and document type
    group_cols = ['EmployeeCode', 'EmployeeName', 'Month', 'DocumentType']
    agg_df = df.groupby(group_cols)[numeric_cols].sum().reset_index()
    # Compute monthly totals across document types
    total_df = agg_df.groupby(['EmployeeCode', 'EmployeeName', 'Month'])[numeric_cols].sum().reset_index()
    total_df['DocumentType'] = 'Total'
    # Concatenate the total rows
    combined_df = pd.concat([agg_df, total_df], ignore_index=True, sort=False)
    # Sort by month (string sorting works for YYYY-MM) and ensure totals appear last
    combined_df['DocTypeOrder'] = combined_df['DocumentType'].apply(lambda x: 1 if x == 'Total' else 0)
    combined_df = combined_df.sort_values(by=['EmployeeCode', 'Month', 'DocTypeOrder', 'DocumentType']).drop(columns=['DocTypeOrder'])
    return combined_df


def write_employee_reports(summary_df: pd.DataFrame, out_xlsx: str) -> None:
    """Write per‑employee reports to an Excel workbook.

    Args:
        summary_df: Aggregated payroll summary with columns as returned by
            `prepare_summary`.
        out_xlsx: Path to the Excel workbook to create.
    """
    if summary_df.empty:
        print("No data to write.")
        return
    with pd.ExcelWriter(
        out_xlsx,
        engine='xlsxwriter',
        engine_kwargs={'options': {'strings_to_formulas': False, 'strings_to_urls': False}},
    ) as writer:
        workbook = writer.book
        # Format definitions
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#DCE6F1'})
        money_fmt = workbook.add_format({'num_format': '#,##0.00'})
        # Iterate over employees
        used_names = set()
        for (emp_code, emp_name), emp_df in summary_df.groupby(['EmployeeCode', 'EmployeeName']):
            # Determine sheet name (use employee name truncated to 25 chars and code)
            safe_name = str(emp_name) if pd.notnull(emp_name) else f"Employee {emp_code}"
            safe_name = safe_name.strip()
            # Excel sheet names have a max length of 31 and cannot contain certain characters
            sheet_name = f"{safe_name} ({emp_code})"
            sheet_name = _sanitize_sheet_name(sheet_name, fallback=f"Employee {emp_code}")
            sheet_name = _unique_sheet_name(sheet_name, used_names)
            # Write DataFrame to sheet
            emp_df = emp_df.drop(columns=['EmployeeCode', 'EmployeeName'])  # these are implicit in sheet name
            emp_df.to_excel(writer, sheet_name=sheet_name, index=False)
            # Adjust column widths and formats
            worksheet = writer.sheets[sheet_name]
            for col_idx, col_name in enumerate(emp_df.columns):
                max_len = max(emp_df[col_name].astype(str).map(len).max(), len(col_name)) + 2
                worksheet.set_column(col_idx, col_idx, max_len)
                # Apply money format to numeric columns
                if col_name in ['BasicSalary', 'TotalEarnings', 'NetPay', 'EFKAEmployee', 'EFKAEmployer', 'TEKAEmployee', 'TEKAEmployer']:
                    worksheet.set_column(col_idx, col_idx, max_len, money_fmt)
            # Write header format
            for col_idx, _ in enumerate(emp_df.columns):
                worksheet.write(0, col_idx, emp_df.columns[col_idx], header_fmt)
    print(f"Wrote reports to {out_xlsx}")


def _unique_sheet_name(name, used_names):
    max_len = 31
    base = name[:max_len]
    candidate = base
    counter = 2
    while candidate.casefold() in used_names:
        suffix = f" ({counter})"
        trim_len = max_len - len(suffix)
        candidate = f"{base[:trim_len]}{suffix}"
        counter += 1
    used_names.add(candidate.casefold())
    return candidate


def _sanitize_sheet_name(name: str, fallback: str) -> str:
    invalid = set('[]:*?/\\')
    cleaned = ''.join('-' if ch in invalid else ch for ch in name).strip()
    if cleaned.startswith("'") or cleaned.endswith("'"):
        cleaned = cleaned.strip("'").strip()
    return cleaned or fallback


def write_detail_report(detail_df: pd.DataFrame, out_xlsx: str) -> None:
    """Write a flat, analytical report with every payroll entry."""
    if detail_df.empty:
        print("No detail data to write.")
        return

    df = detail_df.copy()
    # Normalize date to readable string
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
        df['Date'] = df['Date'].dt.strftime('%d/%m/%Y').fillna('')
    # Normalize legacy document type label
    if 'DocumentType' in df.columns:
        df['DocumentType'] = df['DocumentType'].replace({'Unknown': 'Salary'})
    # Ensure numeric columns have consistent formatting
    numeric_cols = ['BasicSalary', 'TotalEarnings', 'NetPay',
                    'EFKAEmployee', 'EFKAEmployer', 'TEKAEmployee', 'TEKAEmployer']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    sort_order = [col for col in ['EmployeeCode', 'EmployeeName', 'Date', 'DocumentType'] if col in df.columns]
    if sort_order:
        df = df.sort_values(sort_order)

    with pd.ExcelWriter(
        out_xlsx,
        engine='xlsxwriter',
        engine_kwargs={'options': {'strings_to_formulas': False, 'strings_to_urls': False}},
    ) as writer:
        df.to_excel(writer, index=False, sheet_name="Details")
        workbook = writer.book
        worksheet = writer.sheets["Details"]
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2'})
        money_fmt = workbook.add_format({'num_format': '#,##0.00'})

        for col_idx, col_name in enumerate(df.columns):
            display_lengths = df[col_name].map(
                lambda value: 0 if pd.isna(value) else len(str(value))
            )
            max_len = max(display_lengths.max(), len(col_name)) + 2
            fmt = money_fmt if col_name in numeric_cols else None
            worksheet.set_column(col_idx, col_idx, max_len, fmt)
            worksheet.write(0, col_idx, col_name, header_fmt)
    print(f"Wrote detail report to {out_xlsx}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine payroll CSVs and generate per‑employee Excel reports.")
    parser.add_argument("--input-dir", help="Directory containing payroll CSV files", required=False)
    parser.add_argument("--csv-file", action='append', help="Individual CSV file(s) to include", default=[])
    parser.add_argument("--out-xlsx", default="employee_reports.xlsx", help="Summary Excel workbook path")
    parser.add_argument("--detail-xlsx", help="Optional detailed workbook path (all entries)")
    args = parser.parse_args()
    csv_files: List[str] = []
    # If an input directory is provided, collect all CSV files
    if args.input_dir:
        if not os.path.isdir(args.input_dir):
            print(f"Error: {args.input_dir} is not a valid directory")
            return
        for fname in os.listdir(args.input_dir):
            if fname.lower().endswith('.csv'):
                csv_files.append(os.path.join(args.input_dir, fname))
    # Add any explicitly specified CSV files
    csv_files.extend(args.csv_file)
    if not csv_files:
        print("No CSV files provided. Use --input-dir or --csv-file to specify input.")
        return
    # Load and summarise data
    df = load_payroll_data(csv_files)
    summary_df = prepare_summary(df)
    # Write to Excel
    write_employee_reports(summary_df, args.out_xlsx)
    if args.detail_xlsx:
        write_detail_report(df, args.detail_xlsx)


if __name__ == '__main__':
    main()
