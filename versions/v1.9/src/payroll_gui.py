#!/usr/bin/env python3
"""
Payroll Processor GUI Application

A simple drag-and-drop interface for processing payroll ZIP files.
Users can drag ZIP files containing payroll PDFs, and the application
will process them to generate employee reports.

Requirements:
    - tkinter (built-in with Python)
    - tkinterdnd2 (pip install tkinterdnd2)
    - pandas (pip install pandas)
    - xlsxwriter (pip install xlsxwriter)

Usage:
    python3 payroll_gui.py
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tempfile
from typing import List, Dict
import datetime
from pathlib import Path
import subprocess

# Try to import tkinterdnd2 for drag-and-drop functionality
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DRAG_DROP_AVAILABLE = True
except ImportError:
    DRAG_DROP_AVAILABLE = False
    print("Warning: tkinterdnd2 not installed. Drag-and-drop will not be available.")
    print("Install with: pip install tkinterdnd2")

# Import our existing payroll processing functions
import process_payroll
import create_employee_reports
import pandas as pd

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import db_storage

DEFAULT_REPORT_DIR = Path.home() / "Documents" / "Payroll Processor Reports"


class PayrollProcessorGUI:
    """Main GUI application for payroll processing."""
    
    def __init__(self):
        """Initialize the GUI application."""
        # Create main window
        if DRAG_DROP_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()
            
        self.configure_app_identity()

        self.root.title("Payroll Processor")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)
        
        # Variables
        self.zip_files = []  # List of selected ZIP files
        self.processing = False
        self.temp_dir = None
        self.missing_dependencies = self.check_missing_dependencies()
        self.report_dir = DEFAULT_REPORT_DIR
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.report_dir / "Source PDFs"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.last_output_path = None
        self.current_output_paths = None
        self.db_config = db_storage.load_db_config()
        
        # Create GUI elements
        self.create_widgets()
        self.create_menu()
        
        # Setup drag and drop if available
        if DRAG_DROP_AVAILABLE:
            self.setup_drag_drop()
        
        # Surface dependency issues immediately
        self.warn_missing_dependencies()

    def configure_app_identity(self):
        """Ensure the app name shows as Payroll Processor on macOS."""
        try:
            self.root.tk.call('tk', 'appname', 'Payroll Processor')
            if self.root.tk.call('tk', 'windowingsystem') == 'aqua':
                self.root.tk.call('tk::mac::SetApplicationName', 'Payroll Processor')
                self.root.tk.call('tk::mac::setmenuname', 'Payroll Processor')
        except tk.TclError:
            pass
    
    def create_widgets(self):
        """Create and layout all GUI widgets."""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.processing_tab = ttk.Frame(self.notebook, padding="10")
        self.db_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.processing_tab, text="Processing")
        self.notebook.add(self.db_tab, text="Database")
        self.analytics_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.analytics_tab, text="Analytics")


        self.processing_tab.columnconfigure(0, weight=1)
        self.processing_tab.rowconfigure(2, weight=1)

        # Title
        title_label = ttk.Label(
            self.processing_tab,
            text="Payroll Processor",
            font=("Arial", 16, "bold"),
        )
        title_label.grid(row=0, column=0, pady=(0, 20))

        # Instructions
        self.instructions_label = ttk.Label(
            self.processing_tab,
            text=self.get_instructions_text(),
            justify=tk.CENTER,
            wraplength=600,
        )
        self.instructions_label.grid(row=1, column=0, pady=(0, 20))

        # File list frame
        list_frame = ttk.LabelFrame(self.processing_tab, text="Selected Files", padding="5")
        list_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 20))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        # File listbox with scrollbar
        listbox_frame = ttk.Frame(list_frame)
        listbox_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        listbox_frame.columnconfigure(0, weight=1)
        listbox_frame.rowconfigure(0, weight=1)

        self.file_listbox = tk.Listbox(listbox_frame, selectmode=tk.MULTIPLE)
        self.file_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Scrollbar for listbox
        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.file_listbox.configure(yscrollcommand=scrollbar.set)

        # Drag and drop area (visual indicator)
        if DRAG_DROP_AVAILABLE:
            self.drop_label = ttk.Label(
                listbox_frame,
                text="Drop ZIP files here or use Browse button",
                foreground="gray",
                anchor=tk.CENTER,
            )
            self.drop_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Button frame
        button_frame = ttk.Frame(self.processing_tab)
        button_frame.grid(row=3, column=0, pady=(0, 20))

        # Browse button
        self.browse_btn = ttk.Button(button_frame, text="Browse Files", command=self.browse_files)
        self.browse_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Remove selected button
        self.remove_btn = ttk.Button(button_frame, text="Remove Selected", command=self.remove_selected_files)
        self.remove_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Clear all button
        self.clear_btn = ttk.Button(button_frame, text="Clear All", command=self.clear_all_files)
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 20))

        # Output folder button
        self.output_btn = ttk.Button(button_frame, text="Output Folder", command=self.choose_output_folder)
        self.output_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Generate reports button
        self.generate_btn = ttk.Button(
            button_frame,
            text="Generate Reports",
            command=self.generate_reports,
            style="Accent.TButton",
        )
        self.generate_btn.pack(side=tk.LEFT)

        # Progress frame
        progress_frame = ttk.Frame(self.processing_tab)
        progress_frame.grid(row=4, column=0, sticky=(tk.W, tk.E))
        progress_frame.columnconfigure(0, weight=1)

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

        # Status label
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        self.status_label = ttk.Label(progress_frame, textvariable=self.status_var)
        self.status_label.grid(row=1, column=0)

        # Output location info
        self.output_location_var = tk.StringVar(value=f"Reports folder: {self.report_dir}")
        self.output_location_label = ttk.Label(
            progress_frame,
            textvariable=self.output_location_var,
            font=("Arial", 9),
        )
        self.output_location_label.grid(row=2, column=0, pady=(4, 0))

        self.create_db_tab()
        self.create_analytics_tab()
        self.update_ui_state()

    def create_analytics_tab(self):
        """Create the analytics tab with charts."""
        self.analytics_tab.columnconfigure(0, weight=1)
        self.analytics_tab.rowconfigure(1, weight=1)

        header = ttk.Frame(self.analytics_tab)
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        header.columnconfigure(8, weight=1)

        ttk.Label(header, text="Analytics", font=("Arial", 14, "bold")).grid(row=0, column=0, padx=(0, 10))
        refresh_btn = ttk.Button(header, text="Refresh Charts", command=self.refresh_analytics)
        refresh_btn.grid(row=0, column=1, padx=(0, 10))

        ttk.Label(header, text="Year").grid(row=0, column=2, padx=(0, 6))
        self.analytics_year_var = tk.StringVar(value="All")
        self.analytics_year_combo = ttk.Combobox(header, textvariable=self.analytics_year_var, state="readonly", width=8)
        self.analytics_year_combo.grid(row=0, column=3, padx=(0, 10))
        self.analytics_year_combo.bind("<<ComboboxSelected>>", self._on_analytics_year_change)
        self.analytics_year_combo["values"] = ["All"]

        ttk.Label(header, text="Month").grid(row=0, column=4, padx=(0, 6))
        self.analytics_month_var = tk.StringVar(value="All")
        self.analytics_month_combo = ttk.Combobox(header, textvariable=self.analytics_month_var, state="readonly", width=6)
        self.analytics_month_combo.grid(row=0, column=5, padx=(0, 10))
        self.analytics_month_combo["values"] = ["All"]

        ttk.Label(header, text="Top Employees").grid(row=0, column=6, padx=(0, 6))
        self.analytics_top_n_var = tk.IntVar(value=10)
        top_spin = ttk.Spinbox(header, from_=5, to=50, textvariable=self.analytics_top_n_var, width=6)
        top_spin.grid(row=0, column=7, padx=(0, 10))

        self.analytics_status_var = tk.StringVar(value="Ready to refresh.")
        ttk.Label(header, textvariable=self.analytics_status_var).grid(row=0, column=8, sticky=tk.W)

        charts_frame = ttk.Frame(self.analytics_tab)
        charts_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        charts_frame.columnconfigure(0, weight=1)
        charts_frame.columnconfigure(1, weight=1)
        charts_frame.rowconfigure(0, weight=1)
        charts_frame.rowconfigure(1, weight=1)

        self.analytics_fig = Figure(figsize=(10, 8), dpi=100)
        grid = self.analytics_fig.add_gridspec(3, 2, height_ratios=[1, 1, 1.2])
        self.analytics_monthly_ax = self.analytics_fig.add_subplot(grid[0, 0])
        self.analytics_insurance_ax = self.analytics_fig.add_subplot(grid[0, 1])
        self.analytics_doc_type_ax = self.analytics_fig.add_subplot(grid[1, 0])
        self.analytics_heatmap_ax = self.analytics_fig.add_subplot(grid[1, 1])
        self.analytics_employee_ax = self.analytics_fig.add_subplot(grid[2, :])
        self.analytics_heatmap_cbar = None

        self.analytics_canvas = FigureCanvasTkAgg(self.analytics_fig, master=charts_frame)
        self.analytics_canvas.get_tk_widget().grid(row=0, column=0, rowspan=2, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))

    def refresh_analytics(self):
        """Refresh analytics charts from the database."""
        if not self.db_config.get("enabled"):
            self.analytics_status_var.set("Database storage is disabled.")
            self.show_message(
                "Database Disabled",
                "Enable database storage in Settings to view analytics.",
                kind="warning",
            )
            return

        self.analytics_status_var.set("Refreshing...")
        try:
            self._refresh_analytics_filters()
            year_val = self.analytics_year_var.get()
            month_val = self.analytics_month_var.get()
            year = int(year_val) if year_val and year_val != "All" else None
            month = int(month_val) if month_val and month_val != "All" else None

            monthly_rows = db_storage.fetch_monthly_summary(self.db_config, year=year, month=month)
            top_n = int(self.analytics_top_n_var.get())
            employee_rows = db_storage.fetch_employer_costs_by_employee(
                self.db_config,
                limit=top_n,
                year=year,
                month=month,
            )
            doc_type_rows = db_storage.fetch_document_type_breakdown(self.db_config, year=year, month=month)

            heatmap_rows = []
            if year is not None and month is not None:
                heatmap_rows = db_storage.fetch_payment_heatmap(
                    self.db_config,
                    year=year,
                    month=month,
                    limit=top_n,
                )

            self._plot_monthly_burn(monthly_rows)
            self._plot_insurance_breakdown(monthly_rows)
            self._plot_doc_type_breakdown(doc_type_rows)
            self._plot_payment_heatmap(heatmap_rows, year=year, month=month)
            self._plot_employee_costs(employee_rows)
            self.analytics_canvas.draw()
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.analytics_status_var.set(f"Last refreshed at {timestamp}.")
        except Exception as exc:
            self.analytics_status_var.set("Refresh failed.")
            self.show_message("Analytics Error", str(exc), kind="warning")

    def _plot_monthly_burn(self, rows):
        self.analytics_monthly_ax.clear()
        if not rows:
            self.analytics_monthly_ax.set_title("Monthly Payroll Burn")
            self.analytics_monthly_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            return

        monthly = {}
        for year, month, _, total_net_pay, _, employer_insurance in rows:
            key = f"{int(year):04d}-{int(month):02d}"
            entry = monthly.setdefault(key, {"net": 0.0, "employer": 0.0})
            entry["net"] += float(total_net_pay or 0)
            entry["employer"] += float(employer_insurance or 0)

        labels = sorted(monthly.keys())
        net_vals = [monthly[label]["net"] for label in labels]
        employer_cost = [monthly[label]["net"] + monthly[label]["employer"] for label in labels]

        self.analytics_monthly_ax.plot(labels, net_vals, marker="o", label="Net Pay")
        self.analytics_monthly_ax.plot(labels, employer_cost, marker="o", label="Employer Cost")
        self.analytics_monthly_ax.set_title("Monthly Payroll Burn")
        self.analytics_monthly_ax.set_ylabel("Amount")
        self.analytics_monthly_ax.tick_params(axis="x", rotation=45)
        self.analytics_monthly_ax.legend()

    def _plot_doc_type_breakdown(self, rows):
        self.analytics_doc_type_ax.clear()
        if not rows:
            self.analytics_doc_type_ax.set_title("Salary vs Bonus vs Allowances")
            self.analytics_doc_type_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            return

        monthly = {}
        for year, month, category, total_net_pay in rows:
            key = f"{int(year):04d}-{int(month):02d}"
            entry = monthly.setdefault(key, {"Salary": 0.0, "Bonus": 0.0, "Allowance": 0.0, "Other": 0.0})
            entry[category] = float(total_net_pay or 0)

        labels = sorted(monthly.keys())
        salary_vals = [monthly[label]["Salary"] for label in labels]
        bonus_vals = [monthly[label]["Bonus"] for label in labels]
        allowance_vals = [monthly[label]["Allowance"] for label in labels]
        other_vals = [monthly[label]["Other"] for label in labels]

        self.analytics_doc_type_ax.bar(labels, salary_vals, label="Salary")
        self.analytics_doc_type_ax.bar(labels, bonus_vals, bottom=salary_vals, label="Bonus")
        stacked_base = [salary_vals[i] + bonus_vals[i] for i in range(len(labels))]
        self.analytics_doc_type_ax.bar(labels, allowance_vals, bottom=stacked_base, label="Allowance")
        if any(other_vals):
            stacked_base = [stacked_base[i] + allowance_vals[i] for i in range(len(labels))]
            self.analytics_doc_type_ax.bar(labels, other_vals, bottom=stacked_base, label="Other")

        self.analytics_doc_type_ax.set_title("Salary vs Bonus vs Allowances")
        self.analytics_doc_type_ax.tick_params(axis="x", rotation=45)
        self.analytics_doc_type_ax.legend()

    def _plot_insurance_breakdown(self, rows):
        self.analytics_insurance_ax.clear()
        if not rows:
            self.analytics_insurance_ax.set_title("Insurance Breakdown")
            self.analytics_insurance_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            return

        monthly = {}
        for year, month, _, _, employee_insurance, employer_insurance in rows:
            key = f"{int(year):04d}-{int(month):02d}"
            entry = monthly.setdefault(key, {"employee": 0.0, "employer": 0.0})
            entry["employee"] += float(employee_insurance or 0)
            entry["employer"] += float(employer_insurance or 0)

        labels = sorted(monthly.keys())
        employee_vals = [monthly[label]["employee"] for label in labels]
        employer_vals = [monthly[label]["employer"] for label in labels]

        self.analytics_insurance_ax.bar(labels, employer_vals, label="Employer Insurance")
        self.analytics_insurance_ax.bar(labels, employee_vals, bottom=employer_vals, label="Employee Insurance")
        self.analytics_insurance_ax.set_title("Insurance Contribution Breakdown")
        self.analytics_insurance_ax.tick_params(axis="x", rotation=45)
        self.analytics_insurance_ax.legend()

    def _refresh_analytics_filters(self):
        years = db_storage.fetch_available_years(self.db_config)
        year_values = ["All"] + [str(year) for year in years]
        self.analytics_year_combo["values"] = year_values
        if self.analytics_year_var.get() not in year_values:
            self.analytics_year_var.set(year_values[0] if year_values else "All")
        self._refresh_month_values()

    def _refresh_month_values(self):
        year_val = self.analytics_year_var.get()
        if year_val == "All" or not year_val:
            self.analytics_month_combo["values"] = ["All"]
            self.analytics_month_var.set("All")
            return
        months = db_storage.fetch_available_months(self.db_config, int(year_val))
        month_values = ["All"] + [f"{month:02d}" for month in months]
        self.analytics_month_combo["values"] = month_values
        if self.analytics_month_var.get() not in month_values:
            self.analytics_month_var.set(month_values[0] if month_values else "All")

    def _on_analytics_year_change(self, _event=None):
        if not self.db_config.get("enabled"):
            return
        try:
            self._refresh_month_values()
        except Exception:
            pass

    def _plot_payment_heatmap(self, rows, year=None, month=None):
        self.analytics_heatmap_ax.clear()
        if self.analytics_heatmap_cbar is not None:
            self.analytics_heatmap_cbar.remove()
            self.analytics_heatmap_cbar = None
        if year is None or month is None:
            self.analytics_heatmap_ax.set_title("Payment Heat-map")
            self.analytics_heatmap_ax.text(0.5, 0.5, "Select year and month", ha="center", va="center")
            return
        if not rows:
            self.analytics_heatmap_ax.set_title("Payment Heat-map")
            self.analytics_heatmap_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            return

        employees = sorted({row[0] for row in rows})
        dates = sorted({row[1] for row in rows})
        date_labels = [date.strftime("%d") for date in dates]
        data_matrix = [[0.0 for _ in dates] for _ in employees]
        emp_index = {name: idx for idx, name in enumerate(employees)}
        date_index = {date: idx for idx, date in enumerate(dates)}
        for employee, payment_date, total_net in rows:
            i = emp_index[employee]
            j = date_index[payment_date]
            data_matrix[i][j] = float(total_net or 0)

        im = self.analytics_heatmap_ax.imshow(data_matrix, aspect="auto", cmap="YlGnBu")
        self.analytics_heatmap_ax.set_title("Payment Heat-map")
        self.analytics_heatmap_ax.set_yticks(range(len(employees)))
        self.analytics_heatmap_ax.set_yticklabels(employees)
        self.analytics_heatmap_ax.set_xticks(range(len(date_labels)))
        self.analytics_heatmap_ax.set_xticklabels(date_labels, rotation=90)
        self.analytics_heatmap_cbar = self.analytics_fig.colorbar(im, ax=self.analytics_heatmap_ax, fraction=0.046, pad=0.04)

    def _plot_employee_costs(self, rows):
        self.analytics_employee_ax.clear()
        if not rows:
            self.analytics_employee_ax.set_title("Cost Per Employee")
            self.analytics_employee_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            return

        employees = [row[0] for row in rows]
        costs = [float(row[1] or 0) for row in rows]
        self.analytics_employee_ax.barh(employees, costs)
        self.analytics_employee_ax.set_title("Cost Per Employee")
        self.analytics_employee_ax.set_xlabel("Employer Cost")
        self.analytics_employee_ax.invert_yaxis()

    def create_db_tab(self):
        """Create the database views tab."""
        self.db_tab.columnconfigure(0, weight=1)
        self.db_tab.rowconfigure(2, weight=1)

        title_label = ttk.Label(self.db_tab, text="Database Views", font=("Arial", 14, "bold"))
        title_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        toolbar = ttk.Frame(self.db_tab)
        toolbar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        toolbar.columnconfigure(6, weight=1)

        refresh_btn = ttk.Button(toolbar, text="Refresh Data", command=self.refresh_db_views)
        refresh_btn.grid(row=0, column=0, padx=(0, 10))

        ttk.Label(toolbar, text="Filter").grid(row=0, column=1, sticky=tk.W)
        self.db_filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(toolbar, textvariable=self.db_filter_var, width=24)
        filter_entry.grid(row=0, column=2, padx=(6, 10), sticky=tk.W)

        ttk.Label(toolbar, text="Limit").grid(row=0, column=3, sticky=tk.W)
        self.db_limit_var = tk.IntVar(value=500)
        limit_spin = ttk.Spinbox(toolbar, from_=50, to=5000, textvariable=self.db_limit_var, width=6)
        limit_spin.grid(row=0, column=4, padx=(6, 10), sticky=tk.W)

        columns_btn = ttk.Button(toolbar, text="Columns...", command=self.open_column_selector)
        columns_btn.grid(row=0, column=5, padx=(0, 10))

        self.db_status_var = tk.StringVar(value="Ready to refresh.")
        status_label = ttk.Label(toolbar, textvariable=self.db_status_var)
        status_label.grid(row=0, column=6, sticky=tk.W)

        self.db_views_notebook = ttk.Notebook(self.db_tab)
        self.db_views_notebook.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.db_view_trees = {}
        self.db_view_columns = {
            "v_monthly_payroll_summary": [
                "year",
                "month",
                "employee_name",
                "total_net_pay",
                "employee_insurance",
                "employer_insurance",
            ],
            "v_payroll_costs": [
                "employee_name",
                "source_pdf",
                "net_pay",
                "employer_insurance",
                "employer_cost",
            ],
        }
        self.db_view_available_columns = {}
        for view_name, title in (
            ("v_monthly_payroll_summary", "Monthly Summary"),
            ("v_payroll_costs", "Payroll Costs"),
        ):
            frame = ttk.Frame(self.db_views_notebook, padding="5")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)

            tree = ttk.Treeview(frame, columns=(), show="headings")
            tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

            y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
            y_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
            x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
            x_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))

            tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

            self.db_views_notebook.add(frame, text=title)
            self.db_view_trees[view_name] = tree

    def refresh_db_views(self):
        """Refresh data shown in the database views tab."""
        if not self.db_config.get("enabled"):
            self.db_status_var.set("Database storage is disabled.")
            self.show_message(
                "Database Disabled",
                "Enable database storage in Settings to view data.",
                kind="warning",
            )
            return

        self.db_status_var.set("Refreshing...")
        errors = []
        for view_name, tree in self.db_view_trees.items():
            try:
                limit = int(self.db_limit_var.get())
                columns, rows = db_storage.fetch_view_rows(self.db_config, view_name, limit=limit)
                self.db_view_available_columns[view_name] = columns
                display_columns = self.db_view_columns.get(view_name, columns)
                columns, rows = self._filter_view_columns(columns, rows, display_columns)
                rows = self._apply_text_filter(rows)
                self._reset_treeview(tree, columns)
                self._populate_treeview(tree, rows)
            except Exception as exc:
                errors.append(f"{view_name}: {exc}")

        if errors:
            self.db_status_var.set("Refresh completed with errors.")
            self.show_message("Database Error", "\n".join(errors), kind="warning")
        else:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db_status_var.set(f"Last refreshed at {timestamp}.")

    def _reset_treeview(self, tree, columns):
        tree.delete(*tree.get_children())
        tree["columns"] = columns
        for col in columns:
            tree.heading(col, text=col)
            width = max(100, len(col) * 10)
            tree.column(col, width=width, anchor=tk.W)

    def _populate_treeview(self, tree, rows):
        for row in rows:
            tree.insert("", tk.END, values=row)

    def _apply_text_filter(self, rows):
        text = self.db_filter_var.get().strip().lower()
        if not text:
            return rows
        filtered = []
        for row in rows:
            combined = " ".join("" if value is None else str(value) for value in row)
            if text in combined.lower():
                filtered.append(row)
        return filtered

    def _filter_view_columns(self, columns, rows, keep_columns):
        if not columns:
            return columns, rows
        indices = [columns.index(col) for col in keep_columns if col in columns]
        filtered_columns = [columns[idx] for idx in indices]
        filtered_rows = [tuple(row[idx] for idx in indices) for row in rows]
        return filtered_columns, filtered_rows

    def open_column_selector(self):
        """Open a dialog to pick visible columns for the active view."""
        current = self.db_views_notebook.select()
        if not current:
            return
        view_name = None
        for name, tree in self.db_view_trees.items():
            if str(tree.master) == str(current):
                view_name = name
                break
        if not view_name:
            return

        available = self.db_view_available_columns.get(view_name, [])
        if not available:
            self.show_message("Columns", "Refresh data first to load columns.", kind="info")
            return

        selected = set(self.db_view_columns.get(view_name, available))
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Columns")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding="12")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        vars_by_col = {}
        for idx, col in enumerate(available):
            var = tk.BooleanVar(value=col in selected)
            vars_by_col[col] = var
            chk = ttk.Checkbutton(frame, text=col, variable=var)
            chk.grid(row=idx, column=0, sticky=tk.W)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=len(available) + 1, column=0, sticky=tk.E, pady=(10, 0))

        def on_apply():
            chosen = [col for col in available if vars_by_col[col].get()]
            if not chosen:
                self.show_message("Columns", "Select at least one column.", kind="warning")
                return
            self.db_view_columns[view_name] = chosen
            dialog.destroy()
            self.refresh_db_views()

        ttk.Button(button_frame, text="Apply", command=on_apply).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def get_instructions_text(self):
        """Build the instructions text based on drag/drop and output folder."""
        if DRAG_DROP_AVAILABLE:
            return ("Drag and drop ZIP files containing payroll PDFs, "
                    "or click 'Browse' to select files.\n"
                    "Then click 'Generate Reports' to process all files.\n"
                    f"Summary + detail Excel files are saved to:\n{self.report_dir}\n"
                    f"Source PDFs are archived under:\n{self.archive_dir}")
        return ("Click 'Browse' to select ZIP files containing payroll PDFs.\n"
                "Then click 'Generate Reports' to process all files.\n"
                f"Summary + detail Excel files are saved to:\n{self.report_dir}\n"
                f"Source PDFs are archived under:\n{self.archive_dir}")

    def choose_output_folder(self):
        """Allow the user to choose the output folder."""
        new_dir = filedialog.askdirectory(
            title="Select Output Folder",
            initialdir=str(self.report_dir)
        )
        if not new_dir:
            return
        self.report_dir = Path(new_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.report_dir / "Source PDFs"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.output_location_var.set(f"Reports folder: {self.report_dir}")
        self.instructions_label.configure(text=self.get_instructions_text())

    def create_menu(self):
        """Create the app menu with About and Help items."""
        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Database Settings", command=self.open_db_settings)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About Payroll Processor", command=self.show_about)
        help_menu.add_separator()
        help_menu.add_command(label="How to Use Payroll Processor", command=self.show_help)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

        try:
            self.root.createcommand("tkAboutDialog", self.show_about)
        except tk.TclError:
            pass

    def show_about(self):
        """Display About dialog."""
        messagebox.showinfo(
            "About Payroll Processor",
            "Payroll Processor\n"
            "Version 1.9\n"
            "Author: panlam\n"
            "Processes payroll ZIPs and generates Excel reports."
        )

    def show_help(self):
        """Display basic how-to instructions."""
        messagebox.showinfo(
            "How to Use Payroll Processor",
            "1) Drag and drop ZIP files containing payroll PDFs, or click Browse.\n"
            "2) Click Generate Reports.\n"
            "3) Two Excel files are saved in:\n"
            f"{self.report_dir}\n\n"
            "Summary = per-employee workbook\n"
            "Detail = every payroll entry list"
        )

    def open_db_settings(self):
        """Open the database settings panel."""
        settings = tk.Toplevel(self.root)
        settings.title("Database Settings")
        settings.transient(self.root)
        settings.grab_set()
        settings.resizable(False, False)

        enabled_var = tk.BooleanVar(value=bool(self.db_config.get("enabled")))
        host_var = tk.StringVar(value=str(self.db_config.get("host", "")))
        port_var = tk.StringVar(value=str(self.db_config.get("port", "")))
        db_var = tk.StringVar(value=str(self.db_config.get("database", "")))
        user_var = tk.StringVar(value=str(self.db_config.get("user", "")))
        password_var = tk.StringVar(value=str(self.db_config.get("password", "")))
        ssl_var = tk.StringVar(value=str(self.db_config.get("sslmode", "prefer")))

        frame = ttk.Frame(settings, padding="12")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        frame.columnconfigure(1, weight=1)

        enable_check = ttk.Checkbutton(frame, text="Enable database storage", variable=enabled_var)
        enable_check.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        ttk.Label(frame, text="Host").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=host_var, width=30).grid(row=1, column=1, sticky=(tk.W, tk.E))

        ttk.Label(frame, text="Port").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=port_var, width=10).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(frame, text="Database").grid(row=3, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=db_var, width=30).grid(row=3, column=1, sticky=(tk.W, tk.E))

        ttk.Label(frame, text="User").grid(row=4, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=user_var, width=30).grid(row=4, column=1, sticky=(tk.W, tk.E))

        ttk.Label(frame, text="Password").grid(row=5, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=password_var, width=30, show="*").grid(row=5, column=1, sticky=(tk.W, tk.E))

        ttk.Label(frame, text="SSL mode").grid(row=6, column=0, sticky=tk.W)
        ssl_combo = ttk.Combobox(frame, textvariable=ssl_var, state="readonly", width=20)
        ssl_combo["values"] = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
        ssl_combo.grid(row=6, column=1, sticky=tk.W)

        note = ttk.Label(frame, text="Settings are saved locally on this machine.")
        note.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=8, column=0, columnspan=2, sticky=tk.E, pady=(12, 0))

        def collect_config():
            host = host_var.get().strip()
            user = user_var.get().strip()
            database = db_var.get().strip()
            if not host or not user or not database:
                raise ValueError("Host, database, and user are required.")
            try:
                port = int(port_var.get().strip())
            except ValueError as exc:
                raise ValueError("Port must be a number.") from exc
            return {
                "enabled": enabled_var.get(),
                "host": host,
                "port": port,
                "database": database,
                "user": user,
                "password": password_var.get(),
                "sslmode": ssl_var.get(),
            }

        def on_test():
            try:
                config = collect_config()
            except ValueError as exc:
                messagebox.showerror("Invalid Settings", str(exc))
                return
            ok, message = db_storage.test_connection(config)
            if ok:
                messagebox.showinfo("Database Connection", message)
            else:
                messagebox.showerror("Database Connection", message)

        def on_save():
            try:
                config = collect_config()
            except ValueError as exc:
                messagebox.showerror("Invalid Settings", str(exc))
                return
            db_storage.save_db_config(config)
            self.db_config = config
            settings.destroy()

        ttk.Button(button_frame, text="Test Connection", command=on_test).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=settings.destroy).pack(side=tk.LEFT)

    def show_message(self, title, message, kind="info"):
        """Show dialogs from the main thread."""
        def _show():
            if kind == "error":
                messagebox.showerror(title, message)
            elif kind == "warning":
                messagebox.showwarning(title, message)
            else:
                messagebox.showinfo(title, message)
        self.root.after(0, _show)

    def ask_show_in_finder(self, paths):
        """Ask the user to reveal output files in Finder."""
        def _ask():
            if messagebox.askyesno("Show in Finder", "Open the output files in Finder?"):
                for path in paths:
                    if path:
                        subprocess.run(["open", "-R", path], check=False)
        self.root.after(0, _ask)
    
    def check_missing_dependencies(self) -> List[str]:
        """Return a list of missing external dependencies."""
        missing = []
        if shutil.which("pdftotext") is None:
            missing.append("pdftotext (install with 'brew install poppler')")
        return missing
    
    def warn_missing_dependencies(self):
        """Show a non-blocking warning if dependencies are missing."""
        if getattr(self, "status_var", None) and self.missing_dependencies:
            warning = "Missing dependencies: " + ", ".join(self.missing_dependencies)
            self.status_var.set(warning)
    
    def ensure_dependencies_available(self) -> bool:
        """Ensure required tools are installed before processing."""
        self.missing_dependencies = self.check_missing_dependencies()
        if self.missing_dependencies:
            warning = "\n".join(f"• {item}" for item in self.missing_dependencies)
            messagebox.showerror(
                "Missing Dependencies",
                "Payroll Processor needs the following tools:\n\n"
                f"{warning}\n\nInstall them and try again."
            )
            self.warn_missing_dependencies()
            return False
        return True
    
    def setup_drag_drop(self):
        """Setup drag and drop functionality."""
        if not DRAG_DROP_AVAILABLE:
            return
            
        # Enable drag and drop on the file listbox
        self.file_listbox.drop_target_register(DND_FILES)
        self.file_listbox.dnd_bind('<<Drop>>', self.on_drop)
    
    def on_drop(self, event):
        """Handle dropped files."""
        if self.processing:
            return
            
        files = self.root.tk.splitlist(event.data)
        zip_files = [f for f in files if f.lower().endswith('.zip')]
        
        if not zip_files:
            messagebox.showwarning("Invalid Files", 
                                 "Please drop only ZIP files containing payroll data.")
            return
        
        # Add files to list
        for zip_file in zip_files:
            if zip_file not in self.zip_files:
                self.zip_files.append(zip_file)
        
        self.update_file_list()
        self.update_ui_state()
    
    def browse_files(self):
        """Open file browser to select ZIP files."""
        print("DEBUG: browse_files() called")  # Debug print
        if self.processing:
            print("DEBUG: browse_files() - currently processing, returning")  # Debug print
            return
            
        files = filedialog.askopenfilenames(
            title="Select Payroll ZIP Files",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        
        print(f"DEBUG: Selected files: {files}")  # Debug print
        
        # Add selected files
        for file_path in files:
            if file_path not in self.zip_files:
                self.zip_files.append(file_path)
                print(f"DEBUG: Added file: {file_path}")  # Debug print
        
        print(f"DEBUG: zip_files after adding: {self.zip_files}")  # Debug print
        self.update_file_list()
        self.update_ui_state()
    
    def remove_selected_files(self):
        """Remove selected files from the list."""
        if self.processing:
            return
            
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            messagebox.showinfo("No Selection", "Please select files to remove.")
            return
        
        # Remove files in reverse order to maintain indices
        for index in reversed(selected_indices):
            del self.zip_files[index]
        
        self.update_file_list()
        self.update_ui_state()
    
    def clear_all_files(self):
        """Clear all files from the list."""
        if self.processing:
            return
            
        if self.zip_files:
            if messagebox.askyesno("Clear All", "Remove all files from the list?"):
                self.zip_files.clear()
                self.update_file_list()
                self.update_ui_state()
    
    def update_file_list(self):
        """Update the file listbox display."""
        self.file_listbox.delete(0, tk.END)
        for zip_file in self.zip_files:
            filename = os.path.basename(zip_file)
            self.file_listbox.insert(tk.END, filename)
        
        # Hide/show drop label
        if DRAG_DROP_AVAILABLE:
            if self.zip_files:
                self.drop_label.place_forget()
            else:
                self.drop_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
    
    def update_ui_state(self):
        """Update button states based on current state."""
        has_files = bool(self.zip_files)
        print(f"DEBUG: update_ui_state - has_files={has_files}, processing={self.processing}")  # Debug print
        print(f"DEBUG: zip_files content: {self.zip_files}")  # Debug print
        deps_ready = not self.missing_dependencies
        
        # Enable/disable buttons based on state
        state = tk.DISABLED if self.processing else tk.NORMAL
        generate_state = state if has_files else tk.DISABLED
        print(f"DEBUG: generate_btn state will be: {generate_state}")  # Debug print
        
        self.browse_btn.configure(state=state)
        self.remove_btn.configure(state=state if has_files else tk.DISABLED)
        self.clear_btn.configure(state=state if has_files else tk.DISABLED)
        self.generate_btn.configure(state=generate_state)
        self.output_btn.configure(state=state)
        
        if not deps_ready:
            self.warn_missing_dependencies()
    
    def generate_reports(self):
        """Generate payroll reports from selected files."""
        print("DEBUG: generate_reports() called")  # Debug print
        print(f"DEBUG: zip_files = {self.zip_files}")  # Debug print
        print(f"DEBUG: processing = {self.processing}")  # Debug print
        
        if not self.zip_files:
            print("DEBUG: No zip files found")  # Debug print
            messagebox.showwarning("No Files", "Please select ZIP files first.")
            return
        
        if not self.ensure_dependencies_available():
            return
        
        if self.processing:
            print("DEBUG: Already processing")  # Debug print
            return
        
        # Determine automatic output locations (summary & detail)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        summary_path = self.report_dir / f"employee_reports_{timestamp}_summary.xlsx"
        detail_path = self.report_dir / f"employee_reports_{timestamp}_detail.xlsx"
        summary_path = str(summary_path)
        detail_path = str(detail_path)
        self.last_output_path = summary_path
        self.current_output_paths = (summary_path, detail_path)
        self.output_location_var.set(f"Saving summary to:\n{summary_path}\nDetail to:\n{detail_path}")
        self.update_status("Starting report generation...")
        
        # Start processing in a separate thread
        self.processing = True
        self.update_ui_state()
        
        thread = threading.Thread(target=self.process_files, args=(summary_path, detail_path))
        thread.daemon = True
        thread.start()
    
    def process_files(self, summary_output, detail_output):
        """Process the ZIP files and generate reports."""
        try:
            self.update_status("Initializing...")
            self.update_progress(0)
            
            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                self.temp_dir = temp_dir
                csv_files = []
                
                total_files = len(self.zip_files)
                
                # Process each ZIP file
                for i, zip_file in enumerate(self.zip_files):
                    self.update_status(f"Processing {os.path.basename(zip_file)}...")
                    progress = (i / total_files) * 80  # Use 80% for processing
                    self.update_progress(progress)
                    
                    try:
                        # Process the ZIP file
                        df = process_payroll.process_zip(zip_file, temp_dir, archive_root=str(self.archive_dir))
                        
                        if not df.empty:
                            # Save to temporary CSV
                            csv_path = os.path.join(temp_dir, f"temp_payroll_{i}.csv")
                            df["SourceArchive"] = os.path.basename(zip_file)
                            
                            # Normalize numeric fields
                            numeric_cols = [
                                "BasicSalary", "TotalEarnings", "NetPay",
                                "EFKAEmployee", "EFKAEmployer", "TEKAEmployee", "TEKAEmployer"
                            ]
                            for col in numeric_cols:
                                if col in df.columns:
                                    df[col] = df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                                    df[col] = pd.to_numeric(df[col], errors='coerce')
                            
                            df.to_csv(csv_path, index=False)
                            csv_files.append(csv_path)
                        
                    except Exception as e:
                        self.update_status(f"Error processing {os.path.basename(zip_file)}: {str(e)}")
                        continue
                
                if not csv_files:
                    self.update_status("No payroll data found in any files.")
                    self.show_message("No Data", "No payroll data could be extracted from the selected files.", kind="error")
                    return
                
                # Generate employee reports
                self.update_status("Generating employee reports...")
                self.update_progress(85)
                
                # Load and combine all CSV data
                combined_df = create_employee_reports.load_payroll_data(csv_files)
                
                if combined_df.empty:
                    self.update_status("No data to process.")
                    self.show_message("No Data", "No valid payroll data found.", kind="error")
                    return

                db_rows = None
                db_error = None
                if self.db_config.get("enabled"):
                    self.update_status("Writing data to database...")
                    try:
                        db_rows = db_storage.store_payroll_data(combined_df, self.db_config)
                    except Exception as exc:
                        db_error = str(exc)
                        self.show_message(
                            "Database Warning",
                            f"Reports will still be generated, but database storage failed:\n\n{db_error}",
                            kind="warning",
                        )

                # Prepare summary
                self.update_progress(90)
                summary_df = create_employee_reports.prepare_summary(combined_df)

                # Write Excel reports
                self.update_progress(95)
                create_employee_reports.write_employee_reports(summary_df, summary_output)
                create_employee_reports.write_detail_report(combined_df, detail_output)

                # Complete
                self.update_progress(100)
                self.update_status(f"Reports generated successfully!")

                # Show success message
                num_employees = len(summary_df['EmployeeCode'].unique()) if not summary_df.empty else 0
                num_records = len(combined_df)

                summary_text = (
                    f"Employee reports generated successfully!\n\n"
                    f"• Processed {total_files} ZIP files\n"
                    f"• Found {num_records} payroll records\n"
                    f"• Created reports for {num_employees} employees\n"
                    f"• Summary: {summary_output}\n"
                    f"• Detail: {detail_output}"
                )
                if self.db_config.get("enabled"):
                    if db_error:
                        summary_text += f"\n• Database: failed to store data ({db_error})"
                    else:
                        summary_text += f"\n• Database: stored {db_rows} rows"

                self.root.after(0, lambda: self.output_location_var.set(
                    f"Last summary: {summary_output}\nLast detail: {detail_output}"
                ))
                self.show_message("Success", summary_text, kind="info")
                self.ask_show_in_finder([summary_output, detail_output])
                
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            self.show_message("Error", f"An error occurred while processing:\n\n{str(e)}", kind="error")
        
        finally:
            self.processing = False
            self.root.after(0, self.update_ui_state)
            if not self.processing:
                self.root.after(2000, lambda: self.update_status("Ready"))
    
    def update_status(self, message):
        """Update status label thread-safely."""
        self.root.after(0, lambda: self.status_var.set(message))
    
    def update_progress(self, value):
        """Update progress bar thread-safely."""
        self.root.after(0, lambda: self.progress_var.set(value))
    
    def run(self):
        """Start the GUI application."""
        self.root.mainloop()


def main():
    """Main entry point."""
    app = PayrollProcessorGUI()
    app.run()


if __name__ == "__main__":
    main()
