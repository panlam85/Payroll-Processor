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
import calendar
from pathlib import Path
import subprocess
import unicodedata
import math

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
from theme_config import get_theme_tokens

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
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
        self.configure_styles()

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
        self.global_start_year_var = tk.StringVar(value="All")
        self.global_start_month_var = tk.StringVar(value="01")
        self.global_end_year_var = tk.StringVar(value="All")
        self.global_end_month_var = tk.StringVar(value="01")
        self.global_doc_type_var = tk.StringVar(value="All")
        self.grid_search_job = None
        self.global_range_end_year = None
        self.global_range_end_month = None
        self.analytics_selected_employee_code = None
        self.analytics_selected_employee_name = None
        self.analytics_monthly_labels = []
        self.analytics_doc_type_labels = []
        self.analytics_insurance_labels = []
        self.analytics_heatmap_employees = []
        self.analytics_heatmap_dates = []
        self.analytics_employee_bar_map = {}
        self.analytics_grid_tab = None
        self.analytics_detail_tab = None
        self.analytics_grid_page_var = tk.IntVar(value=1)
        self.analytics_grid_total_var = tk.StringVar(value="")
        self.analytics_grid_cache_rows = []
        self.analytics_grid_cache_columns = []
        self.analytics_grid_filter_vars = {}
        self.analytics_grid_filter_columns = []
        self.grid_edit_entry = None
        self.grid_editing_cell = None
        self.analytics_grid_menu = None
        self.edit_undo_stack = []
        self.edit_redo_stack = []
        self.edit_lock_var = tk.BooleanVar(value=False)
        self.last_grid_column = None
        self.ui_prefs = db_storage.load_ui_prefs()
        self.nav_history = []
        self.nav_restoring = False
        self.dashboard_summary_labels = []
        
        # Create GUI elements
        self.create_widgets()
        self.create_menu()
        self.root.bind_all("<Command-z>", lambda _event: self._undo_last_edit())
        self.root.bind_all("<Command-l>", lambda _event: self._toggle_edit_lock())
        self.root.bind_all("<Command-Shift-z>", lambda _event: self._redo_last_edit())
        self.root.bind_all("<Command-f>", lambda _event: self._focus_global_search())
        self.root.bind_all("<Command-r>", lambda _event: self._refresh_all_views())
        self.root.bind_all("<Command-c>", lambda _event: self._copy_grid_cell())
        
        # Setup drag and drop if available
        if DRAG_DROP_AVAILABLE:
            self.setup_drag_drop()
        
        # Surface dependency issues immediately
        self.warn_missing_dependencies()

    def configure_styles(self):
        """Configure ttk styles for a cohesive UI."""
        appearance = None
        try:
            appearance = self.root.tk.call("tk::mac::GetSystemAppearance")
        except tk.TclError:
            appearance = None
        is_dark = bool(appearance and str(appearance).lower() == "dark")
        tokens = get_theme_tokens(is_dark)

        self.root.configure(bg=tokens.bg)
        style = ttk.Style()
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=tokens.bg)
        style.configure("Card.TFrame", background=tokens.surface, relief="solid", borderwidth=1)
        style.configure("CardTitle.TLabel", background=tokens.surface, foreground=tokens.text_secondary, font=(tokens.font_base, 11))
        style.configure("CardValue.TLabel", background=tokens.surface, foreground=tokens.text_primary, font=(tokens.font_base, 18, "bold"))
        style.configure("Header.TLabel", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 16, "bold"))
        style.configure("Section.TLabel", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 13, "bold"))
        style.configure("Body.TLabel", background=tokens.bg, foreground=tokens.text_secondary, font=(tokens.font_base, 11))
        style.configure("App.TLabelframe", background=tokens.bg)
        style.configure("App.TLabelframe.Label", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 11, "bold"))
        style.configure("App.TNotebook", background=tokens.bg)
        style.configure("App.TNotebook.Tab", padding=(12, 6), font=(tokens.font_base, 11))
        style.configure("Treeview", background=tokens.surface, fieldbackground=tokens.surface, foreground=tokens.text_primary, bordercolor=tokens.border)
        style.configure("Treeview.Heading", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 11, "bold"))

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
        main_frame = ttk.Frame(self.root, padding="16", style="App.TFrame")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=0)
        main_frame.rowconfigure(1, weight=0)
        main_frame.rowconfigure(2, weight=1)

        self.global_filter_bar = ttk.Frame(main_frame, style="App.TFrame")
        self.global_filter_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        self.global_filter_bar.columnconfigure(11, weight=1)

        ttk.Label(self.global_filter_bar, text="Filters", style="Section.TLabel").grid(row=0, column=0, padx=(0, 10))

        ttk.Label(self.global_filter_bar, text="Start", style="Body.TLabel").grid(row=0, column=1, padx=(0, 6))
        self.global_start_year_combo = ttk.Combobox(self.global_filter_bar, textvariable=self.global_start_year_var, state="readonly", width=8)
        self.global_start_year_combo.grid(row=0, column=2, padx=(0, 6))
        self.global_start_year_combo.bind("<<ComboboxSelected>>", self._on_global_year_change)
        self.global_start_year_combo["values"] = ["All"]

        self.global_start_month_combo = ttk.Combobox(self.global_filter_bar, textvariable=self.global_start_month_var, state="readonly", width=6)
        self.global_start_month_combo.grid(row=0, column=3, padx=(0, 10))
        self.global_start_month_combo["values"] = [f"{month:02d}" for month in range(1, 13)]
        self.global_start_month_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)

        ttk.Label(self.global_filter_bar, text="End", style="Body.TLabel").grid(row=0, column=4, padx=(0, 6))
        self.global_end_year_combo = ttk.Combobox(self.global_filter_bar, textvariable=self.global_end_year_var, state="readonly", width=8)
        self.global_end_year_combo.grid(row=0, column=5, padx=(0, 6))
        self.global_end_year_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)
        self.global_end_year_combo["values"] = ["All"]

        self.global_end_month_combo = ttk.Combobox(self.global_filter_bar, textvariable=self.global_end_month_var, state="readonly", width=6)
        self.global_end_month_combo.grid(row=0, column=6, padx=(0, 10))
        self.global_end_month_combo["values"] = [f"{month:02d}" for month in range(1, 13)]
        self.global_end_month_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)

        ttk.Label(self.global_filter_bar, text="Document", style="Body.TLabel").grid(row=0, column=7, padx=(0, 6))
        self.global_doc_type_combo = ttk.Combobox(self.global_filter_bar, textvariable=self.global_doc_type_var, state="readonly", width=18)
        self.global_doc_type_combo["values"] = ["All", "salary", "bonus", "vacation_allowance", "unused_leave_compensation", "other"]
        self.global_doc_type_combo.grid(row=0, column=8, padx=(0, 10))
        self.global_doc_type_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)

        ttk.Label(self.global_filter_bar, text="Search", style="Body.TLabel").grid(row=0, column=9, padx=(0, 6))
        self.global_search_var = tk.StringVar(value="")
        self.global_search_entry = ttk.Entry(self.global_filter_bar, textvariable=self.global_search_var, width=20)
        self.global_search_entry.grid(row=0, column=10, padx=(0, 10))
        self.global_search_entry.bind("<KeyRelease>", self._on_global_search)

        self.global_window_label_var = tk.StringVar(value="")
        ttk.Label(self.global_filter_bar, textvariable=self.global_window_label_var, style="Body.TLabel").grid(row=0, column=11, sticky=tk.W)
        self.global_filter_status = tk.StringVar(value="")
        ttk.Label(self.global_filter_bar, textvariable=self.global_filter_status, style="Body.TLabel").grid(row=0, column=12, sticky=tk.E)

        self._apply_ui_prefs()

        separator = ttk.Separator(main_frame, orient=tk.HORIZONTAL)
        separator.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))

        self.notebook = ttk.Notebook(main_frame, style="App.TNotebook")
        self.notebook.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.processing_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.db_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.analytics_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.dashboard_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.notebook.add(self.processing_tab, text="Processing")
        self.notebook.add(self.db_tab, text="Database")
        self.notebook.add(self.analytics_tab, text="Analytics")
        self.notebook.add(self.dashboard_tab, text="Dashboard")


        self.processing_tab.columnconfigure(0, weight=1)
        self.processing_tab.rowconfigure(2, weight=1)

        # Title
        title_label = ttk.Label(
            self.processing_tab,
            text="Payroll Processor",
            style="Header.TLabel",
        )
        title_label.grid(row=0, column=0, pady=(0, 20))

        # Instructions
        self.instructions_label = ttk.Label(
            self.processing_tab,
            text=self.get_instructions_text(),
            justify=tk.CENTER,
            wraplength=600,
            style="Body.TLabel",
        )
        self.instructions_label.grid(row=1, column=0, pady=(0, 20))

        # File list frame
        list_frame = ttk.LabelFrame(self.processing_tab, text="Selected Files", padding="8", style="App.TLabelframe")
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
            style="Body.TLabel",
        )
        self.output_location_label.grid(row=2, column=0, pady=(4, 0))

        self.create_db_tab()
        self.create_analytics_tab()
        self.create_dashboard_tab()
        self.update_ui_state()

    def create_analytics_tab(self):
        """Create the analytics tab with charts."""
        self.analytics_tab.columnconfigure(0, weight=1)
        self.analytics_tab.rowconfigure(2, weight=1)

        header = ttk.Frame(self.analytics_tab)
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        header.columnconfigure(4, weight=1)

        ttk.Label(header, text="Analytics", style="Header.TLabel").grid(row=0, column=0, padx=(0, 10))
        back_btn = ttk.Button(header, text="Back", command=self._navigate_back)
        back_btn.grid(row=0, column=1, padx=(0, 10))
        refresh_btn = ttk.Button(header, text="Refresh Charts", command=self.refresh_analytics)
        refresh_btn.grid(row=0, column=2, padx=(0, 10))

        ttk.Label(header, text="Top Employees", style="Body.TLabel").grid(row=0, column=3, padx=(0, 6))
        self.analytics_top_n_var = tk.IntVar(value=10)
        top_spin = ttk.Spinbox(header, from_=5, to=50, textvariable=self.analytics_top_n_var, width=6)
        top_spin.grid(row=0, column=4, padx=(0, 10))

        self.analytics_status_var = tk.StringVar(value="Ready to refresh.")
        ttk.Label(header, textvariable=self.analytics_status_var, style="Body.TLabel").grid(row=0, column=5, sticky=tk.W)

        cards_frame = ttk.Frame(self.analytics_tab, style="App.TFrame")
        cards_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)
        cards_frame.columnconfigure(2, weight=1)

        self.kpi_total_net_var = tk.StringVar(value="—")
        self.kpi_employer_cost_var = tk.StringVar(value="—")
        self.kpi_total_insurance_var = tk.StringVar(value="—")

        self._build_kpi_card(cards_frame, 0, "Total Net Pay", self.kpi_total_net_var)
        self._build_kpi_card(cards_frame, 1, "Employer Cost", self.kpi_employer_cost_var)
        self._build_kpi_card(cards_frame, 2, "Total Insurance", self.kpi_total_insurance_var)

        ttk.Label(header, textvariable=self.analytics_status_var, style="Body.TLabel").grid(row=0, column=8, sticky=tk.W)

        charts_frame = ttk.Frame(self.analytics_tab, style="App.TFrame")
        charts_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        charts_frame.columnconfigure(0, weight=1)
        charts_frame.rowconfigure(0, weight=1)

        self.analytics_notebook = ttk.Notebook(charts_frame, style="App.TNotebook")
        self.analytics_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.analytics_charts = {}
        for key, title in (
            ("monthly", "Monthly Payroll Burn"),
            ("insurance", "Insurance Breakdown"),
            ("doc_type", "Salary vs Bonus vs Allowances"),
            ("heatmap", "Payment Heat-map"),
            ("employee", "Cost Per Employee"),
            ("monthly_employee", "Monthly Employee Summary"),
            ("grid", "Data Grid"),
            ("detail", "Employee Detail"),
        ):
            frame = ttk.Frame(self.analytics_notebook, padding=8, style="App.TFrame")
            if key == "monthly_employee":
                self._build_monthly_employee_tab(frame)
                self.analytics_notebook.add(frame, text=title)
                continue
            if key == "grid":
                self._build_data_grid(frame)
                self.analytics_grid_tab = frame
                self.analytics_notebook.add(frame, text=title)
                continue
            if key == "detail":
                self._build_detail_tab(frame)
                self.analytics_detail_tab = frame
                self.analytics_notebook.add(frame, text=title)
                continue
            fig = Figure(figsize=(8, 5), dpi=100)
            ax = fig.add_subplot(1, 1, 1)
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            toolbar = NavigationToolbar2Tk(canvas, frame)
            toolbar.update()
            toolbar.pack(side=tk.BOTTOM, fill=tk.X)
            self.analytics_notebook.add(frame, text=title)
            self.analytics_charts[key] = {"fig": fig, "ax": ax, "canvas": canvas, "toolbar": toolbar}

        self.analytics_heatmap_cbar = None
        self.analytics_heatmap_cax = None
        self.analytics_legend_map = {}
        self._bind_chart_drilldowns()

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
            self._refresh_global_filters()
            start_date, end_date, document_type, search = self._get_global_filters()
            monthly_rows = db_storage.fetch_monthly_summary(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            )
            top_n = int(self.analytics_top_n_var.get())
            employee_rows = db_storage.fetch_employer_costs_by_employee(
                self.db_config,
                limit=top_n,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            )
            doc_type_rows = db_storage.fetch_document_type_breakdown(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            )

            heatmap_rows = []
            heatmap_year = self.global_range_end_year
            heatmap_month = self.global_range_end_month
            if heatmap_year is not None and heatmap_month is not None:
                heatmap_rows = db_storage.fetch_payment_heatmap(
                    self.db_config,
                    year=heatmap_year,
                    month=heatmap_month,
                    limit=top_n,
                    document_type=document_type,
                    search=search or None,
                )

            self._refresh_kpis()

            self._plot_monthly_burn(monthly_rows)
            self._plot_insurance_breakdown(monthly_rows)
            self._plot_doc_type_breakdown(doc_type_rows)
            self._plot_payment_heatmap(heatmap_rows, year=heatmap_year, month=heatmap_month)
            self._plot_employee_costs(employee_rows)
            for chart in self.analytics_charts.values():
                chart["canvas"].draw()
            self.refresh_data_grid()
            self.refresh_monthly_employee_summary()
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.analytics_status_var.set(f"Last refreshed at {timestamp}.")
        except Exception as exc:
            self.analytics_status_var.set("Refresh failed.")
            self.show_message("Analytics Error", str(exc), kind="warning")

    def _plot_monthly_burn(self, rows):
        self.analytics_monthly_ax = self.analytics_charts["monthly"]["ax"]
        self.analytics_monthly_ax.clear()
        if not rows:
            self.analytics_monthly_ax.set_title("Monthly Payroll Burn")
            self.analytics_monthly_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            self.analytics_monthly_labels = []
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
        self.analytics_monthly_labels = labels

        self._monthly_line_net, = self.analytics_monthly_ax.plot(labels, net_vals, marker="o", label="Net Pay")
        self._monthly_line_employer, = self.analytics_monthly_ax.plot(labels, employer_cost, marker="o", label="Employer Cost")
        self.analytics_monthly_ax.set_title("Monthly Payroll Burn")
        self.analytics_monthly_ax.set_ylabel("Amount")
        self.analytics_monthly_ax.tick_params(axis="x", rotation=45)
        legend = self.analytics_monthly_ax.legend()
        self._bind_legend_toggle(legend, [self._monthly_line_net, self._monthly_line_employer])

    def _plot_doc_type_breakdown(self, rows):
        self.analytics_doc_type_ax = self.analytics_charts["doc_type"]["ax"]
        self.analytics_doc_type_ax.clear()
        if not rows:
            self.analytics_doc_type_ax.set_title("Salary vs Bonus vs Allowances")
            self.analytics_doc_type_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            self.analytics_doc_type_labels = []
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
        self.analytics_doc_type_labels = labels

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
        self.analytics_insurance_ax = self.analytics_charts["insurance"]["ax"]
        self.analytics_insurance_ax.clear()
        if not rows:
            self.analytics_insurance_ax.set_title("Insurance Breakdown")
            self.analytics_insurance_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            self.analytics_insurance_labels = []
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
        self.analytics_insurance_labels = labels

        self.analytics_insurance_ax.bar(labels, employer_vals, label="Employer Insurance")
        self.analytics_insurance_ax.bar(labels, employee_vals, bottom=employer_vals, label="Employee Insurance")
        self.analytics_insurance_ax.set_title("Insurance Contribution Breakdown")
        self.analytics_insurance_ax.tick_params(axis="x", rotation=45)
        self.analytics_insurance_ax.legend()

    def _plot_payment_heatmap(self, rows, year=None, month=None):
        self.analytics_heatmap_ax = self.analytics_charts["heatmap"]["ax"]
        self.analytics_heatmap_ax.clear()
        if self.analytics_heatmap_cbar is not None:
            try:
                self.analytics_heatmap_cbar.remove()
            except Exception:
                pass
            self.analytics_heatmap_cbar = None
            self.analytics_heatmap_cax = None
        if year is None or month is None:
            self.analytics_heatmap_ax.set_title("Payment Heat-map")
            self.analytics_heatmap_ax.text(0.5, 0.5, "Select year and month", ha="center", va="center")
            self.analytics_heatmap_employees = []
            self.analytics_heatmap_dates = []
            return
        if not rows:
            self.analytics_heatmap_ax.set_title("Payment Heat-map")
            self.analytics_heatmap_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            self.analytics_heatmap_employees = []
            self.analytics_heatmap_dates = []
            return

        employees = sorted({row[0] for row in rows})
        dates = sorted({row[1] for row in rows})
        self.analytics_heatmap_employees = employees
        self.analytics_heatmap_dates = dates
        date_labels = [date.strftime("%d") for date in dates]
        data_matrix = [[0.0 for _ in dates] for _ in employees]
        emp_index = {name: idx for idx, name in enumerate(employees)}
        date_index = {date: idx for idx, date in enumerate(dates)}
        for employee, payment_date, total_net in rows:
            i = emp_index[employee]
            j = date_index[payment_date]
            data_matrix[i][j] = float(total_net or 0)

        heatmap_fig = self.analytics_charts["heatmap"]["fig"]
        im = self.analytics_heatmap_ax.imshow(data_matrix, aspect="auto", cmap="YlGnBu")
        self.analytics_heatmap_ax.set_title("Payment Heat-map")
        self.analytics_heatmap_ax.set_yticks(range(len(employees)))
        self.analytics_heatmap_ax.set_yticklabels(employees)
        self.analytics_heatmap_ax.set_xticks(range(len(date_labels)))
        self.analytics_heatmap_ax.set_xticklabels(date_labels, rotation=90)
        self.analytics_heatmap_cax = heatmap_fig.add_axes([0.88, 0.15, 0.03, 0.7])
        self.analytics_heatmap_cbar = heatmap_fig.colorbar(im, cax=self.analytics_heatmap_cax)

    def _plot_employee_costs(self, rows):
        self.analytics_employee_ax = self.analytics_charts["employee"]["ax"]
        self.analytics_employee_ax.clear()
        if not rows:
            self.analytics_employee_ax.set_title("Cost Per Employee")
            self.analytics_employee_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            self.analytics_employee_bar_map = {}
            return

        employees = [row[0] for row in rows]
        costs = [float(row[1] or 0) for row in rows]
        bars = self.analytics_employee_ax.barh(employees, costs)
        self.analytics_employee_bar_map = {}
        for bar, name in zip(bars, employees):
            bar.set_picker(True)
            self.analytics_employee_bar_map[bar] = name
        self.analytics_employee_ax.set_title("Cost Per Employee")
        self.analytics_employee_ax.set_xlabel("Employer Cost")
        self.analytics_employee_ax.invert_yaxis()

    def _refresh_kpis(self):
        start_date, end_date, document_type, search = self._get_global_filters()
        totals = db_storage.fetch_kpi_totals(
            self.db_config,
            start_date=start_date,
            end_date=end_date,
            document_type=document_type,
            employee_code=self.analytics_selected_employee_code,
            employee_name=self.analytics_selected_employee_name,
            search=search or None,
        )
        total_net, total_employee_ins, total_employer_ins = totals
        total_insurance = total_employee_ins + total_employer_ins
        total_employer_cost = total_net + total_employer_ins
        self.kpi_total_net_var.set(self._format_currency(total_net))
        self.kpi_employer_cost_var.set(self._format_currency(total_employer_cost))
        self.kpi_total_insurance_var.set(self._format_currency(total_insurance))

    def _build_kpi_card(self, parent, column, title, value_var):
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=0, column=column, sticky=(tk.W, tk.E), padx=6)
        title_label = ttk.Label(card, text=title, style="CardTitle.TLabel")
        title_label.pack(anchor=tk.W)
        value_label = ttk.Label(card, textvariable=value_var, style="CardValue.TLabel")
        value_label.pack(anchor=tk.W, pady=(6, 0))

    def _format_currency(self, value):
        try:
            return f"€ {value:,.2f}"
        except Exception:
            return "€ 0.00"

    def _bind_legend_toggle(self, legend, lines):
        if legend is None:
            return
        leg_lines = legend.get_lines()
        self.analytics_legend_map = {}
        for leg_line, orig_line in zip(leg_lines, lines):
            leg_line.set_picker(True)
            self.analytics_legend_map[leg_line] = orig_line
        canvas = self.analytics_charts["monthly"]["canvas"]
        canvas.mpl_connect("pick_event", self._on_legend_pick)

    def _bind_chart_drilldowns(self):
        for key, chart in self.analytics_charts.items():
            chart["canvas"].mpl_connect(
                "button_press_event",
                lambda event, chart_key=key: self._on_chart_click(chart_key, event),
            )
            chart["canvas"].mpl_connect("pick_event", self._on_chart_pick)

    def _on_chart_pick(self, event):
        bar_employee = self.analytics_employee_bar_map.get(event.artist)
        if bar_employee:
            self._open_employee_detail(employee_name=bar_employee)

    def _on_chart_click(self, chart_key, event):
        if event.inaxes is None:
            return
        if chart_key in ("monthly", "doc_type", "insurance"):
            labels = getattr(self, f"analytics_{chart_key}_labels", [])
            label = self._get_label_from_event(labels, event.xdata)
            if label:
                self._set_global_month_range_from_label(label)
                if self.analytics_grid_tab is not None:
                    self.analytics_notebook.select(self.analytics_grid_tab)
        elif chart_key == "heatmap":
            if not self.analytics_heatmap_employees or not self.analytics_heatmap_dates:
                return
            if event.xdata is None or event.ydata is None:
                return
            col = int(round(event.xdata))
            row = int(round(event.ydata))
            if col < 0 or row < 0:
                return
            if row >= len(self.analytics_heatmap_employees) or col >= len(self.analytics_heatmap_dates):
                return
            selected_date = self.analytics_heatmap_dates[col]
            label = f"{selected_date.year:04d}-{selected_date.month:02d}"
            self._set_global_month_range_from_label(label)
            self._open_employee_detail(employee_name=self.analytics_heatmap_employees[row])

    def _get_label_from_event(self, labels, xdata):
        if xdata is None or not labels:
            return None
        idx = int(round(xdata))
        if idx < 0 or idx >= len(labels):
            return None
        return labels[idx]

    def _set_global_month_range_from_label(self, label):
        self._push_nav_state()
        try:
            year_str, month_str = label.split("-", 1)
            year = int(year_str)
            month = int(month_str)
        except Exception:
            return
        self.global_start_year_var.set(str(year))
        self.global_start_month_var.set(f"{month:02d}")
        self.global_end_year_var.set(str(year))
        self.global_end_month_var.set(f"{month:02d}")
        self._update_window_label()
        self._refresh_all_views()

    def _open_employee_detail(self, employee_code=None, employee_name=None, push_state=True):
        if push_state:
            self._push_nav_state()
        self.analytics_selected_employee_code = employee_code
        self.analytics_selected_employee_name = employee_name
        start_date, end_date, document_type, _ = self._get_global_filters()
        detail_columns, detail_rows = db_storage.fetch_employee_entries(
            self.db_config,
            employee_code=employee_code,
            employee_name=employee_name,
            start_date=start_date,
            end_date=end_date,
            document_type=document_type,
            limit=500,
        )
        label = employee_name or employee_code or "Employee"
        self.analytics_detail_label_var.set(f"Showing: {label}")
        total_net = 0.0
        if detail_columns and "net_pay" in detail_columns:
            net_idx = detail_columns.index("net_pay")
            for row in detail_rows:
                try:
                    total_net += float(row[net_idx] or 0)
                except Exception:
                    continue
        self.analytics_detail_total_var.set(f"Total Net Pay: {self._format_currency(total_net)}")
        self._reset_treeview(self.analytics_detail_tree, detail_columns)
        self._populate_treeview(self.analytics_detail_tree, detail_rows)
        if self.analytics_detail_tab is not None:
            self.analytics_notebook.select(self.analytics_detail_tab)
        self._refresh_kpis()

    def _plot_dashboard_summary(self, rows):
        chart = self.dashboard_chart["ax"]
        chart.clear()
        if not rows:
            chart.set_title("Summary Trend")
            chart.text(0.5, 0.5, "No data", ha="center", va="center")
            self.dashboard_summary_labels = []
            self.dashboard_chart["canvas"].draw()
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
        self.dashboard_summary_labels = labels
        chart.plot(labels, net_vals, marker="o", label="Net Pay")
        chart.plot(labels, employer_cost, marker="o", label="Employer Cost")
        chart.set_title("Summary Trend")
        chart.set_ylabel("Amount")
        chart.tick_params(axis="x", rotation=45)
        chart.legend()
        self.dashboard_chart["canvas"].draw()

    def _on_dashboard_chart_click(self, event):
        if event.inaxes is None or not self.dashboard_summary_labels:
            return
        label = self._get_label_from_event(self.dashboard_summary_labels, event.xdata)
        if label:
            self._set_global_month_range_from_label(label)
            self.notebook.select(self.analytics_tab)

    def _on_dashboard_anomaly_select(self, _event=None):
        selection = self.dashboard_anomaly_tree.selection()
        if not selection:
            return
        columns = list(self.dashboard_anomaly_tree["columns"])
        values = self.dashboard_anomaly_tree.item(selection[0], "values")
        employee_name = self._get_grid_value(values, columns, "employee_name")
        payment_date = self._get_grid_value(values, columns, "payment_date")
        self._set_global_month_range_from_date(payment_date)
        self._open_employee_detail(employee_name=employee_name)
        self.notebook.select(self.analytics_tab)

    def _on_dashboard_recent_select(self, _event=None):
        selection = self.dashboard_recent_tree.selection()
        if not selection:
            return
        columns = list(self.dashboard_recent_tree["columns"])
        values = self.dashboard_recent_tree.item(selection[0], "values")
        employee_name = self._get_grid_value(values, columns, "employee_name")
        payment_date = self._get_grid_value(values, columns, "payment_date")
        self._set_global_month_range_from_date(payment_date)
        self._open_employee_detail(employee_name=employee_name)
        self.notebook.select(self.analytics_tab)

    def _set_global_month_range_from_date(self, date_value):
        self._push_nav_state()
        if not date_value:
            return
        if isinstance(date_value, datetime.date):
            year = date_value.year
            month = date_value.month
        else:
            date_str = str(date_value)
            try:
                parsed = datetime.date.fromisoformat(date_str[:10])
            except Exception:
                return
            year = parsed.year
            month = parsed.month
        self.global_start_year_var.set(str(year))
        self.global_start_month_var.set(f"{month:02d}")
        self.global_end_year_var.set(str(year))
        self.global_end_month_var.set(f"{month:02d}")
        self._update_window_label()
        self._refresh_all_views()

    def _snapshot_nav_state(self):
        state = {
            "start_year": self.global_start_year_var.get(),
            "start_month": self.global_start_month_var.get(),
            "end_year": self.global_end_year_var.get(),
            "end_month": self.global_end_month_var.get(),
            "document_type": self.global_doc_type_var.get(),
            "search": self.global_search_var.get(),
            "selected_employee_code": self.analytics_selected_employee_code,
            "selected_employee_name": self.analytics_selected_employee_name,
            "main_tab": self.notebook.select(),
        }
        if hasattr(self, "analytics_notebook"):
            state["analytics_tab"] = self.analytics_notebook.select()
        return state

    def _push_nav_state(self):
        if self.nav_restoring:
            return
        state = self._snapshot_nav_state()
        if self.nav_history and self.nav_history[-1] == state:
            return
        self.nav_history.append(state)

    def _navigate_back(self):
        if not self.nav_history:
            self.show_message("Back", "No previous state.", kind="info")
            return
        state = self.nav_history.pop()
        self._restore_nav_state(state)

    def _restore_nav_state(self, state):
        self.nav_restoring = True
        try:
            self.global_start_year_var.set(state.get("start_year", self.global_start_year_var.get()))
            self.global_start_month_var.set(state.get("start_month", self.global_start_month_var.get()))
            self.global_end_year_var.set(state.get("end_year", self.global_end_year_var.get()))
            self.global_end_month_var.set(state.get("end_month", self.global_end_month_var.get()))
            self.global_doc_type_var.set(state.get("document_type", self.global_doc_type_var.get()))
            self.global_search_var.set(state.get("search", self.global_search_var.get()))
            self.analytics_selected_employee_code = state.get("selected_employee_code")
            self.analytics_selected_employee_name = state.get("selected_employee_name")
            self._update_window_label()
            self._refresh_all_views()
            if self.analytics_selected_employee_code or self.analytics_selected_employee_name:
                self._open_employee_detail(
                    employee_code=self.analytics_selected_employee_code,
                    employee_name=self.analytics_selected_employee_name,
                    push_state=False,
                )
            main_tab = state.get("main_tab")
            if main_tab:
                try:
                    self.notebook.select(main_tab)
                except tk.TclError:
                    pass
            analytics_tab = state.get("analytics_tab")
            if analytics_tab and hasattr(self, "analytics_notebook"):
                try:
                    self.analytics_notebook.select(analytics_tab)
                except tk.TclError:
                    pass
        finally:
            self.nav_restoring = False

    def _on_legend_pick(self, event):
        line = event.artist
        orig = self.analytics_legend_map.get(line)
        if orig is None:
            return
        visible = not orig.get_visible()
        orig.set_visible(visible)
        line.set_alpha(1.0 if visible else 0.2)
        self.analytics_charts["monthly"]["canvas"].draw()

    def _build_data_grid(self, parent):
        toolbar = ttk.Frame(parent, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        toolbar.columnconfigure(12, weight=1)

        ttk.Label(toolbar, text="Limit", style="Body.TLabel").grid(row=0, column=0, padx=(0, 6))
        self.analytics_grid_limit_var = tk.IntVar(value=500)
        limit_spin = ttk.Spinbox(toolbar, from_=50, to=5000, textvariable=self.analytics_grid_limit_var, width=6)
        limit_spin.grid(row=0, column=1, padx=(0, 10))
        limit_spin.bind("<Return>", self._on_grid_limit_change)
        limit_spin.bind("<<Increment>>", self._on_grid_limit_change)
        limit_spin.bind("<<Decrement>>", self._on_grid_limit_change)

        refresh_btn = ttk.Button(toolbar, text="Refresh Grid", command=self.refresh_data_grid)
        refresh_btn.grid(row=0, column=2, sticky=tk.W)

        columns_btn = ttk.Button(toolbar, text="Columns...", command=self.open_grid_column_selector)
        columns_btn.grid(row=0, column=3, padx=(10, 0), sticky=tk.W)

        edit_btn = ttk.Button(toolbar, text="Edit Selected", command=self._open_grid_edit_modal)
        edit_btn.grid(row=0, column=4, padx=(10, 0), sticky=tk.W)

        undo_btn = ttk.Button(toolbar, text="Undo", command=self._undo_last_edit)
        undo_btn.grid(row=0, column=5, padx=(10, 0), sticky=tk.W)

        export_btn = ttk.Button(toolbar, text="Export CSV", command=self.export_grid_csv)
        export_btn.grid(row=0, column=6, padx=(10, 0), sticky=tk.W)

        prev_btn = ttk.Button(toolbar, text="◀ Prev", command=self._prev_grid_page)
        prev_btn.grid(row=0, column=7, padx=(16, 4), sticky=tk.W)
        next_btn = ttk.Button(toolbar, text="Next ▶", command=self._next_grid_page)
        next_btn.grid(row=0, column=8, padx=(0, 10), sticky=tk.W)

        ttk.Label(toolbar, text="Page", style="Body.TLabel").grid(row=0, column=9, padx=(0, 6))
        self.analytics_grid_page_label = ttk.Label(toolbar, textvariable=self.analytics_grid_page_var, style="Body.TLabel")
        self.analytics_grid_page_label.grid(row=0, column=10, padx=(0, 6), sticky=tk.W)
        ttk.Label(toolbar, textvariable=self.analytics_grid_total_var, style="Body.TLabel").grid(row=0, column=11, sticky=tk.W)

        ttk.Label(toolbar, text="Search uses top bar", style="Body.TLabel").grid(row=0, column=12, sticky=tk.W)

        grid_frame = ttk.Frame(parent, style="App.TFrame")
        grid_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.rowconfigure(0, weight=1)

        self.analytics_grid_tree = ttk.Treeview(grid_frame, columns=(), show="headings")
        self.analytics_grid_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.analytics_grid_tree.bind("<Button-1>", self._on_grid_click)
        self.analytics_grid_tree.bind("<Double-1>", self._on_grid_double_click)
        self.analytics_grid_tree.bind("<Button-2>", self._on_grid_right_click)
        self.analytics_grid_tree.bind("<Button-3>", self._on_grid_right_click)
        self.analytics_grid_tree.bind("<Control-Button-1>", self._on_grid_right_click)

        y_scroll = ttk.Scrollbar(grid_frame, orient=tk.VERTICAL, command=self.analytics_grid_tree.yview)
        y_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        x_scroll = ttk.Scrollbar(grid_frame, orient=tk.HORIZONTAL, command=self.analytics_grid_tree.xview)
        x_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.analytics_grid_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        parent.rowconfigure(1, weight=1)

        self.analytics_grid_menu = tk.Menu(self.root, tearoff=0)
        self.analytics_grid_menu.add_command(label="Edit", command=self._open_grid_edit_modal)
        self.analytics_grid_menu.add_command(label="Details", command=self._open_grid_selected_details)

    def refresh_data_grid(self):
        if not self.db_config.get("enabled"):
            self.show_message("Database Disabled", "Enable database storage in Settings to view analytics.", kind="warning")
            return

        self.analytics_selected_employee_code = None
        self.analytics_selected_employee_name = None
        self.analytics_grid_page_var.set(1)
        self._load_grid_page(1)

    def _normalize_text(self, value):
        if value is None:
            return ""
        text = str(value)
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()

    def _apply_search_filter(self, rows, search):
        if not search:
            return rows
        needle = self._normalize_text(search)
        if not needle:
            return rows
        filtered = []
        for row in rows:
            for cell in row:
                if needle in self._normalize_text(cell):
                    filtered.append(row)
                    break
        return filtered

    def _apply_grid_column_filters(self, rows, columns):
        if not self.analytics_grid_filter_vars:
            return rows
        filtered = []
        active_filters = {
            name: self._normalize_text(var.get())
            for name, var in self.analytics_grid_filter_vars.items()
            if var.get().strip()
        }
        if not active_filters:
            return rows
        column_index = {col: idx for idx, col in enumerate(columns)}
        for row in rows:
            matched = True
            for col, needle in active_filters.items():
                idx = column_index.get(col)
                if idx is None:
                    continue
                if needle not in self._normalize_text(row[idx]):
                    matched = False
                    break
            if matched:
                filtered.append(row)
        return filtered

    def _build_grid_filters(self, columns):
        for child in self.analytics_grid_filters_frame.winfo_children():
            child.destroy()
        existing = {col: var.get() for col, var in self.analytics_grid_filter_vars.items()}
        self.analytics_grid_filter_vars = {}
        self.analytics_grid_filter_columns = list(columns)
        if not columns:
            return
        ttk.Label(self.analytics_grid_filters_frame, text="Column Filters", style="Body.TLabel").grid(row=0, column=0, padx=(0, 8))
        for idx, col in enumerate(columns, start=1):
            var = tk.StringVar(value=existing.get(col, ""))
            entry = ttk.Entry(self.analytics_grid_filters_frame, textvariable=var, width=12)
            entry.grid(row=0, column=idx, padx=(0, 6))
            entry.bind("<KeyRelease>", self._on_grid_filter_change)
            self.analytics_grid_filter_vars[col] = var
        clear_btn = ttk.Button(self.analytics_grid_filters_frame, text="Clear Filters", command=self._clear_grid_filters)
        clear_btn.grid(row=0, column=len(columns) + 1, padx=(6, 0), sticky=tk.W)

    def _clear_grid_filters(self):
        for var in self.analytics_grid_filter_vars.values():
            var.set("")
        self._apply_grid_filters_from_cache()

    def _on_grid_filter_change(self, _event=None):
        self._apply_grid_filters_from_cache()

    def _on_grid_limit_change(self, _event=None):
        self.analytics_grid_page_var.set(1)
        self._load_grid_page(1)

    def _prev_grid_page(self):
        current = int(self.analytics_grid_page_var.get())
        if current > 1:
            self._load_grid_page(current - 1)

    def _next_grid_page(self):
        current = int(self.analytics_grid_page_var.get())
        total_pages = self._get_grid_total_pages()
        if current < total_pages:
            self._load_grid_page(current + 1)

    def _get_grid_total_pages(self):
        limit = max(int(self.analytics_grid_limit_var.get()), 1)
        total_rows = getattr(self, "analytics_grid_total_rows", 0)
        if total_rows <= 0:
            return 1
        return max(1, math.ceil(total_rows / limit))

    def _load_grid_page(self, page_number):
        start_date, end_date, document_type, _ = self._get_global_filters()
        limit = max(int(self.analytics_grid_limit_var.get()), 1)
        total_rows = db_storage.fetch_payroll_entry_count(
            self.db_config,
            start_date=start_date,
            end_date=end_date,
            document_type=document_type,
        )
        self.analytics_grid_total_rows = total_rows
        total_pages = max(1, math.ceil(total_rows / limit)) if total_rows else 1
        page_number = max(1, min(page_number, total_pages))
        offset = max(page_number - 1, 0) * limit
        self.analytics_grid_page_var.set(page_number)
        columns, rows = db_storage.fetch_payroll_entries(
            self.db_config,
            start_date=start_date,
            end_date=end_date,
            document_type=document_type,
            search=None,
            limit=limit,
            offset=offset,
        )
        self.analytics_grid_cache_columns = columns
        self.analytics_grid_cache_rows = rows
        if not getattr(self, "analytics_grid_columns", None):
            self.analytics_grid_columns = [col for col in columns if col != "entry_id"]
        self.analytics_grid_total_var.set(f"of {total_pages} ({total_rows} rows)")
        self._apply_grid_filters_from_cache()

    def _apply_grid_filters_from_cache(self):
        columns = self.analytics_grid_cache_columns
        display_columns = self.analytics_grid_columns or [col for col in columns if col != "entry_id"]
        rows = self.analytics_grid_cache_rows
        search = self.global_search_var.get().strip()
        filtered_rows = self._apply_search_filter(rows, search)
        self._reset_grid_treeview(columns, display_columns)
        self._populate_treeview(self.analytics_grid_tree, filtered_rows)
        for col in display_columns:
            self.analytics_grid_tree.heading(col, text=col, command=lambda c=col: self._sort_treeview(self.analytics_grid_tree, c, False))
        if search:
            self.global_filter_status.set(f"Filtered ({len(filtered_rows)} rows)")
        else:
            self.global_filter_status.set("")
        self._refresh_kpis()

    def _reset_grid_treeview(self, columns, display_columns):
        self.analytics_grid_tree.delete(*self.analytics_grid_tree.get_children())
        self.analytics_grid_tree["columns"] = columns
        self.analytics_grid_tree["displaycolumns"] = display_columns
        for col in columns:
            self.analytics_grid_tree.heading(col, text=col)
            width = max(100, len(col) * 10)
            self.analytics_grid_tree.column(col, width=width, anchor=tk.W)
    def _sort_treeview(self, tree, col, reverse):
        data = [(tree.set(k, col), k) for k in tree.get_children("")]
        def to_number(value):
            try:
                return float(value)
            except Exception:
                return value
        data.sort(key=lambda item: to_number(item[0]), reverse=reverse)
        for index, (_, k) in enumerate(data):
            tree.move(k, "", index)
        tree.heading(col, command=lambda: self._sort_treeview(tree, col, not reverse))

    def _on_grid_right_click(self, event):
        if not self.analytics_grid_menu:
            return
        row_id = self.analytics_grid_tree.identify_row(event.y)
        if row_id:
            self.analytics_grid_tree.selection_set(row_id)
        try:
            self.analytics_grid_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.analytics_grid_menu.grab_release()

    def _on_grid_click(self, event):
        col_id = self.analytics_grid_tree.identify_column(event.x)
        if not col_id:
            return
        col_index = int(col_id[1:]) - 1
        display_columns = list(self.analytics_grid_tree["displaycolumns"])
        if col_index < 0 or col_index >= len(display_columns):
            return
        self.last_grid_column = display_columns[col_index]

    def _open_grid_selected_details(self):
        selection = self.analytics_grid_tree.selection()
        if not selection:
            self.show_message("Details", "Select a row to view details.", kind="info")
            return
        row_id = selection[0]
        columns = list(self.analytics_grid_tree["columns"])
        values = self.analytics_grid_tree.item(row_id, "values")
        employee_code = self._get_grid_value(values, columns, "employee_code")
        employee_name = self._get_grid_value(values, columns, "employee_name")
        self._open_employee_detail(employee_code=employee_code, employee_name=employee_name, push_state=True)

    def _on_grid_double_click(self, event):
        if not hasattr(self, "analytics_grid_tree"):
            return
        if not self._can_edit():
            self.show_message("Read-only", "Editing is disabled in viewer mode.", kind="info")
            return
        region = self.analytics_grid_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.analytics_grid_tree.identify_row(event.y)
        col_id = self.analytics_grid_tree.identify_column(event.x)
        if not row_id or not col_id:
            return
        col_index = int(col_id[1:]) - 1
        display_columns = list(self.analytics_grid_tree["displaycolumns"])
        if col_index < 0 or col_index >= len(display_columns):
            return
        col_name = display_columns[col_index]
        editable = {"document_type", "payment_date", "basic_salary", "total_earnings", "net_pay"}
        if col_name not in editable:
            return
        bbox = self.analytics_grid_tree.bbox(row_id, col_id)
        if not bbox:
            return
        value = self.analytics_grid_tree.set(row_id, col_name)
        self._start_grid_edit(row_id, col_name, value, bbox)

    def _start_grid_edit(self, row_id, col_name, value, bbox):
        self._cancel_grid_edit()
        x, y, width, height = bbox
        entry = ttk.Entry(self.analytics_grid_tree)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, value)
        entry.select_range(0, tk.END)
        entry.focus()
        entry.bind("<Return>", lambda _event: self._commit_grid_edit())
        entry.bind("<Escape>", lambda _event: self._cancel_grid_edit())
        entry.bind("<FocusOut>", lambda _event: self._commit_grid_edit())
        self.grid_edit_entry = entry
        self.grid_editing_cell = (row_id, col_name, value)

    def _commit_grid_edit(self):
        if not self.grid_edit_entry or not self.grid_editing_cell:
            return
        if not self._can_edit():
            self._cancel_grid_edit()
            self.show_message("Read-only", "Editing is disabled in viewer mode.", kind="info")
            return
        row_id, col_name, old_value = self.grid_editing_cell
        new_value = self.grid_edit_entry.get().strip()
        self._cancel_grid_edit()
        if new_value == str(old_value):
            return
        is_valid, normalized_value, message = self._validate_grid_edit(col_name, new_value)
        if not is_valid:
            self.show_message("Edit Error", message, kind="warning")
            return
        columns = list(self.analytics_grid_tree["columns"])
        values = self.analytics_grid_tree.item(row_id, "values")
        entry_id = self._get_grid_value(values, columns, "entry_id")
        if entry_id is None:
            self.show_message("Edit Error", "Missing entry id for update.", kind="warning")
            return
        try:
            db_storage.update_payroll_entry(self.db_config, int(entry_id), col_name, normalized_value)
            db_storage.append_audit_log(self.db_config, int(entry_id), col_name, old_value, normalized_value)
        except Exception as exc:
            self.show_message("Edit Error", str(exc), kind="warning")
            return
        self.analytics_grid_tree.set(row_id, col_name, normalized_value)
        self._update_grid_cache(entry_id, col_name, normalized_value)
        self._push_undo(entry_id, col_name, old_value, normalized_value)
        self._refresh_kpis()

    def _cancel_grid_edit(self):
        if self.grid_edit_entry is not None:
            self.grid_edit_entry.destroy()
        self.grid_edit_entry = None
        self.grid_editing_cell = None

    def _validate_grid_edit(self, col_name, value):
        if not value:
            return False, value, "Value is required."
        if col_name in {"basic_salary", "total_earnings", "net_pay"}:
            try:
                parsed = float(value.replace(",", ""))
            except Exception:
                return False, value, "Enter a valid number."
            return True, round(parsed, 2), ""
        if col_name == "payment_date":
            cleaned = value.replace("/", "-")
            try:
                parsed = datetime.date.fromisoformat(cleaned)
            except Exception:
                return False, value, "Use YYYY-MM-DD for dates."
            return True, parsed, ""
        if col_name == "document_type":
            allowed = {"salary", "bonus", "vacation_allowance", "unused_leave_compensation", "other"}
            if value not in allowed:
                return False, value, f"Document type must be one of: {', '.join(sorted(allowed))}."
            return True, value, ""
        return False, value, "This field cannot be edited."

    def _update_grid_cache(self, entry_id, col_name, value):
        if not self.analytics_grid_cache_columns:
            return
        try:
            id_idx = self.analytics_grid_cache_columns.index("entry_id")
            col_idx = self.analytics_grid_cache_columns.index(col_name)
        except ValueError:
            return
        updated_rows = []
        for row in self.analytics_grid_cache_rows:
            if str(row[id_idx]) == str(entry_id):
                row_list = list(row)
                row_list[col_idx] = value
                updated_rows.append(tuple(row_list))
            else:
                updated_rows.append(row)
        self.analytics_grid_cache_rows = updated_rows

    def _push_undo(self, entry_id, field, old_value, new_value):
        self.edit_undo_stack.append(
            {
                "entry_id": int(entry_id),
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
            }
        )
        self.edit_redo_stack.clear()

    def _undo_last_edit(self):
        if not self.edit_undo_stack:
            self.show_message("Undo", "Nothing to undo.", kind="info")
            return
        if not self._can_edit():
            self.show_message("Read-only", "Editing is disabled in viewer mode.", kind="info")
            return
        last = self.edit_undo_stack.pop()
        entry_id = last["entry_id"]
        field = last["field"]
        old_value = last["old_value"]
        new_value = last["new_value"]
        try:
            db_storage.update_payroll_entry(self.db_config, entry_id, field, old_value)
            db_storage.append_audit_log(self.db_config, entry_id, field, new_value, old_value)
        except Exception as exc:
            self.show_message("Undo Error", str(exc), kind="warning")
            return
        self.edit_redo_stack.append(last)
        self._update_grid_cache(entry_id, field, old_value)
        self._apply_grid_cell_update(entry_id, field, old_value)
        self._refresh_kpis()

    def _redo_last_edit(self):
        if not self.edit_redo_stack:
            self.show_message("Redo", "Nothing to redo.", kind="info")
            return
        if not self._can_edit():
            self.show_message("Read-only", "Editing is disabled in viewer mode.", kind="info")
            return
        last = self.edit_redo_stack.pop()
        entry_id = last["entry_id"]
        field = last["field"]
        old_value = last["old_value"]
        new_value = last["new_value"]
        try:
            db_storage.update_payroll_entry(self.db_config, entry_id, field, new_value)
            db_storage.append_audit_log(self.db_config, entry_id, field, old_value, new_value)
        except Exception as exc:
            self.show_message("Redo Error", str(exc), kind="warning")
            return
        self.edit_undo_stack.append(last)
        self._update_grid_cache(entry_id, field, new_value)
        self._apply_grid_cell_update(entry_id, field, new_value)
        self._refresh_kpis()

    def _apply_grid_cell_update(self, entry_id, field, value):
        columns = list(self.analytics_grid_tree["columns"])
        if "entry_id" not in columns:
            return
        id_idx = columns.index("entry_id")
        for row_id in self.analytics_grid_tree.get_children(""):
            values = self.analytics_grid_tree.item(row_id, "values")
            if id_idx < len(values) and str(values[id_idx]) == str(entry_id):
                self.analytics_grid_tree.set(row_id, field, value)
                break

    def _focus_global_search(self):
        if hasattr(self, "global_search_entry"):
            self.global_search_entry.focus_set()
            self.global_search_entry.select_range(0, tk.END)

    def _copy_grid_cell(self):
        if not hasattr(self, "analytics_grid_tree"):
            return
        selection = self.analytics_grid_tree.selection()
        if not selection:
            return
        row_id = selection[0]
        columns = list(self.analytics_grid_tree["columns"])
        values = self.analytics_grid_tree.item(row_id, "values")
        if not values:
            return
        if self.last_grid_column and self.last_grid_column in columns:
            col_idx = columns.index(self.last_grid_column)
            if col_idx < len(values):
                value = values[col_idx]
            else:
                value = values[0]
        else:
            value = values[0]
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(value))
        except tk.TclError:
            pass

    def _apply_ui_prefs(self):
        prefs = self.ui_prefs
        self.global_start_year_var.set(prefs.get("start_year", self.global_start_year_var.get()))
        self.global_start_month_var.set(prefs.get("start_month", self.global_start_month_var.get()))
        self.global_end_year_var.set(prefs.get("end_year", self.global_end_year_var.get()))
        self.global_end_month_var.set(prefs.get("end_month", self.global_end_month_var.get()))
        self.global_doc_type_var.set(prefs.get("document_type", self.global_doc_type_var.get()))
        self.edit_lock_var.set(bool(prefs.get("edit_lock", self.edit_lock_var.get())))
        grid_columns = prefs.get("grid_columns")
        if isinstance(grid_columns, list):
            self.analytics_grid_columns = grid_columns
        self._update_window_label()

    def _open_grid_edit_modal(self):
        if not hasattr(self, "analytics_grid_tree"):
            return
        if not self._can_edit():
            self.show_message("Read-only", "Editing is disabled in viewer mode.", kind="info")
            return
        selection = self.analytics_grid_tree.selection()
        if not selection:
            self.show_message("Edit", "Select a row to edit.", kind="info")
            return
        row_id = selection[0]
        columns = list(self.analytics_grid_tree["columns"])
        values = self.analytics_grid_tree.item(row_id, "values")
        entry_id = self._get_grid_value(values, columns, "entry_id")
        if entry_id is None:
            self.show_message("Edit", "Missing entry id for update.", kind="warning")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Entry")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        def current_value(name):
            return self._get_grid_value(values, columns, name)

        original = {
            "document_type": current_value("document_type") or "",
            "payment_date": current_value("payment_date") or "",
            "basic_salary": current_value("basic_salary") or "",
            "total_earnings": current_value("total_earnings") or "",
            "net_pay": current_value("net_pay") or "",
        }

        doc_var = tk.StringVar(value=original["document_type"])
        date_var = tk.StringVar(value=str(original["payment_date"]))
        basic_var = tk.StringVar(value=str(original["basic_salary"]))
        total_var = tk.StringVar(value=str(original["total_earnings"]))
        net_var = tk.StringVar(value=str(original["net_pay"]))

        ttk.Label(frame, text="Document Type", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        doc_combo = ttk.Combobox(frame, textvariable=doc_var, state="readonly", width=24)
        doc_combo["values"] = ["salary", "bonus", "vacation_allowance", "unused_leave_compensation", "other"]
        doc_combo.grid(row=0, column=1, pady=(0, 6))

        ttk.Label(frame, text="Payment Date (YYYY-MM-DD)", style="Body.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=date_var, width=26).grid(row=1, column=1, pady=(0, 6))

        ttk.Label(frame, text="Basic Salary", style="Body.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=basic_var, width=26).grid(row=2, column=1, pady=(0, 6))

        ttk.Label(frame, text="Total Earnings", style="Body.TLabel").grid(row=3, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=total_var, width=26).grid(row=3, column=1, pady=(0, 6))

        ttk.Label(frame, text="Net Pay", style="Body.TLabel").grid(row=4, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=net_var, width=26).grid(row=4, column=1, pady=(0, 6))

        error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=error_var, style="Body.TLabel").grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(4, 8))

        def on_save():
            updates = {
                "document_type": doc_var.get().strip(),
                "payment_date": date_var.get().strip(),
                "basic_salary": basic_var.get().strip(),
                "total_earnings": total_var.get().strip(),
                "net_pay": net_var.get().strip(),
            }
            normalized = {}
            for field, value in updates.items():
                valid, normalized_value, message = self._validate_grid_edit(field, value)
                if not valid:
                    error_var.set(message)
                    return
                normalized[field] = normalized_value
            try:
                for field, value in normalized.items():
                    if str(value) == str(original.get(field)):
                        continue
                    db_storage.update_payroll_entry(self.db_config, int(entry_id), field, value)
                    db_storage.append_audit_log(self.db_config, int(entry_id), field, original.get(field), value)
                    self.analytics_grid_tree.set(row_id, field, value)
                    self._update_grid_cache(entry_id, field, value)
                    self._push_undo(entry_id, field, original.get(field), value)
            except Exception as exc:
                error_var.set(str(exc))
                return
            dialog.destroy()
            self._refresh_kpis()

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=6, column=0, columnspan=2, sticky=tk.E)
        ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def _build_detail_tab(self, parent):
        header = ttk.Frame(parent, style="App.TFrame")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Employee Detail", style="Section.TLabel").grid(row=0, column=0, padx=(0, 10))
        self.analytics_detail_label_var = tk.StringVar(value="Select an employee from the Data Grid.")
        ttk.Label(header, textvariable=self.analytics_detail_label_var, style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)
        self.analytics_detail_total_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.analytics_detail_total_var, style="Body.TLabel").grid(row=0, column=2, sticky=tk.E)

        frame = ttk.Frame(parent, style="App.TFrame")
        frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.analytics_detail_tree = ttk.Treeview(frame, columns=(), show="headings")
        self.analytics_detail_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.analytics_detail_tree.yview)
        y_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.analytics_detail_tree.xview)
        x_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.analytics_detail_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        parent.rowconfigure(1, weight=1)

    def _get_grid_value(self, values, columns, name):
        if not columns or name not in columns:
            return None
        idx = columns.index(name)
        if idx >= len(values):
            return None
        return values[idx]

    def open_grid_column_selector(self):
        if not hasattr(self, "analytics_grid_cache_columns"):
            return
        available = self.analytics_grid_cache_columns or self.analytics_grid_columns
        available = [col for col in available if col != "entry_id"]
        if not available:
            self.show_message("Columns", "Refresh the grid first.", kind="info")
            return
        selected = set(self.analytics_grid_columns or available)
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Columns")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=12)
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
            self.analytics_grid_columns = chosen
            self._save_ui_prefs()
            dialog.destroy()
            self._filter_grid_columns()

        ttk.Button(button_frame, text="Apply", command=on_apply).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def _filter_grid_columns(self):
        if not hasattr(self, "analytics_grid_columns"):
            return
        self._apply_grid_filters_from_cache()

    def export_grid_csv(self):
        if not hasattr(self, "analytics_grid_tree"):
            return
        path = filedialog.asksaveasfilename(
            title="Export Data Grid",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        columns = self.analytics_grid_tree["columns"]
        rows = [self.analytics_grid_tree.item(k, "values") for k in self.analytics_grid_tree.get_children("")]
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(rows)
            self.show_message("Export", f"CSV exported to:\\n{path}", kind="info")
        except Exception as exc:
            self.show_message("Export Error", str(exc), kind="warning")

    def _on_grid_select(self, _event=None):
        if not hasattr(self, "analytics_grid_tree"):
            return
        selection = self.analytics_grid_tree.selection()
        if not selection:
            self.analytics_selected_employee_code = None
            self.analytics_selected_employee_name = None
            self._refresh_kpis()
            return
        columns = list(self.analytics_grid_tree["columns"])
        values = self.analytics_grid_tree.item(selection[0], "values")
        employee_code = self._get_grid_value(values, columns, "employee_code")
        employee_name = self._get_grid_value(values, columns, "employee_name")
        self._open_employee_detail(employee_code=employee_code, employee_name=employee_name)

    def create_dashboard_tab(self):
        """Create the dashboard tab with current metrics."""
        self.dashboard_tab.columnconfigure(0, weight=1)
        self.dashboard_tab.rowconfigure(2, weight=1)

        header = ttk.Frame(self.dashboard_tab, style="App.TFrame")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        header.columnconfigure(6, weight=1)

        ttk.Label(header, text="Dashboard", style="Header.TLabel").grid(row=0, column=0, padx=(0, 10))
        refresh_btn = ttk.Button(header, text="Refresh", command=self.refresh_dashboard)
        refresh_btn.grid(row=0, column=1, padx=(0, 10))

        self.dashboard_status_var = tk.StringVar(value="Ready.")
        ttk.Label(header, textvariable=self.dashboard_status_var, style="Body.TLabel").grid(row=0, column=2, sticky=tk.W)

        cards_frame = ttk.Frame(self.dashboard_tab, style="App.TFrame")
        cards_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        for idx in range(4):
            cards_frame.columnconfigure(idx, weight=1)

        self.dashboard_total_net_var = tk.StringVar(value="—")
        self.dashboard_employer_cost_var = tk.StringVar(value="—")
        self.dashboard_total_insurance_var = tk.StringVar(value="—")
        self.dashboard_employee_count_var = tk.StringVar(value="—")

        self._build_kpi_card(cards_frame, 0, "Total Net Pay", self.dashboard_total_net_var)
        self._build_kpi_card(cards_frame, 1, "Employer Cost", self.dashboard_employer_cost_var)
        self._build_kpi_card(cards_frame, 2, "Total Insurance", self.dashboard_total_insurance_var)
        self._build_kpi_card(cards_frame, 3, "Employees", self.dashboard_employee_count_var)

        content_frame = ttk.Frame(self.dashboard_tab, style="App.TFrame")
        content_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        content_frame.columnconfigure(0, weight=3)
        content_frame.columnconfigure(1, weight=2)
        content_frame.rowconfigure(0, weight=1)

        chart_frame = ttk.Frame(content_frame, style="App.TFrame")
        chart_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 12))
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(0, weight=1)

        fig = Figure(figsize=(8, 4), dpi=100)
        ax = fig.add_subplot(1, 1, 1)
        canvas = FigureCanvasTkAgg(fig, master=chart_frame)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        toolbar = NavigationToolbar2Tk(canvas, chart_frame)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.dashboard_chart = {"fig": fig, "ax": ax, "canvas": canvas, "toolbar": toolbar}
        canvas.mpl_connect("button_press_event", self._on_dashboard_chart_click)

        anomalies_frame = ttk.Frame(content_frame, style="App.TFrame")
        anomalies_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        anomalies_frame.columnconfigure(0, weight=1)
        anomalies_frame.rowconfigure(1, weight=1)
        anomalies_frame.rowconfigure(3, weight=1)

        ttk.Label(anomalies_frame, text="Anomalies", style="Section.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        self.dashboard_anomaly_tree = ttk.Treeview(anomalies_frame, columns=(), show="headings", height=8)
        self.dashboard_anomaly_tree.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.dashboard_anomaly_tree.bind("<<TreeviewSelect>>", self._on_dashboard_anomaly_select)

        y_scroll = ttk.Scrollbar(anomalies_frame, orient=tk.VERTICAL, command=self.dashboard_anomaly_tree.yview)
        y_scroll.grid(row=1, column=1, sticky=(tk.N, tk.S))
        self.dashboard_anomaly_tree.configure(yscrollcommand=y_scroll.set)

        ttk.Label(anomalies_frame, text="Latest Entries", style="Section.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(12, 6))
        self.dashboard_recent_tree = ttk.Treeview(anomalies_frame, columns=(), show="headings", height=8)
        self.dashboard_recent_tree.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.dashboard_recent_tree.bind("<<TreeviewSelect>>", self._on_dashboard_recent_select)
        recent_scroll = ttk.Scrollbar(anomalies_frame, orient=tk.VERTICAL, command=self.dashboard_recent_tree.yview)
        recent_scroll.grid(row=3, column=1, sticky=(tk.N, tk.S))
        self.dashboard_recent_tree.configure(yscrollcommand=recent_scroll.set)

    def refresh_dashboard(self):
        if not self.db_config.get("enabled"):
            self.dashboard_status_var.set("Database storage is disabled.")
            self.show_message("Database Disabled", "Enable database storage in Settings to view the dashboard.", kind="warning")
            return

        self.dashboard_status_var.set("Refreshing...")
        try:
            self._refresh_global_filters()
            start_date, end_date, document_type, search = self._get_global_filters()

            metrics = db_storage.fetch_dashboard_metrics(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            )
            total_net = metrics["total_net_pay"]
            total_insurance = metrics["employee_insurance"] + metrics["employer_insurance"]
            employer_cost = total_net + metrics["employer_insurance"]

            self.dashboard_total_net_var.set(self._format_currency(total_net))
            self.dashboard_employer_cost_var.set(self._format_currency(employer_cost))
            self.dashboard_total_insurance_var.set(self._format_currency(total_insurance))
            self.dashboard_employee_count_var.set(str(metrics["employee_count"]))

            monthly_rows = db_storage.fetch_monthly_summary(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            )
            self._plot_dashboard_summary(monthly_rows)

            anomaly_columns, anomaly_rows = db_storage.fetch_anomaly_entries(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
                limit=20,
            )
            self._reset_treeview(self.dashboard_anomaly_tree, anomaly_columns)
            self._populate_treeview(self.dashboard_anomaly_tree, anomaly_rows)

            recent_columns, recent_rows = db_storage.fetch_recent_entries(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
                limit=20,
            )
            self._reset_treeview(self.dashboard_recent_tree, recent_columns)
            self._populate_treeview(self.dashboard_recent_tree, recent_rows)

            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.dashboard_status_var.set(f"Last refreshed at {timestamp}.")
        except Exception as exc:
            self.dashboard_status_var.set("Refresh failed.")
            self.show_message("Dashboard Error", str(exc), kind="warning")

    def _build_monthly_employee_tab(self, parent):
        toolbar = ttk.Frame(parent, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        toolbar.columnconfigure(2, weight=1)

        refresh_btn = ttk.Button(toolbar, text="Refresh", command=self.refresh_monthly_employee_summary)
        refresh_btn.grid(row=0, column=0, padx=(0, 10))

        self.analytics_monthly_status_var = tk.StringVar(value="Ready.")
        ttk.Label(toolbar, textvariable=self.analytics_monthly_status_var, style="Body.TLabel").grid(row=0, column=2, sticky=tk.W)

        frame = ttk.Frame(parent, style="App.TFrame")
        frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.analytics_monthly_tree = ttk.Treeview(frame, columns=(), show="headings")
        self.analytics_monthly_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.analytics_monthly_tree.yview)
        y_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.analytics_monthly_tree.xview)
        x_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.analytics_monthly_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        parent.rowconfigure(1, weight=1)

    def refresh_monthly_employee_summary(self):
        if not self.db_config.get("enabled"):
            self.analytics_monthly_status_var.set("Database storage is disabled.")
            self.show_message("Database Disabled", "Enable database storage in Settings to view analytics.", kind="warning")
            return

        try:
            start_date, end_date, document_type, _ = self._get_global_filters()

            columns, rows = db_storage.fetch_monthly_employee_summary(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                limit=500,
            )
            self._reset_treeview(self.analytics_monthly_tree, columns)
            self._populate_treeview(self.analytics_monthly_tree, rows)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.analytics_monthly_status_var.set(f"Last refreshed at {timestamp}.")
        except Exception as exc:
            self.analytics_monthly_status_var.set("Refresh failed.")
            self.show_message("Analytics Error", str(exc), kind="warning")

    def _refresh_global_filters(self):
        if not self.db_config.get("enabled"):
            return
        years = db_storage.fetch_available_years(self.db_config)
        year_values = ["All"] + [str(year) for year in years]
        self.global_start_year_combo["values"] = year_values
        self.global_end_year_combo["values"] = year_values
        if self.global_start_year_var.get() not in year_values:
            self.global_start_year_var.set(year_values[1] if len(year_values) > 1 else "All")
        if self.global_end_year_var.get() not in year_values:
            self.global_end_year_var.set(self.global_start_year_var.get())
        self._refresh_global_months()
        self._update_window_label()

    def _refresh_global_months(self):
        month_values = [f"{month:02d}" for month in range(1, 13)]
        self.global_start_month_combo["values"] = month_values
        self.global_end_month_combo["values"] = month_values
        if self.global_start_month_var.get() not in month_values:
            self.global_start_month_var.set(month_values[0])
        if self.global_end_month_var.get() not in month_values:
            self.global_end_month_var.set(self.global_start_month_var.get())
        self._update_window_label()

    def _on_global_year_change(self, _event=None):
        start_year_val = self.global_start_year_var.get()
        if start_year_val == "All":
            self.global_end_year_var.set("All")
        elif self.global_end_year_var.get() == "All":
            self.global_end_year_var.set(start_year_val)
        self._refresh_global_months()
        self._save_ui_prefs()
        self._refresh_all_views()

    def _on_global_filter_change(self, _event=None):
        self._update_window_label()
        self._save_ui_prefs()
        self._refresh_all_views()

    def _on_global_search(self, _event=None):
        if self.grid_search_job is not None:
            try:
                self.root.after_cancel(self.grid_search_job)
            except tk.TclError:
                pass
        self.global_filter_status.set("Searching…")
        self.grid_search_job = self.root.after(300, self.refresh_data_grid)

    def _refresh_all_views(self):
        self.refresh_analytics()
        self.refresh_dashboard()
        self.refresh_data_grid()
        self.refresh_monthly_employee_summary()

    def _update_window_label(self):
        start_year_val = self.global_start_year_var.get()
        end_year_val = self.global_end_year_var.get()
        start_month_val = self.global_start_month_var.get()
        end_month_val = self.global_end_month_var.get()
        if (
            not start_year_val
            or start_year_val == "All"
            or not end_year_val
            or end_year_val == "All"
            or not start_month_val
            or not end_month_val
        ):
            self.global_window_label_var.set("All months")
            self.global_range_end_year = None
            self.global_range_end_month = None
            return
        start_year = int(start_year_val)
        start_month = int(start_month_val)
        end_year = int(end_year_val)
        end_month = int(end_month_val)
        start_date = datetime.date(start_year, start_month, 1)
        end_day = calendar.monthrange(end_year, end_month)[1]
        end_date = datetime.date(end_year, end_month, end_day)
        if end_date < start_date:
            end_year = start_year
            end_month = start_month
            self.global_end_year_var.set(str(end_year))
            self.global_end_month_var.set(f"{end_month:02d}")
        self.global_range_end_year = end_year
        self.global_range_end_month = end_month
        start_label = f"{calendar.month_name[start_month][:3]} {start_year}"
        end_label = f"{calendar.month_name[end_month][:3]} {end_year}"
        self.global_window_label_var.set(f"{start_label} → {end_label}")

    def _get_global_filters(self):
        start_year_val = self.global_start_year_var.get()
        end_year_val = self.global_end_year_var.get()
        start_month_val = self.global_start_month_var.get()
        end_month_val = self.global_end_month_var.get()
        if (
            start_year_val
            and start_year_val != "All"
            and end_year_val
            and end_year_val != "All"
            and start_month_val
            and end_month_val
        ):
            start_year = int(start_year_val)
            start_month = int(start_month_val)
            end_year = int(end_year_val)
            end_month = int(end_month_val)
            start_date = datetime.date(start_year, start_month, 1)
            end_day = calendar.monthrange(end_year, end_month)[1]
            end_date = datetime.date(end_year, end_month, end_day)
            if end_date < start_date:
                end_year = start_year
                end_month = start_month
                self.global_end_year_var.set(str(end_year))
                self.global_end_month_var.set(f"{end_month:02d}")
                end_day = calendar.monthrange(end_year, end_month)[1]
                end_date = datetime.date(end_year, end_month, end_day)
            self.global_range_end_year = end_year
            self.global_range_end_month = end_month
        else:
            start_date = None
            end_date = None
            self.global_range_end_year = None
            self.global_range_end_month = None
        doc_type_val = self.global_doc_type_var.get()
        document_type = None if doc_type_val == "All" else doc_type_val
        search = self.global_search_var.get().strip()
        return start_date, end_date, document_type, search

    def create_db_tab(self):
        """Create the database views tab."""
        self.db_tab.columnconfigure(0, weight=1)
        self.db_tab.rowconfigure(2, weight=1)

        title_label = ttk.Label(self.db_tab, text="Database Views", style="Section.TLabel")
        title_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        toolbar = ttk.Frame(self.db_tab)
        toolbar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        toolbar.columnconfigure(6, weight=1)

        refresh_btn = ttk.Button(toolbar, text="Refresh Data", command=self.refresh_db_views)
        refresh_btn.grid(row=0, column=0, padx=(0, 10))

        ttk.Label(toolbar, text="Filter", style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)
        self.db_filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(toolbar, textvariable=self.db_filter_var, width=24)
        filter_entry.grid(row=0, column=2, padx=(6, 10), sticky=tk.W)

        ttk.Label(toolbar, text="Limit", style="Body.TLabel").grid(row=0, column=3, sticky=tk.W)
        self.db_limit_var = tk.IntVar(value=500)
        limit_spin = ttk.Spinbox(toolbar, from_=50, to=5000, textvariable=self.db_limit_var, width=6)
        limit_spin.grid(row=0, column=4, padx=(6, 10), sticky=tk.W)

        columns_btn = ttk.Button(toolbar, text="Columns...", command=self.open_column_selector)
        columns_btn.grid(row=0, column=5, padx=(0, 10))

        self.db_status_var = tk.StringVar(value="Ready to refresh.")
        status_label = ttk.Label(toolbar, textvariable=self.db_status_var, style="Body.TLabel")
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
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", accelerator="Cmd+Z", command=self._undo_last_edit)
        edit_menu.add_command(label="Redo", accelerator="Shift+Cmd+Z", command=self._redo_last_edit)
        edit_menu.add_separator()
        edit_menu.add_checkbutton(
            label="Lock Editing",
            variable=self.edit_lock_var,
            command=self._toggle_edit_lock,
        )
        menubar.add_cascade(label="Edit", menu=edit_menu)
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
            "Version 2.2.5\n"
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
        role_var = tk.StringVar(value=str(self.db_config.get("role", "editor")))
        audit_user_var = tk.StringVar(value=str(self.db_config.get("audit_user", "")))

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

        ttk.Label(frame, text="Role").grid(row=7, column=0, sticky=tk.W)
        role_combo = ttk.Combobox(frame, textvariable=role_var, state="readonly", width=20)
        role_combo["values"] = ("viewer", "editor")
        role_combo.grid(row=7, column=1, sticky=tk.W)

        ttk.Label(frame, text="Audit User").grid(row=8, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=audit_user_var, width=30).grid(row=8, column=1, sticky=(tk.W, tk.E))

        note = ttk.Label(frame, text="Settings are saved locally on this machine.")
        note.grid(row=9, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=10, column=0, columnspan=2, sticky=tk.E, pady=(12, 0))

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
                "role": role_var.get(),
                "audit_user": audit_user_var.get().strip(),
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

    def _can_edit(self):
        return (
            str(self.db_config.get("role", "editor")).lower() == "editor"
            and not bool(self.edit_lock_var.get())
        )

    def _toggle_edit_lock(self):
        locked = bool(self.edit_lock_var.get())
        self._save_ui_prefs()
        if locked:
            self.show_message("Edit Lock", "Editing is locked.", kind="info")
        else:
            self.show_message("Edit Lock", "Editing is unlocked.", kind="info")

    def _save_ui_prefs(self):
        prefs = {
            "start_year": self.global_start_year_var.get(),
            "start_month": self.global_start_month_var.get(),
            "end_year": self.global_end_year_var.get(),
            "end_month": self.global_end_month_var.get(),
            "document_type": self.global_doc_type_var.get(),
            "grid_columns": self.analytics_grid_columns if getattr(self, "analytics_grid_columns", None) else None,
            "edit_lock": bool(self.edit_lock_var.get()),
        }
        db_storage.save_ui_prefs(prefs)

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
