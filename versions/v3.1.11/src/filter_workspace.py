"""Workspace filter summary and an animated overlay drawer."""

import calendar
import datetime
import time
import tkinter as tk
from tkinter import ttk


DOCUMENT_LABELS = {
    "All": "All documents",
    "salary": "Salary",
    "bonus": "Bonus",
    "vacation_allowance": "Vacation allowance",
    "unused_leave_compensation": "Unused leave compensation",
    "other": "Other",
}


class FilterWorkspaceMixin:
    def _create_filter_workspace(self, parent):
        self.global_filter_bar = ttk.Frame(parent, style="App.TFrame", padding=(24, 16, 24, 0))
        self.global_filter_bar.grid(row=0, column=0, sticky="ew")
        self.global_filter_bar.columnconfigure(0, weight=1)
        header = ttk.Frame(self.global_filter_bar, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.filters_expanded = False
        self.filter_workspace = parent
        self._filter_slide_job = None
        self._filter_slide_progress = 0.0
        self.filter_toggle_btn = ttk.Button(header, text="Filters ▾", command=self._toggle_filter_panel)
        self.filter_toggle_btn.grid(row=0, column=0, sticky="nw", padx=(0, 12))
        self.filter_summary_var = tk.StringVar(value="All time · All documents")
        self.filter_summary_label = ttk.Label(
            header, textvariable=self.filter_summary_var, style="Hint.TLabel", justify="left",
        )
        self.filter_summary_label.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.reset_filters_btn = ttk.Button(header, text="Reset", command=self._reset_global_filters)
        self.reset_filters_btn.grid(row=0, column=2, sticky="ne")
        self._add_tooltip(self.reset_filters_btn, "Clear the period, document type and search conditions.")

        # Place the drawer over the workspace, outside the grid's size negotiation.
        self.filter_panel = ttk.Frame(parent, style="Card.TFrame", padding=16)
        self.filter_panel.columnconfigure(0, weight=1)
        self.filter_panel.rowconfigure(1, weight=1)
        title = ttk.Frame(self.filter_panel, style="Surface.TFrame")
        title.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        title.columnconfigure(0, weight=1)
        ttk.Label(title, text="Filters", style="SurfaceTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.close_filters_btn = ttk.Button(title, text="Close ✕", width=8, command=self._close_filter_panel)
        self.close_filters_btn.grid(row=0, column=1, sticky="e")
        self.filter_canvas = tk.Canvas(self.filter_panel, highlightthickness=0, bd=0, bg=self.theme.surface)
        self.filter_canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.filter_panel, orient="vertical", command=self.filter_canvas.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.filter_canvas.configure(yscrollcommand=scrollbar.set)
        self.filter_body = ttk.Frame(self.filter_canvas, style="Surface.TFrame")
        self.filter_body.columnconfigure(0, weight=1)
        body_window = self.filter_canvas.create_window(0, 0, window=self.filter_body, anchor="nw")
        self.filter_canvas.bind("<Configure>", lambda e: self.filter_canvas.itemconfigure(body_window, width=e.width))
        self.filter_body.bind("<Configure>", lambda _e: self.filter_canvas.configure(scrollregion=self.filter_canvas.bbox("all")))
        ttk.Label(
            self.filter_body, text="Changes apply automatically. Close to see your results.",
            style="SurfaceHint.TLabel", wraplength=370,
        ).grid(row=0, column=0, sticky="w", pady=(0, 14))
        presets = ttk.Frame(self.filter_body, style="Surface.TFrame")
        presets.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        presets.columnconfigure((0, 1), weight=1)
        for i, (label, value) in enumerate((("All time", "all"), ("This month", "month"),
                                           ("Last month", "previous"), ("This year", "year"))):
            ttk.Button(presets, text=label, command=lambda p=value: self._set_filter_period(p)).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=(0, 6), pady=(0, 6),
            )

        self.filter_fields = ttk.Frame(self.filter_body, style="Surface.TFrame")
        self.filter_fields.grid(row=2, column=0, sticky="ew")
        self.filter_field_groups = []
        years = ["All"] + [str(year) for year in range(datetime.date.today().year, 1999, -1)]
        for endpoint, label in (("start", "From"), ("end", "Through")):
            group = ttk.Frame(self.filter_fields, style="Surface.TFrame")
            self.filter_field_groups.append(group)
            ttk.Label(group, text=label, style="SurfaceBody.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
            display_var = tk.StringVar(value="January")
            setattr(self, f"filter_{endpoint}_month_label", display_var)
            month_combo = ttk.Combobox(group, textvariable=display_var, values=list(calendar.month_name)[1:], width=11, state="readonly")
            month_combo.grid(row=1, column=0, padx=(0, 6))
            month_combo.bind("<<ComboboxSelected>>", lambda _e, p=endpoint: self._on_filter_month_selected(p))
            setattr(self, f"global_{endpoint}_month_combo", month_combo)
            year_combo = ttk.Combobox(group, textvariable=getattr(self, f"global_{endpoint}_year_var"), values=years, width=6, state="readonly")
            year_combo.grid(row=1, column=1)
            year_combo.bind("<<ComboboxSelected>>", lambda _e, p=endpoint: self._on_filter_year_selected(p))
            setattr(self, f"global_{endpoint}_year_combo", year_combo)
        doc_group = ttk.Frame(self.filter_fields, style="Surface.TFrame")
        self.filter_field_groups.append(doc_group)
        ttk.Label(doc_group, text="Document type", style="SurfaceBody.TLabel").pack(anchor="w", pady=(0, 5))
        self.filter_document_label = tk.StringVar(value="All documents")
        self.global_doc_type_combo = ttk.Combobox(doc_group, textvariable=self.filter_document_label, values=list(DOCUMENT_LABELS.values()), state="readonly", width=26)
        self.global_doc_type_combo.pack(anchor="w")
        self.global_doc_type_combo.bind("<<ComboboxSelected>>", self._on_filter_document_selected)

        search = ttk.Frame(self.filter_body, style="Surface.TFrame")
        search.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        search.columnconfigure(0, weight=1)
        ttk.Label(search, text="Search records", style="SurfaceBody.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.global_search_var = tk.StringVar(value="")
        self.global_search_entry = ttk.Entry(search, textvariable=self.global_search_var)
        self.global_search_entry.grid(row=1, column=0, sticky="ew")
        self.global_search_entry.bind("<KeyRelease>", self._on_global_search)
        self.add_search_clause_btn = ttk.Button(search, text="Add condition", command=self._add_search_clause)
        self.add_search_clause_btn.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.search_clause_frame = ttk.Frame(self.filter_body, style="Surface.TFrame")
        self.search_clause_frame.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.global_filter_status = tk.StringVar(value="")
        ttk.Label(self.filter_body, textvariable=self.global_filter_status, style="SurfaceHint.TLabel").grid(row=5, column=0, sticky="w")
        self.global_window_label_var = tk.StringVar(value="All months")
        footer = ttk.Frame(self.filter_panel, style="Surface.TFrame")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(footer, text="Reset filters", command=self._reset_global_filters).pack(side="left")
        ttk.Button(footer, text="Show results", style="Accent.TButton", command=self._close_filter_panel).pack(side="right")
        for row, group in enumerate(self.filter_field_groups):
            group.grid(row=row, column=0, sticky="w", pady=(0, 14))
        parent.bind("<Configure>", self._position_filter_drawer, add="+")
        self.root.bind("<Escape>", self._dismiss_filter_escape, add="+")
        self.root.bind("<Button-1>", self._dismiss_filter_outside, add="+")
        self.root.bind("<MouseWheel>", self._scroll_filter_drawer, add="+")
        self.global_filter_bar.bind("<Configure>", self._reflow_filter_bar)

    def _toggle_filter_panel(self):
        self._set_filter_panel_open(not self.filters_expanded)

    def _close_filter_panel(self):
        self._set_filter_panel_open(False)

    def _set_filter_panel_open(self, expanded, *, animate=True, restore_focus=True):
        if self._filter_slide_job is not None:
            self.root.after_cancel(self._filter_slide_job)
            self._filter_slide_job = None
        self.filters_expanded = expanded
        self._render_filter_chips()
        if expanded:
            self.filter_panel.lift()
            self.close_filters_btn.focus_set()
        elif restore_focus:
            self.filter_toggle_btn.focus_set()
        start = self._filter_slide_progress
        target = 1.0 if expanded else 0.0
        started = time.monotonic()

        def step():
            self._filter_slide_job = None
            elapsed = min(1.0, (time.monotonic() - started) / 0.18) if animate else 1.0
            eased = 1.0 - (1.0 - elapsed) ** 3
            self._filter_slide_progress = start + (target - start) * eased
            if elapsed >= 1 and not expanded:
                self.filter_panel.place_forget()
            else:
                self._position_filter_drawer()
            if elapsed < 1:
                self._filter_slide_job = self.root.after(16, step)

        step()

    def _position_filter_drawer(self, _event=None):
        if not self.filters_expanded and self._filter_slide_progress <= 0:
            return
        available = self.filter_workspace.winfo_width()
        width = min(460, max(1, available - 16))
        top = self.global_filter_bar.winfo_height()
        height = max(1, self.filter_workspace.winfo_height() - top)
        self.filter_panel.place(
            x=round(available - width * self._filter_slide_progress), y=top,
            width=width, height=height,
        )
        self.filter_panel.lift()

    def _filter_contains(self, widget, container):
        while widget is not None:
            if widget is container:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _dismiss_filter_escape(self, _event=None):
        if self.filters_expanded:
            self._close_filter_panel()
            return "break"

    def _dismiss_filter_outside(self, event):
        if (self.filters_expanded
                and not self._filter_contains(event.widget, self.filter_panel)
                and not self._filter_contains(event.widget, self.global_filter_bar)):
            self._set_filter_panel_open(False, restore_focus=False)

    def _scroll_filter_drawer(self, event):
        if self.filters_expanded and self._filter_contains(event.widget, self.filter_body):
            # Let comboboxes handle their own wheel events.
            if isinstance(event.widget, ttk.Combobox):
                return
            delta = event.delta
            if delta:
                steps = max(1, abs(int(delta)) // 120)
                self.filter_canvas.yview_scroll(-steps if delta > 0 else steps, "units")
                return "break"

    def _reflow_filter_bar(self, _event=None):
        available = self.global_filter_bar.winfo_width() - 48
        if available <= 0:
            return
        summary_width = available - self.filter_toggle_btn.winfo_reqwidth() - self.reset_filters_btn.winfo_reqwidth() - 28
        self.filter_summary_label.configure(wraplength=max(120, summary_width))
        self._position_filter_drawer()

    def _sync_filter_controls(self):
        """Keep human-readable controls in sync with persisted numeric values."""
        if not hasattr(self, "filter_document_label"):
            return
        for endpoint in ("start", "end"):
            month = int(getattr(self, f"global_{endpoint}_month_var").get())
            getattr(self, f"filter_{endpoint}_month_label").set(calendar.month_name[month])
            enabled = getattr(self, f"global_{endpoint}_year_var").get() != "All"
            getattr(self, f"global_{endpoint}_month_combo").configure(state="readonly" if enabled else "disabled")
        self.filter_document_label.set(DOCUMENT_LABELS.get(self.global_doc_type_var.get(), "All documents"))

    def _on_filter_year_selected(self, endpoint):
        other = "end" if endpoint == "start" else "start"
        year = getattr(self, f"global_{endpoint}_year_var").get()
        other_year = getattr(self, f"global_{other}_year_var")
        if year == "All":
            other_year.set("All")
        elif other_year.get() == "All":
            other_year.set(year)
            getattr(self, f"global_{other}_month_var").set(getattr(self, f"global_{endpoint}_month_var").get())
        self._align_filter_range(endpoint)
        self._on_global_filter_change()

    def _on_filter_month_selected(self, endpoint):
        name = getattr(self, f"filter_{endpoint}_month_label").get()
        getattr(self, f"global_{endpoint}_month_var").set(f"{list(calendar.month_name).index(name):02d}")
        self._align_filter_range(endpoint)
        self._on_global_filter_change()

    def _align_filter_range(self, endpoint):
        if "All" in (self.global_start_year_var.get(), self.global_end_year_var.get()):
            return
        start = (int(self.global_start_year_var.get()), int(self.global_start_month_var.get()))
        end = (int(self.global_end_year_var.get()), int(self.global_end_month_var.get()))
        if end < start:
            other = "end" if endpoint == "start" else "start"
            for part in ("year", "month"):
                getattr(self, f"global_{other}_{part}_var").set(getattr(self, f"global_{endpoint}_{part}_var").get())

    def _on_filter_document_selected(self, _event=None):
        reverse = {label: value for value, label in DOCUMENT_LABELS.items()}
        self.global_doc_type_var.set(reverse[self.filter_document_label.get()])
        self._on_global_filter_change()

    def _set_filter_period(self, preset, today=None):
        today = today or datetime.date.today()
        if preset == "all":
            self.global_start_year_var.set("All")
            self.global_end_year_var.set("All")
        else:
            if preset == "previous":
                today = today.replace(day=1) - datetime.timedelta(days=1)
            self.global_start_year_var.set(str(today.year))
            self.global_end_year_var.set(str(today.year))
            self.global_start_month_var.set("01" if preset == "year" else f"{today.month:02d}")
            self.global_end_month_var.set("12" if preset == "year" else f"{today.month:02d}")
        self._on_global_filter_change()

    def _render_filter_chips(self):
        """Show the applied scope even when the controls are collapsed."""
        if not hasattr(self, "filter_summary_var"):
            return
        self._sync_filter_controls()
        chips = self._active_filter_chips()
        period = self.global_window_label_var.get()
        parts = ["All time" if period == "All months" else period,
                 DOCUMENT_LABELS.get(self.global_doc_type_var.get(), "All documents")]
        for label, _clear in chips:
            if not label.startswith(("Period:", "Document:")):
                parts.append(label if len(label) <= 48 else label[:45] + "…")
        self.filter_summary_var.set(" · ".join(parts))
        count = len(chips)
        arrow = "›" if self.filters_expanded else "‹"
        self.filter_toggle_btn.configure(text=f"Filters{f' ({count})' if count else ''} {arrow}")
        self.reset_filters_btn.state(["!disabled"] if chips else ["disabled"])
        self.add_search_clause_btn.state(["disabled"] if len(self.search_clauses) >= 2 else ["!disabled"])
