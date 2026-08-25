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

# Ensure Tk uses the app name before it initializes the Aqua menubar.
os.environ["TK_APP_NAME"] = "Payroll Processor"
import re
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import tempfile
from typing import List, Dict
import datetime
import calendar
from pathlib import Path
import subprocess
import unicodedata
import math
import textwrap
import time
import traceback
import zipfile
import json
import uuid

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
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt
import db_storage
from app_paths import DEFAULT_REPORT_DIR


def _detect_app_version(default: str = "unknown") -> str:
    """Read the version from the versions/vX.Y.Z directory this file lives in.

    The About dialog reported 3.1.3 from inside a 3.1.4 tree because the string
    was hardcoded in two places and only one got bumped. Deriving it keeps the
    two in step; the default covers the app bundle, where src/ is flattened into
    Contents/Resources and the version directory is no longer in the path.
    """
    try:
        bundled_version = Path(__file__).resolve().with_name("APP_VERSION")
        if bundled_version.is_file():
            value = bundled_version.read_text(encoding="utf-8").strip()
            if value and all(part.isdigit() for part in value.split(".")):
                return value
        name = Path(__file__).resolve().parent.parent.name
        if name.startswith("v") and all(part.isdigit() for part in name[1:].split(".")):
            return name[1:]
    except Exception:
        pass
    return default


APP_VERSION = _detect_app_version()


class Tooltip:
    """Simple tooltip helper for tkinter widgets.

    Tooltips kept surviving their trigger: <Leave> is not delivered when a
    sidebar button is restyled on a view change, when the pointer jumps out of
    the window fast, or when focus moves to another app. Rather than chase every
    such event, the visible tip polls for the pointer and retires itself, and
    only one tip is ever on screen at a time.
    """

    _visible = None  # the single tooltip currently shown, if any

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tipwindow = None
        self._after_id = None
        self._auto_hide_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        # Switching views can move focus or tear the widget down without ever
        # delivering <Leave>, which left a tooltip floating over the sidebar.
        widget.bind("<Destroy>", self._hide, add="+")
        widget.bind("<FocusOut>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self):
        if self.tipwindow or not self.text:
            return
        # Only show if the pointer is genuinely still over this widget. Restyling
        # a sidebar button on view change does not deliver <Leave>, so a tip
        # scheduled just before the switch could otherwise appear over the new
        # view and stay there with nothing left to dismiss it.
        try:
            px, py = self.widget.winfo_pointerxy()
            under = self.widget.winfo_containing(px, py)
            if under is not self.widget:
                return
        except (tk.TclError, KeyError):
            return
        # Anchor to the pointer, not to the widget. Anchoring under the widget
        # dropped the tip squarely on top of the next control in the sidebar,
        # which read as a rendering fault rather than a hint.
        try:
            px, py = self.widget.winfo_pointerxy()
        except tk.TclError:
            return
        x, y = px + 14, py + 22
        try:
            self.tipwindow = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            try:
                # Keep it above the window without stealing focus.
                tw.wm_attributes("-topmost", True)
            except tk.TclError:
                pass
            # Plain tk widgets, not ttk: aqua ignores ttk background, which is
            # what made the tip a flat white pill with no edges.
            frame = tk.Frame(tw, background="#2B2D31", highlightthickness=0, bd=0)
            frame.pack(fill=tk.BOTH, expand=True)
            label = tk.Label(
                frame,
                text=self.text,
                background="#2B2D31",
                foreground="#F5F5F7",
                font=("SF Pro Text", 11),
                padx=8,
                pady=4,
                justify=tk.LEFT,
            )
            label.pack()
            tw.update_idletasks()
            # Keep it on screen when hovering near an edge.
            width, height = tw.winfo_reqwidth(), tw.winfo_reqheight()
            screen_w = tw.winfo_screenwidth()
            screen_h = tw.winfo_screenheight()
            if x + width > screen_w - 8:
                x = max(8, screen_w - width - 8)
            if y + height > screen_h - 8:
                y = max(8, py - height - 12)
            tw.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            self.tipwindow = None
            return
        # Belt and braces: even if no hide event ever arrives, the tip retires
        # on its own rather than sitting on top of the UI indefinitely.
        # Only one tip on screen: a leaked predecessor cannot linger behind this
        # one where nothing would ever dismiss it.
        previous = Tooltip._visible
        if previous is not None and previous is not self:
            previous._hide()
        Tooltip._visible = self
        try:
            self._auto_hide_id = self.widget.after(150, self._poll_pointer)
        except tk.TclError:
            self._auto_hide_id = None

    def _poll_pointer(self):
        """Retire the tip as soon as the pointer is no longer over its widget.

        Polling frequently is what makes this reliable: whatever event was
        missed, the tip clears within a fraction of a second of the pointer
        moving away, instead of hanging around until something dismisses it.
        """
        self._auto_hide_id = None
        if not self.tipwindow:
            return
        try:
            px, py = self.widget.winfo_pointerxy()
            under = self.widget.winfo_containing(px, py)
        except (tk.TclError, KeyError):
            self._hide()
            return
        # The tip is drawn just below the pointer, so landing on the tip itself
        # still counts as hovering the trigger.
        if under is not self.widget and (
            self.tipwindow is None or under is None or not str(under).startswith(str(self.tipwindow))
        ):
            self._hide()
            return
        try:
            self._auto_hide_id = self.widget.after(150, self._poll_pointer)
        except tk.TclError:
            self._auto_hide_id = None

    def _hide(self, _event=None):
        self._cancel()
        if self._auto_hide_id:
            try:
                self.widget.after_cancel(self._auto_hide_id)
            except tk.TclError:
                pass
            self._auto_hide_id = None
        if self.tipwindow:
            try:
                self.tipwindow.destroy()
            except tk.TclError:
                pass
            self.tipwindow = None
        if Tooltip._visible is self:
            Tooltip._visible = None


class PayrollProcessorGUI:
    """Main GUI application for payroll processing."""

    # Analytics charts, grouped by the question they answer. Each group is one
    # tab holding a grid of chart cards.
    CHART_GROUPS = (
        ("Spend", (
            ("monthly", "Monthly Payroll Burn"),
            ("doc_type", "Salary vs Bonus vs Allowances"),
            ("employee", "Cost Per Employee"),
            ("cost_ratio", "Employer Cost per € of Net Pay"),
        )),
        ("Trends", (
            ("same_month_yoy", "Same Month Across Years"),
            ("ytd_compare", "YTD vs Prior YTD"),
            ("rolling_yoy", "Rolling 12-Month YoY"),
        )),
        ("Insurance", (
            ("insurance", "Insurance Breakdown"),
            ("insurance_burden", "Insurance Burden %"),
        )),
        ("Payments", (
            ("heatmap", "Payment Heat-map"),
            ("paid_aging", "Paid vs Unpaid + Aging"),
            ("avg_days_paid", "Avg Days to Paid"),
        )),
        ("Workforce", (
            ("headcount", "Headcount Trend"),
            ("pay_distribution", "Median vs Average Pay"),
        )),
    )


    def __init__(self):
        """Initialize the GUI application."""
        # Create main window
        if DRAG_DROP_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.ui_prefs = db_storage.load_ui_prefs()
        self.theme_mode_var = tk.StringVar(value=self.ui_prefs.get("theme_mode", "auto"))
        self.configure_app_identity()
        self.configure_styles()

        self.root.title("Payroll Processor")
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)

        # Variables
        self.zip_files = []  # List of selected ZIP files
        self.processing = False
        self.temp_dir = None
        self.missing_dependencies = self.check_missing_dependencies()
        self.report_dir = DEFAULT_REPORT_DIR
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.employee_reports_dir = self.report_dir / "Employees Reports"
        self.employee_reports_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir_custom = bool(self.ui_prefs.get("pdf_archive_dir"))
        archive_root = self.ui_prefs.get("pdf_archive_dir") or (self.report_dir / "Source PDFs")
        self.archive_dir = Path(archive_root)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.signed_docs_dir = self.report_dir / "Signed Documents"
        self.signed_docs_dir.mkdir(parents=True, exist_ok=True)
        self.last_output_path = None
        self.current_output_paths = None
        self.db_config = db_storage.load_db_config()
        if self.db_config.get("enabled"):
            try:
                db_storage.migrate_paid_date_column(self.db_config)
                db_storage.ensure_insurance_claims_table(self.db_config)
                db_storage.ensure_employee_profile_columns(self.db_config)
                db_storage.migrate_signed_flags(self.db_config)
            except Exception:
                pass
        self.global_start_year_var = tk.StringVar(value="All")
        self.global_start_month_var = tk.StringVar(value="01")
        self.global_end_year_var = tk.StringVar(value="All")
        self.global_end_month_var = tk.StringVar(value="01")
        self.global_doc_type_var = tk.StringVar(value="All")
        self.search_clauses = []
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
        self.analytics_grid_view_tab = None
        self.analytics_grid_notebook = None
        self.analytics_grid_page_var = tk.IntVar(value=1)
        self.analytics_grid_total_var = tk.StringVar(value="")
        self.analytics_grid_cache_rows = []
        self.analytics_grid_cache_columns = []
        self.analytics_detail_cache_rows = []
        self.analytics_detail_cache_columns = []
        self.insurance_tab = None
        self.insurance_tree = None
        self.insurance_status_var = tk.StringVar(value="")
        self.insurance_cache = {}
        self.employees_tab = None
        self.employees_tree = None
        self.employee_search_var = tk.StringVar(value="")
        self.employee_selected_code = None
        self.employee_profile_vars = {}
        self.employee_monthly_tree = None
        self.employee_due_tree = None
        self.employee_paid_tree = None
        self.analytics_detail_columns = None
        self.analytics_monthly_cache_rows = []
        self.analytics_monthly_cache_columns = []
        self.analytics_monthly_columns = None
        self.show_db_tab_var = tk.BooleanVar(value=self._normalize_pref_bool(self.ui_prefs.get("show_database_tab", True)))
        self.auto_backup_enabled_var = tk.BooleanVar(value=bool(self.ui_prefs.get("auto_backup_enabled", False)))
        self.auto_backup_frequency_var = tk.StringVar(value=self.ui_prefs.get("auto_backup_frequency", "20 minutes"))
        self.last_backup_at = self.ui_prefs.get("last_backup_at")
        self.backup_dir = Path(self.ui_prefs.get("backup_dir") or (self.report_dir / "Backups"))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._auto_backup_job = None
        self._auto_backup_running = False
        self.watch_enabled_var = tk.BooleanVar(value=bool(self.ui_prefs.get("watch_enabled", False)))
        self.watch_interval_var = tk.IntVar(value=int(self.ui_prefs.get("watch_interval", 10)))
        self.watch_dir = Path(self.ui_prefs.get("watch_dir") or (self.report_dir / "Watch Folder"))
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.watch_seen = set()
        self.watch_pending = {}
        self.watch_job = None
        self.watch_queue = []
        self.analytics_grid_filter_vars = {}
        self.analytics_grid_filter_columns = []
        self.grid_edit_entry = None
        self.grid_editing_cell = None
        self.analytics_grid_menu = None
        self.edit_undo_stack = []
        self.edit_redo_stack = []
        self.edit_lock_var = tk.BooleanVar(value=True)
        self.window_geometry = None
        self._geometry_job = None
        self.last_grid_column = None
        self.tooltips = []
        self.icons = {}
        self._load_icons()
        self.nav_history = []
        self.nav_restoring = False
        self.dashboard_summary_labels = []
        self.toasts = []
        self._db_notice_panels = {}
        self._async_tokens = {}

        # Create GUI elements
        self.create_widgets()
        self.create_menu()
        self.root.bind_all("<Command-z>", lambda _event: self._undo_last_edit())
        self.root.bind_all("<Command-l>", lambda _event: self._toggle_edit_lock())
        self.root.bind_all("<Command-Shift-z>", lambda _event: self._redo_last_edit())
        self.root.bind_all("<Command-f>", lambda _event: self._focus_global_search())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind_all("<Command-r>", lambda _event: self._refresh_all_views())
        self.root.bind_all("<Command-c>", lambda _event: self._copy_grid_cell())
        self._init_watch_state()
        self._schedule_auto_backup()

        # Setup drag and drop if available
        if DRAG_DROP_AVAILABLE:
            self.setup_drag_drop()

        # Surface dependency issues immediately
        self.warn_missing_dependencies()

        self.root.bind("<Configure>", self._schedule_geometry_save)

    def resolve_theme(self):
        """Return the tokens for the appearance the user asked for."""
        theme_mode = self.theme_mode_var.get() if hasattr(self, "theme_mode_var") else "auto"
        if theme_mode == "dark":
            is_dark = True
        elif theme_mode == "light":
            is_dark = False
        else:
            appearance = None
            try:
                appearance = self.root.tk.call("tk::mac::GetSystemAppearance")
            except tk.TclError:
                appearance = None
            is_dark = bool(appearance and str(appearance).lower() == "dark")
        return theme_mode, get_theme_tokens(is_dark)

    def configure_styles(self):
        """Configure ttk styles for a cohesive UI."""
        theme_mode, tokens = self.resolve_theme()
        self.theme = tokens

        self.root.configure(bg=tokens.bg)
        style = ttk.Style()
        self.style = style
        try:
            # clam honours background/foreground options that aqua ignores, so
            # an explicit light/dark choice needs it to actually take effect.
            if theme_mode in ("light", "dark"):
                style.theme_use("clam")
            else:
                style.theme_use("aqua")
        except tk.TclError:
            pass
        # Aqua draws native chrome and ignores `background`, but it still honours
        # `foreground`. Setting a light-on-accent label there paints white text on
        # a default light button, which reads as a blank control. Emphasis styles
        # must therefore skip the colours entirely under aqua and lean on weight.
        try:
            self._is_aqua = style.theme_use() == "aqua"
        except tk.TclError:
            self._is_aqua = False
        style.configure("App.TFrame", background=tokens.bg)
        style.configure("Card.TFrame", background=tokens.surface, relief="solid", borderwidth=1)
        style.configure("CardTitle.TLabel", background=tokens.surface, foreground=tokens.text_secondary, font=(tokens.font_base, 11))
        style.configure("CardValue.TLabel", background=tokens.surface, foreground=tokens.text_primary, font=(tokens.font_base, 18, "bold"))
        style.configure("CardDelta.TLabel", background=tokens.surface, foreground=tokens.text_secondary, font=(tokens.font_base, 11))
        style.configure("CardDeltaUp.TLabel", background=tokens.surface, foreground=tokens.positive, font=(tokens.font_base, 11, "bold"))
        style.configure("CardDeltaDown.TLabel", background=tokens.surface, foreground=tokens.negative, font=(tokens.font_base, 11, "bold"))
        style.configure("Header.TLabel", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 16, "bold"))
        style.configure("Section.TLabel", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 13, "bold"))
        style.configure("Body.TLabel", background=tokens.bg, foreground=tokens.text_secondary, font=(tokens.font_base, 11))
        style.configure("Hint.TLabel", background=tokens.bg, foreground=tokens.muted, font=(tokens.font_base, 10))
        style.configure("Warning.TLabel", background=tokens.bg, foreground=tokens.warning, font=(tokens.font_base, 11))
        style.configure("App.TLabelframe", background=tokens.bg)
        style.configure("App.TLabelframe.Label", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 11, "bold"))
        style.configure("App.TNotebook", background=tokens.bg)
        style.configure("App.TNotebook.Tab", padding=(12, 6), font=(tokens.font_base, 11))
        style.configure("App.TSeparator", background=tokens.border)

        # Empty states: a bordered surface panel with a title and a hint.
        style.configure("Empty.TFrame", background=tokens.surface, relief="solid", borderwidth=1)
        style.configure("EmptyTitle.TLabel", background=tokens.surface, foreground=tokens.text_primary, font=(tokens.font_base, 13, "bold"))
        style.configure("EmptyBody.TLabel", background=tokens.surface, foreground=tokens.text_secondary, font=(tokens.font_base, 11))

        # Filter chips.
        style.configure("Chip.TFrame", background=tokens.selection, relief="flat", borderwidth=0)
        style.configure("Chip.TLabel", background=tokens.selection, foreground=tokens.text_primary, font=(tokens.font_base, 10))

        self._configure_button_styles(style, tokens)

        style.configure(
            "Treeview",
            background=tokens.surface,
            fieldbackground=tokens.surface,
            foreground=tokens.text_primary,
            bordercolor=tokens.border,
            rowheight=22,
        )
        style.map(
            "Treeview",
            background=[("selected", tokens.selection)],
            foreground=[("selected", tokens.text_primary)],
        )
        style.configure("Treeview.Heading", background=tokens.bg, foreground=tokens.text_primary, font=(tokens.font_base, 11, "bold"))
        style.layout("Hidden.TNotebook.Tab", [])
        style.layout("Hidden.TNotebook", [("Notebook.client", {"sticky": "nswe"})])

    def _configure_button_styles(self, style, tokens):
        """Give the primary and destructive actions their own weight.

        Aqua draws its own button chrome and ignores background/foreground, so
        on the automatic appearance the emphasis falls back to a bold label -
        which is still a visible difference from the neutral buttons beside it.
        """
        accent_colors = {} if self._is_aqua else {
            "background": tokens.accent,
            "foreground": tokens.accent_text,
            "bordercolor": tokens.accent,
            "focuscolor": tokens.accent,
        }
        style.configure(
            "Accent.TButton",
            padding=(14, 7),
            font=(tokens.font_base, 11, "bold"),
            **accent_colors,
        )
        if not self._is_aqua:
            style.map(
                "Accent.TButton",
                background=[("pressed", tokens.accent_active), ("active", tokens.accent_active), ("disabled", tokens.border)],
                foreground=[("disabled", tokens.text_secondary)],
            )
        danger_colors = {} if self._is_aqua else {
            "background": tokens.danger,
            "foreground": tokens.danger_text,
            "bordercolor": tokens.danger,
            "focuscolor": tokens.danger,
        }
        style.configure(
            "Danger.TButton",
            padding=(12, 6),
            font=(tokens.font_base, 11, "bold"),
            **danger_colors,
        )
        if not self._is_aqua:
            style.map(
                "Danger.TButton",
                background=[("pressed", tokens.danger_active), ("active", tokens.danger_active), ("disabled", tokens.border)],
                foreground=[("disabled", tokens.text_secondary)],
            )
        style.configure("Sidebar.TButton", padding=(12, 8), font=(tokens.font_base, 11), anchor=tk.W)
        style.configure(
            "SidebarActive.TButton",
            padding=(12, 8),
            font=(tokens.font_base, 11, "bold"),
            anchor=tk.W,
            **accent_colors,
        )
        if not self._is_aqua:
            style.map(
                "SidebarActive.TButton",
                background=[("pressed", tokens.accent_active), ("active", tokens.accent_active)],
                foreground=[("pressed", tokens.accent_text), ("active", tokens.accent_text)],
            )
        style.configure("Chip.TButton", padding=(4, 0), font=(tokens.font_base, 10))

    # ------------------------------------------------------------------
    # Chart styling
    # ------------------------------------------------------------------

    def _series_color(self, index):
        """Nth colour of the shared series palette, wrapping if needed."""
        palette = self.theme.chart_series
        return palette[index % len(palette)]

    def _format_axis_amount(self, value, _pos=None):
        """Compact euro tick label: € 1.2k, € 3.4M."""
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return ""
        magnitude = abs(amount)
        if magnitude >= 1_000_000:
            return f"€ {amount / 1_000_000:,.1f}M"
        if magnitude >= 1_000:
            return f"€ {amount / 1_000:,.1f}k"
        return f"€ {amount:,.0f}"

    def _style_axes(self, ax, currency=False, percent=False, suffix=None, rotate=None,
                    grid_axis="y", tight=True):
        """Apply the app's appearance to a matplotlib axes.

        Every ``_plot_*`` method ends with this call, so the figures follow the
        light/dark theme, drop their top and right spines, get a soft grid and
        read their amounts in euros rather than raw floats.
        """
        tokens = getattr(self, "theme", None)
        if tokens is None:
            return
        fig = ax.get_figure()
        fig.set_facecolor(tokens.chart_bg)
        ax.set_facecolor(tokens.chart_bg)

        for name, spine in ax.spines.items():
            if name in ("top", "right"):
                spine.set_visible(False)
            else:
                spine.set_color(tokens.border)
        ax.tick_params(colors=tokens.text_secondary, labelsize=9, length=3, width=0.8)
        ax.xaxis.label.set_color(tokens.text_secondary)
        ax.yaxis.label.set_color(tokens.text_secondary)
        ax.xaxis.label.set_fontsize(10)
        ax.yaxis.label.set_fontsize(10)
        ax.title.set_color(tokens.text_primary)
        ax.title.set_fontsize(12)
        ax.title.set_fontweight("bold")

        if grid_axis:
            ax.grid(True, axis=grid_axis, color=tokens.chart_grid, linewidth=0.8)
            ax.set_axisbelow(True)
        else:
            ax.grid(False)

        if currency:
            ax.yaxis.set_major_formatter(FuncFormatter(self._format_axis_amount))
        elif percent:
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}%"))
        elif suffix:
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}{suffix}"))

        if rotate:
            for label in ax.get_xticklabels():
                label.set_rotation(rotate)
                label.set_horizontalalignment("right")

        legend = ax.get_legend()
        if legend is not None:
            frame = legend.get_frame()
            frame.set_facecolor(tokens.chart_bg)
            frame.set_edgecolor(tokens.border)
            frame.set_alpha(0.95)
            for text in legend.get_texts():
                text.set_color(tokens.text_secondary)
                text.set_fontsize(9)

        if tight:
            # A constrained-layout figure re-solves itself on every draw and
            # resize. Calling tight_layout() on top of it switches the engine
            # back (emitting "The figure layout has changed to tight") and
            # reintroduces the clipped-title-on-resize problem.
            engine = None
            try:
                engine = fig.get_layout_engine()
            except AttributeError:
                engine = None
            if engine is None or type(engine).__name__ != "ConstrainedLayoutEngine":
                try:
                    fig.tight_layout()
                except Exception:
                    # A colourbar can refuse; the chart is still readable
                    # without the reflow.
                    pass

    def _empty_axes(self, ax, title, message="No data for the current filters"):
        """Draw a titled placeholder instead of an empty grid."""
        tokens = getattr(self, "theme", None)
        ax.set_title(title)
        ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            transform=ax.transAxes,
            color=tokens.muted if tokens else "#6B7280",
            fontsize=11,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        self._style_axes(ax, grid_axis=None)

    def configure_app_identity(self):
        """Ensure the app name shows as Payroll Processor on macOS."""
        self._apply_macos_app_name()

    def _apply_macos_app_name(self):
        """Force the macOS menu bar to use the app name instead of Python."""
        try:
            if self.root.tk.call('tk', 'windowingsystem') != 'aqua':
                return
            os.environ["TK_APP_NAME"] = "Payroll Processor"
            for command in (
                ('tk', 'appname', 'Payroll Processor'),
                ('set', '::tk::mac::appname', 'Payroll Processor'),
                ('tk::mac::SetApplicationName', 'Payroll Processor'),
                ('tk::mac::setmenuname', 'Payroll Processor'),
            ):
                try:
                    self.root.tk.call(*command)
                except tk.TclError:
                    continue
        except tk.TclError:
            return

    def _load_icons(self):
        base_dir = Path(__file__).resolve().parent
        assets_root = base_dir / "assets"
        if not assets_root.exists():
            assets_root = base_dir.parent / "assets"
        icons_dir = assets_root / "icons"
        icons = {}
        if icons_dir.exists():
            for path in icons_dir.glob("*.png"):
                try:
                    image = tk.PhotoImage(file=str(path))
                    icons[path.stem] = self._fit_icon(image, size=18)
                except tk.TclError:
                    continue
        self.icons = icons

        self.logo_image = None
        logo_path = assets_root / "logo.png"
        if logo_path.exists():
            try:
                logo_image = tk.PhotoImage(file=str(logo_path))
                self.logo_image = self._fit_icon(logo_image, size=64)
            except tk.TclError:
                self.logo_image = None

        self.app_icon_image = None
        app_icon_path = assets_root / "app_icon.png"
        if app_icon_path.exists():
            try:
                self.app_icon_image = tk.PhotoImage(file=str(app_icon_path))
                self.root.iconphoto(True, self.app_icon_image)
            except tk.TclError:
                self.app_icon_image = None

    def _fit_icon(self, image, size=18):
        """Downscale icons to fit inside buttons without padding overflow."""
        try:
            width = image.width()
            height = image.height()
        except tk.TclError:
            return image
        if width <= size and height <= size:
            return image
        scale = max(1, math.ceil(max(width, height) / size))
        return image.subsample(scale, scale)

    def _add_tooltip(self, widget, text):
        if not widget or not text:
            return
        self.tooltips.append(Tooltip(widget, text))

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

        # The filter bar drives every view, so it is grouped rather than laid
        # out as one long row of unlabelled controls: period, document, search,
        # then the state of the filters as removable chips underneath.
        self.global_filter_bar = ttk.Frame(main_frame, style="App.TFrame")
        self.global_filter_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        # Column 2 takes the slack so the state and the reset control stay right
        # aligned while the filter groups keep their natural width.
        self.global_filter_bar.columnconfigure(2, weight=1)

        controls = ttk.Frame(self.global_filter_bar, style="App.TFrame")
        controls.grid(row=0, column=0, sticky=(tk.W, tk.E))
        self.filter_controls = controls

        period_group = ttk.Frame(controls, style="App.TFrame")
        period_group.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(period_group, text="Period", style="Body.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self.global_start_year_combo = ttk.Combobox(period_group, textvariable=self.global_start_year_var, state="readonly", width=7)
        self.global_start_year_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.global_start_year_combo.bind("<<ComboboxSelected>>", self._on_global_year_change)
        self.global_start_year_combo["values"] = ["All"]

        self.global_start_month_combo = ttk.Combobox(period_group, textvariable=self.global_start_month_var, state="readonly", width=4)
        self.global_start_month_combo.pack(side=tk.LEFT)
        self.global_start_month_combo["values"] = [f"{month:02d}" for month in range(1, 13)]
        self.global_start_month_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)

        ttk.Label(period_group, text="→", style="Body.TLabel").pack(side=tk.LEFT, padx=6)

        self.global_end_year_combo = ttk.Combobox(period_group, textvariable=self.global_end_year_var, state="readonly", width=7)
        self.global_end_year_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.global_end_year_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)
        self.global_end_year_combo["values"] = ["All"]

        self.global_end_month_combo = ttk.Combobox(period_group, textvariable=self.global_end_month_var, state="readonly", width=4)
        self.global_end_month_combo.pack(side=tk.LEFT)
        self.global_end_month_combo["values"] = [f"{month:02d}" for month in range(1, 13)]
        self.global_end_month_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)

        doc_group = ttk.Frame(controls, style="App.TFrame")
        doc_group.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(doc_group, text="Document", style="Body.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self.global_doc_type_combo = ttk.Combobox(doc_group, textvariable=self.global_doc_type_var, state="readonly", width=18)
        self.global_doc_type_combo["values"] = ["All", "salary", "bonus", "vacation_allowance", "unused_leave_compensation", "other"]
        self.global_doc_type_combo.pack(side=tk.LEFT)
        self.global_doc_type_combo.bind("<<ComboboxSelected>>", self._on_global_filter_change)

        # Search lives directly in the bar so it can drop to its own line when
        # the window is too narrow for one row (see _reflow_filter_bar).
        self.filter_search_group = ttk.Frame(self.global_filter_bar, style="App.TFrame")
        search_group = self.filter_search_group
        ttk.Label(search_group, text="Search", style="Body.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self.global_search_var = tk.StringVar(value="")
        self.global_search_entry = ttk.Entry(search_group, textvariable=self.global_search_var, width=22)
        self.global_search_entry.pack(side=tk.LEFT)
        self.global_search_entry.bind("<KeyRelease>", self._on_global_search)
        self.add_search_clause_btn = ttk.Button(search_group, text="+", width=2, command=self._add_search_clause)
        self.add_search_clause_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.filter_search_wrapped = None

        # Right-hand side: state and the controls that act on all of it.
        trailing = ttk.Frame(self.global_filter_bar, style="App.TFrame")
        trailing.grid(row=0, column=2, sticky=tk.E)
        self.filter_trailing = trailing

        self.lock_canvas = tk.Canvas(
            trailing,
            width=22,
            height=22,
            highlightthickness=0,
            bd=0,
            relief=tk.FLAT,
            bg=self.theme.bg,
        )
        self.lock_canvas.pack(side=tk.RIGHT, padx=(10, 0))
        self.lock_canvas.bind("<Button-1>", lambda _event: self._toggle_edit_lock())
        self._add_tooltip(self.lock_canvas, "Toggle edit lock.")

        self.reset_filters_btn = ttk.Button(trailing, text="Clear all", command=self._reset_global_filters)
        self.reset_filters_btn.pack(side=tk.RIGHT)
        self._add_tooltip(self.reset_filters_btn, "Clear every filter and search term.")

        self.global_filter_status = tk.StringVar(value="")
        ttk.Label(trailing, textvariable=self.global_filter_status, style="Body.TLabel").pack(side=tk.RIGHT, padx=(0, 12))

        # Then the applied filters, one removable chip each.
        self.filter_chip_frame = ttk.Frame(self.global_filter_bar, style="App.TFrame")
        self.filter_chip_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(8, 0))
        # The active window is shown by the period chip, so the label that used
        # to repeat it is kept only as the chip's source of text.
        self.global_window_label_var = tk.StringVar(value="")

        self.search_clause_frame = ttk.Frame(self.global_filter_bar, style="App.TFrame")
        self.search_clause_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))
        self.global_filter_bar.bind("<Configure>", self._reflow_filter_bar)
        self._reflow_filter_bar()

        self._add_tooltip(self.global_start_year_combo, "Start year for the global filter range.")
        self._add_tooltip(self.global_start_month_combo, "Start month for the global filter range.")
        self._add_tooltip(self.global_end_year_combo, "End year for the global filter range.")
        self._add_tooltip(self.global_end_month_combo, "End month for the global filter range.")
        self._add_tooltip(self.global_doc_type_combo, "Filter by document type.")
        self._add_tooltip(self.global_search_entry, "Search across analytics and dashboard views.")

        self._apply_ui_prefs()
        self._update_lock_indicator()
        self._render_filter_chips()

        separator = ttk.Separator(main_frame, orient=tk.HORIZONTAL)
        separator.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))

        content_frame = ttk.Frame(main_frame, style="App.TFrame")
        content_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        content_frame.columnconfigure(0, weight=0)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(content_frame, style="App.TFrame")
        sidebar.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W), padx=(0, 12))
        sidebar.columnconfigure(0, weight=1)

        self.sidebar_buttons = {}
        sidebar_icon_map = {
            "Dashboard": "dashboard",
            "Analytics Data Grid": "analytics_data_grid",
            "Analytics Graphs": "analytics_graphs",
            "Insurance": "insurance",
            "Employees": "employees",
            "Processing": "processing",
            "Database": "database",
            "Settings": "settings",
        }
        for idx, view_name in enumerate((
            "Dashboard",
            "Analytics Data Grid",
            "Analytics Graphs",
            "Insurance",
            "Employees",
            "Processing",
            "Database",
            "Settings",
        )):
            btn = ttk.Button(
                sidebar,
                text=view_name,
                style="Sidebar.TButton",
                command=lambda name=view_name: self._set_active_view(name),
            )
            icon_key = sidebar_icon_map.get(view_name)
            if icon_key and self.icons.get(icon_key):
                btn.configure(image=self.icons.get(icon_key), compound=tk.LEFT)
            btn.grid(row=idx, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
            self.sidebar_buttons[view_name] = btn
            # ⌘1..⌘8 jump straight to a view, in sidebar order.
            self.root.bind_all(
                f"<Command-Key-{idx + 1}>",
                lambda _event, name=view_name: self._set_active_view(name),
            )
            self._add_tooltip(btn, f"{view_name}  (⌘{idx + 1})")

        self.notebook = ttk.Notebook(content_frame, style="Hidden.TNotebook")
        self.notebook.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.processing_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.db_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.analytics_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.analytics_grid_view_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.insurance_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.employees_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.settings_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.dashboard_tab = ttk.Frame(self.notebook, padding="12", style="App.TFrame")
        self.notebook.add(self.processing_tab, text="Processing")
        self.notebook.add(self.db_tab, text="Database")
        self.notebook.add(self.analytics_tab, text="Analytics Graphs")
        self.notebook.add(self.analytics_grid_view_tab, text="Analytics Data Grid")
        self.notebook.add(self.insurance_tab, text="Insurance")
        self.notebook.add(self.employees_tab, text="Employees")
        self.notebook.add(self.settings_tab, text="Settings")
        self.notebook.add(self.dashboard_tab, text="Dashboard")
        self.notebook.bind("<<NotebookTabChanged>>", self._sync_view_selector)
        self._apply_database_tab_visibility()
        self._set_active_view("Dashboard")


        self.processing_tab.columnconfigure(0, weight=1)
        self.processing_tab.rowconfigure(3, weight=1)

        # Title + logo, left aligned like every other view's header.
        header = ttk.Frame(self.processing_tab, style="App.TFrame")
        header.grid(row=0, column=0, pady=(0, 12), sticky=tk.EW)
        if self.logo_image:
            ttk.Label(header, image=self.logo_image).pack(side=tk.LEFT, padx=(0, 12))
        title_block = ttk.Frame(header, style="App.TFrame")
        title_block.pack(side=tk.LEFT, anchor=tk.W)
        ttk.Label(title_block, text="Processing", style="Header.TLabel").pack(anchor=tk.W)
        self.instructions_label = ttk.Label(
            title_block,
            text=self.get_instructions_text(),
            justify=tk.LEFT,
            wraplength=620,
            style="Body.TLabel",
        )
        self.instructions_label.pack(anchor=tk.W, pady=(2, 0))

        # Setup banner: only present while something needs attention.
        self.setup_banner = ttk.Frame(self.processing_tab, style="Empty.TFrame", padding=12)
        self.setup_banner_body = ttk.Label(
            self.setup_banner,
            text="",
            style="EmptyBody.TLabel",
            justify=tk.LEFT,
            wraplength=640,
        )
        self.setup_banner_title = ttk.Label(self.setup_banner, text="", style="EmptyTitle.TLabel")
        self.setup_banner_title.pack(anchor=tk.W)
        self.setup_banner_body.pack(anchor=tk.W, pady=(4, 0))
        self.setup_banner_actions = ttk.Frame(self.setup_banner, style="Empty.TFrame")
        self.setup_banner_actions.pack(anchor=tk.W, pady=(10, 0))

        # File list
        list_frame = ttk.LabelFrame(self.processing_tab, text="Selected Files", padding="8", style="App.TLabelframe")
        list_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 12))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        listbox_frame = ttk.Frame(list_frame)
        listbox_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        listbox_frame.columnconfigure(0, weight=1)
        listbox_frame.rowconfigure(0, weight=1)

        self.file_listbox = tk.Listbox(
            listbox_frame,
            selectmode=tk.MULTIPLE,
            bg=self.theme.surface,
            fg=self.theme.text_primary,
            selectbackground=self.theme.selection,
            selectforeground=self.theme.text_primary,
            highlightthickness=1,
            highlightbackground=self.theme.border,
            highlightcolor=self.theme.accent,
            borderwidth=0,
            activestyle="none",
        )
        self.file_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.file_listbox.configure(yscrollcommand=scrollbar.set)

        # Drop-zone hint, shown over an empty list.
        self.drop_label = ttk.Label(
            listbox_frame,
            text=(
                "Drop ZIP or PDF files here"
                if DRAG_DROP_AVAILABLE
                else "Click Browse Files to choose ZIP or PDF payroll files"
            ),
            style="Hint.TLabel",
            anchor=tk.CENTER,
        )
        self.drop_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Actions: destructive and neutral on the left, the primary action right.
        button_frame = ttk.Frame(self.processing_tab, style="App.TFrame")
        button_frame.grid(row=4, column=0, pady=(0, 12), sticky=tk.EW)

        self.browse_btn = ttk.Button(
            button_frame,
            text="Browse Files",
            command=self.browse_files,
            image=self.icons.get("browse_files"),
            compound=tk.LEFT,
        )
        self.browse_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.remove_btn = ttk.Button(button_frame, text="Remove Selected", command=self.remove_selected_files)
        self.remove_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.clear_btn = ttk.Button(button_frame, text="Clear All", command=self.clear_all_files)
        self.clear_btn.pack(side=tk.LEFT)

        self.generate_btn = ttk.Button(
            button_frame,
            text="Generate Reports",
            command=self.generate_reports,
            style="Accent.TButton",
        )
        self.generate_btn.pack(side=tk.RIGHT)
        self.file_count_var = tk.StringVar(value="No files selected")
        ttk.Label(button_frame, textvariable=self.file_count_var, style="Body.TLabel").pack(side=tk.RIGHT, padx=(0, 12))

        # Progress + live log
        progress_frame = ttk.Frame(self.processing_tab, style="App.TFrame")
        progress_frame.grid(row=5, column=0, sticky=(tk.W, tk.E))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 6))

        status_row = ttk.Frame(progress_frame, style="App.TFrame")
        status_row.grid(row=1, column=0, sticky=(tk.W, tk.E))
        status_row.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        self.status_label = ttk.Label(status_row, textvariable=self.status_var, style="Body.TLabel")
        self.status_label.grid(row=0, column=0, sticky=tk.W)
        self.log_toggle_btn = ttk.Button(status_row, text="Show log", width=10, command=self._toggle_processing_log)
        self.log_toggle_btn.grid(row=0, column=1, sticky=tk.E)

        self.log_frame = ttk.Frame(progress_frame, style="App.TFrame")
        self.log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            self.log_frame,
            height=8,
            wrap=tk.NONE,
            bg=self.theme.surface,
            fg=self.theme.text_secondary,
            insertbackground=self.theme.text_primary,
            highlightthickness=1,
            highlightbackground=self.theme.border,
            borderwidth=0,
            state=tk.DISABLED,
            font=(self.theme.font_base, 10),
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
        log_scroll = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_visible = False

        self.output_location_var = tk.StringVar(value=f"Reports are saved to {self.employee_reports_dir}")
        self.output_location_label = ttk.Label(
            progress_frame,
            textvariable=self.output_location_var,
            style="Hint.TLabel",
        )
        self.output_location_label.grid(row=3, column=0, sticky=tk.W, pady=(6, 0))

        self.create_db_tab()
        self.create_analytics_tab()
        self.create_analytics_grid_tab()
        self.create_insurance_tab()
        self.create_employees_tab()
        self.create_settings_tab()
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
        back_btn = ttk.Button(
            header,
            text="Back",
            command=self._navigate_back,
            image=self.icons.get("back"),
            compound=tk.LEFT,
        )
        back_btn.grid(row=0, column=1, padx=(0, 10))
        refresh_btn = ttk.Button(
            header,
            text="Refresh Charts",
            command=self.refresh_analytics,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=2, padx=(0, 10))
        self._add_tooltip(back_btn, "Return to the previous view.")
        self._add_tooltip(refresh_btn, "Refresh analytics charts and KPIs.")

        ttk.Label(header, text="Top Employees", style="Body.TLabel").grid(row=0, column=3, padx=(0, 6))
        self.analytics_top_n_var = tk.IntVar(value=10)
        top_spin = ttk.Spinbox(header, from_=5, to=50, textvariable=self.analytics_top_n_var, width=6)
        top_spin.grid(row=0, column=4, padx=(0, 10))
        self._add_tooltip(top_spin, "Number of employees to show in the cost chart.")

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

        charts_frame = ttk.Frame(self.analytics_tab, style="App.TFrame")
        charts_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        charts_frame.columnconfigure(0, weight=1)
        charts_frame.rowconfigure(0, weight=1)

        self.analytics_notebook = ttk.Notebook(charts_frame, style="App.TNotebook")
        self.analytics_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.analytics_charts = {}
        self.analytics_chart_groups = {}
        self.analytics_group_frames = {}
        self.expanded_chart = None
        # Fourteen charts used to be fourteen tabs. Grouping them by question -
        # what we spend, how it moves, insurance, payment status, the workforce -
        # puts related charts side by side and cuts the tab strip to five.
        for group_title, chart_specs in self.CHART_GROUPS:
            group = ttk.Frame(self.analytics_notebook, padding=8, style="App.TFrame")
            self.analytics_notebook.add(group, text=group_title)
            self.analytics_group_frames[group_title] = group
            self.analytics_chart_groups[group_title] = [key for key, _ in chart_specs]
            columns = 1 if len(chart_specs) == 1 else 2
            for index in range(columns):
                group.columnconfigure(index, weight=1, uniform="charts")
            for index in range((len(chart_specs) + columns - 1) // columns):
                group.rowconfigure(index, weight=1)

            for index, (key, title) in enumerate(chart_specs):
                row, column = divmod(index, columns)
                card = ttk.Frame(group, style="Card.TFrame", padding=6)
                card.grid(row=row, column=column, sticky=(tk.W, tk.E, tk.N, tk.S), padx=4, pady=4)
                card.columnconfigure(0, weight=1)
                card.rowconfigure(1, weight=1)

                card_header = ttk.Frame(card, style="Card.TFrame")
                card_header.grid(row=0, column=0, sticky=(tk.W, tk.E))
                card_header.columnconfigure(0, weight=1)
                ttk.Label(card_header, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky=tk.W)
                expand_btn = ttk.Button(
                    card_header,
                    text="⤢",
                    width=3,
                    command=lambda chart_key=key: self._toggle_chart_expand(chart_key),
                )
                expand_btn.grid(row=0, column=1, sticky=tk.E)
                self._add_tooltip(expand_btn, "Fill the tab with this chart, with zoom and export tools.")

                body = ttk.Frame(card, style="Card.TFrame")
                body.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

                fig = Figure(figsize=(4.4, 2.8), dpi=100)
                ax = fig.add_subplot(1, 1, 1)
                canvas = FigureCanvasTkAgg(fig, master=body)
                canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

                # The matplotlib toolbar is developer chrome; it appears only
                # when a chart is expanded.
                toolbar_holder = ttk.Frame(card, style="Card.TFrame")
                toolbar = NavigationToolbar2Tk(canvas, toolbar_holder)
                toolbar.update()
                toolbar.pack(side=tk.BOTTOM, fill=tk.X)

                self.analytics_charts[key] = {
                    "fig": fig,
                    "ax": ax,
                    "canvas": canvas,
                    "toolbar": toolbar,
                    "toolbar_holder": toolbar_holder,
                    "card": card,
                    "group": group_title,
                    "position": (row, column),
                    "expand_btn": expand_btn,
                    "stale": True,
                }

        self.analytics_notebook.bind("<<NotebookTabChanged>>", self._on_analytics_group_change)
        self.analytics_heatmap_cbar = None
        self.analytics_heatmap_cax = None
        self.analytics_legend_map = {}
        self._bind_chart_drilldowns()

    def _visible_chart_group(self):
        """Title of the analytics group currently on screen, if any."""
        notebook = getattr(self, "analytics_notebook", None)
        if notebook is None:
            return None
        try:
            current = notebook.select()
        except tk.TclError:
            return None
        if not current:
            return None
        for title, frame in self.analytics_group_frames.items():
            if str(frame) == current:
                return title
        return None

    def _draw_visible_charts(self):
        """Render the charts in the visible group, skipping fresh ones."""
        group_title = self._visible_chart_group()
        if group_title is None:
            return
        for key in self.analytics_chart_groups.get(group_title, []):
            chart = self.analytics_charts[key]
            if chart.get("stale", True):
                chart["canvas"].draw()
                chart["stale"] = False

    def _on_analytics_group_change(self, _event=None):
        self._draw_visible_charts()

    def _toggle_chart_expand(self, key):
        """Fill the group tab with one chart, or restore the grid."""
        chart = self.analytics_charts.get(key)
        if not chart:
            return
        group_title = chart["group"]
        group = self.analytics_group_frames[group_title]
        siblings = [self.analytics_charts[k] for k in self.analytics_chart_groups[group_title]]

        if self.expanded_chart == key:
            for sibling in siblings:
                row, column = sibling["position"]
                sibling["card"].grid(row=row, column=column, columnspan=1, rowspan=1,
                                     sticky=(tk.W, tk.E, tk.N, tk.S), padx=4, pady=4)
                sibling["toolbar_holder"].grid_forget()
                sibling["expand_btn"].configure(text="⤢")
            self.expanded_chart = None
        else:
            if self.expanded_chart:
                self._toggle_chart_expand(self.expanded_chart)
            for sibling in siblings:
                sibling["card"].grid_remove()
            rows = max(1, group.grid_size()[1])
            columns = max(1, group.grid_size()[0])
            chart["card"].grid(row=0, column=0, columnspan=columns, rowspan=rows,
                               sticky=(tk.W, tk.E, tk.N, tk.S), padx=4, pady=4)
            chart["toolbar_holder"].grid(row=2, column=0, sticky=(tk.W, tk.E))
            chart["expand_btn"].configure(text="⤡")
            self.expanded_chart = key
        chart["canvas"].draw_idle()

    def refresh_analytics(self):
        """Refresh analytics charts from the database, off the UI thread."""
        if not self.db_config.get("enabled"):
            self.analytics_status_var.set("Database storage is disabled.")
            self._database_notice(
                self.analytics_tab,
                "Charts are drawn from stored payroll entries. Turn storage on to see them.",
            )
            return
        self._clear_database_notice(self.analytics_tab)

        self.analytics_status_var.set("Refreshing…")
        try:
            self._refresh_global_filters()
            filters = self._get_global_filters()
            top_n = int(self.analytics_top_n_var.get())
        except Exception as exc:
            self.analytics_status_var.set("Refresh failed.")
            self.show_message("Analytics Error", str(exc), kind="warning")
            return

        heatmap_year = self.global_range_end_year
        heatmap_month = self.global_range_end_month
        employee_code = self.analytics_selected_employee_code
        employee_name = self.analytics_selected_employee_name

        # A dozen queries and fourteen figures used to run on the Tk thread, so
        # every filter change froze the window. The queries now run in a worker
        # and only the drawing happens back on the UI thread.
        self._run_async(
            "analytics",
            lambda: self._fetch_analytics_data(
                filters, top_n, heatmap_year, heatmap_month, employee_code, employee_name
            ),
            self._render_analytics,
            on_error=self._analytics_failed,
        )

    def _fetch_analytics_data(self, filters, top_n, heatmap_year, heatmap_month,
                              employee_code, employee_name):
        """Every query the analytics view needs. Runs on a worker thread."""
        start_date, end_date, document_type, search = filters
        end_date_ref = end_date or datetime.date.today()
        rolling_end = self._month_end(end_date_ref)
        rolling_start = self._add_months(self._month_start(rolling_end), -23)

        prior_end_day = min(
            end_date_ref.day,
            calendar.monthrange(end_date_ref.year - 1, end_date_ref.month)[1],
        )
        prior_end = datetime.date(end_date_ref.year - 1, end_date_ref.month, prior_end_day)

        heatmap_rows = []
        if heatmap_year is not None and heatmap_month is not None:
            heatmap_rows = db_storage.fetch_payment_heatmap(
                self.db_config,
                year=heatmap_year,
                month=heatmap_month,
                limit=top_n,
                document_type=document_type,
                search=search or None,
            )

        return {
            "end_date_ref": end_date_ref,
            "rolling_end": rolling_end,
            "heatmap_year": heatmap_year,
            "heatmap_month": heatmap_month,
            "heatmap_rows": heatmap_rows,
            "kpi_totals": db_storage.fetch_kpi_totals(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                employee_code=employee_code,
                employee_name=employee_name,
                search=search or None,
            ),
            "monthly_rows": db_storage.fetch_monthly_summary(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "monthly_totals": db_storage.fetch_monthly_totals(
                self.db_config,
                start_date=rolling_start,
                end_date=rolling_end,
                document_type=document_type,
                search=search or None,
            ),
            "employee_rows": db_storage.fetch_employer_costs_by_employee(
                self.db_config,
                limit=top_n,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "doc_type_rows": db_storage.fetch_document_type_breakdown(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "same_month_rows": db_storage.fetch_month_totals_by_year(
                self.db_config,
                month=end_date_ref.month,
                document_type=document_type,
                search=search or None,
            ),
            "current_ytd": db_storage.fetch_dashboard_metrics(
                self.db_config,
                start_date=datetime.date(end_date_ref.year, 1, 1),
                end_date=end_date_ref,
                document_type=document_type,
                search=search or None,
            ),
            "prior_ytd": db_storage.fetch_dashboard_metrics(
                self.db_config,
                start_date=datetime.date(end_date_ref.year - 1, 1, 1),
                end_date=prior_end,
                document_type=document_type,
                search=search or None,
            ),
            "paid_unpaid": db_storage.fetch_paid_unpaid_totals(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "unpaid_buckets": db_storage.fetch_unpaid_aging_buckets(
                self.db_config,
                as_of=end_date_ref,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "avg_days_rows": db_storage.fetch_avg_days_to_paid_by_month(
                self.db_config,
                start_date=rolling_start,
                end_date=rolling_end,
                document_type=document_type,
                search=search or None,
            ),
            "cost_ratio_rows": db_storage.fetch_employer_cost_ratio_by_month(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "headcount_rows": db_storage.fetch_headcount_trend(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                search=search or None,
            ),
            "distribution_rows": db_storage.fetch_net_pay_distribution(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
        }

    def _render_analytics(self, data):
        """Draw the analytics view from fetched data. UI thread only."""
        total_net, total_employee_ins, total_employer_ins = data["kpi_totals"]
        self._apply_kpi_totals(total_net, total_employee_ins, total_employer_ins)

        end_date_ref = data["end_date_ref"]
        self._plot_monthly_burn(data["monthly_rows"])
        self._plot_insurance_breakdown(data["monthly_rows"])
        self._plot_doc_type_breakdown(data["doc_type_rows"])
        self._plot_payment_heatmap(
            data["heatmap_rows"], year=data["heatmap_year"], month=data["heatmap_month"]
        )
        self._plot_employee_costs(data["employee_rows"])
        self._plot_same_month_yoy(data["same_month_rows"], end_date_ref.month)
        self._plot_ytd_compare(data["current_ytd"], data["prior_ytd"], end_date_ref.year)
        self._plot_rolling_yoy(data["monthly_totals"], data["rolling_end"])
        self._plot_insurance_burden(data["monthly_totals"])
        self._plot_paid_aging(data["paid_unpaid"], data["unpaid_buckets"])
        self._plot_avg_days_to_paid(data["avg_days_rows"])
        self._plot_cost_ratio(data["cost_ratio_rows"])
        self._plot_headcount_trend(data["headcount_rows"])
        self._plot_pay_distribution(data["distribution_rows"])

        # Rendering fourteen figures costs more than querying for them, so only
        # the visible group is drawn now; the rest are marked stale and drawn
        # when their tab is opened.
        for chart in self.analytics_charts.values():
            chart["stale"] = True
        self._draw_visible_charts()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.analytics_status_var.set(f"Last refreshed at {timestamp}.")

    def _analytics_failed(self, exc):
        self.analytics_status_var.set("Refresh failed.")
        self.show_message("Analytics Error", str(exc), kind="warning")

    def _plot_monthly_burn(self, rows):
        self.analytics_monthly_ax = self.analytics_charts["monthly"]["ax"]
        self.analytics_monthly_ax.clear()
        if not rows:
            self._empty_axes(self.analytics_monthly_ax, "Monthly Payroll Burn")
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

        self._monthly_line_net, = self.analytics_monthly_ax.plot(
            labels, net_vals, marker="o", markersize=4, linewidth=2,
            color=self._series_color(0), label="Net Pay",
        )
        self._monthly_line_employer, = self.analytics_monthly_ax.plot(
            labels, employer_cost, marker="o", markersize=4, linewidth=2,
            color=self._series_color(1), label="Employer Cost",
        )
        self.analytics_monthly_ax.set_title("Monthly Payroll Burn")
        self.analytics_monthly_ax.set_ylabel("Amount")
        legend = self.analytics_monthly_ax.legend(frameon=True)
        self._bind_legend_toggle(legend, [self._monthly_line_net, self._monthly_line_employer])
        self._style_axes(self.analytics_monthly_ax, currency=True, rotate=45)

    def _plot_doc_type_breakdown(self, rows):
        self.analytics_doc_type_ax = self.analytics_charts["doc_type"]["ax"]
        self.analytics_doc_type_ax.clear()
        if not rows:
            self._empty_axes(self.analytics_doc_type_ax, "Salary vs Bonus vs Allowances")
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

        self.analytics_doc_type_ax.bar(labels, salary_vals, label="Salary", color=self._series_color(0))
        self.analytics_doc_type_ax.bar(labels, bonus_vals, bottom=salary_vals, label="Bonus", color=self._series_color(1))
        stacked_base = [salary_vals[i] + bonus_vals[i] for i in range(len(labels))]
        self.analytics_doc_type_ax.bar(labels, allowance_vals, bottom=stacked_base, label="Allowance", color=self._series_color(2))
        if any(other_vals):
            stacked_base = [stacked_base[i] + allowance_vals[i] for i in range(len(labels))]
            self.analytics_doc_type_ax.bar(labels, other_vals, bottom=stacked_base, label="Other", color=self._series_color(7))

        self.analytics_doc_type_ax.set_title("Salary vs Bonus vs Allowances")
        self.analytics_doc_type_ax.set_ylabel("Net Pay")
        self.analytics_doc_type_ax.legend(frameon=True)
        self._style_axes(self.analytics_doc_type_ax, currency=True, rotate=45)

    def _plot_insurance_breakdown(self, rows):
        self.analytics_insurance_ax = self.analytics_charts["insurance"]["ax"]
        self.analytics_insurance_ax.clear()
        if not rows:
            self._empty_axes(self.analytics_insurance_ax, "Insurance Breakdown")
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

        self.analytics_insurance_ax.bar(labels, employer_vals, label="Employer Insurance", color=self._series_color(0))
        self.analytics_insurance_ax.bar(labels, employee_vals, bottom=employer_vals, label="Employee Insurance", color=self._series_color(5))
        self.analytics_insurance_ax.set_title("Insurance Contribution Breakdown")
        self.analytics_insurance_ax.set_ylabel("Contributions")
        self.analytics_insurance_ax.legend(frameon=True)
        self._style_axes(self.analytics_insurance_ax, currency=True, rotate=45)

    def _plot_same_month_yoy(self, rows, target_month):
        ax = self.analytics_charts["same_month_yoy"]["ax"]
        ax.clear()
        if not rows:
            self._empty_axes(ax, "Same Month Across Years")
            return
        labels = [str(int(year)) for year, *_ in rows]
        values = [float(net or 0) + float(employer_ins or 0) for year, net, employer_ins, _ in rows]
        ax.bar(labels, values, color=self._series_color(0), width=0.6)
        ax.set_title(f"Same Month Across Years (Month {target_month:02d})")
        ax.set_ylabel("Employer Cost")
        if len(values) >= 2:
            last = values[-1]
            prev = values[-2]
            if prev:
                pct = ((last - prev) / prev) * 100
                self._annotate_change(ax, f"YoY {pct:+.1f}%", pct)
        self._style_axes(ax, currency=True)

    def _plot_ytd_compare(self, current_metrics, prior_metrics, year):
        ax = self.analytics_charts["ytd_compare"]["ax"]
        ax.clear()
        current_total = float(current_metrics.get("total_net_pay", 0)) + float(current_metrics.get("employer_insurance", 0))
        prior_total = float(prior_metrics.get("total_net_pay", 0)) + float(prior_metrics.get("employer_insurance", 0))
        ax.bar(
            [str(year - 1), str(year)],
            [prior_total, current_total],
            color=[self.theme.muted, self._series_color(0)],
            width=0.5,
        )
        ax.set_title("YTD vs Prior YTD (Employer Cost)")
        ax.set_ylabel("Amount")
        if prior_total:
            pct = ((current_total - prior_total) / prior_total) * 100
            self._annotate_change(ax, f"{pct:+.1f}%", pct)
        self._style_axes(ax, currency=True)

    def _plot_rolling_yoy(self, rows, end_date):
        ax = self.analytics_charts["rolling_yoy"]["ax"]
        ax.clear()
        if not rows:
            self._empty_axes(ax, "Rolling 12-Month YoY")
            return
        monthly = {(int(year), int(month)): float(net or 0) + float(employer_ins or 0) for year, month, net, employer_ins, _ in rows}
        start = self._add_months(self._month_start(end_date), -23)
        months = []
        current = start
        for _ in range(24):
            months.append((current.year, current.month))
            current = self._add_months(current, 1)
        values = [monthly.get(key, 0.0) for key in months]
        prior_vals = values[:12]
        current_vals = values[12:]
        labels = [f"{y:04d}-{m:02d}" for (y, m) in months[12:]]
        ax.plot(labels, current_vals, marker="o", markersize=4, linewidth=2,
                color=self._series_color(0), label="Current 12 mo")
        ax.plot(labels, prior_vals, marker="o", markersize=3, linewidth=1.5, linestyle="--",
                color=self.theme.muted, label="Prior 12 mo")
        ax.set_title("Rolling 12-Month YoY (Employer Cost)")
        ax.set_ylabel("Employer Cost")
        ax.legend(frameon=True)
        self._style_axes(ax, currency=True, rotate=45)

    def _plot_insurance_burden(self, rows):
        ax = self.analytics_charts["insurance_burden"]["ax"]
        ax.clear()
        if not rows:
            self._empty_axes(ax, "Insurance Burden %")
            return
        labels = []
        burdens = []
        for year, month, net, employer_ins, employee_ins in rows:
            total_cost = float(net or 0) + float(employer_ins or 0)
            total_ins = float(employer_ins or 0) + float(employee_ins or 0)
            if total_cost <= 0:
                burden = 0
            else:
                burden = (total_ins / total_cost) * 100
            labels.append(f"{int(year):04d}-{int(month):02d}")
            burdens.append(burden)
        ax.plot(labels, burdens, marker="o", markersize=4, linewidth=2, color=self._series_color(4))
        ax.set_title("Insurance Burden % (Insurance / Total Cost)")
        ax.set_ylabel("Share of total cost")
        self._style_axes(ax, percent=True, rotate=45)

    def _plot_paid_aging(self, totals, buckets):
        ax = self.analytics_charts["paid_aging"]["ax"]
        ax.clear()
        paid_total, unpaid_total = totals
        labels = ["Paid", "Unpaid", "0-30", "31-60", "61-90", "90+"]
        values = [
            float(paid_total or 0),
            float(unpaid_total or 0),
            float(buckets.get("0_30", 0)),
            float(buckets.get("31_60", 0)),
            float(buckets.get("61_90", 0)),
            float(buckets.get("90_plus", 0)),
        ]
        tokens = self.theme
        # Paid and unpaid carry semantic colour; the aging buckets darken as
        # they age, so the eye lands on the oldest debt first.
        ax.bar(
            labels,
            values,
            color=[
                tokens.positive,
                tokens.negative,
                self._series_color(1),
                self._series_color(6),
                self._series_color(4),
                tokens.muted,
            ],
            width=0.6,
        )
        ax.set_title("Paid vs Unpaid Totals + Aging Buckets")
        ax.set_ylabel("Net Pay")
        self._style_axes(ax, currency=True, rotate=20)

    def _plot_avg_days_to_paid(self, rows):
        ax = self.analytics_charts["avg_days_paid"]["ax"]
        ax.clear()
        if not rows:
            self._empty_axes(ax, "Average Days to Paid")
            return
        labels = [f"{int(year):04d}-{int(month):02d}" for year, month, _ in rows]
        values = [float(avg_days or 0) for _, _, avg_days in rows]
        ax.plot(labels, values, marker="o", markersize=4, linewidth=2, color=self._series_color(0))
        ax.set_title("Average Days to Paid")
        ax.set_ylabel("Days")
        self._style_axes(ax, suffix="d", rotate=45)

    def _plot_cost_ratio(self, rows):
        ax = self.analytics_charts["cost_ratio"]["ax"]
        ax.clear()
        if not rows:
            self._empty_axes(ax, "Employer Cost vs Net Pay")
            return
        labels = []
        ratios = []
        for year, month, _net_pay, _employer_cost, ratio in rows:
            labels.append(f"{int(year):04d}-{int(month):02d}")
            ratios.append(float(ratio or 0))
        ax.plot(labels, ratios, marker="o", markersize=4, linewidth=2, color=self._series_color(5))
        # 1.0 means the employer pays exactly the take-home amount and nothing more.
        ax.axhline(1.0, color=self.theme.muted, linestyle="--", linewidth=1)
        ax.set_title("Employer Cost per € of Net Pay")
        ax.set_ylabel("Cost ratio")
        self._style_axes(ax, rotate=45)

    def _plot_headcount_trend(self, rows):
        ax = self.analytics_charts["headcount"]["ax"]
        ax.clear()
        if not rows:
            self._empty_axes(ax, "Headcount Trend")
            return
        labels = []
        headcounts = []
        joiners = []
        leavers = []
        for year, month, headcount, joined, left in rows:
            labels.append(f"{int(year):04d}-{int(month):02d}")
            headcounts.append(int(headcount or 0))
            joiners.append(int(joined or 0))
            leavers.append(-int(left or 0))
        tokens = self.theme
        ax.bar(labels, joiners, color=tokens.positive, label="Joined", width=0.6)
        ax.bar(labels, leavers, color=tokens.negative, label="Left", width=0.6)
        ax.plot(labels, headcounts, marker="o", markersize=4, linewidth=2,
                color=self._series_color(0), label="Headcount")
        ax.axhline(0, color=tokens.border, linewidth=1)
        ax.set_title("Headcount Trend with Joiners and Leavers")
        ax.set_ylabel("Employees")
        ax.legend(loc="best", frameon=True)
        self._style_axes(ax, rotate=45)

    def _plot_pay_distribution(self, rows):
        ax = self.analytics_charts["pay_distribution"]["ax"]
        ax.clear()
        if not rows:
            self._empty_axes(ax, "Median vs Average Pay")
            return
        labels = []
        averages = []
        medians = []
        p25s = []
        p75s = []
        for year, month, avg, median, p25, p75, _headcount in rows:
            labels.append(f"{int(year):04d}-{int(month):02d}")
            averages.append(float(avg or 0))
            medians.append(float(median or 0))
            p25s.append(float(p25 or 0))
            p75s.append(float(p75 or 0))
        # The shaded band is the interquartile range: where the middle half sits.
        ax.fill_between(labels, p25s, p75s, color=self._series_color(0), alpha=0.18, label="25th–75th pct")
        ax.plot(labels, averages, marker="o", markersize=4, linewidth=2,
                color=self._series_color(1), label="Average")
        ax.plot(labels, medians, marker="s", markersize=4, linewidth=2,
                color=self._series_color(0), label="Median")
        ax.set_title("Median vs Average Monthly Net Pay")
        ax.set_ylabel("Net Pay")
        ax.legend(loc="best", frameon=True)
        self._style_axes(ax, currency=True, rotate=45)

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
            self._empty_axes(
                self.analytics_heatmap_ax,
                "Payment Heat-map",
                "Pick a year and month in the filter bar",
            )
            self.analytics_heatmap_employees = []
            self.analytics_heatmap_dates = []
            return
        if not rows:
            self._empty_axes(self.analytics_heatmap_ax, "Payment Heat-map")
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

        tokens = self.theme
        heatmap_fig = self.analytics_charts["heatmap"]["fig"]
        im = self.analytics_heatmap_ax.imshow(data_matrix, aspect="auto", cmap=tokens.chart_colormap)
        self.analytics_heatmap_ax.set_title("Payment Heat-map")
        self.analytics_heatmap_ax.set_yticks(range(len(employees)))
        self.analytics_heatmap_ax.set_yticklabels(
            [name if len(str(name)) <= 22 else f"{str(name)[:21]}…" for name in employees]
        )
        self.analytics_heatmap_ax.set_xticks(range(len(date_labels)))
        self.analytics_heatmap_ax.set_xticklabels(date_labels, rotation=90)
        self.analytics_heatmap_cax = heatmap_fig.add_axes([0.88, 0.15, 0.03, 0.7])
        self.analytics_heatmap_cbar = heatmap_fig.colorbar(im, cax=self.analytics_heatmap_cax)
        self.analytics_heatmap_cbar.outline.set_edgecolor(tokens.border)
        self.analytics_heatmap_cax.tick_params(colors=tokens.text_secondary, labelsize=8)
        # The colourbar lives in manually placed axes, so a reflow would move it
        # out from under the heat-map; the margins are set explicitly instead,
        # leaving room for the employee names on the left.
        heatmap_fig.subplots_adjust(left=0.26, right=0.85, bottom=0.16, top=0.90)
        self._style_axes(self.analytics_heatmap_ax, grid_axis=None, tight=False)

    def _month_start(self, date_value):
        return datetime.date(date_value.year, date_value.month, 1)

    def _month_end(self, date_value):
        last_day = calendar.monthrange(date_value.year, date_value.month)[1]
        return datetime.date(date_value.year, date_value.month, last_day)

    def _add_months(self, date_value, months):
        year = date_value.year + (date_value.month - 1 + months) // 12
        month = (date_value.month - 1 + months) % 12 + 1
        day = min(date_value.day, calendar.monthrange(year, month)[1])
        return datetime.date(year, month, day)

    def _plot_employee_costs(self, rows):
        self.analytics_employee_ax = self.analytics_charts["employee"]["ax"]
        self.analytics_employee_ax.clear()
        if not rows:
            self._empty_axes(self.analytics_employee_ax, "Cost Per Employee")
            self.analytics_employee_bar_map = {}
            return

        employees = [row[0] for row in rows]
        costs = [float(row[1] or 0) for row in rows]
        bars = self.analytics_employee_ax.barh(employees, costs, color=self._series_color(0), height=0.65)
        self.analytics_employee_bar_map = {}
        for bar, name in zip(bars, employees):
            bar.set_picker(True)
            self.analytics_employee_bar_map[bar] = name
        self.analytics_employee_ax.set_title("Cost Per Employee")
        self.analytics_employee_ax.set_xlabel("Employer Cost")
        self.analytics_employee_ax.invert_yaxis()
        self.analytics_employee_ax.xaxis.set_major_formatter(FuncFormatter(self._format_axis_amount))
        self._style_axes(self.analytics_employee_ax, grid_axis="x")

    def create_analytics_grid_tab(self):
        """Create the analytics data grid and detail views."""
        self.analytics_grid_view_tab.columnconfigure(0, weight=1)
        self.analytics_grid_view_tab.rowconfigure(2, weight=1)
        self.analytics_grid_view_tab.rowconfigure(3, weight=0)

        header = ttk.Frame(self.analytics_grid_view_tab)
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        header.columnconfigure(2, weight=1)

        ttk.Label(header, text="Analytics Data Grid", style="Header.TLabel").grid(row=0, column=0, padx=(0, 10))
        refresh_btn = ttk.Button(
            header,
            text="Refresh Grid",
            command=self.refresh_data_grid,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=1, padx=(0, 10))
        self._add_tooltip(refresh_btn, "Reload analytics grid data.")
        self.analytics_grid_status_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.analytics_grid_status_var, style="Body.TLabel").grid(row=0, column=2, sticky=tk.W)

        cards_frame = ttk.Frame(self.analytics_grid_view_tab, style="App.TFrame")
        cards_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)
        cards_frame.columnconfigure(2, weight=1)
        self._build_kpi_card(cards_frame, 0, "Total Net Pay", self.kpi_total_net_var)
        self._build_kpi_card(cards_frame, 1, "Employer Cost", self.kpi_employer_cost_var)
        self._build_kpi_card(cards_frame, 2, "Total Insurance", self.kpi_total_insurance_var)

        self.analytics_grid_notebook = ttk.Notebook(self.analytics_grid_view_tab, style="App.TNotebook")
        self.analytics_grid_notebook.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        grid_frame = ttk.Frame(self.analytics_grid_notebook, padding=8, style="App.TFrame")
        self._build_data_grid(grid_frame)
        self.analytics_grid_tab = grid_frame
        self.analytics_grid_notebook.add(grid_frame, text="Data Grid")

        detail_frame = ttk.Frame(self.analytics_grid_notebook, padding=8, style="App.TFrame")
        self._build_detail_tab(detail_frame)
        self.analytics_detail_tab = detail_frame
        self.analytics_grid_notebook.add(detail_frame, text="Employee Detail")

        monthly_frame = ttk.Frame(self.analytics_grid_notebook, padding=8, style="App.TFrame")
        self._build_monthly_employee_tab(monthly_frame)
        self.analytics_monthly_tab = monthly_frame
        self.analytics_grid_notebook.add(monthly_frame, text="Monthly Employee Summary")

        for key in ("<Left>", "<Right>"):
            self.analytics_grid_notebook.bind(key, self._cycle_analytics_grid_tab, add="+")

        footer = ttk.Frame(self.analytics_grid_view_tab, style="App.TFrame")
        footer.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(8, 0))
        footer.columnconfigure(6, weight=1)

        self.analytics_footer_export_btn = ttk.Menubutton(
            footer,
            text="Export",
            image=self.icons.get("export"),
            compound=tk.LEFT,
        )
        self.analytics_footer_export_btn.grid(row=0, column=0, padx=(0, 10), sticky=tk.W)
        self.analytics_footer_export_menu = tk.Menu(self.analytics_footer_export_btn, tearoff=0)
        self.analytics_footer_export_menu.add_command(label="CSV", command=self.export_active_grid_csv)
        self.analytics_footer_export_menu.add_command(label="XLSX", command=self.export_active_grid_xlsx)
        self.analytics_footer_export_menu.add_command(label="PDF", command=self.export_active_grid_pdf)
        self.analytics_footer_export_btn.configure(menu=self.analytics_footer_export_menu)
        self._add_tooltip(self.analytics_footer_export_btn, "Export selected rows or all rows from the active tab.")

        self.analytics_footer_undo_btn = ttk.Button(
            footer,
            text="Undo",
            command=self._undo_last_edit,
            image=self.icons.get("undo"),
            compound=tk.LEFT,
        )
        self.analytics_footer_undo_btn.grid(row=0, column=1, padx=(0, 10), sticky=tk.W)
        self._add_tooltip(self.analytics_footer_undo_btn, "Undo the last edit in the data grid.")

        self.analytics_footer_prev_btn = ttk.Button(
            footer,
            text="Prev",
            command=self._prev_grid_page,
            image=self.icons.get("previous"),
            compound=tk.LEFT,
        )
        self.analytics_footer_prev_btn.grid(row=0, column=2, padx=(16, 4), sticky=tk.W)
        self.analytics_footer_next_btn = ttk.Button(
            footer,
            text="Next",
            command=self._next_grid_page,
            image=self.icons.get("next"),
            compound=tk.LEFT,
        )
        self.analytics_footer_next_btn.grid(row=0, column=3, padx=(0, 10), sticky=tk.W)
        self._add_tooltip(self.analytics_footer_prev_btn, "Go to the previous page.")
        self._add_tooltip(self.analytics_footer_next_btn, "Go to the next page.")

        ttk.Label(footer, text="Page", style="Body.TLabel").grid(row=0, column=4, padx=(0, 6))
        self.analytics_footer_page_label = ttk.Label(footer, textvariable=self.analytics_grid_page_var, style="Body.TLabel")
        self.analytics_footer_page_label.grid(row=0, column=5, padx=(0, 6), sticky=tk.W)
        ttk.Label(footer, textvariable=self.analytics_grid_total_var, style="Body.TLabel").grid(row=0, column=6, sticky=tk.W)

        self.analytics_grid_notebook.bind("<<NotebookTabChanged>>", self._on_analytics_grid_tab_change)

    def create_insurance_tab(self):
        """Create the insurance comparison tab."""
        self.insurance_tab.columnconfigure(0, weight=1)
        self.insurance_tab.rowconfigure(1, weight=1)

        header = ttk.Frame(self.insurance_tab, style="App.TFrame")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        header.columnconfigure(5, weight=1)

        ttk.Label(header, text="Insurance", style="Header.TLabel").grid(row=0, column=0, padx=(0, 10))
        refresh_btn = ttk.Button(
            header,
            text="Refresh",
            command=self.refresh_insurance_summary,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=1, padx=(0, 10))
        self._add_tooltip(refresh_btn, "Refresh insurance summary.")
        mark_paid_btn = ttk.Button(header, text="Mark Paid", command=self._mark_insurance_paid)
        mark_paid_btn.grid(row=0, column=2, padx=(0, 8))
        mark_unpaid_btn = ttk.Button(header, text="Mark Unpaid", command=self._mark_insurance_unpaid)
        mark_unpaid_btn.grid(row=0, column=3, padx=(0, 8))
        set_date_btn = ttk.Button(header, text="Set Paid Date…", command=self._set_insurance_paid_date)
        set_date_btn.grid(row=0, column=4, padx=(0, 8))
        ttk.Label(header, textvariable=self.insurance_status_var, style="Body.TLabel").grid(row=0, column=5, sticky=tk.W)

        frame = ttk.Frame(self.insurance_tab, style="App.TFrame")
        frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.insurance_columns = [
            "year",
            "month",
            "calculated_insurance",
            "official_efka",
            "official_teka",
            "official_total",
            "variance",
            "employee_insurance",
            "employer_insurance",
            "official_earnings",
            "paid_status",
            "paid_date",
            "latest_submission_date",
            "tpte_codes",
            "source_pdfs",
        ]
        self.insurance_tree = ttk.Treeview(frame, columns=self.insurance_columns, show="headings")
        self.insurance_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.insurance_tree.bind("<Button-3>", self._show_insurance_context_menu)
        self.insurance_tree.bind("<Button-2>", self._show_insurance_context_menu)
        self.insurance_tree.bind("<Control-Button-1>", self._show_insurance_context_menu)
        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.insurance_tree.yview)
        y_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.insurance_tree.xview)
        x_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.insurance_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        headings = {
            "year": "Year",
            "month": "Month",
            "calculated_insurance": "Calculated Insurance",
            "official_efka": "Official EFKA",
            "official_teka": "Official TEKA",
            "official_total": "Official Total",
            "variance": "Difference",
            "employee_insurance": "Employee Insurance",
            "employer_insurance": "Employer Insurance",
            "official_earnings": "Official Earnings",
            "paid_status": "Paid",
            "paid_date": "Paid Date",
            "latest_submission_date": "Submitted",
            "tpte_codes": "T.P.T.E.",
            "source_pdfs": "Source PDFs",
        }
        for col in self.insurance_columns:
            self.insurance_tree.heading(col, text=headings.get(col, col))
            anchor = tk.W if col in {"tpte_codes", "source_pdfs"} else tk.CENTER
            width = 110 if col in {"paid_status", "paid_date"} else 140
            self.insurance_tree.column(col, width=width, anchor=anchor, stretch=True)

    def refresh_insurance_summary(self):
        if not self.db_config.get("enabled"):
            self.insurance_status_var.set("Database storage is disabled.")
            self._database_notice(
                self.insurance_tab,
                "The EFKA/TEKA comparison reads stored claims. Turn storage on to see it.",
            )
            return
        self._clear_database_notice(self.insurance_tab)
        if not self.insurance_tree:
            return
        start_date, end_date, document_type, search = self._get_global_filters()
        try:
            rows = db_storage.fetch_insurance_comparison(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search,
            )
        except Exception as exc:
            self.insurance_status_var.set("Failed to load insurance summary.")
            self.show_message("Database Error", str(exc), kind="warning")
            return
        for item in self.insurance_tree.get_children():
            self.insurance_tree.delete(item)
        self.insurance_cache.clear()

        def fmt_currency(value):
            if value is None:
                return ""
            return self._format_currency(float(value))

        for row in rows:
            row_map = dict(zip(self.insurance_columns, row))
            if row_map.get("year") and row_map.get("month"):
                self.insurance_cache[(int(row_map["year"]), int(row_map["month"]))] = row_map
            paid_status = row_map.get("paid_status")
            paid_label = "Yes" if paid_status else ("No" if paid_status is not None else "")
            values = (
                row_map.get("year") or "",
                f"{int(row_map['month']):02d}" if row_map.get("month") else "",
                fmt_currency(row_map.get("calculated_insurance")),
                fmt_currency(row_map.get("official_efka")),
                fmt_currency(row_map.get("official_teka")),
                fmt_currency(row_map.get("official_total")),
                fmt_currency(row_map.get("variance")),
                fmt_currency(row_map.get("employee_insurance")),
                fmt_currency(row_map.get("employer_insurance")),
                fmt_currency(row_map.get("official_earnings")),
                paid_label,
                row_map.get("paid_date").strftime("%d/%m/%Y") if row_map.get("paid_date") else "",
                row_map.get("latest_submission_date").strftime("%d/%m/%Y") if row_map.get("latest_submission_date") else "",
                row_map.get("tpte_codes") or "",
                row_map.get("source_pdfs") or "",
            )
            self.insurance_tree.insert("", tk.END, values=values)
        self.insurance_status_var.set(f"{len(rows)} month(s) loaded.")

    def create_employees_tab(self):
        """Create the employees tab with profile and monthly totals."""
        self.employees_tab.columnconfigure(0, weight=1)
        self.employees_tab.rowconfigure(1, weight=1)

        header = ttk.Frame(self.employees_tab, style="App.TFrame")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        header.columnconfigure(3, weight=1)
        ttk.Label(header, text="Employees", style="Header.TLabel").grid(row=0, column=0, padx=(0, 10))
        refresh_btn = ttk.Button(
            header,
            text="Refresh",
            command=self.refresh_employees_tab,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=1, padx=(0, 10))
        ttk.Label(header, text="Search", style="Body.TLabel").grid(row=0, column=2, sticky=tk.W)
        search_entry = ttk.Entry(header, textvariable=self.employee_search_var, width=24)
        search_entry.grid(row=0, column=3, sticky=tk.W)
        search_entry.bind("<KeyRelease>", lambda _e: self.refresh_employees_tab())

        body = ttk.Frame(self.employees_tab, style="App.TFrame")
        body.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(body, style="App.TFrame")
        list_frame.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W), padx=(0, 12))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.employees_tree = ttk.Treeview(list_frame, columns=("code", "name", "iban"), show="headings", height=18)
        self.employees_tree.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W, tk.E))
        employees_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.employees_tree.yview)
        employees_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.employees_tree.configure(yscrollcommand=employees_scroll.set)
        self.employees_tree.heading("code", text="Code")
        self.employees_tree.heading("name", text="Name")
        self.employees_tree.heading("iban", text="IBAN")
        self.employees_tree.column("code", width=90, anchor=tk.W)
        self.employees_tree.column("name", width=200, anchor=tk.W)
        self.employees_tree.column("iban", width=180, anchor=tk.W)
        self.employees_tree.bind("<<TreeviewSelect>>", self._on_employee_select)

        detail_frame = ttk.Frame(body, style="App.TFrame")
        detail_frame.grid(row=0, column=1, sticky=(tk.N, tk.S, tk.W, tk.E))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(2, weight=1)
        detail_frame.rowconfigure(4, weight=1)

        profile_frame = ttk.LabelFrame(detail_frame, text="Profile", padding=12, style="App.TLabelframe")
        profile_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        profile_frame.columnconfigure(1, weight=1)

        self.employee_profile_vars = {
            "code": tk.StringVar(value="—"),
            "name": tk.StringVar(value="—"),
            "iban": tk.StringVar(value="—"),
            "beneficiary": tk.StringVar(value="—"),
            "first_worked": tk.StringVar(value="—"),
            "last_paid": tk.StringVar(value="—"),
            "rate_monthly": tk.StringVar(value="—"),
            "rate_hourly": tk.StringVar(value="—"),
            "rate_daily": tk.StringVar(value="—"),
            "rate_double": tk.StringVar(value="—"),
            "rate_abroad": tk.StringVar(value="—"),
            "rate_abroad_double": tk.StringVar(value="—"),
        }

        ttk.Label(profile_frame, text="Code", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, textvariable=self.employee_profile_vars["code"], style="Body.TLabel").grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, text="Name", style="Body.TLabel").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, textvariable=self.employee_profile_vars["name"], style="Body.TLabel").grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, text="IBAN", style="Body.TLabel").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, textvariable=self.employee_profile_vars["iban"], style="Body.TLabel").grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, text="Beneficiary", style="Body.TLabel").grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, textvariable=self.employee_profile_vars["beneficiary"], style="Body.TLabel").grid(row=3, column=1, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, text="First Worked", style="Body.TLabel").grid(row=4, column=0, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, textvariable=self.employee_profile_vars["first_worked"], style="Body.TLabel").grid(row=4, column=1, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, text="Last Paid", style="Body.TLabel").grid(row=5, column=0, sticky=tk.W, pady=2)
        ttk.Label(profile_frame, textvariable=self.employee_profile_vars["last_paid"], style="Body.TLabel").grid(row=5, column=1, sticky=tk.W, pady=2)

        rates_frame = ttk.Frame(profile_frame, style="App.TFrame")
        rates_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(6, 0))
        rates_frame.columnconfigure(1, weight=1)
        ttk.Label(rates_frame, text="Monthly Rate", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, textvariable=self.employee_profile_vars["rate_monthly"], style="Body.TLabel").grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, text="Hourly Rate", style="Body.TLabel").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, textvariable=self.employee_profile_vars["rate_hourly"], style="Body.TLabel").grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, text="Daily Rate", style="Body.TLabel").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, textvariable=self.employee_profile_vars["rate_daily"], style="Body.TLabel").grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, text="Double Rate", style="Body.TLabel").grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, textvariable=self.employee_profile_vars["rate_double"], style="Body.TLabel").grid(row=3, column=1, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, text="Abroad Rate", style="Body.TLabel").grid(row=4, column=0, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, textvariable=self.employee_profile_vars["rate_abroad"], style="Body.TLabel").grid(row=4, column=1, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, text="Abroad Double", style="Body.TLabel").grid(row=5, column=0, sticky=tk.W, pady=2)
        ttk.Label(rates_frame, textvariable=self.employee_profile_vars["rate_abroad_double"], style="Body.TLabel").grid(row=5, column=1, sticky=tk.W, pady=2)

        edit_btn = ttk.Button(profile_frame, text="Edit Profile", command=self._edit_employee_profile)
        edit_btn.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        totals_frame = ttk.LabelFrame(detail_frame, text="Monthly Totals", padding=12, style="App.TLabelframe")
        totals_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        totals_frame.columnconfigure(0, weight=1)
        totals_frame.rowconfigure(0, weight=1)

        self.employee_monthly_tree = ttk.Treeview(
            totals_frame,
            columns=("year", "month", "net_pay", "employee_insurance", "employer_insurance", "total_insurance"),
            show="headings",
            height=6,
        )
        self.employee_monthly_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        ttk.Scrollbar(totals_frame, orient=tk.VERTICAL, command=self.employee_monthly_tree.yview).grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.employee_monthly_tree.heading("year", text="Year")
        self.employee_monthly_tree.heading("month", text="Month")
        self.employee_monthly_tree.heading("net_pay", text="Net Pay")
        self.employee_monthly_tree.heading("employee_insurance", text="Employee Ins.")
        self.employee_monthly_tree.heading("employer_insurance", text="Employer Ins.")
        self.employee_monthly_tree.heading("total_insurance", text="Total Ins.")
        for col in ("year", "month", "net_pay", "employee_insurance", "employer_insurance", "total_insurance"):
            self.employee_monthly_tree.column(col, width=100, anchor=tk.CENTER)

        payments_frame = ttk.LabelFrame(detail_frame, text="Payments", padding=12, style="App.TLabelframe")
        payments_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        payments_frame.columnconfigure(0, weight=1)
        payments_frame.rowconfigure(0, weight=1)

        payments_notebook = ttk.Notebook(payments_frame, style="App.TNotebook")
        payments_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        due_frame = ttk.Frame(payments_notebook, padding=8, style="App.TFrame")
        paid_frame = ttk.Frame(payments_notebook, padding=8, style="App.TFrame")
        payments_notebook.add(due_frame, text="Due")
        payments_notebook.add(paid_frame, text="Paid")

        self.employee_due_tree = ttk.Treeview(
            due_frame,
            columns=("payment_date", "document_type", "net_pay", "paid_date", "source_pdf"),
            show="headings",
            height=6,
        )
        self.employee_paid_tree = ttk.Treeview(
            paid_frame,
            columns=("payment_date", "document_type", "net_pay", "paid_date", "source_pdf"),
            show="headings",
            height=6,
        )
        for tree in (self.employee_due_tree, self.employee_paid_tree):
            tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            scroll = ttk.Scrollbar(tree.master, orient=tk.VERTICAL, command=tree.yview)
            scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
            tree.configure(yscrollcommand=scroll.set)
            for col, text in (
                ("payment_date", "Payment Date"),
                ("document_type", "Doc Type"),
                ("net_pay", "Net Pay"),
                ("paid_date", "Paid Date"),
                ("source_pdf", "Source PDF"),
            ):
                tree.heading(col, text=text)
                anchor = tk.W if col == "source_pdf" else tk.CENTER
                tree.column(col, width=120 if col != "source_pdf" else 260, anchor=anchor)

    def refresh_employees_tab(self):
        if not self.db_config.get("enabled"):
            self._database_notice(
                self.employees_tab,
                "Employee profiles are built from stored payroll entries. Turn storage on to see them.",
            )
            return
        self._clear_database_notice(self.employees_tab)
        if not self.employees_tree:
            return
        search = self.employee_search_var.get().strip()
        rows = db_storage.fetch_employees_list(self.db_config, search=search or None)
        for item in self.employees_tree.get_children():
            self.employees_tree.delete(item)
        for code, name, iban, _beneficiary, first_worked, last_paid in rows:
            self.employees_tree.insert(
                "",
                tk.END,
                values=(
                    code or "",
                    name or "",
                    iban or "",
                ),
            )
        if not rows:
            self.employee_selected_code = None
            self._clear_employee_profile()
            return
        if self.employee_selected_code:
            self._load_employee_profile(self.employee_selected_code)

    def _on_employee_select(self, _event=None):
        if not self.employees_tree:
            return
        selection = self.employees_tree.selection()
        if not selection:
            return
        values = self.employees_tree.item(selection[0], "values")
        if not values:
            return
        code = values[0]
        if code:
            self._load_employee_profile(code)

    def _load_employee_profile(self, employee_code):
        self.employee_selected_code = employee_code
        profile = db_storage.fetch_employee_profile(self.db_config, employee_code)
        if not profile:
            return
        (
            code,
            name,
            iban,
            beneficiary_name,
            first_worked,
            last_paid,
            rate_monthly,
            rate_hourly,
            rate_daily,
            rate_double,
            rate_abroad,
            rate_abroad_double,
        ) = profile
        self.employee_profile_vars["code"].set(code or "—")
        self.employee_profile_vars["name"].set(name or "—")
        self.employee_profile_vars["iban"].set(iban or "—")
        self.employee_profile_vars["beneficiary"].set(beneficiary_name or "—")
        self.employee_profile_vars["first_worked"].set(first_worked.strftime("%d/%m/%Y") if first_worked else "—")
        self.employee_profile_vars["last_paid"].set(last_paid.strftime("%d/%m/%Y") if last_paid else "—")
        self.employee_profile_vars["rate_monthly"].set(self._format_rate(rate_monthly))
        self.employee_profile_vars["rate_hourly"].set(self._format_rate(rate_hourly))
        self.employee_profile_vars["rate_daily"].set(self._format_rate(rate_daily))
        self.employee_profile_vars["rate_double"].set(self._format_rate(rate_double))
        self.employee_profile_vars["rate_abroad"].set(self._format_rate(rate_abroad))
        self.employee_profile_vars["rate_abroad_double"].set(self._format_rate(rate_abroad_double))

        start_date, end_date, _, _ = self._get_global_filters()
        totals = db_storage.fetch_employee_monthly_totals(
            self.db_config,
            employee_code,
            start_date=start_date,
            end_date=end_date,
        )
        for item in self.employee_monthly_tree.get_children():
            self.employee_monthly_tree.delete(item)
        for year, month, net_pay, employee_ins, employer_ins, total_ins in totals:
            self.employee_monthly_tree.insert(
                "",
                tk.END,
                values=(
                    year,
                    f"{int(month):02d}",
                    self._format_currency(net_pay or 0),
                    self._format_currency(employee_ins or 0),
                    self._format_currency(employer_ins or 0),
                    self._format_currency(total_ins or 0),
                ),
            )

        columns, entries = db_storage.fetch_employee_entries(self.db_config, employee_code=employee_code, limit=200)
        col_idx = {col: idx for idx, col in enumerate(columns)}
        for tree in (self.employee_due_tree, self.employee_paid_tree):
            for item in tree.get_children():
                tree.delete(item)
        for row in entries:
            paid_status = row[col_idx.get("paid_status")]
            paid_date = row[col_idx.get("paid_date")]
            payment_date = row[col_idx.get("payment_date")]
            doc_type = row[col_idx.get("document_type")]
            net_pay = row[col_idx.get("net_pay")]
            source_pdf = row[col_idx.get("source_pdf")]
            values = (
                payment_date.strftime("%d/%m/%Y") if payment_date else "",
                doc_type or "",
                self._format_currency(net_pay or 0),
                paid_date.strftime("%d/%m/%Y") if paid_date else "",
                source_pdf or "",
            )
            if paid_status:
                self.employee_paid_tree.insert("", tk.END, values=values)
            else:
                self.employee_due_tree.insert("", tk.END, values=values)

    def _clear_employee_profile(self):
        for key, var in self.employee_profile_vars.items():
            var.set("—")
        if self.employee_monthly_tree:
            for item in self.employee_monthly_tree.get_children():
                self.employee_monthly_tree.delete(item)
        for tree in (self.employee_due_tree, self.employee_paid_tree):
            if tree:
                for item in tree.get_children():
                    tree.delete(item)

    def _edit_employee_profile(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — employee profiles cannot be edited.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        code = self.employee_selected_code
        if not code:
            self.show_toast("Select an employee first.")
            return
        profile = db_storage.fetch_employee_profile(self.db_config, code)
        if not profile:
            return
        (
            _code,
            name,
            iban,
            beneficiary_name,
            first_worked,
            last_paid,
            rate_monthly,
            rate_hourly,
            rate_daily,
            rate_double,
            rate_abroad,
            rate_abroad_double,
        ) = profile

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Employee {code}")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        frame.columnconfigure(1, weight=1)

        iban_var = tk.StringVar(value=iban or "")
        beneficiary_var = tk.StringVar(value=beneficiary_name or "")
        first_var = tk.StringVar(value=first_worked.strftime("%Y-%m-%d") if first_worked else "")
        last_var = tk.StringVar(value=last_paid.strftime("%Y-%m-%d") if last_paid else "")
        monthly_var = tk.StringVar(value=self._format_value_for_edit(rate_monthly))
        hourly_var = tk.StringVar(value=self._format_value_for_edit(rate_hourly))
        daily_var = tk.StringVar(value=self._format_value_for_edit(rate_daily))
        double_var = tk.StringVar(value=self._format_value_for_edit(rate_double))
        abroad_var = tk.StringVar(value=self._format_value_for_edit(rate_abroad))
        abroad_double_var = tk.StringVar(value=self._format_value_for_edit(rate_abroad_double))

        ttk.Label(frame, text=f"{name or ''} ({code})", style="Body.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
        ttk.Label(frame, text="IBAN", style="Body.TLabel").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=iban_var, width=32).grid(row=1, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Beneficiary", style="Body.TLabel").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=beneficiary_var, width=32).grid(row=2, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="First Worked (YYYY-MM-DD)", style="Body.TLabel").grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=first_var, width=24).grid(row=3, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Last Paid (YYYY-MM-DD)", style="Body.TLabel").grid(row=4, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=last_var, width=24).grid(row=4, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Monthly Rate", style="Body.TLabel").grid(row=5, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=monthly_var, width=20).grid(row=5, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Hourly Rate", style="Body.TLabel").grid(row=6, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=hourly_var, width=20).grid(row=6, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Daily Rate", style="Body.TLabel").grid(row=7, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=daily_var, width=20).grid(row=7, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Double Rate", style="Body.TLabel").grid(row=8, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=double_var, width=20).grid(row=8, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Abroad Rate", style="Body.TLabel").grid(row=9, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=abroad_var, width=20).grid(row=9, column=1, sticky=tk.W, pady=4)
        ttk.Label(frame, text="Abroad Double", style="Body.TLabel").grid(row=10, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=abroad_double_var, width=20).grid(row=10, column=1, sticky=tk.W, pady=4)

        error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=error_var, style="Body.TLabel").grid(row=11, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        def parse_amount(value):
            if value is None:
                return None
            cleaned = value.strip()
            if not cleaned:
                return None
            if "," in cleaned and "." in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                cleaned = cleaned.replace(",", ".")
            try:
                return float(cleaned)
            except ValueError:
                return None

        def parse_date(text):
            text = text.strip()
            if not text:
                return None
            return datetime.date.fromisoformat(text)

        def on_save():
            try:
                first_date = parse_date(first_var.get())
                last_date = parse_date(last_var.get())
            except ValueError:
                error_var.set("Invalid date format.")
                return
            db_storage.update_employee_profile(
                self.db_config,
                code,
                iban=iban_var.get().strip() or None,
                beneficiary_name=beneficiary_var.get().strip() or None,
                first_worked_date=first_date,
                last_paid_date=last_date,
                pay_rate_monthly=parse_amount(monthly_var.get()),
                pay_rate_hourly=parse_amount(hourly_var.get()),
                pay_rate_daily=parse_amount(daily_var.get()),
                pay_rate_double=parse_amount(double_var.get()),
                pay_rate_abroad=parse_amount(abroad_var.get()),
                pay_rate_abroad_double=parse_amount(abroad_double_var.get()),
            )
            dialog.destroy()
            self._load_employee_profile(code)
            self.refresh_employees_tab()

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=12, column=0, columnspan=2, pady=(8, 0), sticky=tk.W)
        ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def _format_rate(self, value):
        if value is None:
            return "—"
        try:
            return self._format_currency(float(value))
        except Exception:
            return "—"

    def _show_insurance_context_menu(self, event):
        if not self.insurance_tree:
            return
        row_id = self.insurance_tree.identify_row(event.y)
        if row_id:
            self.insurance_tree.selection_set(row_id)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Edit", command=self._edit_insurance_scanned_values)
        menu.add_command(label="Open Insurance Folder", command=self._open_insurance_folder)
        menu.add_command(label="Show PDF in Finder", command=self._reveal_insurance_pdf)
        menu.add_command(label="Delete Entry…", command=self._delete_insurance_entry)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _edit_insurance_scanned_values(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — insurance claims cannot be edited.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        period = self._get_selected_insurance_period()
        if not period:
            return
        year, month = period
        row_map = self.insurance_cache.get((year, month), {})

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Insurance {year}-{month:02d}")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        frame.columnconfigure(1, weight=1)

        efka_var = tk.StringVar(value=self._format_value_for_edit(row_map.get("official_efka")))
        teka_var = tk.StringVar(value=self._format_value_for_edit(row_map.get("official_teka")))
        earnings_var = tk.StringVar(value=self._format_value_for_edit(row_map.get("official_earnings")))
        submitted_var = tk.StringVar(
            value=row_map.get("latest_submission_date").strftime("%Y-%m-%d") if row_map.get("latest_submission_date") else ""
        )
        tpte_var = tk.StringVar(value=row_map.get("tpte_codes") or "")
        paid_var = tk.StringVar(value="Yes" if row_map.get("paid_status") else "No")
        paid_date_var = tk.StringVar(
            value=row_map.get("paid_date").strftime("%Y-%m-%d") if row_map.get("paid_date") else ""
        )

        ttk.Label(frame, text="Official EFKA", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=efka_var, width=24).grid(row=0, column=1, sticky=tk.W, pady=(0, 6))
        ttk.Label(frame, text="Official TEKA", style="Body.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=teka_var, width=24).grid(row=1, column=1, sticky=tk.W, pady=(0, 6))
        ttk.Label(frame, text="Official Earnings", style="Body.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=earnings_var, width=24).grid(row=2, column=1, sticky=tk.W, pady=(0, 6))
        ttk.Label(frame, text="Submitted (YYYY-MM-DD)", style="Body.TLabel").grid(row=3, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=submitted_var, width=24).grid(row=3, column=1, sticky=tk.W, pady=(0, 6))
        ttk.Label(frame, text="T.P.T.E. Code(s)", style="Body.TLabel").grid(row=4, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=tpte_var, width=24).grid(row=4, column=1, sticky=tk.W, pady=(0, 6))
        ttk.Label(frame, text="Paid", style="Body.TLabel").grid(row=5, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Combobox(frame, textvariable=paid_var, values=["Yes", "No"], state="readonly", width=22).grid(
            row=5, column=1, sticky=tk.W, pady=(0, 6)
        )
        ttk.Label(frame, text="Paid Date (YYYY-MM-DD)", style="Body.TLabel").grid(row=6, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=paid_date_var, width=24).grid(row=6, column=1, sticky=tk.W, pady=(0, 6))

        error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=error_var, style="Body.TLabel").grid(row=7, column=0, columnspan=2, sticky=tk.W)

        def _parse_amount_input(value):
            if value is None:
                return None
            cleaned = value.strip()
            if not cleaned:
                return None
            if "," in cleaned and "." in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                cleaned = cleaned.replace(",", ".")
            try:
                return float(cleaned)
            except ValueError:
                return None

        def on_save():
            efka_val = _parse_amount_input(efka_var.get())
            teka_val = _parse_amount_input(teka_var.get())
            earnings_val = _parse_amount_input(earnings_var.get())
            submitted_text = submitted_var.get().strip()
            tpte_text = tpte_var.get().strip()
            paid_text = paid_var.get().strip().lower()
            paid_date_text = paid_date_var.get().strip()

            submission_date = None
            if submitted_text:
                try:
                    submission_date = datetime.date.fromisoformat(submitted_text)
                except ValueError:
                    error_var.set("Invalid submitted date format.")
                    return

            paid_status = True if paid_text == "yes" else False
            paid_date = None
            if paid_date_text:
                try:
                    paid_date = datetime.date.fromisoformat(paid_date_text)
                except ValueError:
                    error_var.set("Invalid paid date format.")
                    return

            try:
                db_storage.update_insurance_claims_for_period(
                    self.db_config,
                    year,
                    month,
                    efka_total=efka_val,
                    teka_total=teka_val,
                    total_earnings=earnings_val,
                    submission_date=submission_date,
                    tpte_code=tpte_text or None,
                    paid_status=paid_status,
                    paid_date=paid_date,
                )
            except Exception as exc:
                error_var.set(str(exc))
                return
            dialog.destroy()
            self.refresh_insurance_summary()

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=8, column=0, columnspan=2, pady=(8, 0), sticky=tk.W)
        ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def _delete_insurance_entry(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — insurance claims cannot be deleted.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        period = self._get_selected_insurance_period()
        if not period:
            return
        year, month = period
        ok = messagebox.askyesno(
            "Delete Insurance Entry",
            f"Delete insurance claim entries for {year}-{month:02d}?\nThis cannot be undone.",
            parent=self.root,
        )
        if not ok:
            return
        try:
            deleted = db_storage.delete_insurance_claims_for_period(self.db_config, year, month)
        except Exception as exc:
            self.show_message("Insurance", f"Failed to delete:\n{exc}", kind="warning")
            return
        self.refresh_insurance_summary()
        self.insurance_status_var.set(f"Deleted {deleted} claim(s) for {year}-{month:02d}.")

    def _open_insurance_folder(self):
        period = self._get_selected_insurance_period()
        if not period:
            return
        year, _month = period
        folder = self.archive_dir / str(year) / "Insurance"
        if not folder.exists():
            self.show_toast(f"No folder found at {folder}", kind="warning")
            return
        subprocess.run(["open", str(folder)], check=False)

    def _reveal_insurance_pdf(self):
        period = self._get_selected_insurance_period()
        if not period:
            return
        year, month = period
        row_map = self.insurance_cache.get((year, month), {})
        folder = self.archive_dir / str(year) / "Insurance"
        if not folder.exists():
            self.show_toast(f"No folder found at {folder}", kind="warning")
            return
        tpte_codes = row_map.get("tpte_codes") or ""
        codes = [code.strip() for code in tpte_codes.split(",") if code.strip()]
        if not codes:
            self.show_toast("No T.P.T.E. code found for this entry.")
            subprocess.run(["open", str(folder)], check=False)
            return
        matches = []
        try:
            for fname in os.listdir(folder):
                for code in codes:
                    if code in fname:
                        matches.append(fname)
                        break
        except OSError:
            matches = []
        if not matches:
            self.show_toast("No matching PDF found in the folder.")
            subprocess.run(["open", str(folder)], check=False)
            return
        matches.sort()
        target = folder / matches[0]
        subprocess.run(["open", "-R", str(target)], check=False)

    def _format_value_for_edit(self, value):
        if value is None:
            return ""
        try:
            return f"{float(value):.2f}"
        except Exception:
            return ""

    def _get_selected_insurance_period(self):
        if not self.insurance_tree:
            return None
        selection = self.insurance_tree.selection()
        if not selection:
            self.show_toast("Select a month row first.")
            return None
        values = self.insurance_tree.item(selection[0], "values")
        if not values or len(values) < 2:
            return None
        try:
            year = int(values[0])
            month = int(values[1])
        except (TypeError, ValueError):
            self.show_message("Insurance", "Invalid year/month selection.", kind="warning")
            return None
        return year, month

    def _mark_insurance_paid(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — insurance claims cannot be edited.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        period = self._get_selected_insurance_period()
        if not period:
            return
        year, month = period
        try:
            updated = db_storage.update_insurance_claims_paid(self.db_config, year, month, True)
        except Exception as exc:
            self.show_message("Insurance", f"Failed to mark paid:\n{exc}", kind="warning")
            return
        self.refresh_insurance_summary()
        self.insurance_status_var.set(f"Marked paid for {year}-{month:02d} ({updated} claims).")

    def _mark_insurance_unpaid(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — insurance claims cannot be edited.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        period = self._get_selected_insurance_period()
        if not period:
            return
        year, month = period
        try:
            updated = db_storage.update_insurance_claims_paid(self.db_config, year, month, False)
        except Exception as exc:
            self.show_message("Insurance", f"Failed to mark unpaid:\n{exc}", kind="warning")
            return
        self.refresh_insurance_summary()
        self.insurance_status_var.set(f"Marked unpaid for {year}-{month:02d} ({updated} claims).")

    def _set_insurance_paid_date(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — insurance claims cannot be edited.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        period = self._get_selected_insurance_period()
        if not period:
            return
        year, month = period
        date_text = simpledialog.askstring("Paid Date", "Paid Date (YYYY-MM-DD)", parent=self.root)
        if date_text is None:
            return
        date_text = date_text.strip()
        if not date_text:
            self.show_message("Insurance", "Paid date is required.", kind="warning")
            return
        try:
            paid_date = datetime.date.fromisoformat(date_text)
        except ValueError:
            self.show_message("Insurance", "Invalid date format. Use YYYY-MM-DD.", kind="warning")
            return
        try:
            updated = db_storage.update_insurance_claims_paid(self.db_config, year, month, True, paid_date)
        except Exception as exc:
            self.show_message("Insurance", f"Failed to set paid date:\n{exc}", kind="warning")
            return
        self.refresh_insurance_summary()
        self.insurance_status_var.set(f"Paid date set for {year}-{month:02d} ({updated} claims).")

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
        self._apply_kpi_totals(*totals)

    def _apply_kpi_totals(self, total_net, total_employee_ins, total_employer_ins):
        total_insurance = total_employee_ins + total_employer_ins
        total_employer_cost = total_net + total_employer_ins
        self.kpi_total_net_var.set(self._format_currency(total_net))
        self.kpi_employer_cost_var.set(self._format_currency(total_employer_cost))
        self.kpi_total_insurance_var.set(self._format_currency(total_insurance))

    def _build_kpi_card(self, parent, column, title, value_var, row=0, delta_var=None):
        """A KPI tile: caption, large value, optional coloured delta line."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        card.grid(row=row, column=column, sticky=(tk.W, tk.E), padx=6, pady=(0, 6) if row else 0)
        title_label = ttk.Label(card, text=title, style="CardTitle.TLabel")
        title_label.pack(anchor=tk.W)
        value_label = ttk.Label(card, textvariable=value_var, style="CardValue.TLabel")
        value_label.pack(anchor=tk.W, pady=(6, 0))
        widgets = [card, title_label, value_label]
        delta_label = None
        if delta_var is not None:
            delta_label = ttk.Label(card, textvariable=delta_var, style="CardDelta.TLabel")
            delta_label.pack(anchor=tk.W, pady=(2, 0))
            widgets.append(delta_label)
        for widget in widgets:
            widget.configure(cursor="hand2")
            widget.bind(
                "<Button-1>",
                lambda _event, var=value_var, label=title: self._copy_value_to_clipboard(var.get(), label=label),
            )
        return {"card": card, "value": value_label, "delta": delta_label}

    def _apply_mom_card(self, key, change, as_currency=True):
        """Fill a month-over-month card from a comparison dict."""
        value_text, delta_text, direction = self._comparison_parts(change, as_currency=as_currency)
        value_var, delta_var = {
            "net": (self.dashboard_mom_net_var, self.dashboard_mom_net_delta),
            "employer_cost": (self.dashboard_mom_employer_cost_var, self.dashboard_mom_employer_cost_delta),
            "insurance": (self.dashboard_mom_insurance_var, self.dashboard_mom_insurance_delta),
            "count": (self.dashboard_mom_count_var, self.dashboard_mom_count_delta),
        }[key]
        value_var.set(value_text)
        delta_var.set(delta_text)
        self._set_kpi_delta(self.dashboard_mom_cards.get(key), direction)

    def _set_kpi_delta(self, card, direction):
        """Colour a KPI's delta line by direction: 1 up, -1 down, 0 flat."""
        label = card.get("delta") if card else None
        if label is None:
            return
        label.configure(style={
            1: "CardDeltaUp.TLabel",
            -1: "CardDeltaDown.TLabel",
        }.get(direction, "CardDelta.TLabel"))

    def _copy_value_to_clipboard(self, value, label=None):
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            return
        if getattr(self, "status_var", None):
            previous = self.status_var.get()
            message = f"Copied {label}: {text}" if label else f"Copied {text}"
            self.update_status(message)
            self.root.after(2000, lambda: self.update_status(previous))

    def _format_currency(self, value):
        try:
            return f"€ {value:,.2f}"
        except Exception:
            return "€ 0.00"

    def _format_comparison(self, change, as_currency=True):
        """Render a period-over-period change as "current (±delta, ±pct)".

        A previous value of zero yields "n/a" for the percentage rather than a
        misleading infinity, and an absent change renders as an em dash.
        """
        if not change:
            return "—"
        current = change.get("current") or 0
        delta = change.get("delta") or 0
        pct = change.get("pct_change")
        if as_currency:
            current_text = self._format_currency(current)
            delta_text = f"{'+' if delta >= 0 else '−'}{abs(delta):,.2f}"
        else:
            current_text = f"{int(current)}"
            delta_text = f"{'+' if delta >= 0 else '−'}{abs(int(delta))}"
        if pct is None:
            pct_text = "n/a"
        else:
            pct_text = f"{'+' if pct >= 0 else '−'}{abs(pct):.1f}%"
        return f"{current_text}  ({delta_text}, {pct_text})"

    def _comparison_parts(self, change, as_currency=True):
        """Split a period-over-period change into (value, delta, direction).

        The KPI cards render the value large and the delta underneath in the
        colour of its direction: 1 for up, -1 for down, 0 for flat or unknown.
        """
        if not change:
            return "—", "", 0
        current = change.get("current") or 0
        delta = change.get("delta") or 0
        pct = change.get("pct_change")
        if as_currency:
            value_text = self._format_currency(current)
            delta_text = f"{'+' if delta >= 0 else '−'}{self._format_currency(abs(delta))}"
        else:
            value_text = f"{int(current)}"
            delta_text = f"{'+' if delta >= 0 else '−'}{abs(int(delta))}"
        if pct is None:
            delta_text = f"{delta_text} vs last month"
        else:
            delta_text = f"{delta_text}  ({'+' if pct >= 0 else '−'}{abs(pct):.1f}%)"
        if delta > 0:
            direction = 1
        elif delta < 0:
            direction = -1
        else:
            direction = 0
        return value_text, delta_text, direction

    def _annotate_change(self, ax, text, pct):
        """Corner annotation coloured by the direction of the change."""
        tokens = self.theme
        colour = tokens.positive if pct >= 0 else tokens.negative
        ax.text(
            0.98,
            0.95,
            text,
            transform=ax.transAxes,
            ha="right",
            va="top",
            color=colour,
            fontsize=10,
            fontweight="bold",
        )

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
                if self.analytics_grid_view_tab is not None:
                    self.notebook.select(self.analytics_grid_view_tab)
                if self.analytics_grid_tab is not None and hasattr(self, "analytics_grid_notebook"):
                    self.analytics_grid_notebook.select(self.analytics_grid_tab)
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
            self._open_employee_detail(employee_name=self.analytics_heatmap_employees[row], push_state=True)

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

    def _open_employee_detail(self, employee_code=None, employee_name=None, push_state=True, switch_tabs=True):
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
        self.analytics_detail_cache_columns = detail_columns
        self.analytics_detail_cache_rows = detail_rows
        self._apply_detail_column_filters()
        if switch_tabs:
            if self.analytics_grid_view_tab is not None:
                self.notebook.select(self.analytics_grid_view_tab)
            if self.analytics_detail_tab is not None and hasattr(self, "analytics_grid_notebook"):
                self.analytics_grid_notebook.select(self.analytics_detail_tab)
        self._refresh_kpis()

    def _plot_dashboard_summary(self, rows):
        chart = self.dashboard_chart["ax"]
        chart.clear()
        if not rows:
            self._empty_axes(chart, "Summary Trend", "Process a payroll ZIP to see the trend")
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
        chart.plot(labels, net_vals, marker="o", markersize=4, linewidth=2,
                   color=self._series_color(0), label="Net Pay")
        chart.plot(labels, employer_cost, marker="o", markersize=4, linewidth=2,
                   color=self._series_color(1), label="Employer Cost")
        chart.set_title("Summary Trend")
        chart.set_ylabel("Amount")
        chart.legend(frameon=True)
        self._style_axes(chart, currency=True, rotate=45)
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
        if self.analytics_grid_view_tab is not None:
            self.notebook.select(self.analytics_grid_view_tab)

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
        if self.analytics_grid_view_tab is not None:
            self.notebook.select(self.analytics_grid_view_tab)

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
            state["charts_tab"] = self.analytics_notebook.select()
        if hasattr(self, "analytics_grid_notebook"):
            state["grid_tab"] = self.analytics_grid_notebook.select()
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
            self.show_toast("Nothing to go back to.")
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
            charts_tab = state.get("charts_tab")
            if charts_tab and hasattr(self, "analytics_notebook"):
                try:
                    self.analytics_notebook.select(charts_tab)
                except tk.TclError:
                    pass
            grid_tab = state.get("grid_tab")
            if grid_tab and hasattr(self, "analytics_grid_notebook"):
                try:
                    self.analytics_grid_notebook.select(grid_tab)
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
        toolbar.columnconfigure(6, weight=1)

        ttk.Label(toolbar, text="Limit", style="Body.TLabel").grid(row=0, column=0, padx=(0, 6))
        self.analytics_grid_limit_var = tk.IntVar(value=500)
        limit_spin = ttk.Spinbox(toolbar, from_=50, to=5000, textvariable=self.analytics_grid_limit_var, width=6)
        limit_spin.grid(row=0, column=1, padx=(0, 10))
        limit_spin.bind("<Return>", self._on_grid_limit_change)
        limit_spin.bind("<<Increment>>", self._on_grid_limit_change)
        limit_spin.bind("<<Decrement>>", self._on_grid_limit_change)

        refresh_btn = ttk.Button(
            toolbar,
            text="Refresh Grid",
            command=self.refresh_data_grid,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=2, sticky=tk.W)
        self._add_tooltip(refresh_btn, "Reload data for the analytics grid.")

        columns_btn = ttk.Button(
            toolbar,
            text="Columns...",
            command=self.open_grid_column_selector,
            image=self.icons.get("columns_selector"),
            compound=tk.LEFT,
        )
        columns_btn.grid(row=0, column=3, padx=(10, 0), sticky=tk.W)
        self._add_tooltip(columns_btn, "Choose which columns are visible in the grid.")

        duplicates_btn = ttk.Button(
            toolbar,
            text="Duplicates...",
            command=self._open_duplicate_cleanup,
        )
        duplicates_btn.grid(row=0, column=4, padx=(10, 0), sticky=tk.W)
        self._add_tooltip(duplicates_btn, "Find and remove duplicate entries (same name/date/type/amount).")

        edit_btn = ttk.Button(
            toolbar,
            text="Edit Selected",
            command=self._open_grid_edit_modal,
            image=self.icons.get("edit"),
            compound=tk.LEFT,
        )
        edit_btn.grid(row=0, column=5, padx=(10, 0), sticky=tk.W)
        self._add_tooltip(edit_btn, "Edit the selected entry in the grid.")

        # Wrap rather than run off the toolbar: at narrower widths this hint was
        # clipped mid-word ("Search uses to").
        toolbar.columnconfigure(6, weight=1)
        ttk.Label(
            toolbar,
            text="Search uses top bar",
            style="Hint.TLabel",
            wraplength=130,
            justify=tk.LEFT,
        ).grid(row=0, column=6, sticky=tk.W, padx=(12, 0))

        grid_frame = ttk.Frame(parent, style="App.TFrame")
        grid_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.rowconfigure(0, weight=1)

        self.analytics_grid_tree = ttk.Treeview(grid_frame, columns=(), show="headings", selectmode=tk.EXTENDED)
        self.analytics_grid_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.analytics_grid_tree.bind("<Button-1>", self._on_grid_click)
        self.analytics_grid_tree.bind("<Double-1>", self._on_grid_double_click)
        self.analytics_grid_tree.bind("<Button-2>", self._on_grid_right_click)
        self.analytics_grid_tree.bind("<Button-3>", self._on_grid_right_click)
        self.analytics_grid_tree.bind("<Control-Button-1>", self._on_grid_right_click)
        self.analytics_grid_tree.bind("<<TreeviewSelect>>", self._on_grid_select)

        y_scroll = ttk.Scrollbar(grid_frame, orient=tk.VERTICAL, command=self.analytics_grid_tree.yview)
        y_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        x_scroll = ttk.Scrollbar(grid_frame, orient=tk.HORIZONTAL, command=self.analytics_grid_tree.xview)
        x_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.analytics_grid_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        parent.rowconfigure(1, weight=1)

        self.analytics_grid_menu = tk.Menu(self.root, tearoff=0)
        self.analytics_grid_menu.add_command(label="Edit", command=self._open_grid_edit_modal)
        self.analytics_grid_menu.add_command(label="Details", command=self._open_grid_selected_details)
        self.analytics_grid_menu.add_separator()
        self.analytics_grid_menu.add_command(label="Delete", command=self._delete_selected_entries)

    def refresh_data_grid(self):
        if not self.db_config.get("enabled"):
            self._database_notice(
                self.analytics_grid_view_tab,
                "The data grid lists stored payroll entries. Turn storage on to see them.",
            )
            return
        self._clear_database_notice(self.analytics_grid_view_tab)

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
        if isinstance(search, list):
            clauses = []
            for clause in search:
                term = self._normalize_text(clause.get("term", ""))
                if term:
                    clauses.append((str(clause.get("op", "AND")).upper(), term))
            if not clauses:
                return rows
            filtered = []
            for row in rows:
                row_cells = [self._normalize_text(cell) for cell in row]
                result = None
                for op, term in clauses:
                    match = any(term in cell for cell in row_cells)
                    if result is None:
                        result = match
                    elif op == "OR":
                        result = result or match
                    elif op == "NOT":
                        result = result and (not match)
                    else:
                        result = result and match
                if result:
                    filtered.append(row)
            return filtered
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
        start_date, end_date, document_type, search = self._get_global_filters()
        limit = max(int(self.analytics_grid_limit_var.get()), 1)
        total_rows = db_storage.fetch_payroll_entry_count(
            self.db_config,
            start_date=start_date,
            end_date=end_date,
            document_type=document_type,
            search=search,
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
            search=search,
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
        search = self._collect_search_clauses()
        filtered_rows = self._apply_search_filter(rows, search)
        self._reset_grid_treeview(columns, display_columns)
        display_rows = [self._format_grid_row(columns, row) for row in filtered_rows]
        self._populate_treeview(self.analytics_grid_tree, display_rows)
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
            self.analytics_grid_tree.column(col, width=width, anchor=tk.W, stretch=False)
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
        col_name = display_columns[col_index]
        self.last_grid_column = col_name
        if col_name != "paid_status":
            return
        if not self._can_edit():
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
            return
        row_id = self.analytics_grid_tree.identify_row(event.y)
        if not row_id:
            return
        columns = list(self.analytics_grid_tree["columns"])
        values = self.analytics_grid_tree.item(row_id, "values")
        entry_id = self._get_grid_value(values, columns, "entry_id")
        if entry_id is None:
            self.show_message("Edit Error", "Missing entry id for update.", kind="warning")
            return
        current = self._get_grid_value(values, columns, "paid_status")
        new_status = not self._normalize_paid_status(current)
        try:
            db_storage.update_payroll_entry(self.db_config, entry_id, "paid_status", new_status)
            db_storage.append_audit_log(self.db_config, entry_id, "paid_status", current, new_status)
            if new_status:
                actual_value = self._get_grid_value(values, columns, "paid_date")
                if self._is_empty_date(actual_value):
                    today = datetime.date.today()
                    db_storage.update_payroll_entry(self.db_config, entry_id, "paid_date", today)
                    db_storage.append_audit_log(self.db_config, entry_id, "paid_date", actual_value, today)
                    self.analytics_grid_tree.set(row_id, "paid_date", today)
                    self._update_grid_cache(entry_id, "paid_date", today)
        except Exception as exc:
            self.show_message("Edit Error", str(exc), kind="warning")
            return
        self.analytics_grid_tree.set(row_id, "paid_status", self._format_paid_status(new_status))
        self._update_grid_cache(entry_id, "paid_status", new_status)
        self._push_undo(entry_id, "paid_status", current, new_status)
        self._refresh_kpis()

    def _open_grid_selected_details(self):
        selection = self.analytics_grid_tree.selection()
        if not selection:
            self.show_toast("Select a row to view its details.")
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
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
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
        editable = {"document_type", "payment_date", "paid_date", "basic_salary", "total_earnings", "net_pay"}
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
        if col_name == "document_type":
            values = ["salary", "bonus", "vacation_allowance", "unused_leave_compensation", "other"]
            entry = ttk.Combobox(
                self.analytics_grid_tree,
                values=values,
                state="readonly",
            )
            entry.set(value)
            entry.bind("<<ComboboxSelected>>", lambda _event: self._commit_grid_edit())
        else:
            entry = ttk.Entry(self.analytics_grid_tree)
            entry.insert(0, value)
            entry.select_range(0, tk.END)
        entry.place(x=x, y=y, width=width, height=height)
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
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
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
            db_storage.update_payroll_entry(self.db_config, entry_id, col_name, normalized_value)
            db_storage.append_audit_log(self.db_config, entry_id, col_name, old_value, normalized_value)
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
        if col_name in {"payment_date", "paid_date"}:
            cleaned = value.replace("/", "-")
            try:
                parsed = datetime.date.fromisoformat(cleaned)
            except Exception:
                return False, value, "Use YYYY-MM-DD for dates."
            return True, parsed, ""
        if col_name == "document_type":
            canonical_types = {
                "salary": "Salary",
                "bonus": "Bonus",
                "vacationallowance": "VacationAllowance",
                "unusedleavecompensation": "UnusedLeaveCompensation",
                "payslip": "Payslip",
                "other": "Other",
            }
            normalized = re.sub(r"[\s_-]+", "", value).casefold()
            canonical = canonical_types.get(normalized)
            if canonical is None:
                allowed = sorted(canonical_types.values())
                return False, value, f"Document type must be one of: {', '.join(allowed)}."
            return True, canonical, ""
        if col_name == "paid_status":
            normalized = value.strip().lower()
            truthy = {"yes", "true", "1", "paid"}
            falsy = {"no", "false", "0", "unpaid"}
            if normalized in truthy:
                return True, True, ""
            if normalized in falsy:
                return True, False, ""
            return False, value, "Paid status must be Yes or No."
        return False, value, "This field cannot be edited."

    def _format_paid_status(self, value):
        return "Yes" if self._normalize_paid_status(value) else "No"

    def _normalize_paid_status(self, value):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "paid"}:
            return True
        if text in {"0", "false", "no", "unpaid", ""}:
            return False
        return False

    def _is_empty_date(self, value):
        if value is None:
            return True
        text = str(value).strip().lower()
        return text in {"", "none", "nat", "null"}

    def _normalize_pref_bool(self, value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        if value is None:
            return default
        return bool(value)

    def _format_grid_row(self, columns, row):
        if not columns or not row:
            return row
        row_list = list(row)
        try:
            idx = columns.index("paid_status")
        except ValueError:
            return row
        if idx < len(row_list):
            row_list[idx] = self._format_paid_status(row_list[idx])
        return tuple(row_list)

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
                "entry_id": entry_id,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
            }
        )
        self.edit_redo_stack.clear()

    def _undo_last_edit(self):
        if not self.edit_undo_stack:
            self.show_toast("Nothing to undo.")
            return
        if not self._can_edit():
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
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
            self.show_toast("Nothing to redo.")
            return
        if not self._can_edit():
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
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
                display_value = self._format_paid_status(value) if field == "paid_status" else value
                self.analytics_grid_tree.set(row_id, field, display_value)
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
        self.edit_lock_var.set(bool(prefs.get("edit_lock", True)))
        if "show_database_tab" in prefs:
            self.show_db_tab_var.set(self._normalize_pref_bool(prefs.get("show_database_tab"), True))
        if hasattr(self, "lock_canvas"):
            self._update_lock_indicator()
        watch_dir = prefs.get("watch_dir")
        if watch_dir:
            try:
                self.watch_dir = Path(watch_dir)
                self.watch_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        if "watch_enabled" in prefs:
            self.watch_enabled_var.set(self._normalize_pref_bool(prefs.get("watch_enabled"), False))
        if "watch_interval" in prefs:
            try:
                self.watch_interval_var.set(int(prefs.get("watch_interval")))
            except (TypeError, ValueError):
                pass
        geometry = prefs.get("window_geometry")
        if geometry:
            try:
                self.root.geometry(geometry)
            except tk.TclError:
                pass
        archive_dir = prefs.get("pdf_archive_dir")
        if archive_dir:
            try:
                self.archive_dir = Path(archive_dir)
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                self.archive_dir_custom = True
            except OSError:
                self.archive_dir_custom = False
        if "theme_mode" in prefs:
            self.theme_mode_var.set(prefs.get("theme_mode", self.theme_mode_var.get()))
        grid_columns = prefs.get("grid_columns")
        if isinstance(grid_columns, list):
            self.analytics_grid_columns = grid_columns
        detail_columns = prefs.get("detail_columns")
        if isinstance(detail_columns, list):
            self.analytics_detail_columns = detail_columns
        monthly_columns = prefs.get("monthly_columns")
        if isinstance(monthly_columns, list):
            self.analytics_monthly_columns = monthly_columns
        self._update_window_label()

    def _schedule_geometry_save(self, _event=None):
        if self._geometry_job is not None:
            try:
                self.root.after_cancel(self._geometry_job)
            except tk.TclError:
                pass
        self._geometry_job = self.root.after(500, self._save_window_geometry)

    def _save_window_geometry(self):
        self._geometry_job = None
        try:
            geometry = self.root.winfo_geometry()
        except tk.TclError:
            return
        self.window_geometry = geometry
        self._save_ui_prefs()

    def _set_active_view(self, view_name):
        tab_map = {
            "Dashboard": self.dashboard_tab,
            "Analytics Data Grid": self.analytics_grid_view_tab,
            "Analytics Graphs": self.analytics_tab,
            "Insurance": self.insurance_tab,
            "Employees": self.employees_tab,
            "Processing": self.processing_tab,
            "Database": self.db_tab,
            "Settings": self.settings_tab,
        }
        tab = tab_map.get(view_name)
        if tab is not None and str(tab) in self.notebook.tabs():
            self.notebook.select(tab)
        for name, btn in self.sidebar_buttons.items():
            btn.configure(style="SidebarActive.TButton" if name == view_name else "Sidebar.TButton")

    def _sync_view_selector(self, _event=None):
        current = self.notebook.select()
        if not current:
            return
        tab_map = {
            str(self.dashboard_tab): "Dashboard",
            str(self.analytics_grid_view_tab): "Analytics Data Grid",
            str(self.analytics_tab): "Analytics Graphs",
            str(self.insurance_tab): "Insurance",
            str(self.employees_tab): "Employees",
            str(self.processing_tab): "Processing",
            str(self.db_tab): "Database",
            str(self.settings_tab): "Settings",
        }
        label = tab_map.get(current)
        if label:
            self._set_active_view(label)
        self._refresh_active_view(current)

    def _refresh_active_view(self, current_tab=None):
        if current_tab is None:
            current_tab = self.notebook.select()
        if current_tab == str(self.dashboard_tab):
            self.refresh_dashboard()
        elif current_tab == str(self.analytics_tab):
            self.refresh_analytics()
        elif current_tab == str(self.analytics_grid_view_tab):
            self._on_analytics_grid_tab_change()
        elif current_tab == str(self.insurance_tab):
            self.refresh_insurance_summary()
        elif current_tab == str(self.employees_tab):
            self.refresh_employees_tab()
        elif current_tab == str(self.db_tab):
            self.refresh_db_views()
        elif current_tab == str(self.settings_tab):
            self._refresh_settings_labels()

    def _apply_database_tab_visibility(self):
        show = bool(self.show_db_tab_var.get())
        btn = self.sidebar_buttons.get("Database")
        if show:
            if btn and not btn.winfo_ismapped():
                btn.grid()
            if str(self.db_tab) not in self.notebook.tabs():
                self.notebook.insert(1, self.db_tab, text="Database")
        else:
            if btn and btn.winfo_ismapped():
                btn.grid_remove()
            if self.notebook.select() == str(self.db_tab):
                self._set_active_view("Dashboard")
            if str(self.db_tab) in self.notebook.tabs():
                self.notebook.forget(self.db_tab)

    def _toggle_database_tab(self):
        self._apply_database_tab_visibility()
        self._save_ui_prefs()

    def _toggle_watch_folder(self):
        if self.watch_enabled_var.get():
            self._prime_watch_seen()
            self._schedule_watch_poll()
        else:
            if self.watch_job is not None:
                try:
                    self.root.after_cancel(self.watch_job)
                except tk.TclError:
                    pass
                self.watch_job = None
        self._save_ui_prefs()

    def _open_grid_edit_modal(self):
        if not hasattr(self, "analytics_grid_tree"):
            return
        if not self._can_edit():
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
            return
        selection = self.analytics_grid_tree.selection()
        if not selection:
            self.show_toast("Select a row to edit.")
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
            "paid_status": current_value("paid_status"),
            "paid_date": current_value("paid_date") or "",
            "basic_salary": current_value("basic_salary") or "",
            "total_earnings": current_value("total_earnings") or "",
            "net_pay": current_value("net_pay") or "",
        }

        doc_var = tk.StringVar(value=original["document_type"])
        date_var = tk.StringVar(value=str(original["payment_date"]))
        paid_var = tk.StringVar(value="Yes" if str(original["paid_status"]).lower() in {"true", "yes", "1"} else "No")
        actual_date_var = tk.StringVar(value=str(original["paid_date"]))
        basic_var = tk.StringVar(value=str(original["basic_salary"]))
        total_var = tk.StringVar(value=str(original["total_earnings"]))
        net_var = tk.StringVar(value=str(original["net_pay"]))

        ttk.Label(frame, text="Document Type", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        doc_combo = ttk.Combobox(frame, textvariable=doc_var, state="readonly", width=24)
        doc_combo["values"] = ["salary", "bonus", "vacation_allowance", "unused_leave_compensation", "other"]
        doc_combo.grid(row=0, column=1, pady=(0, 6))

        ttk.Label(frame, text="Payment Date (YYYY-MM-DD)", style="Body.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=date_var, width=26).grid(row=1, column=1, pady=(0, 6))

        ttk.Label(frame, text="Paid", style="Body.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(0, 6))
        paid_combo = ttk.Combobox(frame, textvariable=paid_var, state="readonly", width=24)
        paid_combo["values"] = ["Yes", "No"]
        paid_combo.grid(row=2, column=1, pady=(0, 6))

        ttk.Label(frame, text="Paid Date (YYYY-MM-DD)", style="Body.TLabel").grid(row=3, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=actual_date_var, width=26).grid(row=3, column=1, pady=(0, 6))

        ttk.Label(frame, text="Basic Salary", style="Body.TLabel").grid(row=4, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=basic_var, width=26).grid(row=4, column=1, pady=(0, 6))

        ttk.Label(frame, text="Total Earnings", style="Body.TLabel").grid(row=5, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=total_var, width=26).grid(row=5, column=1, pady=(0, 6))

        ttk.Label(frame, text="Net Pay", style="Body.TLabel").grid(row=6, column=0, sticky=tk.W, pady=(0, 6))
        ttk.Entry(frame, textvariable=net_var, width=26).grid(row=6, column=1, pady=(0, 6))

        error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=error_var, style="Body.TLabel").grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(4, 8))

        def on_save():
            updates = {
                "document_type": doc_var.get().strip(),
                "payment_date": date_var.get().strip(),
                "paid_status": paid_var.get().strip(),
                "paid_date": actual_date_var.get().strip(),
                "basic_salary": basic_var.get().strip(),
                "total_earnings": total_var.get().strip(),
                "net_pay": net_var.get().strip(),
            }
            if updates["paid_status"].strip().lower() in {"yes", "true", "1", "paid"} and not updates["paid_date"].strip():
                updates["paid_date"] = datetime.date.today().isoformat()
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
                    db_storage.update_payroll_entry(self.db_config, entry_id, field, value)
                    db_storage.append_audit_log(self.db_config, entry_id, field, original.get(field), value)
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

    def _open_duplicate_cleanup(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — duplicate cleanup needs it.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        if not self._can_edit():
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
            return
        start_date, end_date, document_type, search = self._get_global_filters()
        try:
            columns, rows = db_storage.fetch_duplicate_payroll_entries(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search,
            )
        except Exception as exc:
            self.show_message("Duplicates Error", str(exc), kind="warning")
            return
        if not rows:
            self.show_toast("No duplicate entries found with the current filters.", kind="success")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Duplicate Cleanup")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.rowconfigure(1, weight=1)
        dialog.columnconfigure(0, weight=1)

        index = {name: idx for idx, name in enumerate(columns)}
        group_map = {}
        for row in rows:
            key = (
                row[index["employee_name"]],
                row[index["payment_date"]],
                row[index["document_type"]],
                row[index["net_pay"]],
            )
            if key not in group_map:
                group_map[key] = len(group_map) + 1

        header_text = f"Found {len(rows)} duplicate entries across {len(group_map)} groups."
        ttk.Label(dialog, text=header_text, style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, padx=12, pady=(12, 6))

        frame = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        tree_columns = ["group", "employee_name", "payment_date", "document_type", "net_pay", "source_pdf", "entry_id"]
        display_columns = ["group", "employee_name", "payment_date", "document_type", "net_pay", "source_pdf"]
        tree = ttk.Treeview(frame, columns=tree_columns, show="headings", selectmode=tk.EXTENDED)
        tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree["displaycolumns"] = display_columns

        tree.heading("group", text="Group")
        tree.heading("employee_name", text="Name")
        tree.heading("payment_date", text="Date")
        tree.heading("document_type", text="Type")
        tree.heading("net_pay", text="Amount")
        tree.heading("source_pdf", text="Source PDF")

        tree.column("group", width=80, anchor=tk.W, stretch=False)
        tree.column("employee_name", width=220, anchor=tk.W, stretch=True)
        tree.column("payment_date", width=110, anchor=tk.W, stretch=False)
        tree.column("document_type", width=140, anchor=tk.W, stretch=False)
        tree.column("net_pay", width=120, anchor=tk.E, stretch=False)
        tree.column("source_pdf", width=360, anchor=tk.W, stretch=True)
        tree.column("entry_id", width=0, stretch=False)

        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        y_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        x_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        for row in rows:
            name = row[index["employee_name"]]
            pay_date = row[index["payment_date"]]
            doc_type = row[index["document_type"]]
            net_pay = row[index["net_pay"]]
            source_pdf = row[index["source_pdf"]]
            entry_id = row[index["entry_id"]]
            key = (name, pay_date, doc_type, net_pay)
            group_label = f"Group {group_map[key]}"
            date_text = pay_date.strftime("%Y-%m-%d") if hasattr(pay_date, "strftime") else str(pay_date or "")
            amount_text = self._format_currency(net_pay if net_pay is not None else 0)
            tree.insert(
                "",
                tk.END,
                values=(group_label, name, date_text, doc_type, amount_text, source_pdf, entry_id),
            )

        def select_duplicates():
            tree.selection_remove(tree.selection())
            groups = {}
            for item in tree.get_children():
                group = tree.set(item, "group")
                groups.setdefault(group, []).append(item)
            for items in groups.values():
                for item in items[1:]:
                    tree.selection_add(item)

        def delete_selected():
            selection = tree.selection()
            if not selection:
                self.show_toast("Select one or more duplicate rows to delete.")
                return
            entry_ids = [tree.set(item, "entry_id") for item in selection if tree.set(item, "entry_id")]
            if not entry_ids:
                self.show_message("Duplicates", "Selected rows are missing entry ids.", kind="warning")
                return
            if not messagebox.askyesno("Delete Duplicates", f"Delete {len(entry_ids)} selected entries?"):
                return
            try:
                deleted = db_storage.delete_payroll_entries(self.db_config, entry_ids)
            except Exception as exc:
                self.show_message("Delete Error", str(exc), kind="warning")
                return
            self.show_toast(f"Deleted {deleted} entries.", kind="success")
            dialog.destroy()
            self._refresh_all_views()

        button_frame = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        button_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        button_frame.columnconfigure(0, weight=1)
        ttk.Button(button_frame, text="Select All But First", command=select_duplicates).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(button_frame, text="Delete Selected", command=delete_selected).grid(row=0, column=1, padx=(10, 0), sticky=tk.W)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).grid(row=0, column=2, padx=(10, 0), sticky=tk.E)

    def _build_detail_tab(self, parent):
        header = ttk.Frame(parent, style="App.TFrame")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        header.columnconfigure(2, weight=1)

        ttk.Label(header, text="Employee Detail", style="Section.TLabel").grid(row=0, column=0, padx=(0, 10))
        columns_btn = ttk.Button(
            header,
            text="Columns...",
            command=self.open_detail_column_selector,
            image=self.icons.get("columns_selector"),
            compound=tk.LEFT,
        )
        columns_btn.grid(row=0, column=1, padx=(0, 10))
        self._add_tooltip(columns_btn, "Choose which columns are visible in Employee Detail.")

        self.analytics_detail_label_var = tk.StringVar(value="Select an employee from the Data Grid.")
        ttk.Label(header, textvariable=self.analytics_detail_label_var, style="Body.TLabel").grid(row=0, column=2, sticky=tk.W)
        self.analytics_detail_total_var = tk.StringVar(value="")
        self.analytics_detail_total_label = ttk.Label(
            header,
            textvariable=self.analytics_detail_total_var,
            style="Body.TLabel",
        )
        self.analytics_detail_total_label.grid(row=0, column=3, sticky=tk.E)
        self.analytics_detail_total_label.configure(cursor="hand2")
        self.analytics_detail_total_label.bind(
            "<Button-1>",
            lambda _event: self._copy_value_to_clipboard(self.analytics_detail_total_var.get(), label="Total Net Pay"),
        )

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
            self.show_toast("Refresh the grid first to load its columns.")
            return
        selected = set(self.analytics_grid_columns or available)
        self._open_column_selector_dialog(
            "Select Columns",
            available,
            selected,
            self._apply_grid_column_selection,
        )

    def open_detail_column_selector(self):
        if not self.analytics_detail_cache_columns:
            self.show_toast("Select an employee first.")
            return
        available = list(self.analytics_detail_cache_columns)
        selected = set(self.analytics_detail_columns or available)
        self._open_column_selector_dialog(
            "Select Detail Columns",
            available,
            selected,
            self._apply_detail_column_selection,
        )

    def open_monthly_column_selector(self):
        if not self.analytics_monthly_cache_columns:
            self.show_toast("Refresh the summary first to load its columns.")
            return
        available = list(self.analytics_monthly_cache_columns)
        selected = set(self.analytics_monthly_columns or available)
        self._open_column_selector_dialog(
            "Select Summary Columns",
            available,
            selected,
            self._apply_monthly_column_selection,
        )

    def _open_column_selector_dialog(self, title, available, selected, on_apply):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
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

        def on_apply_click():
            chosen = [col for col in available if vars_by_col[col].get()]
            if not chosen:
                self.show_message("Columns", "Select at least one column.", kind="warning")
                return
            on_apply(chosen)
            self._save_ui_prefs()
            dialog.destroy()

        ttk.Button(button_frame, text="Apply", command=on_apply_click).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def _apply_grid_column_selection(self, chosen):
        self.analytics_grid_columns = chosen
        self._filter_grid_columns()

    def _apply_detail_column_selection(self, chosen):
        self.analytics_detail_columns = chosen
        self._apply_detail_column_filters()

    def _apply_monthly_column_selection(self, chosen):
        self.analytics_monthly_columns = chosen
        self._apply_monthly_column_filters()

    def _filter_grid_columns(self):
        if not hasattr(self, "analytics_grid_columns"):
            return
        self._apply_grid_filters_from_cache()

    def _apply_detail_column_filters(self):
        columns = self.analytics_detail_cache_columns
        rows = self.analytics_detail_cache_rows
        selected = self.analytics_detail_columns or list(columns)
        self._apply_tree_column_filters(self.analytics_detail_tree, columns, rows, selected)

    def _apply_monthly_column_filters(self):
        columns = self.analytics_monthly_cache_columns
        rows = self.analytics_monthly_cache_rows
        selected = self.analytics_monthly_columns or list(columns)
        self._apply_tree_column_filters(self.analytics_monthly_tree, columns, rows, selected)

    def _apply_tree_column_filters(self, tree, columns, rows, selected):
        if not columns:
            return
        indices = [columns.index(col) for col in selected if col in columns]
        display_columns = [columns[idx] for idx in indices]
        display_rows = [tuple(row[idx] for idx in indices) for row in rows]
        self._reset_treeview(tree, display_columns)
        self._populate_treeview(tree, display_rows)
        for col in display_columns:
            tree.heading(col, text=col, command=lambda c=col, t=tree: self._sort_treeview(t, c, False))

    def export_active_grid_csv(self):
        tree = self._get_active_analytics_tree()
        if tree is None:
            self.show_toast("Select a data grid tab to export.")
            return
        self._export_tree_csv(tree, title="Export Data Grid")

    def export_active_grid_xlsx(self):
        tree = self._get_active_analytics_tree()
        if tree is None:
            self.show_toast("Select a data grid tab to export.")
            return
        self._export_tree_xlsx(tree, title="Export Data Grid")

    def export_active_grid_pdf(self):
        tree = self._get_active_analytics_tree()
        if tree is None:
            self.show_toast("Select a data grid tab to export.")
            return
        self._export_tree_pdf(tree, title="Export Data Grid")

    def _export_tree_csv(self, tree, title="Export Data Grid"):
        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        columns, rows, meta_lines, totals_row = self._prepare_export_payload(tree)
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                for label, value in meta_lines:
                    writer.writerow([label, value])
                if meta_lines:
                    writer.writerow([])
                writer.writerow(columns)
                writer.writerows(rows)
                if totals_row:
                    writer.writerow(totals_row)
            self.show_toast(f"CSV exported to {Path(path).name}", kind="success",
                            action_text="Show in Finder", action=lambda: self.reveal_in_finder(path))
        except Exception as exc:
            self.show_message("Export Error", str(exc), kind="warning")

    def _export_tree_xlsx(self, tree, title="Export Data Grid"):
        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if not path:
            return
        columns, rows, meta_lines, totals_row = self._prepare_export_payload(tree)
        try:
            df = pd.DataFrame(rows, columns=columns)
            with pd.ExcelWriter(
                path,
                engine="xlsxwriter",
                engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
            ) as writer:
                start_row = len(meta_lines) + (1 if meta_lines else 0)
                df.to_excel(writer, index=False, sheet_name="Export", startrow=start_row)
                worksheet = writer.sheets["Export"]
                if meta_lines:
                    meta_fmt = writer.book.add_format({"italic": True})
                    for idx, (label, value) in enumerate(meta_lines):
                        worksheet.write(idx, 0, label, meta_fmt)
                        worksheet.write(idx, 1, value, meta_fmt)
                if totals_row:
                    total_row_idx = start_row + 1 + len(df)
                    total_fmt = writer.book.add_format({"bold": True})
                    for col_idx, value in enumerate(totals_row):
                        worksheet.write(total_row_idx, col_idx, value, total_fmt)
            self.show_toast(f"XLSX exported to {Path(path).name}", kind="success",
                            action_text="Show in Finder", action=lambda: self.reveal_in_finder(path))
        except Exception as exc:
            self.show_message("Export Error", str(exc), kind="warning")

    def _export_tree_pdf(self, tree, title="Export Data Grid"):
        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        columns, rows, meta_lines, totals_row = self._prepare_export_payload(tree)
        try:
            self._write_pdf_report(path, title, columns, rows, meta_lines, totals_row)
            self.show_toast(f"PDF exported to {Path(path).name}", kind="success",
                            action_text="Show in Finder", action=lambda: self.reveal_in_finder(path))
        except Exception as exc:
            self.show_message("Export Error", str(exc), kind="warning")

    def _write_pdf_report(self, path, title, columns, rows, meta_lines, totals_row):
        if totals_row:
            rows = list(rows) + [totals_row]
        from matplotlib.backends.backend_pdf import PdfPages
        rows_per_page = 25
        with PdfPages(path) as pdf:
            total_pages = max(1, math.ceil(len(rows) / rows_per_page)) if rows else 1
            for page_index in range(total_pages):
                start = page_index * rows_per_page
                end = start + rows_per_page
                page_rows = rows[start:end]
                fig, ax = plt.subplots(figsize=(11.69, 8.27))
                ax.axis("off")
                wrapped_headers, wrapped_rows, col_widths = self._wrap_export_table(columns, page_rows)
                table = ax.table(
                    cellText=wrapped_rows,
                    colLabels=wrapped_headers,
                    loc="center",
                    cellLoc="left",
                    bbox=[0.0, 0.08, 0.99, 0.74] if meta_lines else [0.0, 0.02, 0.99, 0.9],
                )
                table.auto_set_font_size(False)
                table.set_fontsize(7)
                table.scale(1.0, 1.4)
                for col_idx, width in enumerate(col_widths):
                    for row_idx in range(len(page_rows) + 1):
                        cell = table[(row_idx, col_idx)]
                        cell.set_width(width)
                for (row_idx, _), cell in table.get_celld().items():
                    if row_idx == 0:
                        cell.get_text().set_fontweight("bold")
                    elif row_idx > 0 and page_rows[row_idx - 1][0] == "TOTAL":
                        cell.get_text().set_fontweight("bold")
                ax.set_title(f"{title} (Page {page_index + 1} of {total_pages})", pad=12)
                if meta_lines:
                    meta_text = "\n".join([f"{label}: {value}" for label, value in meta_lines])
                    fig.text(0.02, 0.98, meta_text, ha="left", va="top", fontsize=9)
                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)

    def _prepare_export_payload(self, tree):
        columns, rows = self._collect_tree_export_data(tree)
        meta_lines = self._build_export_meta()
        totals_row = self._build_export_totals(columns, rows)
        return columns, rows, meta_lines, totals_row

    def _collect_tree_export_data(self, tree):
        columns = list(tree["columns"])
        selection = tree.selection()
        if selection:
            rows = [tree.item(k, "values") for k in selection]
        else:
            rows = [tree.item(k, "values") for k in tree.get_children("")]
        return columns, rows

    def _build_export_meta(self):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timeframe = self.global_window_label_var.get() or "All months"
        if timeframe == "All months":
            start_date, end_date, _, _ = self._get_global_filters()
            if start_date and end_date:
                timeframe = f"{start_date:%b %Y} → {end_date:%b %Y}"
        employee = "All employees"
        if self.analytics_selected_employee_name and self.analytics_selected_employee_code:
            employee = f"{self.analytics_selected_employee_name} ({self.analytics_selected_employee_code})"
        elif self.analytics_selected_employee_name:
            employee = self.analytics_selected_employee_name
        elif self.analytics_selected_employee_code:
            employee = self.analytics_selected_employee_code
        return [
            ("Exported", timestamp),
            ("Timeframe", timeframe),
            ("Employee", employee),
        ]

    def _build_export_totals(self, columns, rows):
        if not rows or not columns:
            return None
        totals = {}
        for col in columns:
            if self._should_total_column(col):
                totals[col] = 0.0
        if not totals:
            return None
        for row in rows:
            for col_idx, col in enumerate(columns):
                if col not in totals:
                    continue
                value = self._parse_numeric(row[col_idx])
                if value is not None:
                    totals[col] += value
        totals_row = [""] * len(columns)
        totals_row[0] = "TOTAL"
        for col_idx, col in enumerate(columns):
            if col in totals:
                totals_row[col_idx] = f"{totals[col]:.2f}"
        return totals_row

    def _wrap_export_table(self, columns, rows):
        max_chars_total = 140
        max_col_chars = 28
        min_col_chars = 8
        lengths = []
        for col_idx, col in enumerate(columns):
            max_len = len(str(col))
            for row in rows:
                if col_idx < len(row):
                    max_len = max(max_len, len(str(row[col_idx])))
            lengths.append(max(min_col_chars, min(max_len, max_col_chars)))
        total_len = max(1, sum(lengths))
        col_widths = [length / total_len for length in lengths]
        wrapped_headers = []
        wrapped_rows = []
        for col_idx, col in enumerate(columns):
            max_chars = max(min_col_chars, int(max_chars_total * col_widths[col_idx]))
            wrapped_headers.append(textwrap.fill(str(col), width=max_chars))
        for row in rows:
            wrapped_row = []
            for col_idx, value in enumerate(row):
                max_chars = max(min_col_chars, int(max_chars_total * col_widths[col_idx]))
                wrapped_row.append(textwrap.fill(str(value), width=max_chars))
            wrapped_rows.append(wrapped_row)
        return wrapped_headers, wrapped_rows, col_widths

    def _should_total_column(self, column_name):
        name = column_name.lower()
        skip_tokens = ("date", "id", "code", "month", "year", "type", "name", "source", "basic_salary", "basic salary")
        if any(token in name for token in skip_tokens):
            return False
        return True

    def _parse_numeric(self, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text or text in {"—", "-", "None"}:
            return None
        for symbol in ("€", "$"):
            text = text.replace(symbol, "")
        text = text.replace(" ", "")
        comma_count = text.count(",")
        dot_count = text.count(".")
        if comma_count and dot_count:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif comma_count == 1:
            whole, fractional = text.split(",", 1)
            whole_digits = whole.lstrip("+-")
            if whole_digits != "0" and whole_digits.isdigit() and len(fractional) == 3 and fractional.isdigit():
                text = whole + fractional
            else:
                text = whole + "." + fractional
        elif comma_count > 1:
            groups = text.split(",")
            if not groups[0].lstrip("+-").isdigit() or not all(
                group.isdigit() and len(group) == 3 for group in groups[1:]
            ):
                return None
            text = "".join(groups)
        elif dot_count > 1:
            groups = text.split(".")
            if not groups[0].lstrip("+-").isdigit() or not all(
                group.isdigit() and len(group) == 3 for group in groups[1:]
            ):
                return None
            text = "".join(groups)
        try:
            return float(text)
        except ValueError:
            return None

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
        self.analytics_selected_employee_code = employee_code
        self.analytics_selected_employee_name = employee_name
        current = self.analytics_grid_notebook.select() if hasattr(self, "analytics_grid_notebook") else None
        if current == str(getattr(self, "analytics_detail_tab", "")):
            self._open_employee_detail(
                employee_code=employee_code,
                employee_name=employee_name,
                push_state=False,
                switch_tabs=False,
            )
        else:
            self._refresh_kpis()

    def _get_active_analytics_tree(self):
        if not hasattr(self, "analytics_grid_notebook"):
            return None
        current = self.analytics_grid_notebook.select()
        if hasattr(self, "analytics_grid_tab") and str(self.analytics_grid_tab) == current:
            return getattr(self, "analytics_grid_tree", None)
        if hasattr(self, "analytics_detail_tab") and str(self.analytics_detail_tab) == current:
            return getattr(self, "analytics_detail_tree", None)
        if hasattr(self, "analytics_monthly_tab") and str(self.analytics_monthly_tab) == current:
            return getattr(self, "analytics_monthly_tree", None)
        return None

    def _on_analytics_grid_tab_change(self, _event=None):
        current = self.analytics_grid_notebook.select()
        if current == str(getattr(self, "analytics_grid_tab", "")):
            self.refresh_data_grid()
        elif current == str(getattr(self, "analytics_monthly_tab", "")):
            self.refresh_monthly_employee_summary()
        elif current == str(getattr(self, "analytics_detail_tab", "")):
            if self.analytics_selected_employee_code or self.analytics_selected_employee_name:
                self._open_employee_detail(
                    employee_code=self.analytics_selected_employee_code,
                    employee_name=self.analytics_selected_employee_name,
                    push_state=False,
                    switch_tabs=False,
                )

    def _cycle_analytics_grid_tab(self, event):
        if not hasattr(self, "analytics_grid_notebook"):
            return
        tabs = [
            getattr(self, "analytics_grid_tab", None),
            getattr(self, "analytics_detail_tab", None),
            getattr(self, "analytics_monthly_tab", None),
        ]
        tabs = [tab for tab in tabs if tab is not None]
        if not tabs:
            return
        current = self.analytics_grid_notebook.select()
        try:
            idx = tabs.index(self.analytics_grid_notebook.nametowidget(current))
        except Exception:
            idx = 0
        step = -1 if event.keysym == "Left" else 1
        next_idx = (idx + step) % len(tabs)
        self.analytics_grid_notebook.select(tabs[next_idx])
        return "break"

    def _delete_selected_entries(self):
        if not self._can_edit():
            self.show_toast("Editing is disabled in viewer mode.", kind="warning")
            return
        if not hasattr(self, "analytics_grid_tree"):
            return
        selection = self.analytics_grid_tree.selection()
        if not selection:
            self.show_toast("Select one or more rows to delete.")
            return
        columns = list(self.analytics_grid_tree["columns"])
        if "entry_id" not in columns:
            self.show_message("Delete", "Missing entry ids in the data grid.", kind="warning")
            return
        entry_ids = []
        for row_id in selection:
            values = self.analytics_grid_tree.item(row_id, "values")
            entry_id = self._get_grid_value(values, columns, "entry_id")
            if entry_id is not None:
                entry_ids.append(entry_id)
        if not entry_ids:
            self.show_message("Delete", "Selected rows are missing entry ids.", kind="warning")
            return
        if not messagebox.askyesno("Delete Entries", f"Delete {len(entry_ids)} selected entries?"):
            return
        try:
            deleted = db_storage.delete_payroll_entries(self.db_config, entry_ids)
        except Exception as exc:
            self.show_message("Delete Error", str(exc), kind="warning")
            return
        self.show_toast(f"Deleted {deleted} entries.", kind="success")
        self._refresh_all_views()

    def create_dashboard_tab(self):
        """Create the dashboard tab with current metrics."""
        self.dashboard_tab.columnconfigure(0, weight=1)
        self.dashboard_tab.rowconfigure(2, weight=1)

        header = ttk.Frame(self.dashboard_tab, style="App.TFrame")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        header.columnconfigure(6, weight=1)

        ttk.Label(header, text="Dashboard", style="Header.TLabel").grid(row=0, column=0, padx=(0, 10))
        refresh_btn = ttk.Button(
            header,
            text="Refresh",
            command=self.refresh_dashboard,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=1, padx=(0, 10))
        self._add_tooltip(refresh_btn, "Refresh dashboard metrics and alerts.")

        self.dashboard_status_var = tk.StringVar(value="Ready.")
        ttk.Label(header, textvariable=self.dashboard_status_var, style="Body.TLabel").grid(row=0, column=2, sticky=tk.W)

        cards_frame = ttk.Frame(self.dashboard_tab, style="App.TFrame")
        cards_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        for idx in range(4):
            cards_frame.columnconfigure(idx, weight=1)
        cards_frame.rowconfigure(1, weight=0)

        self.dashboard_total_net_var = tk.StringVar(value="—")
        self.dashboard_employer_cost_var = tk.StringVar(value="—")
        self.dashboard_total_insurance_var = tk.StringVar(value="—")
        self.dashboard_employee_count_var = tk.StringVar(value="—")
        self.dashboard_unpaid_last_month_var = tk.StringVar(value="—")
        self.dashboard_unpaid_current_month_var = tk.StringVar(value="—")
        self.dashboard_unpaid_current_year_var = tk.StringVar(value="—")

        self._build_kpi_card(cards_frame, 0, "Total Net Pay", self.dashboard_total_net_var)
        self._build_kpi_card(cards_frame, 1, "Employer Cost", self.dashboard_employer_cost_var)
        self._build_kpi_card(cards_frame, 2, "Total Insurance", self.dashboard_total_insurance_var)
        self._build_kpi_card(cards_frame, 3, "Employees", self.dashboard_employee_count_var)
        self.dashboard_mom_net_var = tk.StringVar(value="—")
        self.dashboard_mom_employer_cost_var = tk.StringVar(value="—")
        self.dashboard_mom_insurance_var = tk.StringVar(value="—")
        self.dashboard_mom_count_var = tk.StringVar(value="—")
        # The month-over-month cards show the value large and the change
        # underneath, coloured by direction, instead of one long line.
        self.dashboard_mom_net_delta = tk.StringVar(value="")
        self.dashboard_mom_employer_cost_delta = tk.StringVar(value="")
        self.dashboard_mom_insurance_delta = tk.StringVar(value="")
        self.dashboard_mom_count_delta = tk.StringVar(value="")

        self._build_kpi_card(cards_frame, 0, "Unpaid (Last Month)", self.dashboard_unpaid_last_month_var, row=1)
        self._build_kpi_card(cards_frame, 1, "Unpaid (Current Month)", self.dashboard_unpaid_current_month_var, row=1)
        self._build_kpi_card(cards_frame, 2, "Unpaid (Current Year)", self.dashboard_unpaid_current_year_var, row=1)
        self.dashboard_mom_cards = {
            "net": self._build_kpi_card(
                cards_frame, 0, "Net Pay vs Last Month", self.dashboard_mom_net_var,
                row=2, delta_var=self.dashboard_mom_net_delta,
            ),
            "employer_cost": self._build_kpi_card(
                cards_frame, 1, "Employer Cost vs Last Month", self.dashboard_mom_employer_cost_var,
                row=2, delta_var=self.dashboard_mom_employer_cost_delta,
            ),
            "insurance": self._build_kpi_card(
                cards_frame, 2, "Insurance vs Last Month", self.dashboard_mom_insurance_var,
                row=2, delta_var=self.dashboard_mom_insurance_delta,
            ),
            "count": self._build_kpi_card(
                cards_frame, 3, "Employees vs Last Month", self.dashboard_mom_count_var,
                row=2, delta_var=self.dashboard_mom_count_delta,
            ),
        }

        content_frame = ttk.Frame(self.dashboard_tab, style="App.TFrame")
        content_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        content_frame.columnconfigure(0, weight=3)
        # The matplotlib canvas claims width aggressively, which squeezed this
        # column until "Latest Entries" was clipped mid-word. A floor keeps the
        # headings and tree readable at any window size.
        content_frame.columnconfigure(1, weight=2, minsize=280)
        content_frame.rowconfigure(0, weight=1)

        chart_frame = ttk.Frame(content_frame, style="App.TFrame")
        chart_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 12))
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(0, weight=1)

        # Constrained layout re-solves on every resize. tight_layout() only runs
        # at draw time, so once the canvas shrank to fit the frame the title was
        # left outside the axes area and clipped.
        fig = Figure(figsize=(8, 4), dpi=100, layout="constrained")
        ax = fig.add_subplot(1, 1, 1)
        canvas = FigureCanvasTkAgg(fig, master=chart_frame)
        # Pack the toolbar first. Tk hands out space in pack order, so an
        # expanding canvas packed ahead of it claimed the frame and left the
        # toolbar nothing - the chart then overflowed and clipped its own title.
        toolbar = NavigationToolbar2Tk(canvas, chart_frame)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.dashboard_chart = {"fig": fig, "ax": ax, "canvas": canvas, "toolbar": toolbar}
        canvas.mpl_connect("button_press_event", self._on_dashboard_chart_click)

        anomalies_frame = ttk.Frame(content_frame, style="App.TFrame")
        anomalies_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        anomalies_frame.columnconfigure(0, weight=1)
        anomalies_frame.rowconfigure(1, weight=1)
        anomalies_frame.rowconfigure(4, weight=1)

        ttk.Label(anomalies_frame, text="Alerts", style="Section.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        self.dashboard_anomaly_tree = ttk.Treeview(anomalies_frame, columns=(), show="headings", height=8)
        self.dashboard_anomaly_tree.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.dashboard_anomaly_tree.bind("<<TreeviewSelect>>", self._on_dashboard_anomaly_select)
        self._add_tooltip(self.dashboard_anomaly_tree, "Alerts for unusual entries. Click to drill into details.")

        y_scroll = ttk.Scrollbar(anomalies_frame, orient=tk.VERTICAL, command=self.dashboard_anomaly_tree.yview)
        y_scroll.grid(row=1, column=1, sticky=(tk.N, tk.S))
        x_scroll = ttk.Scrollbar(anomalies_frame, orient=tk.HORIZONTAL, command=self.dashboard_anomaly_tree.xview)
        x_scroll.grid(row=2, column=0, sticky=(tk.W, tk.E))
        self.dashboard_anomaly_tree.configure(yscrollcommand=y_scroll.set)
        self.dashboard_anomaly_tree.configure(xscrollcommand=x_scroll.set)

        ttk.Label(anomalies_frame, text="Latest Entries", style="Section.TLabel").grid(row=3, column=0, sticky=tk.W, pady=(12, 6))
        self.dashboard_recent_tree = ttk.Treeview(anomalies_frame, columns=(), show="headings", height=8)
        self.dashboard_recent_tree.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.dashboard_recent_tree.bind("<<TreeviewSelect>>", self._on_dashboard_recent_select)
        self._add_tooltip(self.dashboard_recent_tree, "Latest payroll entries. Click to view details.")
        recent_scroll = ttk.Scrollbar(anomalies_frame, orient=tk.VERTICAL, command=self.dashboard_recent_tree.yview)
        recent_scroll.grid(row=4, column=1, sticky=(tk.N, tk.S))
        recent_x_scroll = ttk.Scrollbar(anomalies_frame, orient=tk.HORIZONTAL, command=self.dashboard_recent_tree.xview)
        recent_x_scroll.grid(row=5, column=0, sticky=(tk.W, tk.E))
        self.dashboard_recent_tree.configure(yscrollcommand=recent_scroll.set, xscrollcommand=recent_x_scroll.set)

    def refresh_dashboard(self):
        """Reload dashboard metrics, alerts and trend, off the UI thread."""
        if not self.db_config.get("enabled"):
            self.dashboard_status_var.set("Database storage is disabled.")
            self._database_notice(
                self.dashboard_tab,
                "KPIs, alerts and trends are read from stored payroll entries. "
                "Turn storage on, then process a payroll ZIP.",
            )
            # Without this the canvas keeps matplotlib's default 0.0-1.0 axes,
            # which look like a broken chart rather than an empty one.
            self._plot_dashboard_summary([])
            return
        self._clear_database_notice(self.dashboard_tab)

        self.dashboard_status_var.set("Refreshing…")
        try:
            self._refresh_global_filters()
            filters = self._get_global_filters()
        except Exception as exc:
            self.dashboard_status_var.set("Refresh failed.")
            self.show_message("Dashboard Error", str(exc), kind="warning")
            return

        self._run_async(
            "dashboard",
            lambda: self._fetch_dashboard_data(filters),
            self._render_dashboard,
            on_error=self._dashboard_failed,
        )

    def _fetch_dashboard_data(self, filters):
        """Every query the dashboard needs. Runs on a worker thread."""
        start_date, end_date, document_type, search = filters
        today = datetime.date.today()
        current_month_start = datetime.date(today.year, today.month, 1)
        current_month_end = datetime.date(
            today.year, today.month, calendar.monthrange(today.year, today.month)[1]
        )
        last_month_end = current_month_start - datetime.timedelta(days=1)
        last_month_start = datetime.date(last_month_end.year, last_month_end.month, 1)
        current_year_start = datetime.date(today.year, 1, 1)
        current_year_end = datetime.date(today.year, 12, 31)

        anomaly_columns, anomaly_rows = db_storage.fetch_anomaly_entries(
            self.db_config,
            start_date=start_date,
            end_date=end_date,
            document_type=document_type,
            search=search or None,
            limit=20,
        )
        recent_columns, recent_rows = db_storage.fetch_recent_entries(
            self.db_config,
            start_date=start_date,
            end_date=end_date,
            document_type=document_type,
            search=search or None,
            limit=20,
        )
        return {
            "metrics": db_storage.fetch_dashboard_metrics(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "unpaid_last_month": db_storage.fetch_unpaid_amount(
                self.db_config,
                start_date=last_month_start,
                end_date=last_month_end,
                document_type=document_type,
            ),
            "unpaid_current_month": db_storage.fetch_unpaid_amount(
                self.db_config,
                start_date=current_month_start,
                end_date=current_month_end,
                document_type=document_type,
            ),
            "unpaid_current_year": db_storage.fetch_unpaid_amount(
                self.db_config,
                start_date=current_year_start,
                end_date=current_year_end,
                document_type=document_type,
            ),
            "comparison": db_storage.fetch_period_comparison(
                self.db_config,
                year=today.year,
                month=today.month,
                document_type=document_type,
                search=search or None,
            ),
            "monthly_rows": db_storage.fetch_monthly_summary(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "anomaly_columns": anomaly_columns,
            "anomaly_rows": list(anomaly_rows),
            "jump_rows": self._fetch_jump_alerts(
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search or None,
            ),
            "recent_columns": recent_columns,
            "recent_rows": recent_rows,
        }

    def _render_dashboard(self, data):
        """Fill the dashboard from fetched data. UI thread only."""
        metrics = data["metrics"]
        total_net = metrics["total_net_pay"]
        total_insurance = metrics["employee_insurance"] + metrics["employer_insurance"]
        employer_cost = total_net + metrics["employer_insurance"]

        self.dashboard_total_net_var.set(self._format_currency(total_net))
        self.dashboard_employer_cost_var.set(self._format_currency(employer_cost))
        self.dashboard_total_insurance_var.set(self._format_currency(total_insurance))
        self.dashboard_employee_count_var.set(str(metrics["employee_count"]))

        self.dashboard_unpaid_last_month_var.set(self._format_currency(data["unpaid_last_month"]))
        self.dashboard_unpaid_current_month_var.set(self._format_currency(data["unpaid_current_month"]))
        self.dashboard_unpaid_current_year_var.set(self._format_currency(data["unpaid_current_year"]))

        comparison = data["comparison"]
        self._apply_mom_card("net", comparison.get("net_pay"))
        self._apply_mom_card("employer_cost", comparison.get("employer_cost"))
        insurance_change = None
        employee_ins = comparison.get("employee_insurance")
        employer_ins = comparison.get("employer_insurance")
        if employee_ins and employer_ins:
            insurance_change = {
                "current": employee_ins["current"] + employer_ins["current"],
                "previous": employee_ins["previous"] + employer_ins["previous"],
            }
            insurance_change["delta"] = (
                insurance_change["current"] - insurance_change["previous"]
            )
            insurance_change["pct_change"] = (
                insurance_change["delta"] / insurance_change["previous"] * 100.0
                if insurance_change["previous"]
                else None
            )
        self._apply_mom_card("insurance", insurance_change)
        self._apply_mom_card("count", comparison.get("employee_count"), as_currency=False)

        self._plot_dashboard_summary(data["monthly_rows"])

        self._reset_treeview(self.dashboard_anomaly_tree, data["anomaly_columns"])
        self._populate_treeview(
            self.dashboard_anomaly_tree, data["jump_rows"] + data["anomaly_rows"]
        )

        self._reset_treeview(self.dashboard_recent_tree, data["recent_columns"])
        self._populate_treeview(self.dashboard_recent_tree, data["recent_rows"])

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.dashboard_status_var.set(f"Last refreshed at {timestamp}.")

    def _dashboard_failed(self, exc):
        self.dashboard_status_var.set("Refresh failed.")
        self.show_message("Dashboard Error", str(exc), kind="warning")

    def _build_monthly_employee_tab(self, parent):
        toolbar = ttk.Frame(parent, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        toolbar.columnconfigure(5, weight=1)

        refresh_btn = ttk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh_monthly_employee_summary,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=0, padx=(0, 10))

        columns_btn = ttk.Button(
            toolbar,
            text="Columns...",
            command=self.open_monthly_column_selector,
            image=self.icons.get("columns_selector"),
            compound=tk.LEFT,
        )
        columns_btn.grid(row=0, column=1, padx=(0, 10))
        self._add_tooltip(columns_btn, "Choose which columns are visible in Monthly Summary.")

        mark_paid_btn = ttk.Button(toolbar, text="Mark as Paid", command=self._mark_monthly_employee_paid)
        mark_paid_btn.grid(row=0, column=2, padx=(0, 10))
        self._add_tooltip(mark_paid_btn, "Mark all entries for the selected employee/month as paid.")

        monthly_report_btn = ttk.Button(toolbar, text="Create Monthly Report", command=self._create_monthly_reports)
        monthly_report_btn.grid(row=0, column=3, padx=(0, 10))
        self._add_tooltip(monthly_report_btn, "Create a per-employee report for selected months.")

        self.analytics_monthly_status_var = tk.StringVar(value="Ready.")
        ttk.Label(toolbar, textvariable=self.analytics_monthly_status_var, style="Body.TLabel").grid(row=0, column=5, sticky=tk.W)

        frame = ttk.Frame(parent, style="App.TFrame")
        frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.analytics_monthly_tree = ttk.Treeview(frame, columns=(), show="headings", selectmode=tk.EXTENDED)
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
            self._database_notice(
                self.analytics_grid_view_tab,
                "The monthly summary is built from stored payroll entries. Turn storage on to see it.",
            )
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
            self.analytics_monthly_cache_columns = columns
            self.analytics_monthly_cache_rows = rows
            self._apply_monthly_column_filters()
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.analytics_monthly_status_var.set(f"Last refreshed at {timestamp}.")
        except Exception as exc:
            self.analytics_monthly_status_var.set("Refresh failed.")
            self.show_message("Analytics Error", str(exc), kind="warning")

    def _mark_monthly_employee_paid(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — entries cannot be updated.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        selection = self.analytics_monthly_tree.selection() if hasattr(self, "analytics_monthly_tree") else []
        if not selection:
            self.show_toast("Select an employee row in the monthly summary first.")
            return
        columns = list(self.analytics_monthly_tree["columns"])
        values = self.analytics_monthly_tree.item(selection[0], "values")
        year = self._get_grid_value(values, columns, "year")
        month = self._get_grid_value(values, columns, "month")
        employee_code = self._get_grid_value(values, columns, "employee_code")
        employee_name = self._get_grid_value(values, columns, "employee_name")
        if not year or not month:
            self.show_message("Mark as Paid", "Missing year/month in selected row.", kind="warning")
            return
        if not employee_code and not employee_name:
            self.show_message("Mark as Paid", "Missing employee in selected row.", kind="warning")
            return
        label = employee_name or employee_code
        if not messagebox.askyesno(
            "Mark as Paid",
            f"Mark all entries for {label} in {year}-{int(month):02d} as paid?",
        ):
            return
        try:
            updated = db_storage.mark_entries_paid_for_month(
                self.db_config,
                employee_code=employee_code,
                employee_name=employee_name,
                year=int(year),
                month=int(month),
            )
            self.show_toast(f"Marked {updated} entries as paid.", kind="success")
            self.refresh_monthly_employee_summary()
            self.refresh_data_grid()
            self._refresh_kpis()
        except Exception as exc:
            self.show_message("Mark as Paid Error", str(exc), kind="warning")

    def _create_monthly_reports(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — monthly reports need it.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        if not hasattr(self, "analytics_monthly_tree"):
            self.show_toast("The monthly employee summary is not available yet.")
            return
        selection = self.analytics_monthly_tree.selection()
        if not selection:
            self.show_toast("Select one or more employee rows first.")
            return
        columns = list(self.analytics_monthly_tree["columns"])
        employees = set()
        for item_id in selection:
            values = self.analytics_monthly_tree.item(item_id, "values")
            employee_code = self._get_grid_value(values, columns, "employee_code")
            employee_name = self._get_grid_value(values, columns, "employee_name")
            if employee_code or employee_name:
                employees.add((employee_code, employee_name))
        if not employees:
            self.show_message(
                "Monthly Reports",
                "Employee columns are missing. Show employee_code or employee_name in the grid and try again.",
                kind="warning",
            )
            return
        month_labels = self._collect_monthly_report_months()
        if not month_labels:
            self.show_toast("Refresh the summary to load the available months.")
            return
        selected_labels = self._prompt_month_selection(month_labels)
        if not selected_labels:
            return
        months = []
        for label in selected_labels:
            try:
                year_str, month_str = label.split("-")
                months.append((int(year_str), int(month_str)))
            except ValueError:
                continue
        if not months:
            self.show_toast("No valid months selected.")
            return
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_paths = []
        skipped = 0
        for employee_code, employee_name in sorted(employees, key=lambda item: (item[1] or "", item[0] or "")):
            label_parts = [part for part in [employee_name, employee_code] if part]
            employee_label = " ".join(label_parts) if label_parts else "Employee"
            safe_label = self._sanitize_filename(employee_label)
            for year, month in months:
                columns, rows = db_storage.fetch_employee_monthly_entries(
                    self.db_config,
                    employee_code=employee_code,
                    employee_name=employee_name,
                    months=[(year, month)],
                )
                if not rows:
                    skipped += 1
                    continue
                formatted_rows = []
                total_net = 0.0
                for row in rows:
                    payment_date, paid_status, document_type, net_pay, source_pdf, source_archive = row
                    if isinstance(payment_date, (datetime.date, datetime.datetime)):
                        payment_date = payment_date.strftime("%Y-%m-%d")
                    if net_pay is None:
                        net_pay = ""
                    else:
                        try:
                            net_pay_value = float(net_pay)
                            total_net += net_pay_value
                            net_pay = f"{net_pay_value:.2f}"
                        except (TypeError, ValueError):
                            net_pay = str(net_pay)
                    formatted_rows.append([
                        payment_date or "",
                        bool(paid_status),
                        document_type or "",
                        net_pay,
                        source_pdf or "",
                        source_archive or "",
                    ])
                totals_row = None
                if formatted_rows:
                    totals_row = [""] * len(columns)
                    if columns:
                        totals_row[0] = "TOTAL"
                    if "net_pay" in columns:
                        totals_row[columns.index("net_pay")] = f"{total_net:.2f}"
                month_label = datetime.date(year, month, 1).strftime("%b %Y")
                meta_lines = [
                    ("Exported", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    ("Timeframe", month_label),
                    ("Employee", employee_label),
                ]
                filename = f"monthly_report_{safe_label}_{year:04d}-{month:02d}_{timestamp}.pdf"
                output_path = self.employee_reports_dir / filename
                try:
                    self._write_pdf_report(
                        str(output_path),
                        "Monthly Employee Report",
                        columns,
                        formatted_rows,
                        meta_lines,
                        totals_row,
                    )
                    output_paths.append(str(output_path))
                except Exception as exc:
                    self.show_message("Monthly Report Error", str(exc), kind="warning")
        if not output_paths:
            self.show_toast("No reports were generated.", kind="warning")
            return
        summary = f"Created {len(output_paths)} report(s)."
        if skipped:
            summary += f" Skipped {skipped} month(s) with no entries."
        self.show_toast(
            summary,
            kind="success",
            seconds=8,
            action_text="Show in Finder",
            action=lambda: self.reveal_in_finder(*output_paths),
        )

    def _collect_monthly_report_months(self):
        columns = self.analytics_monthly_cache_columns or []
        rows = self.analytics_monthly_cache_rows or []
        if not columns or not rows:
            return []
        if "year" not in columns or "month" not in columns:
            return []
        year_idx = columns.index("year")
        month_idx = columns.index("month")
        labels = set()
        for row in rows:
            if year_idx >= len(row) or month_idx >= len(row):
                continue
            year = row[year_idx]
            month = row[month_idx]
            if year and month:
                labels.add(f"{int(year):04d}-{int(month):02d}")
        return sorted(labels, reverse=True)

    def _prompt_month_selection(self, month_labels):
        if not month_labels:
            return []
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Months")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0)

        ttk.Label(frame, text="Choose one or more months:", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W)
        listbox = tk.Listbox(frame, selectmode=tk.MULTIPLE, exportselection=False, height=min(12, len(month_labels)))
        listbox.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(6, 10))
        for label in month_labels:
            listbox.insert(tk.END, label)
        for idx in range(len(month_labels)):
            listbox.selection_set(idx)

        result = []

        def _select_all():
            listbox.selection_set(0, tk.END)

        def _clear_all():
            listbox.selection_clear(0, tk.END)

        def _confirm():
            selected = listbox.curselection()
            for idx in selected:
                result.append(month_labels[idx])
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky=tk.E)
        ttk.Button(buttons, text="Select All", command=_select_all).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="Clear", command=_clear_all).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="OK", command=_confirm).pack(side=tk.LEFT)

        dialog.wait_window()
        return result

    def _sanitize_filename(self, value):
        if value is None:
            return "report"
        text = str(value).strip()
        if not text:
            return "report"
        normalized = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        safe = []
        for ch in text:
            if ch.isalnum() or ch in ("-", "_"):
                safe.append(ch)
            elif ch.isspace():
                safe.append("_")
        cleaned = "".join(safe).strip("_")
        return cleaned or "report"

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
        self.grid_search_job = self.root.after(300, self._refresh_all_views)

    def _add_search_clause(self):
        if len(self.search_clauses) >= 2:
            return
        clause = {
            "op_var": tk.StringVar(value="AND"),
            "term_var": tk.StringVar(value=""),
        }
        self.search_clauses.append(clause)
        self._render_search_clauses()

    def _remove_search_clause(self, index):
        if index < 0 or index >= len(self.search_clauses):
            return
        self.search_clauses.pop(index)
        self._render_search_clauses()
        self._on_global_search()

    def _render_search_clauses(self):
        for child in self.search_clause_frame.winfo_children():
            child.destroy()
        self.search_clause_frame.columnconfigure(1, weight=0)
        for idx, clause in enumerate(self.search_clauses):
            op_combo = ttk.Combobox(
                self.search_clause_frame,
                textvariable=clause["op_var"],
                values=["AND", "OR", "NOT"],
                state="readonly",
                width=6,
            )
            if idx == 0:
                clause["op_var"].set("AND")
                op_combo.configure(state="disabled")
            op_combo.grid(row=idx, column=0, padx=(0, 6), sticky=tk.W)
            op_combo.bind("<<ComboboxSelected>>", self._on_global_search)

            term_entry = ttk.Entry(self.search_clause_frame, textvariable=clause["term_var"], width=20)
            term_entry.grid(row=idx, column=1, padx=(0, 6), sticky=tk.W)
            term_entry.bind("<KeyRelease>", self._on_global_search)

            remove_btn = ttk.Button(self.search_clause_frame, text="-", width=2, command=lambda i=idx: self._remove_search_clause(i))
            remove_btn.grid(row=idx, column=2, padx=(0, 4), sticky=tk.W)

            if idx == len(self.search_clauses) - 1 and len(self.search_clauses) < 2:
                add_btn = ttk.Button(self.search_clause_frame, text="+", width=2, command=self._add_search_clause)
                add_btn.grid(row=idx, column=3, sticky=tk.W)
        self._render_filter_chips()

    def _reflow_filter_bar(self, _event=None):
        """Keep the filter controls on one line, wrapping search when narrow.

        At the 900px minimum window width all four groups do not fit, so the
        search group drops to its own line instead of being clipped.
        """
        controls = getattr(self, "filter_controls", None)
        search = getattr(self, "filter_search_group", None)
        if controls is None or search is None:
            return
        available = self.global_filter_bar.winfo_width()
        if available <= 1:
            available = self.root.winfo_width() - 32
        trailing = getattr(self, "filter_trailing", None)
        needed = controls.winfo_reqwidth() + search.winfo_reqwidth() + 24
        if trailing is not None:
            needed += trailing.winfo_reqwidth()
        wrapped = needed > available
        if wrapped == self.filter_search_wrapped:
            return
        self.filter_search_wrapped = wrapped
        search.grid_forget()
        if wrapped:
            search.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))
        else:
            search.grid(row=0, column=1, sticky=tk.W, padx=(18, 0))

    def _reset_global_filters(self):
        """Clear every filter and search term, then reload the views."""
        self.global_start_year_var.set("All")
        self.global_end_year_var.set("All")
        self.global_start_month_var.set("01")
        self.global_end_month_var.set("01")
        self.global_doc_type_var.set("All")
        self.global_search_var.set("")
        self.search_clauses = []
        self._render_search_clauses()
        self._update_window_label()
        self._save_ui_prefs()
        self._refresh_all_views()
        self.show_toast("Filters cleared.", seconds=3)

    def _active_filter_chips(self):
        """The filters currently narrowing the data, as (label, clear) pairs."""
        chips = []
        start_year = self.global_start_year_var.get()
        end_year = self.global_end_year_var.get()
        if start_year and start_year != "All" and end_year and end_year != "All":
            window = self.global_window_label_var.get() or f"{start_year} → {end_year}"

            def clear_period():
                self.global_start_year_var.set("All")
                self.global_end_year_var.set("All")
                self._on_global_filter_change()

            chips.append((f"Period: {window}", clear_period))

        doc_type = self.global_doc_type_var.get()
        if doc_type and doc_type != "All":
            def clear_doc():
                self.global_doc_type_var.set("All")
                self._on_global_filter_change()

            chips.append((f"Document: {doc_type}", clear_doc))

        term = self.global_search_var.get().strip()
        if term:
            def clear_term():
                self.global_search_var.set("")
                self._on_global_filter_change()

            chips.append((f'Search: "{term}"', clear_term))

        for index, clause in enumerate(self.search_clauses):
            clause_term = clause["term_var"].get().strip()
            if not clause_term:
                continue
            operator = clause["op_var"].get().strip().upper() or "AND"
            chips.append((
                f'{operator} "{clause_term}"',
                lambda i=index: self._remove_search_clause(i),
            ))
        return chips

    def _render_filter_chips(self):
        """Redraw the applied-filter chips under the filter controls."""
        if not hasattr(self, "filter_chip_frame"):
            return
        for child in self.filter_chip_frame.winfo_children():
            child.destroy()
        chips = self._active_filter_chips()
        if not chips:
            ttk.Label(
                self.filter_chip_frame,
                text="No filters applied — showing everything.",
                style="Hint.TLabel",
            ).pack(side=tk.LEFT)
            self.reset_filters_btn.state(["disabled"])
            return
        self.reset_filters_btn.state(["!disabled"])
        for label, clear in chips:
            chip = ttk.Frame(self.filter_chip_frame, style="Chip.TFrame", padding=(8, 3))
            chip.pack(side=tk.LEFT, padx=(0, 6))
            ttk.Label(chip, text=label, style="Chip.TLabel").pack(side=tk.LEFT)
            close = ttk.Label(chip, text="✕", style="Chip.TLabel", cursor="hand2")
            close.pack(side=tk.LEFT, padx=(6, 0))
            close.bind("<Button-1>", lambda _event, fn=clear: fn())

    def _refresh_all_views(self):
        self._render_filter_chips()
        self.refresh_analytics()
        self.refresh_dashboard()
        self.refresh_data_grid()
        self.refresh_monthly_employee_summary()
        self.refresh_insurance_summary()
        self.refresh_employees_tab()
        # "Searching…" is set when typing begins, but only the data-grid path
        # cleared it. With storage off that path returns early, so the label
        # stayed on screen forever. Clearing here covers every route.
        self.grid_search_job = None
        if self.global_filter_status.get() == "Searching…":
            self.global_filter_status.set("")

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
            self._render_filter_chips()
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
        self._render_filter_chips()

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
        search = self._collect_search_clauses()
        return start_date, end_date, document_type, search

    def _collect_search_clauses(self):
        clauses = []
        first_term = self.global_search_var.get().strip()
        if first_term:
            clauses.append({"op": "AND", "term": first_term})
        for idx, clause in enumerate(self.search_clauses):
            term = clause["term_var"].get().strip()
            if not term:
                continue
            op = clause["op_var"].get().strip().upper() or "AND"
            if idx == 0:
                op = "AND"
            clauses.append({"op": op, "term": term})
        return clauses or None

    def create_db_tab(self):
        """Create the database views tab."""
        self.db_tab.columnconfigure(0, weight=1)
        self.db_tab.rowconfigure(2, weight=1)

        title_label = ttk.Label(self.db_tab, text="Database Views", style="Section.TLabel")
        title_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        toolbar = ttk.Frame(self.db_tab)
        toolbar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        toolbar.columnconfigure(6, weight=1)

        refresh_btn = ttk.Button(
            toolbar,
            text="Refresh Data",
            command=self.refresh_db_views,
            image=self.icons.get("refresh"),
            compound=tk.LEFT,
        )
        refresh_btn.grid(row=0, column=0, padx=(0, 10))
        self._add_tooltip(refresh_btn, "Reload database views.")

        ttk.Label(toolbar, text="Filter", style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)
        self.db_filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(toolbar, textvariable=self.db_filter_var, width=24)
        filter_entry.grid(row=0, column=2, padx=(6, 10), sticky=tk.W)
        self._add_tooltip(filter_entry, "Filter rows in the current database view.")

        ttk.Label(toolbar, text="Limit", style="Body.TLabel").grid(row=0, column=3, sticky=tk.W)
        self.db_limit_var = tk.IntVar(value=500)
        limit_spin = ttk.Spinbox(toolbar, from_=50, to=5000, textvariable=self.db_limit_var, width=6)
        limit_spin.grid(row=0, column=4, padx=(6, 10), sticky=tk.W)
        self._add_tooltip(limit_spin, "Row limit for database views.")

        columns_btn = ttk.Button(
            toolbar,
            text="Columns...",
            command=self.open_column_selector,
            image=self.icons.get("columns_selector"),
            compound=tk.LEFT,
        )
        columns_btn.grid(row=0, column=5, padx=(0, 10))
        self._add_tooltip(columns_btn, "Choose columns shown in the database views.")

        self.db_status_var = tk.StringVar(value="Ready to refresh.")
        status_label = ttk.Label(toolbar, textvariable=self.db_status_var, style="Body.TLabel")
        status_label.grid(row=0, column=6, sticky=tk.W)

        self.db_views_notebook = ttk.Notebook(self.db_tab)
        self.db_views_notebook.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.db_views_notebook.bind("<<NotebookTabChanged>>", lambda _e: self.refresh_db_views())

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
            self._database_notice(
                self.db_tab,
                "These views query the payroll database directly. Turn storage on to use them.",
            )
            return
        self._clear_database_notice(self.db_tab)

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
                for col in columns:
                    tree.heading(col, text=col, command=lambda c=col, t=tree: self._sort_treeview(t, c, False))
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
            tree.column(col, width=width, anchor=tk.W, stretch=False)

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
            self.show_toast("Refresh the data first to load its columns.")
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
        """One line of guidance; the folder paths live under the progress bar."""
        if DRAG_DROP_AVAILABLE:
            return "Drop ZIP or PDF payroll files below, or browse for them, then generate the reports."
        return "Browse for ZIP or PDF payroll files, then generate the reports."

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
        self.employee_reports_dir = self.report_dir / "Employees Reports"
        self.employee_reports_dir.mkdir(parents=True, exist_ok=True)
        if not self.archive_dir_custom:
            self.archive_dir = self.report_dir / "Source PDFs"
            self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.signed_docs_dir = self.report_dir / "Signed Documents"
        self.signed_docs_dir.mkdir(parents=True, exist_ok=True)
        self.output_location_var.set(f"Reports are saved to {self.employee_reports_dir}")
        self.instructions_label.configure(text=self.get_instructions_text())
        self._refresh_settings_labels()

    def choose_pdf_archive_folder(self):
        """Allow the user to choose the PDF archive folder."""
        new_dir = filedialog.askdirectory(
            title="Select PDF Archive Folder",
            initialdir=str(self.archive_dir)
        )
        if not new_dir:
            return
        new_archive = Path(new_dir)
        new_archive.mkdir(parents=True, exist_ok=True)
        old_archive = self.archive_dir
        if old_archive.exists() and old_archive != new_archive:
            should_move = messagebox.askyesno(
                "Move Archived PDFs",
                f"Move existing PDFs from:\n{old_archive}\n\nto:\n{new_archive}?"
            )
            if should_move:
                try:
                    for item in old_archive.iterdir():
                        target = new_archive / item.name
                        if target.exists():
                            continue
                        shutil.move(str(item), str(target))
                except Exception as exc:
                    messagebox.showwarning("Move Failed", str(exc))
        self.archive_dir = new_archive
        self.archive_dir_custom = True
        self._save_ui_prefs()
        self.instructions_label.configure(text=self.get_instructions_text())
        self._refresh_settings_labels()

    def import_signed_documents(self):
        """Import signed documents from the Signed folder or chosen files."""
        repo_root = Path(__file__).resolve().parents[3]
        signed_dir = repo_root / "Signed"
        paths = []
        if signed_dir.exists():
            candidates = [
                p for p in signed_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".pdf", ".zip"}
            ]
            if candidates:
                if messagebox.askyesno(
                    "Import Signed Docs",
                    f"Found {len(candidates)} file(s) in:\n{signed_dir}\n\nImport them?",
                ):
                    paths = [str(p) for p in candidates]
        if not paths:
            file_paths = filedialog.askopenfilenames(
                title="Select Signed Documents",
                initialdir=str(signed_dir if signed_dir.exists() else self.report_dir),
                filetypes=[("Signed docs", "*.pdf *.zip"), ("PDF files", "*.pdf"), ("ZIP files", "*.zip")],
            )
            if not file_paths:
                return
            paths = list(file_paths)

        summary = self._archive_signed_documents(paths)
        message = (
            f"Imported {summary['archived']} signed document(s).\n"
            f"Skipped {summary['skipped']} existing file(s).\n"
            f"Errors: {summary['errors']}"
        )
        self._append_processing_log(summary["log_lines"])
        self.show_toast(message, kind="success", seconds=8)

    def _archive_signed_documents(self, paths):
        log_lines = [f"=== {datetime.datetime.now().isoformat(timespec='seconds')} ===", "Signed docs import"]
        archived = 0
        skipped = 0
        errors = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            for path in paths:
                try:
                    path_obj = Path(path)
                    if path_obj.suffix.lower() == ".zip":
                        log_lines.append(f"ZIP: {path}")
                        with zipfile.ZipFile(path_obj, "r") as zf:
                            members = process_payroll._validated_zip_members(zf)
                            process_payroll._extract_pdf_members(zf, members, temp_dir)
                        for root, _, files in os.walk(temp_dir):
                            for fname in files:
                                if not fname.lower().endswith(".pdf"):
                                    continue
                                src = os.path.join(root, fname)
                                result = self._archive_signed_pdf(src)
                                if result:
                                    archived += 1
                                    log_lines.append(f"Archived: {result}")
                                else:
                                    skipped += 1
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        os.makedirs(temp_dir, exist_ok=True)
                    elif path_obj.suffix.lower() == ".pdf":
                        result = self._archive_signed_pdf(str(path_obj))
                        if result:
                            archived += 1
                            log_lines.append(f"Archived: {result}")
                        else:
                            skipped += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    errors += 1
                    log_lines.append(f"Error: {path} ({exc})")
        return {"archived": archived, "skipped": skipped, "errors": errors, "log_lines": log_lines}

    def _archive_signed_pdf(self, pdf_path: str):
        doc_type, employee = self._classify_signed_doc(pdf_path)
        date = datetime.date.fromtimestamp(os.path.getmtime(pdf_path))
        year = str(date.year)
        employee_part = self._sanitize_filename(employee or "Unknown")
        doc_part = self._sanitize_filename(doc_type or "Signed")
        base = self._sanitize_filename(Path(pdf_path).stem)
        dest_dir = self.signed_docs_dir / doc_part / year / employee_part
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"{date:%Y%m%d}_{doc_part}_{employee_part}_{base}.pdf"
        dest_path = dest_dir / dest_name
        if dest_path.exists():
            return None
        shutil.copy2(pdf_path, dest_path)
        self._apply_signed_flags(doc_type, employee, date)
        return str(dest_path)

    def _fetch_jump_alerts(self, start_date=None, end_date=None, document_type=None, search=None):
        """Return month-over-month jumps shaped like the anomaly alert rows.

        fetch_entry_jumps returns its own column set, so rows are reshaped to
        (alert, employee, date, document_type, net_pay, total_insurance) to sit
        in the same alerts table. Insurance is blank because a jump is measured
        on net pay alone.
        """
        try:
            _columns, rows = db_storage.fetch_entry_jumps(
                self.db_config,
                start_date=start_date,
                end_date=end_date,
                document_type=document_type,
                search=search,
                limit=20,
            )
        except Exception:
            return []
        alerts = []
        for row in rows:
            employee_name, _code, doc_type, period, _prev, net_pay, _delta, pct = row
            direction = "▲" if (pct or 0) >= 0 else "▼"
            alerts.append(
                (
                    f"Sudden Jump {direction} {abs(float(pct or 0)):.0f}%",
                    employee_name,
                    period,
                    doc_type,
                    net_pay,
                    "",
                )
            )
        return alerts

    def _signed_flags_for_doc_type(self, doc_type: str):
        """Map a signed document type to (signed_employer, signed_employee).

        Government filings are made by the employer, so they only evidence the
        employer side. A document explicitly marked as signatures evidences
        both. None means "leave that flag alone".
        """
        # Case matters here. _classify_signed_doc returns "SIGNED" when the
        # filename actually says so, but "Signed" as its fallback for anything
        # it could not identify. Upper-casing first would conflate the two and
        # flag every unrecognised PDF as fully signed.
        if doc_type in {"ΥΠΟΓΡΑΦΕΣ", "SIGNED"}:
            return True, True
        if doc_type in {"E9", "ΠΡΟΣΛΗΨΗ", "ΕΝΤΥΠΟ3", "GOVGR"}:
            return True, None
        return None, None

    def _apply_signed_flags(self, doc_type: str, employee: str, date) -> int:
        """Flag the matching employee-month as signed, if we can identify one."""
        if not self.db_config.get("enabled") or not employee or date is None:
            return 0
        signed_employer, signed_employee = self._signed_flags_for_doc_type(doc_type)
        if signed_employer is None and signed_employee is None:
            return 0
        try:
            return db_storage.mark_signed_for_period(
                self.db_config,
                employee_name=employee,
                year=date.year,
                month=date.month,
                signed_employer=signed_employer,
                signed_employee=signed_employee,
                signed_date=date,
            )
        except Exception:
            # Archiving must not fail because the database is unreachable.
            return 0

    def _classify_signed_doc(self, pdf_path: str):
        name = Path(pdf_path).stem
        upper = name.upper()
        doc_type = "Signed"
        if upper.startswith("E9") or "Ε9" in upper:
            doc_type = "E9"
        elif "ΠΡΟΣΛΗΨΗ" in upper:
            doc_type = "ΠΡΟΣΛΗΨΗ"
        elif "ΕΝΤΥΠΟ3" in upper or "ENTYPO3" in upper or "ENTYPO 3" in upper:
            doc_type = "ΕΝΤΥΠΟ3"
        elif "GOVGR_DOCUMENT" in upper:
            doc_type = "GOVGR"
        elif "SIGNED" in upper:
            doc_type = "SIGNED"
        elif "YPOGRAF" in upper or "REYPOGRAF" in upper or "ΥΠΟΓΡΑΦ" in upper:
            doc_type = "ΥΠΟΓΡΑΦΕΣ"

        employee = None
        match = re.search(r"(?:E9|Ε9)\s+(.+)", name, re.IGNORECASE)
        if match:
            employee = match.group(1)
        if employee:
            employee = re.sub(r"\bcopy\b", "", employee, flags=re.IGNORECASE).strip()
        return doc_type, employee

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
        settings_menu.add_command(label="Open Settings", command=lambda: self._set_active_view("Settings"))
        menubar.add_cascade(label="Settings", menu=settings_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About Payroll Processor", command=self.show_about)
        help_menu.add_separator()
        help_menu.add_command(label="How to Use Payroll Processor", command=self.show_help)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

        try:
            self._apply_macos_app_name()
            self.root.after(0, self._apply_macos_app_name)
            self.root.after(250, self._apply_macos_app_name)
            self.root.createcommand("tkAboutDialog", self.show_about)
        except tk.TclError:
            pass

    def show_about(self):
        """Display About dialog."""
        messagebox.showinfo(
            "About Payroll Processor",
            "Payroll Processor\n"
            f"Version {APP_VERSION}\n"
            "Author: panlam\n"
            "Processes payroll ZIPs and generates Excel reports."
        )

    def show_help(self):
        """Display basic how-to instructions."""
        messagebox.showinfo(
            "How to Use Payroll Processor",
            "1) Drag and drop ZIP or PDF files containing payroll data, or click Browse.\n"
            "2) Click Generate Reports.\n"
            "3) Two Excel files are saved in:\n"
            f"{self.employee_reports_dir}\n\n"
            "Summary = per-employee workbook\n"
            "Detail = every payroll entry list\n\n"
            "Output folder can be changed from Settings → Storage.\n\n"
            "Keyboard shortcuts:\n"
            "Cmd+Z = Undo last edit\n"
            "Shift+Cmd+Z = Redo last edit\n"
            "Cmd+L = Toggle edit lock\n"
            "Cmd+F = Focus global search\n"
            "Cmd+R = Refresh views\n"
            "Cmd+C = Copy selected grid cell"
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

    def open_theme_settings(self):
        """Open the appearance settings panel."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Appearance")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        mode_var = tk.StringVar(value=self.theme_mode_var.get())
        frame = ttk.Frame(dialog, padding="12")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Theme", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 8))
        mode_combo = ttk.Combobox(frame, textvariable=mode_var, state="readonly", width=20)
        mode_combo["values"] = ("auto", "light", "dark")
        mode_combo.grid(row=0, column=1, sticky=tk.W, pady=(0, 8))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=1, column=0, columnspan=2, sticky=tk.E)

        def on_save():
            self.theme_mode_var.set(mode_var.get())
            self._save_ui_prefs()
            self.apply_theme()
            dialog.destroy()

        ttk.Button(button_frame, text="Save", style="Accent.TButton", command=on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def apply_theme(self):
        """Repaint the whole app after an appearance change.

        ttk styles only reach ttk widgets. The listbox, the log pane, the lock
        canvas and every matplotlib figure carry their own colours, so they are
        repainted here - otherwise switching to dark left a half-light window
        until the next restart.
        """
        self.configure_styles()
        tokens = self.theme
        self.root.configure(bg=tokens.bg)

        listbox = getattr(self, "file_listbox", None)
        if listbox is not None:
            listbox.configure(
                bg=tokens.surface,
                fg=tokens.text_primary,
                selectbackground=tokens.selection,
                selectforeground=tokens.text_primary,
                highlightbackground=tokens.border,
                highlightcolor=tokens.accent,
            )

        log_text = getattr(self, "log_text", None)
        if log_text is not None:
            log_text.configure(
                bg=tokens.surface,
                fg=tokens.text_secondary,
                insertbackground=tokens.text_primary,
                highlightbackground=tokens.border,
            )

        if getattr(self, "lock_canvas", None) is not None:
            self.lock_canvas.configure(bg=tokens.bg)
            self._update_lock_indicator()

        if getattr(self, "settings_canvas", None) is not None:
            self.settings_canvas.configure(bg=tokens.bg)

        # Toasts are built from raw Tk frames; the live ones keep the old
        # palette, so they are cleared rather than left mismatched.
        for toast in list(self.toasts):
            self._dismiss_toast(toast)

        # Give every figure the new background immediately, then re-plot so the
        # series colours follow too.
        figures = [chart for chart in getattr(self, "analytics_charts", {}).values()]
        if getattr(self, "dashboard_chart", None):
            figures.append(self.dashboard_chart)
        for chart in figures:
            chart["fig"].set_facecolor(tokens.chart_bg)
            chart["ax"].set_facecolor(tokens.chart_bg)
            chart["canvas"].draw_idle()

        self._render_filter_chips()
        self._refresh_setup_banner()
        self._refresh_all_views()

    def create_settings_tab(self):
        """Create the Settings tab."""
        self.settings_tab.columnconfigure(0, weight=1)
        header = ttk.Frame(self.settings_tab, style="App.TFrame")
        header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        ttk.Label(header, text="Settings", style="Header.TLabel").grid(row=0, column=0, padx=(0, 10))
        ttk.Label(header, text="Configure storage, database, and appearance.", style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)

        # The settings groups are taller than the 900x600 minimum window, so
        # the content scrolls instead of being clipped.
        self.settings_tab.rowconfigure(1, weight=1)
        scroll_host = ttk.Frame(self.settings_tab, style="App.TFrame")
        scroll_host.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scroll_host.columnconfigure(0, weight=1)
        scroll_host.rowconfigure(0, weight=1)

        self.settings_canvas = tk.Canvas(
            scroll_host,
            highlightthickness=0,
            bd=0,
            bg=self.theme.bg,
        )
        self.settings_canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        settings_scroll = ttk.Scrollbar(scroll_host, orient=tk.VERTICAL, command=self.settings_canvas.yview)
        settings_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.settings_canvas.configure(yscrollcommand=settings_scroll.set)

        content = ttk.Frame(self.settings_canvas, style="App.TFrame")
        content_window = self.settings_canvas.create_window((0, 0), window=content, anchor=tk.NW)
        content.columnconfigure(0, weight=1)

        def _resize_content(_event=None):
            self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all"))
            self.settings_canvas.itemconfigure(content_window, width=self.settings_canvas.winfo_width())

        content.bind("<Configure>", _resize_content)
        self.settings_canvas.bind("<Configure>", _resize_content)
        self.settings_canvas.bind_all(
            "<MouseWheel>",
            lambda event: self._scroll_settings(event),
            add="+",
        )

        storage_frame = ttk.LabelFrame(content, text="Storage", padding=12, style="App.TLabelframe")
        storage_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        storage_frame.columnconfigure(1, weight=1)
        storage_frame.columnconfigure(2, minsize=140)
        ttk.Label(storage_frame, text="Employee reports folder:", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.settings_reports_var = tk.StringVar(value=str(self.employee_reports_dir))
        ttk.Label(storage_frame, textvariable=self.settings_reports_var, style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)
        ttk.Button(storage_frame, text="Change…", command=self.choose_output_folder).grid(row=0, column=2, padx=(8, 0), sticky=tk.E)

        ttk.Label(storage_frame, text="PDF archive folder:", style="Body.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(6, 0), padx=(0, 8))
        self.settings_archive_var = tk.StringVar(value=str(self.archive_dir))
        ttk.Label(storage_frame, textvariable=self.settings_archive_var, style="Body.TLabel").grid(row=1, column=1, sticky=tk.W, pady=(6, 0))
        ttk.Button(storage_frame, text="Change…", command=self.choose_pdf_archive_folder).grid(row=1, column=2, padx=(8, 0), pady=(6, 0), sticky=tk.E)
        ttk.Label(storage_frame, text="Signed docs folder:", style="Body.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(6, 0), padx=(0, 8))
        self.settings_signed_var = tk.StringVar(value=str(self.signed_docs_dir))
        ttk.Label(storage_frame, textvariable=self.settings_signed_var, style="Body.TLabel").grid(row=2, column=1, sticky=tk.W, pady=(6, 0))
        ttk.Button(storage_frame, text="Import…", command=self.import_signed_documents).grid(row=2, column=2, padx=(8, 0), pady=(6, 0), sticky=tk.E)

        watch_frame = ttk.LabelFrame(content, text="Watch Folder", padding=12, style="App.TLabelframe")
        watch_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        watch_frame.columnconfigure(1, weight=1)
        watch_frame.columnconfigure(2, minsize=140)
        ttk.Label(watch_frame, text="Folder:", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.settings_watch_var = tk.StringVar(value=str(self.watch_dir))
        ttk.Label(watch_frame, textvariable=self.settings_watch_var, style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)
        ttk.Button(watch_frame, text="Change…", command=self.choose_watch_folder).grid(row=0, column=2, padx=(8, 0), sticky=tk.E)
        watch_controls = ttk.Frame(watch_frame, style="App.TFrame")
        watch_controls.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(6, 0))
        watch_controls.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            watch_controls,
            text="Auto-process new ZIP/PDF files",
            variable=self.watch_enabled_var,
            command=self._toggle_watch_folder,
        ).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(watch_controls, text="Interval (sec)", style="Body.TLabel").grid(row=0, column=1, sticky=tk.W, padx=(12, 8))
        interval_spin = ttk.Spinbox(
            watch_controls,
            from_=2,
            to=120,
            textvariable=self.watch_interval_var,
            width=6,
            command=self._toggle_watch_folder,
        )
        interval_spin.grid(row=0, column=2, sticky=tk.W)

        db_frame = ttk.LabelFrame(content, text="Database", padding=12, style="App.TLabelframe")
        db_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        db_frame.columnconfigure(1, weight=1)
        db_frame.columnconfigure(2, minsize=160)
        ttk.Button(db_frame, text="Database Settings…", command=self.open_db_settings).grid(row=0, column=0, padx=(0, 10), sticky=tk.W)
        ttk.Label(db_frame, text="Backups and exports", style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)
        ttk.Button(db_frame, text="Backup Database…", command=self.backup_database).grid(row=1, column=0, pady=(8, 0), sticky=tk.W)
        ttk.Button(db_frame, text="Restore Database…", command=self.restore_database).grid(row=1, column=1, padx=(10, 0), pady=(8, 0), sticky=tk.W)
        ttk.Button(db_frame, text="Export Data (CSV)…", command=self.export_database_csv).grid(row=1, column=2, padx=(10, 0), pady=(8, 0), sticky=tk.E)
        ttk.Checkbutton(
            db_frame,
            text="Show Database tab",
            variable=self.show_db_tab_var,
            command=self._toggle_database_tab,
        ).grid(row=2, column=0, pady=(8, 0), sticky=tk.W)
        ttk.Button(
            db_frame,
            text="Delete All Data…",
            style="Danger.TButton",
            command=self.delete_all_database_data,
        ).grid(row=2, column=1, padx=(10, 0), pady=(8, 0), sticky=tk.W)

        backup_frame = ttk.LabelFrame(content, text="Backups", padding=12, style="App.TLabelframe")
        backup_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        backup_frame.columnconfigure(1, weight=1)
        backup_frame.columnconfigure(2, minsize=140)
        ttk.Label(backup_frame, text="Backup folder:", style="Body.TLabel").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.settings_backup_var = tk.StringVar(value=str(self.backup_dir))
        ttk.Label(backup_frame, textvariable=self.settings_backup_var, style="Body.TLabel").grid(row=0, column=1, sticky=tk.W)
        ttk.Button(backup_frame, text="Change…", command=self.choose_backup_folder).grid(row=0, column=2, padx=(8, 0), sticky=tk.E)
        ttk.Checkbutton(
            backup_frame,
            text="Auto backup",
            variable=self.auto_backup_enabled_var,
            command=self._save_ui_prefs,
        ).grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Label(backup_frame, text="Frequency", style="Body.TLabel").grid(row=1, column=1, sticky=tk.W, pady=(6, 0))
        frequency_combo = ttk.Combobox(backup_frame, textvariable=self.auto_backup_frequency_var, state="readonly", width=12)
        frequency_combo["values"] = ["20 minutes", "daily", "weekly"]
        frequency_combo.grid(row=1, column=2, sticky=tk.W, pady=(6, 0))
        frequency_combo.bind("<<ComboboxSelected>>", lambda _event: self._schedule_auto_backup())
        ttk.Button(backup_frame, text="Run Backup Now", command=self._run_backup_now).grid(row=2, column=0, pady=(8, 0), sticky=tk.W)
        ttk.Button(backup_frame, text="Verify Backup…", command=self.verify_backup).grid(row=2, column=1, padx=(10, 0), pady=(8, 0), sticky=tk.W)

        appearance_frame = ttk.LabelFrame(content, text="Appearance & Editing", padding=12, style="App.TLabelframe")
        appearance_frame.grid(row=4, column=0, sticky=(tk.W, tk.E))
        appearance_frame.columnconfigure(1, weight=1)
        ttk.Button(appearance_frame, text="Appearance…", command=self.open_theme_settings).grid(row=0, column=0, padx=(0, 10), sticky=tk.W)
        ttk.Checkbutton(
            appearance_frame,
            text="Lock table editing",
            variable=self.edit_lock_var,
            command=self._toggle_edit_lock,
        ).grid(row=0, column=1, sticky=tk.W)

    def _scroll_settings(self, event):
        """Wheel scrolling for the settings pane, only while it is visible."""
        canvas = getattr(self, "settings_canvas", None)
        if canvas is None:
            return
        try:
            if self.notebook.select() != str(self.settings_tab):
                return
            canvas.yview_scroll(-1 * int(event.delta), "units")
        except tk.TclError:
            return

    def _refresh_settings_labels(self):
        if hasattr(self, "settings_reports_var"):
            self.settings_reports_var.set(str(self.employee_reports_dir))
        if hasattr(self, "settings_archive_var"):
            self.settings_archive_var.set(str(self.archive_dir))
        if hasattr(self, "settings_signed_var"):
            self.settings_signed_var.set(str(self.signed_docs_dir))
        if hasattr(self, "settings_backup_var"):
            self.settings_backup_var.set(str(self.backup_dir))
        if hasattr(self, "settings_watch_var"):
            self.settings_watch_var.set(str(self.watch_dir))

    def backup_database(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — there is nothing to back up.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        path = filedialog.asksaveasfilename(
            title="Save Database Backup",
            defaultextension=".dump",
            filetypes=[("PostgreSQL Backup", "*.dump"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            db_storage.backup_database(self.db_config, path)
            self.show_toast(f"Database backup saved to {Path(path).name}", kind="success",
                            action_text="Show in Finder", action=lambda: self.reveal_in_finder(path))
        except Exception as exc:
            self.show_message("Backup Error", str(exc), kind="warning")

    def restore_database(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — turn it on before restoring.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        path = filedialog.askopenfilename(
            title="Restore Database Backup",
            filetypes=[("PostgreSQL Backup", "*.dump"), ("All Files", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Restore Database",
            "This will overwrite existing database data. Continue?",
        ):
            return
        try:
            db_storage.restore_database(self.db_config, path)
            self.show_toast("Database restore finished.", kind="success")
            self._refresh_all_views()
        except Exception as exc:
            self.show_message("Restore Error", str(exc), kind="warning")

    def export_database_csv(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — there is nothing to export.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        output_dir = filedialog.askdirectory(
            title="Select Folder for CSV Export",
        )
        if not output_dir:
            return
        try:
            db_storage.export_all_tables_to_csv(self.db_config, output_dir)
            self.show_toast("CSV files exported.", kind="success",
                            action_text="Show in Finder", action=lambda: self.reveal_in_finder(output_dir))
        except Exception as exc:
            self.show_message("Export Error", str(exc), kind="warning")

    def delete_all_database_data(self):
        if not self.db_config.get("enabled"):
            self.show_toast("Database storage is off — there is nothing to delete.", kind="warning",
                            action_text="Open Database Settings…", action=self.open_db_settings)
            return
        confirm = messagebox.askyesno(
            "Delete All Data",
            "This will permanently delete all payroll data, documents, and summaries.\n\n"
            "Do you want to continue?",
        )
        if not confirm:
            return
        typed = simpledialog.askstring("Confirm Delete", "Type DELETE to confirm.", parent=self.root)
        if typed != "DELETE":
            self.show_toast("Delete All Data was cancelled.")
            return
        try:
            db_storage.delete_all_data(self.db_config)
            self.show_toast("All database data has been removed.", kind="success")
            self._refresh_all_views()
            self._clear_employee_profile()
        except Exception as exc:
            self.show_message("Delete Error", str(exc), kind="warning")

    def choose_backup_folder(self):
        new_dir = filedialog.askdirectory(
            title="Select Backup Folder",
            initialdir=str(self.backup_dir)
        )
        if not new_dir:
            return
        self.backup_dir = Path(new_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._save_ui_prefs()
        self._refresh_settings_labels()

    def choose_watch_folder(self):
        new_dir = filedialog.askdirectory(
            title="Select Watch Folder",
            initialdir=str(self.watch_dir)
        )
        if not new_dir:
            return
        self.watch_dir = Path(new_dir)
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self._prime_watch_seen()
        self._refresh_settings_labels()
        self._toggle_watch_folder()

    def run_total_backup(self, notify=True):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}.zip"
        temp_dir = Path(tempfile.mkdtemp(prefix="backup_"))
        db_dump_path = None
        csv_dir = temp_dir / "csv"
        pdf_dir = temp_dir / "pdfs"
        try:
            metadata = {
                "timestamp": timestamp,
                "db_included": False,
                "csv_included": False,
                "pdfs_included": False,
            }
            if self.db_config.get("enabled"):
                db_dump_path = temp_dir / "db.dump"
                db_storage.backup_database(self.db_config, str(db_dump_path))
                metadata["db_included"] = True
                db_storage.export_all_tables_to_csv(self.db_config, str(csv_dir))
                metadata["csv_included"] = True
            if self.archive_dir.exists():
                shutil.copytree(self.archive_dir, pdf_dir, dirs_exist_ok=True)
                metadata["pdfs_included"] = True

            (temp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in temp_dir.rglob("*"):
                    if path.is_file():
                        zf.write(path, path.relative_to(temp_dir))
            self.last_backup_at = timestamp
            self.root.after(0, self._save_ui_prefs)
            if notify:
                self.show_toast(f"Backup saved to {Path(backup_path).name}", kind="success",
                                action_text="Show in Finder", action=lambda: self.reveal_in_finder(backup_path))
        except Exception as exc:
            if notify:
                self.show_message("Backup Error", str(exc), kind="warning")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_backup_now(self):
        """Back up on demand without freezing the window."""
        if self._auto_backup_running:
            self.show_toast("A backup is already running.", kind="warning")
            return
        self.show_toast("Backing up… this can take a while.", seconds=4)
        self._start_auto_backup()

    def _get_auto_backup_interval_seconds(self):
        frequency = (self.auto_backup_frequency_var.get() or "").strip().lower()
        if frequency == "20 minutes":
            return 20 * 60
        if frequency == "weekly":
            return 7 * 24 * 60 * 60
        return 24 * 60 * 60

    def _schedule_auto_backup(self):
        if getattr(self, "_auto_backup_job", None):
            try:
                self.root.after_cancel(self._auto_backup_job)
            except tk.TclError:
                pass
        interval_ms = int(self._get_auto_backup_interval_seconds() * 1000)
        self._auto_backup_job = self.root.after(interval_ms, self._auto_backup_tick)

    def _auto_backup_tick(self):
        self._auto_backup_job = None
        if self.auto_backup_enabled_var.get():
            self._start_auto_backup()
        self._schedule_auto_backup()

    def _start_auto_backup(self):
        if self._auto_backup_running:
            return
        self._auto_backup_running = True
        def _worker():
            try:
                self.run_total_backup()
            finally:
                self._auto_backup_running = False
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def verify_backup(self):
        path = filedialog.askopenfilename(
            title="Verify Backup",
            filetypes=[("Backup ZIP", "*.zip"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = set(zf.namelist())
                missing = []
                if "metadata.json" in names:
                    metadata = json.loads(zf.read("metadata.json").decode("utf-8"))
                    if metadata.get("db_included") and "db.dump" not in names:
                        missing.append("db.dump")
                    if metadata.get("csv_included"):
                        required = {
                            "employees.csv",
                            "payroll_runs.csv",
                            "payroll_entries.csv",
                            "insurance_contributions.csv",
                            "insurance_claims.csv",
                            "documents.csv",
                        }
                        if not required.issubset({Path(n).name for n in names}):
                            missing.append("csv tables")
                else:
                    missing.append("metadata.json")
                if missing:
                    self.show_message("Verify Backup", f"Backup missing: {', '.join(missing)}", kind="warning")
                else:
                    self.show_toast("Backup looks valid.", kind="success")
        except Exception as exc:
            self.show_message("Verify Backup Error", str(exc), kind="warning")

    def _should_run_auto_backup(self):
        if not self.auto_backup_enabled_var.get():
            return False
        if not self.last_backup_at:
            return True
        try:
            last = datetime.datetime.strptime(self.last_backup_at, "%Y%m%d_%H%M%S")
        except Exception:
            return True
        now = datetime.datetime.now()
        if self.auto_backup_frequency_var.get() == "weekly":
            return (now - last).days >= 7
        return (now - last).days >= 1

    def _on_close(self):
        """Quit, running the closing backup visibly instead of freezing."""
        if not self.auto_backup_enabled_var.get():
            self.root.destroy()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Backing up")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Backing up before quitting…", style="Section.TLabel").pack(anchor=tk.W)
        ttk.Label(
            frame,
            text="Auto backup is on, so the database and archived PDFs are being zipped.",
            style="Body.TLabel",
            wraplength=360,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 12))
        progress = ttk.Progressbar(frame, mode="indeterminate", length=320)
        progress.pack(fill=tk.X)
        progress.start(12)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        dialog.grab_set()
        dialog.update_idletasks()

        def _worker():
            try:
                self.run_total_backup(notify=False)
            finally:
                self.root.after(0, self.root.destroy)

        threading.Thread(target=_worker, name="payroll-final-backup", daemon=True).start()

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _run_async(self, name, work, on_done, on_error=None):
        """Run a blocking query off the Tk thread and apply its result on it.

        Each name keeps a generation counter, so a refresh that is superseded
        while it is still running is discarded instead of overwriting the newer
        one - which is what happens when the user changes filters quickly.
        """
        generation = self._async_tokens.get(name, 0) + 1
        self._async_tokens[name] = generation

        def _post(error, result, callback):
            try:
                self.root.after(0, lambda: self._async_finish(name, generation, error, result, callback))
            except tk.TclError:
                # The window closed while the query was still running.
                pass

        def _worker():
            try:
                result = work()
            except Exception as exc:  # surfaced on the UI thread below
                _post(exc, None, on_error)
                return
            _post(None, result, on_done)

        thread = threading.Thread(target=_worker, name=f"payroll-{name}", daemon=True)
        thread.start()

    def _async_finish(self, name, generation, error, result, callback):
        if self._async_tokens.get(name) != generation:
            return
        if error is not None:
            if callback is not None:
                callback(error)
            return
        callback(result)

    def show_toast(self, message, kind="info", seconds=5, action_text=None, action=None):
        """Non-blocking notice in the bottom-right corner.

        Anything the user does not have to acknowledge - guidance, a
        confirmation, a finished export - belongs here rather than in a modal
        dialog, which stops the app until it is dismissed. Errors that need a
        decision still use ``show_message``.
        """
        def _show():
            tokens = self.theme
            accent = {
                "info": tokens.accent,
                "success": tokens.positive,
                "warning": tokens.warning,
                "error": tokens.negative,
            }.get(kind, tokens.accent)

            toast = tk.Frame(
                self.root,
                bg=tokens.surface,
                highlightbackground=tokens.border,
                highlightcolor=tokens.border,
                highlightthickness=1,
                bd=0,
            )
            stripe = tk.Frame(toast, bg=accent, width=4)
            stripe.pack(side=tk.LEFT, fill=tk.Y)
            body = tk.Frame(toast, bg=tokens.surface)
            body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)
            label = tk.Label(
                body,
                text=message,
                bg=tokens.surface,
                fg=tokens.text_primary,
                justify=tk.LEFT,
                wraplength=320,
                font=(tokens.font_base, 11),
            )
            label.pack(anchor=tk.W)
            if action_text and action:
                link = tk.Label(
                    body,
                    text=action_text,
                    bg=tokens.surface,
                    fg=accent,
                    cursor="hand2",
                    font=(tokens.font_base, 11, "bold"),
                )
                link.pack(anchor=tk.W, pady=(6, 0))
                link.bind("<Button-1>", lambda _event: self._run_toast_action(toast, action))
            for widget in (toast, body, label):
                widget.bind("<Button-1>", lambda _event, t=toast: self._dismiss_toast(t))

            self.toasts.append(toast)
            while len(self.toasts) > 3:
                self._dismiss_toast(self.toasts[0])
            self._layout_toasts()
            self.root.after(int(seconds * 1000), lambda: self._dismiss_toast(toast))

        self.root.after(0, _show)

    def _run_toast_action(self, toast, action):
        self._dismiss_toast(toast)
        try:
            action()
        except Exception as exc:  # an action failing must not kill the toast layer
            self.show_message("Error", str(exc), kind="warning")

    def _dismiss_toast(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        try:
            toast.destroy()
        except tk.TclError:
            pass
        self._layout_toasts()

    def _layout_toasts(self):
        """Stack the live toasts upward from the bottom-right corner."""
        offset = 16
        for toast in reversed(self.toasts):
            try:
                toast.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-16, y=-offset)
                toast.lift()
                toast.update_idletasks()
                offset += toast.winfo_reqheight() + 8
            except tk.TclError:
                continue

    def _database_notice(self, container, message):
        """Show an inline 'database is off' panel over a view.

        Refreshing a view the database feeds used to raise a modal warning, so
        moving between tabs with storage disabled meant dismissing a dialog per
        tab. The panel says the same thing without blocking, and offers the
        action that fixes it.
        """
        entry = self._db_notice_panels.get(container)
        if entry is None:
            panel = ttk.Frame(container, style="Empty.TFrame", padding=(16, 10))
            ttk.Label(panel, text="Database storage is off", style="EmptyTitle.TLabel").pack(
                side=tk.LEFT, padx=(0, 12)
            )
            # Pack the button before the expanding body so it keeps its width;
            # otherwise the message absorbs the row and squeezes the action out.
            ttk.Button(
                panel,
                text="Open Database Settings…",
                style="Accent.TButton",
                command=self.open_db_settings,
            ).pack(side=tk.RIGHT, padx=(12, 0))
            body = ttk.Label(
                panel,
                text=message,
                style="EmptyBody.TLabel",
                justify=tk.LEFT,
            )
            body.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # A fixed wraplength either clips (too wide for the column) or wastes
            # the row (too narrow), and the column width depends on the window.
            # Track the label's real width instead, with a guard so re-wrapping
            # cannot feed itself a new <Configure> forever.
            def _rewrap(event, label=body):
                target = max(200, event.width - 8)
                if abs(int(label.cget("wraplength") or 0) - target) > 8:
                    label.configure(wraplength=target)

            body.bind("<Configure>", _rewrap, add="+")
            self._db_notice_panels[container] = (panel, body)
        else:
            panel, body = entry
            body.configure(text=message)
        # Overlaying (place) always hid whatever sat underneath - first a centred
        # card over the KPI grid, then a top strip over the card headings. Adding
        # the notice as a real row below the existing children keeps it visible
        # and non-blocking without covering anything.
        placed = self._place_database_notice(panel, container)
        if not placed:
            try:
                panel.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
            except tk.TclError:
                panel.place(relx=0.0, rely=1.0, relwidth=1.0, anchor=tk.SW)
        panel.lift()

    @staticmethod
    def _place_database_notice(panel, container):
        """Place a database notice after the container's existing grid rows."""
        try:
            column_count, row_count = container.grid_size()
            if column_count or row_count:
                panel.grid(
                    row=row_count,
                    column=0,
                    columnspan=max(column_count, 1),
                    sticky=(tk.W, tk.E),
                    pady=(10, 0),
                )
                return True
        except tk.TclError:
            pass
        return False

    def _clear_database_notice(self, container):
        entry = self._db_notice_panels.get(container)
        if entry:
            panel = entry[0]
            try:
                manager = panel.winfo_manager()
                if manager == "grid":
                    panel.grid_remove()
                elif manager == "pack":
                    panel.pack_forget()
                elif manager == "place":
                    panel.place_forget()
            except tk.TclError:
                pass

    def show_message(self, title, message, kind="info", auto_close_seconds=None):
        """Show dialogs from the main thread."""
        def _show():
            if auto_close_seconds and kind == "info":
                self._show_timed_dialog(title, message, auto_close_seconds)
                return
            if kind == "error":
                messagebox.showerror(title, message)
            elif kind == "warning":
                messagebox.showwarning(title, message)
            else:
                messagebox.showinfo(title, message)
        self.root.after(0, _show)

    def _show_timed_dialog(self, title, message, seconds):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        label = ttk.Label(frame, text=message, justify=tk.LEFT, wraplength=640)
        label.grid(row=0, column=0, sticky=tk.W)
        button = ttk.Button(frame, text="OK", command=dialog.destroy)
        button.grid(row=1, column=0, sticky=tk.E, pady=(12, 0))
        dialog.after(int(seconds * 1000), dialog.destroy)
        dialog.grab_set()

    def _append_processing_log(self, lines):
        log_path = self.report_dir / "processing_log.txt"
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(f"{line}\n")
                handle.write("\n")
        except OSError:
            pass
        self.log_lines(lines)

    def log_lines(self, lines):
        """Append lines to the on-screen processing log, from any thread."""
        text = "\n".join(str(line) for line in lines)
        if not text:
            return

        def _append():
            widget = getattr(self, "log_text", None)
            if widget is None:
                return
            widget.configure(state=tk.NORMAL)
            widget.insert(tk.END, text + "\n")
            widget.see(tk.END)
            widget.configure(state=tk.DISABLED)

        self.root.after(0, _append)

    def _toggle_processing_log(self):
        """Show or hide the live processing log."""
        if self.log_visible:
            self.log_frame.grid_forget()
            self.log_toggle_btn.configure(text="Show log")
        else:
            self.log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(8, 0))
            self.log_toggle_btn.configure(text="Hide log")
        self.log_visible = not self.log_visible

    def _refresh_setup_banner(self):
        """Surface anything that blocks a first run, inline and dismissable.

        Missing dependencies used to appear only as a line of status text, and
        database storage being off was invisible until a view complained.
        """
        banner = getattr(self, "setup_banner", None)
        if banner is None:
            return
        for child in self.setup_banner_actions.winfo_children():
            child.destroy()

        if self.missing_dependencies:
            self.setup_banner_title.configure(text="A required tool is missing")
            self.setup_banner_body.configure(
                text="Payroll Processor needs " + ", ".join(self.missing_dependencies)
                + ". PDF parsing will fail until it is installed."
            )
            ttk.Button(
                self.setup_banner_actions,
                text="Copy install command",
                style="Accent.TButton",
                command=lambda: self._copy_value_to_clipboard("brew install poppler", label="Install command"),
            ).pack(side=tk.LEFT)
            banner.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
            return

        if not self.db_config.get("enabled"):
            self.setup_banner_title.configure(text="Database storage is off")
            self.setup_banner_body.configure(
                text="Reports still work, but the dashboard, analytics, insurance and "
                     "employee views stay empty until storage is on."
            )
            ttk.Button(
                self.setup_banner_actions,
                text="Open Database Settings…",
                style="Accent.TButton",
                command=self.open_db_settings,
            ).pack(side=tk.LEFT)
            banner.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
            return

        banner.grid_forget()

    def _can_edit(self):
        return (
            str(self.db_config.get("role", "editor")).lower() == "editor"
            and not bool(self.edit_lock_var.get())
        )

    def _toggle_edit_lock(self):
        locked = bool(self.edit_lock_var.get())
        self._save_ui_prefs()
        self._update_lock_indicator()
        self.show_toast(
            "Table editing locked." if locked else "Table editing unlocked.",
            kind="info",
            seconds=3,
        )

    def _update_lock_indicator(self):
        if not hasattr(self, "lock_canvas"):
            return
        locked = bool(self.edit_lock_var.get())
        color = self.theme.danger if locked else self.theme.accent
        canvas = self.lock_canvas
        canvas.delete("lock")
        canvas.create_arc(5, 2, 17, 14, start=0, extent=180, style=tk.ARC, width=2, outline=color, tags="lock")
        canvas.create_rectangle(6, 10, 16, 19, fill=color, outline=color, tags="lock")

    def _save_ui_prefs(self):
        prefs = {
            "start_year": self.global_start_year_var.get(),
            "start_month": self.global_start_month_var.get(),
            "end_year": self.global_end_year_var.get(),
            "end_month": self.global_end_month_var.get(),
            "document_type": self.global_doc_type_var.get(),
            "grid_columns": self.analytics_grid_columns if getattr(self, "analytics_grid_columns", None) else None,
            "detail_columns": self.analytics_detail_columns if getattr(self, "analytics_detail_columns", None) else None,
            "monthly_columns": self.analytics_monthly_columns if getattr(self, "analytics_monthly_columns", None) else None,
            "edit_lock": bool(self.edit_lock_var.get()),
            "show_database_tab": bool(self.show_db_tab_var.get()),
            "theme_mode": self.theme_mode_var.get(),
            "window_geometry": self.window_geometry,
            "pdf_archive_dir": str(self.archive_dir) if self.archive_dir_custom else None,
            "backup_dir": str(self.backup_dir),
            "auto_backup_enabled": bool(self.auto_backup_enabled_var.get()),
            "auto_backup_frequency": self.auto_backup_frequency_var.get(),
            "last_backup_at": self.last_backup_at,
            "watch_dir": str(self.watch_dir),
            "watch_enabled": bool(self.watch_enabled_var.get()),
            "watch_interval": int(self.watch_interval_var.get()),
        }
        db_storage.save_ui_prefs(prefs)

    def reveal_in_finder(self, *paths):
        """Reveal the given files or folders in Finder."""
        for path in paths:
            if not path:
                continue
            target = Path(path)
            if target.is_dir():
                subprocess.run(["open", str(target)], check=False)
            else:
                subprocess.run(["open", "-R", str(target)], check=False)

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
        accepted_files = [f for f in files if f.lower().endswith(('.zip', '.pdf'))]

        if not accepted_files:
            messagebox.showwarning("Invalid Files",
                                 "Please drop only ZIP or PDF files containing payroll data.")
            return

        # Add files to list
        for file_path in accepted_files:
            if file_path not in self.zip_files:
                self.zip_files.append(file_path)

        self.update_file_list()
        self.update_ui_state()

    def browse_files(self):
        """Open file browser to select ZIP files."""
        if self.processing:
            return

        files = filedialog.askopenfilenames(
            title="Select Payroll ZIP or PDF Files",
            filetypes=[("Payroll files", "*.zip *.pdf"), ("ZIP files", "*.zip"), ("PDF files", "*.pdf"), ("All files", "*.*")]
        )


        # Add selected files
        for file_path in files:
            if file_path not in self.zip_files:
                self.zip_files.append(file_path)

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

        count = len(self.zip_files)
        if count == 0:
            self.file_count_var.set("No files selected")
        elif count == 1:
            self.file_count_var.set("1 file ready")
        else:
            self.file_count_var.set(f"{count} files ready")

        # The drop hint belongs to the empty state only.
        if self.zip_files:
            self.drop_label.place_forget()
        else:
            self.drop_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def update_ui_state(self):
        """Update button states based on current state."""
        has_files = bool(self.zip_files)
        deps_ready = not self.missing_dependencies

        # Enable/disable buttons based on state
        state = tk.DISABLED if self.processing else tk.NORMAL
        generate_state = state if has_files else tk.DISABLED

        self.browse_btn.configure(state=state)
        self.remove_btn.configure(state=state if has_files else tk.DISABLED)
        self.clear_btn.configure(state=state if has_files else tk.DISABLED)
        self.generate_btn.configure(state=generate_state)

        if not deps_ready:
            self.warn_missing_dependencies()
        self._refresh_setup_banner()

    def _init_watch_state(self):
        if self.watch_enabled_var.get():
            self._prime_watch_seen()
            self._schedule_watch_poll()

    def _prime_watch_seen(self):
        try:
            files = [p for p in self.watch_dir.iterdir() if p.is_file() and p.suffix.lower() in {".zip", ".pdf"}]
        except OSError:
            files = []
        self.watch_seen = {str(p) for p in files}
        self.watch_pending = {}

    def _schedule_watch_poll(self):
        if self.watch_job is not None:
            try:
                self.root.after_cancel(self.watch_job)
            except tk.TclError:
                pass
        interval_ms = max(2, int(self.watch_interval_var.get())) * 1000
        self.watch_job = self.root.after(interval_ms, self._poll_watch_folder)

    def _poll_watch_folder(self):
        if not self.watch_enabled_var.get():
            return
        try:
            candidates = [p for p in self.watch_dir.iterdir() if p.is_file() and p.suffix.lower() in {".zip", ".pdf"}]
        except OSError:
            self._schedule_watch_poll()
            return
        now = time.time()
        ready = []
        for path in candidates:
            key = str(path)
            if key in self.watch_seen:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            pending = self.watch_pending.get(key)
            if not pending:
                self.watch_pending[key] = (size, now)
                continue
            last_size, last_time = pending
            if size != last_size:
                self.watch_pending[key] = (size, now)
                continue
            if now - last_time < 2:
                continue
            self.watch_pending.pop(key, None)
            self.watch_seen.add(key)
            ready.append(str(path))
        if ready:
            self._process_watch_files(ready)
        self._schedule_watch_poll()

    def _process_watch_files(self, paths):
        if not paths:
            return
        if self.processing:
            self.watch_queue.extend(paths)
            return
        self.update_status(f"Auto-processing {len(paths)} new file(s)...")
        self.generate_reports(files_override=paths, auto_trigger=True)

    def _process_watch_queue(self):
        if self.processing or not getattr(self, "watch_queue", None):
            return
        queued = list(self.watch_queue)
        self.watch_queue.clear()
        self._process_watch_files(queued)

    def generate_reports(self, files_override=None, auto_trigger=False):
        """Generate payroll reports from selected files."""
        files_to_process = list(files_override) if files_override is not None else list(self.zip_files)

        if not files_to_process:
            if not auto_trigger:
                messagebox.showwarning("No Files", "Please select ZIP or PDF files first.")
            return

        if not self.ensure_dependencies_available():
            return

        if self.processing:
            return

        # Determine automatic output locations (summary & detail)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        run_token = uuid.uuid4().hex[:8]
        summary_path = self.employee_reports_dir / f"employee_reports_{timestamp}_{run_token}_summary.xlsx"
        detail_path = self.employee_reports_dir / f"employee_reports_{timestamp}_{run_token}_detail.xlsx"
        summary_path = str(summary_path)
        detail_path = str(detail_path)
        self.last_output_path = summary_path
        self.current_output_paths = (summary_path, detail_path)
        self.output_location_var.set(f"Writing reports to {self.employee_reports_dir}")
        self.update_status("Starting report generation...")

        # Start processing in a separate thread
        self.processing = True
        self.update_ui_state()

        thread = threading.Thread(target=self.process_files, args=(summary_path, detail_path, files_to_process))
        thread.daemon = True
        thread.start()

    def process_files(self, summary_output, detail_output, file_paths):
        """Process the ZIP/PDF files and generate reports."""
        try:
            self.update_status("Initializing...")
            self.update_progress(0)
            log_lines = []
            log_lines.append(f"=== {datetime.datetime.now().isoformat(timespec='seconds')} ===")
            log_lines.append(f"Files: {len(file_paths)}")
            for path in file_paths:
                log_lines.append(f"- {path}")
            receipt_count = 0
            receipt_updates_total = 0
            claim_count = 0
            claim_store_count = None
            claim_store_error = None
            insurance_claims = []

            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                self.temp_dir = temp_dir
                csv_files = []

                total_files = len(file_paths)

                # Process each ZIP file
                for i, file_path in enumerate(file_paths):
                    self.update_status(f"Processing {os.path.basename(file_path)}...")
                    progress = (i / total_files) * 80  # Use 80% for processing
                    self.update_progress(progress)

                    try:
                        # Process the ZIP or PDF file
                        if file_path.lower().endswith(".zip"):
                            zip_result = process_payroll.process_zip(file_path, temp_dir, archive_root=str(self.archive_dir))
                            if isinstance(zip_result, tuple):
                                df = zip_result[0]
                                receipts = zip_result[1] if len(zip_result) > 1 else []
                                claims = zip_result[2] if len(zip_result) > 2 else []
                            else:
                                df, receipts = zip_result, []
                                claims = []
                            for receipt in receipts:
                                receipt_count += 1
                                log_lines.append(
                                    f"Receipt: {receipt['employee_name']} {receipt['amount']:.2f} on {receipt['paid_date']}"
                                )
                                if self.db_config.get("enabled"):
                                    updated = db_storage.mark_paid_by_receipt_total(
                                        self.db_config,
                                        receipt["employee_name"],
                                        receipt["amount"],
                                        receipt["paid_date"],
                                        iban=receipt.get("iban"),
                                        beneficiary_name=receipt.get("beneficiary_name"),
                                        payroll_year=receipt.get("payroll_year"),
                                        payroll_month=receipt.get("payroll_month"),
                                    )
                                    receipt_updates_total += updated
                                    log_lines.append(f"Receipt updates: {updated} entries")
                                    if receipt.get("iban") or receipt.get("beneficiary_name"):
                                        iban_updates = db_storage.update_employee_bank_details_by_name(
                                            self.db_config,
                                            receipt["employee_name"],
                                            receipt.get("iban"),
                                            receipt.get("beneficiary_name"),
                                        )
                                        log_lines.append(f"Bank updates: {iban_updates} employees")
                                    archive_path = receipt.get("archive_path")
                                    if archive_path:
                                        archive_note = "stored" if receipt.get("archive_copied") else "exists"
                                        log_lines.append(f"Receipt archived ({archive_note}): {archive_path}")
                                else:
                                    log_lines.append("Receipt skipped (database disabled)")
                            for claim in claims:
                                claim_count += 1
                                insurance_claims.append(claim)
                                claim_month = claim.get("claim_month")
                                claim_year = claim.get("claim_year")
                                if isinstance(claim_month, int) and isinstance(claim_year, int):
                                    claim_label = f"{claim_month:02d}/{claim_year}"
                                else:
                                    claim_label = "Unknown period"
                                archive_path = claim.get("archive_path")
                                if archive_path:
                                    archive_note = "stored" if claim.get("archive_copied") else "exists"
                                    log_lines.append(f"Insurance claim archive ({archive_note}): {archive_path}")
                                log_lines.append(
                                    f"Insurance claim: {claim_label} {claim.get('total_contributions')}"
                                )
                        elif file_path.lower().endswith(".pdf"):
                            receipt = process_payroll.parse_transfer_receipt(file_path)
                            if receipt:
                                receipt_count += 1
                                log_lines.append(
                                    f"Receipt: {receipt['employee_name']} {receipt['amount']:.2f} on {receipt['paid_date']}"
                                )
                                if self.db_config.get("enabled"):
                                    updated = db_storage.mark_paid_by_receipt_total(
                                        self.db_config,
                                        receipt["employee_name"],
                                        receipt["amount"],
                                        receipt["paid_date"],
                                        iban=receipt.get("iban"),
                                        beneficiary_name=receipt.get("beneficiary_name"),
                                        payroll_year=receipt.get("payroll_year"),
                                        payroll_month=receipt.get("payroll_month"),
                                    )
                                    receipt_updates_total += updated
                                    log_lines.append(f"Receipt updates: {updated} entries")
                                    if receipt.get("iban") or receipt.get("beneficiary_name"):
                                        iban_updates = db_storage.update_employee_bank_details_by_name(
                                            self.db_config,
                                            receipt["employee_name"],
                                            receipt.get("iban"),
                                            receipt.get("beneficiary_name"),
                                        )
                                        log_lines.append(f"Bank updates: {iban_updates} employees")
                                else:
                                    log_lines.append("Receipt skipped (database disabled)")
                                archive_info = process_payroll._archive_pdf_for_receipt(
                                    str(self.archive_dir),
                                    file_path,
                                    receipt,
                                )
                                receipt["archive_path"] = archive_info["path"]
                                receipt["archive_copied"] = archive_info["copied"]
                                archive_note = "stored" if archive_info["copied"] else "exists"
                                log_lines.append(f"Receipt archived ({archive_note}): {archive_info['path']}")
                                process_payroll._merge_receipts_after_archiving(
                                    str(self.archive_dir),
                                    [receipt],
                                )
                                for target in receipt.get("merged_into", []):
                                    log_lines.append(f"Receipt merged into: {target}")
                                for target in receipt.get("merge_skipped", []):
                                    log_lines.append(f"Receipt merge skipped: {target}")
                                continue
                            pdf_result = process_payroll.process_pdf_file(file_path, temp_dir, archive_root=str(self.archive_dir))
                            if isinstance(pdf_result, tuple):
                                df = pdf_result[0]
                                claims = pdf_result[1] if len(pdf_result) > 1 else []
                                receipts = pdf_result[2] if len(pdf_result) > 2 else []
                                for claim in claims:
                                    claim_count += 1
                                    insurance_claims.append(claim)
                                    claim_month = claim.get("claim_month")
                                    claim_year = claim.get("claim_year")
                                    if isinstance(claim_month, int) and isinstance(claim_year, int):
                                        claim_label = f"{claim_month:02d}/{claim_year}"
                                    else:
                                        claim_label = "Unknown period"
                                    archive_path = claim.get("archive_path")
                                    if archive_path:
                                        archive_note = "stored" if claim.get("archive_copied") else "exists"
                                        log_lines.append(f"Insurance claim archive ({archive_note}): {archive_path}")
                                    log_lines.append(
                                        f"Insurance claim: {claim_label} {claim.get('total_contributions')}"
                                    )
                                for receipt in receipts:
                                    receipt_count += 1
                                    log_lines.append(
                                        f"Receipt: {receipt['employee_name']} {receipt['amount']:.2f} on {receipt['paid_date']}"
                                    )
                                    if self.db_config.get("enabled"):
                                        updated = db_storage.mark_paid_by_receipt_total(
                                            self.db_config,
                                            receipt["employee_name"],
                                            receipt["amount"],
                                            receipt["paid_date"],
                                            iban=receipt.get("iban"),
                                            beneficiary_name=receipt.get("beneficiary_name"),
                                            payroll_year=receipt.get("payroll_year"),
                                            payroll_month=receipt.get("payroll_month"),
                                        )
                                        receipt_updates_total += updated
                                        log_lines.append(f"Receipt updates: {updated} entries")
                                        if receipt.get("iban") or receipt.get("beneficiary_name"):
                                            iban_updates = db_storage.update_employee_bank_details_by_name(
                                                self.db_config,
                                                receipt["employee_name"],
                                                receipt.get("iban"),
                                                receipt.get("beneficiary_name"),
                                            )
                                            log_lines.append(f"Bank updates: {iban_updates} employees")
                                    archive_path = receipt.get("archive_path")
                                    if archive_path:
                                        archive_note = "stored" if receipt.get("archive_copied") else "exists"
                                        log_lines.append(f"Receipt archived ({archive_note}): {archive_path}")
                            else:
                                df = pdf_result
                        else:
                            continue

                        if not df.empty:
                            log_lines.append(f"Processed: {file_path} ({len(df)} rows)")
                            # Save to temporary CSV
                            csv_path = os.path.join(temp_dir, f"temp_payroll_{i}.csv")
                            df["SourceArchive"] = os.path.basename(file_path)

                            # Normalize numeric fields
                            numeric_cols = [
                                "BasicSalary", "TotalEarnings", "NetPay",
                                "EFKAEmployee", "EFKAEmployer", "TEKAEmployee", "TEKAEmployer"
                            ]
                            for col in numeric_cols:
                                if col in df.columns:
                                    df[col] = df[col].map(process_payroll._parse_amount)

                            df.to_csv(csv_path, index=False)
                            csv_files.append(csv_path)

                    except Exception as e:
                        self.update_status(f"Error processing {os.path.basename(file_path)}: {str(e)}")
                        log_lines.append(f"Error: {file_path} ({e})")
                        continue

                if not csv_files:
                    if self.db_config.get("enabled") and insurance_claims:
                        try:
                            claim_store_count = db_storage.store_insurance_claims(insurance_claims, self.db_config)
                        except Exception as exc:
                            claim_store_error = str(exc)
                            self.show_message(
                                "Database Warning",
                                f"Insurance claims could not be stored:\n\n{claim_store_error}",
                                kind="warning",
                            )
                    if receipt_count or claim_count:
                        summary_text = []
                        if receipt_count:
                            summary_text.append(
                                f"Processed {receipt_count} receipt file(s) (updated {receipt_updates_total} entries)."
                            )
                        if claim_count:
                            if self.db_config.get("enabled"):
                                if claim_store_error:
                                    summary_text.append(f"Insurance claims failed to store ({claim_store_error}).")
                                else:
                                    summary_text.append(f"Insurance claims stored: {claim_store_count} (processed {claim_count}).")
                            else:
                                summary_text.append(f"Insurance claims processed: {claim_count} (database disabled).")
                        self.update_status("Non-payroll files processed.")
                        self._append_processing_log(log_lines)
                        self.show_toast("\n".join(summary_text), kind="success", seconds=10)
                    else:
                        self.update_status("No payroll data found in any files.")
                        self.show_message("No Data", "No payroll data could be extracted from the selected files.", kind="error")
                        self._append_processing_log(log_lines)
                    return

                # Generate employee reports
                self.update_status("Generating employee reports...")
                self.update_progress(85)

                # Load and combine all CSV data
                combined_df = create_employee_reports.load_payroll_data(csv_files)

                if combined_df.empty:
                    self.update_status("No data to process.")
                    self.show_message("No Data", "No valid payroll data found.", kind="error")
                    self._append_processing_log(log_lines)
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
                    if insurance_claims:
                        try:
                            claim_store_count = db_storage.store_insurance_claims(insurance_claims, self.db_config)
                        except Exception as exc:
                            claim_store_error = str(exc)
                            self.show_message(
                                "Database Warning",
                                f"Insurance claims could not be stored:\n\n{claim_store_error}",
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
                    f"• Processed {total_files} files\n"
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
                if receipt_count:
                    summary_text += f"\n• Receipts processed: {receipt_count} (updated {receipt_updates_total} entries)"
                if claim_count:
                    if self.db_config.get("enabled"):
                        if claim_store_error:
                            summary_text += f"\n• Insurance claims: failed to store ({claim_store_error})"
                        else:
                            summary_text += f"\n• Insurance claims: stored {claim_store_count} (processed {claim_count})"
                    else:
                        summary_text += f"\n• Insurance claims processed: {claim_count} (database disabled)"

                self.root.after(0, lambda: self.output_location_var.set(
                    f"Last run wrote {Path(summary_output).name} and {Path(detail_output).name}"
                ))
                log_lines.append(f"Summary: {summary_output}")
                log_lines.append(f"Detail: {detail_output}")
                if self.db_config.get("enabled"):
                    if db_error:
                        log_lines.append(f"Database: failed ({db_error})")
                    else:
                        log_lines.append(f"Database: stored {db_rows} rows")
                    if claim_count:
                        if claim_store_error:
                            log_lines.append(f"Insurance claims: failed ({claim_store_error})")
                        else:
                            log_lines.append(f"Insurance claims: stored {claim_store_count} rows")
                self._append_processing_log(log_lines)
                self.show_toast(
                    summary_text,
                    kind="success",
                    seconds=12,
                    action_text="Show in Finder",
                    action=lambda: self.reveal_in_finder(summary_output, detail_output),
                )

        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            self.show_message("Error", f"An error occurred while processing:\n\n{str(e)}", kind="error")
            self._append_processing_log([f"=== {datetime.datetime.now().isoformat(timespec='seconds')} ===",
                                         f"Error: {e}"])

        finally:
            self.processing = False
            self.root.after(0, self.update_ui_state)
            if not self.processing:
                self.root.after(2000, lambda: self.update_status("Ready"))
            self.root.after(0, self._process_watch_queue)

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
