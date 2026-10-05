"""Employee profiles with a month-by-month payroll workspace."""

import datetime
import tkinter as tk
from tkinter import ttk

import db_storage
from employee_months import build_monthly_ledger


class EmployeeWorkspaceMixin:
    def create_employees_tab(self):
        self.employees_tab.columnconfigure(0, weight=1)
        self.employees_tab.rowconfigure(1, weight=1)
        self.employee_months = {}
        self.employee_entry_columns = []
        self.employee_selected_period = None
        self.employee_search_job = None

        header = ttk.Frame(self.employees_tab, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(2, weight=1)
        ttk.Label(header, text="Employees", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Refresh", command=self.refresh_employees_tab).grid(row=0, column=1, padx=12)
        self.employee_status_var = tk.StringVar(value="Choose an employee to explore their payroll.")
        ttk.Label(header, textvariable=self.employee_status_var, style="Hint.TLabel").grid(row=0, column=2, sticky="w")

        body = ttk.Frame(self.employees_tab, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        list_frame = ttk.Frame(body, style="App.TFrame")
        list_frame.grid(row=0, column=0, sticky="ns", padx=(0, 16))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(2, weight=1)
        ttk.Label(list_frame, text="Find an employee", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        search = ttk.Entry(list_frame, textvariable=self.employee_search_var, width=26)
        search.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        search.bind("<KeyRelease>", self._schedule_employee_search)
        list_table = ttk.Frame(list_frame, style="App.TFrame")
        list_table.grid(row=2, column=0, sticky="nsew")
        self.employees_tree = self._employee_tree(list_table, [
            ("code", "Code", 65), ("name", "Name", 205),
        ], height=16)
        self.employees_tree.bind("<<TreeviewSelect>>", self._on_employee_select)

        detail = ttk.Frame(body, style="App.TFrame")
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(2, weight=1)
        self.employee_heading_var = tk.StringVar(value="Choose an employee")
        ttk.Label(detail, textvariable=self.employee_heading_var, style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(detail, text="Select a month to see its totals and payslips.", style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 12))
        self.employee_notebook = ttk.Notebook(detail, style="App.TNotebook")
        self.employee_notebook.grid(row=2, column=0, sticky="nsew")
        monthly = ttk.Frame(self.employee_notebook, padding=12, style="App.TFrame")
        profile = ttk.Frame(self.employee_notebook, padding=12, style="App.TFrame")
        history = ttk.Frame(self.employee_notebook, padding=12, style="App.TFrame")
        self.employee_notebook.add(monthly, text="Monthly payroll")
        self.employee_notebook.add(profile, text="Profile")
        self.employee_notebook.add(history, text="Payment history")
        self._build_employee_monthly_tab(monthly)
        self._build_employee_profile_tab(profile)
        self._build_employee_history_tab(history)

    def _employee_tree(self, parent, headings, height=6):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tree = ttk.Treeview(parent, columns=[h[0] for h in headings], show="headings", selectmode="browse", height=height)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for key, title, width in headings:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=width, stretch=True, anchor="w")
        return tree

    def _build_employee_monthly_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        parent.rowconfigure(5, weight=2)
        toolbar = ttk.Frame(parent, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(toolbar, text="Year", style="Body.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self.employee_year_var = tk.StringVar(value="All years")
        self.employee_year_combo = ttk.Combobox(toolbar, textvariable=self.employee_year_var, values=["All years"], state="readonly", width=12)
        self.employee_year_combo.pack(side=tk.LEFT)
        self.employee_year_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_employee_months())
        ttk.Label(toolbar, text="Months follow the filters above.", style="Hint.TLabel").pack(side=tk.LEFT, padx=12)

        cards = ttk.Frame(parent, style="App.TFrame")
        cards.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.employee_month_kpis = {}
        for index, (key, title) in enumerate([
            ("net_pay", "Net pay"), ("paid", "Paid"), ("due", "Still due"), ("insurance", "Total insurance"),
        ]):
            cards.columnconfigure(index, weight=1, uniform="employee-cards")
            value = tk.StringVar(value="—")
            self.employee_month_kpis[key] = value
            card = ttk.Frame(cards, padding=10, style="Card.TFrame")
            card.grid(row=0, column=index, sticky="ew", padx=(0, 8 if index < 3 else 0))
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=value, style="CardValue.TLabel").pack(anchor="w", pady=(6, 0))

        ttk.Label(parent, text="Monthly totals", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 6))
        totals = ttk.Frame(parent, style="App.TFrame")
        totals.grid(row=3, column=0, sticky="nsew")
        self.employee_monthly_tree = self._employee_tree(totals, [
            ("month", "Month", 110), ("net_pay", "Net pay", 100),
            ("paid", "Paid", 100), ("due", "Still due", 100),
            ("employee_insurance", "Employee ins.", 115), ("employer_insurance", "Employer ins.", 115),
        ], height=6)
        self.employee_monthly_tree.bind("<<TreeviewSelect>>", self._on_employee_month_select)
        self.employee_month_title_var = tk.StringVar(value="No month selected")
        ttk.Label(parent, textvariable=self.employee_month_title_var, style="Body.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 6))
        entries = ttk.Frame(parent, style="App.TFrame")
        entries.grid(row=5, column=0, sticky="nsew")
        self.employee_month_entries_tree = self._employee_tree(entries, [
            ("date", "Payslip date", 100), ("type", "Document", 165),
            ("gross", "Gross pay", 100), ("net", "Net pay", 100), ("status", "Status", 90),
            ("paid_date", "Paid on", 100), ("employee_insurance", "Employee ins.", 115),
            ("employer_insurance", "Employer ins.", 115), ("source", "Source PDF", 240),
        ], height=6)
        self.employee_month_entries_tree.tag_configure("due", foreground=self.theme.warning)
        self.employee_month_entries_tree.tag_configure("paid", foreground=self.theme.positive)

    def _build_employee_profile_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        profile_frame = ttk.LabelFrame(parent, text="Profile", padding=12, style="App.TLabelframe")
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


    def _build_employee_history_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        ttk.Label(parent, text="All payments in the current filter range.", style="Hint.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        notebook = ttk.Notebook(parent, style="App.TNotebook")
        notebook.grid(row=1, column=0, sticky="nsew")
        headings = [("payment_date", "Payslip date", 100), ("document_type", "Document", 165),
                    ("net_pay", "Net pay", 100), ("paid_date", "Paid on", 100), ("source_pdf", "Source PDF", 240)]
        for attribute, label in [("employee_due_tree", "Due"), ("employee_paid_tree", "Paid")]:
            frame = ttk.Frame(notebook, padding=8, style="App.TFrame")
            notebook.add(frame, text=label)
            setattr(self, attribute, self._employee_tree(frame, headings, height=14))

    def _schedule_employee_search(self, _event=None):
        if self.employee_search_job is not None:
            self.root.after_cancel(self.employee_search_job)
        self.employee_search_job = self.root.after(250, self.refresh_employees_tab)

    def refresh_employees_tab(self):
        if not self.db_config.get("enabled"):
            self._database_notice(self.employees_tab,
                "Employee profiles are built from stored payroll entries. Turn storage on to see them.")
            tokens = getattr(self, '_async_tokens', {})
            tokens['employees-list'] = tokens.get('employees-list', 0) + 1
            if getattr(self, 'employees_tree', None):
                self._clear_employee_profile()
            return
        self._clear_database_notice(self.employees_tab)
        if not self.employees_tree:
            return
        if self.employee_search_job is not None:
            self.root.after_cancel(self.employee_search_job)
            self.employee_search_job = None
        search = self.employee_search_var.get().strip()
        config = self.db_config.copy()
        self.employee_status_var.set("Loading employees…")
        self._run_async("employees-list", lambda: db_storage.fetch_employees_list(config, search=search or None),
                        self._apply_employee_list, self._employee_load_error)

    def _apply_employee_list(self, rows):
        if not self.db_config.get('enabled'):
            return
        self.employees_tree.delete(*self.employees_tree.get_children())
        selected = None
        for index, row in enumerate(rows):
            code, name = row[:2]
            item = self.employees_tree.insert("", tk.END, iid=f"employee-{index}", values=(code or "", name or ""))
            if code == self.employee_selected_code:
                selected = item
        self.employee_status_var.set(f"{len(rows)} employee{'s' if len(rows) != 1 else ''}")
        if not rows:
            self._clear_employee_profile()
            self.employee_heading_var.set("No employees match your search")
            return
        selected = selected or self.employees_tree.get_children()[0]
        self.employees_tree.selection_set(selected)
        self.employees_tree.focus(selected)
        self.employees_tree.see(selected)
        self._load_employee_profile(self.employees_tree.item(selected, "values")[0])

    def _on_employee_select(self, _event=None):
        selection = self.employees_tree.selection() if self.employees_tree else ()
        if selection:
            code = self.employees_tree.item(selection[0], "values")[0]
            if code and code != self.employee_selected_code:
                self._load_employee_profile(code)

    def _load_employee_profile(self, employee_code):
        previous_period = self.employee_selected_period if employee_code == self.employee_selected_code else None
        self._clear_employee_profile()
        self.employee_selected_code = employee_code
        self.employee_heading_var.set("Loading employee…")
        config = self.db_config.copy()
        start, end, document_type, search = self._get_global_filters()

        def work():
            profile = db_storage.fetch_employee_profile(config, employee_code)
            columns, rows = db_storage.fetch_employee_payroll_detail(config, employee_code,
                start_date=start, end_date=end, document_type=document_type, search=search)
            return profile, columns, rows, build_monthly_ledger(columns, rows)

        def done(result):
            if self.employee_selected_code != employee_code:
                return
            profile, columns, rows, months = result
            if profile is None:
                self._clear_employee_profile()
                return
            self._apply_employee_profile(profile)
            self.employee_entry_columns = columns
            self.employee_months = {month['period']: month for month in months}
            self.employee_selected_period = previous_period
            years = ["All years"] + [str(year) for year in sorted({p[0] for p in self.employee_months}, reverse=True)]
            self.employee_year_combo['values'] = years
            if self.employee_year_var.get() not in years:
                self.employee_year_var.set("All years")
            self._render_employee_months()
            self._render_employee_history(columns, rows)

        self._run_async("employee-profile", work, done, self._employee_load_error)

    def _apply_employee_profile(self, profile):
        code, name, iban, beneficiary, first_worked, last_paid, *rates = profile
        self.employee_heading_var.set(f"{name or 'Employee'} · {code or '—'}")
        for key, value in [("code", code), ("name", name), ("iban", iban), ("beneficiary", beneficiary)]:
            self.employee_profile_vars[key].set(value or "—")
        for key, value in [("first_worked", first_worked), ("last_paid", last_paid)]:
            self.employee_profile_vars[key].set(value.strftime("%d/%m/%Y") if value else "—")
        for key, value in zip(["rate_monthly", "rate_hourly", "rate_daily", "rate_double", "rate_abroad", "rate_abroad_double"], rates):
            self.employee_profile_vars[key].set(self._format_rate(value))

    def _render_employee_months(self):
        year = self.employee_year_var.get()
        periods = [period for period in sorted(self.employee_months, reverse=True)
                   if year == "All years" or str(period[0]) == year]
        self.employee_monthly_tree.delete(*self.employee_monthly_tree.get_children())
        for period in periods:
            month = self.employee_months[period]
            values = [datetime.date(*period, 1).strftime("%b %Y")]
            values.extend(self._format_currency(month[key]) for key in ["net_pay", "paid", "due", "employee_insurance", "employer_insurance"])
            self.employee_monthly_tree.insert("", tk.END, iid=f"{period[0]:04d}-{period[1]:02d}", values=values)
        if not periods:
            self._show_employee_month(None)
            self.employee_month_title_var.set("No payroll entries match the current filters.")
            return
        period = self.employee_selected_period if self.employee_selected_period in periods else periods[0]
        item = f"{period[0]:04d}-{period[1]:02d}"
        self.employee_monthly_tree.selection_set(item)
        self.employee_monthly_tree.focus(item)
        self.employee_monthly_tree.see(item)
        self._show_employee_month(period)

    def _on_employee_month_select(self, _event=None):
        selection = self.employee_monthly_tree.selection()
        if selection:
            period = tuple(map(int, selection[0].split('-')))
            if period in self.employee_months and period != self.employee_selected_period:
                self._show_employee_month(period)

    def _show_employee_month(self, period):
        self.employee_selected_period = period
        self.employee_month_entries_tree.delete(*self.employee_month_entries_tree.get_children())
        for variable in self.employee_month_kpis.values():
            variable.set("—")
        if period is None:
            self.employee_month_title_var.set("No month selected")
            return
        month = self.employee_months[period]
        for key in ('net_pay', 'paid', 'due'):
            self.employee_month_kpis[key].set(self._format_currency(month[key]))
        self.employee_month_kpis['insurance'].set(self._format_currency(month['employee_insurance'] + month['employer_insurance']))
        count = len(month['entries'])
        label = datetime.date(*period, 1).strftime('%B %Y')
        self.employee_month_title_var.set(f"{label} · {count} payslip{'s' if count != 1 else ''}")
        indexes = {column: index for index, column in enumerate(self.employee_entry_columns)}
        for row in month['entries']:
            entry = {column: row[index] for column, index in indexes.items()}
            paid = bool(entry['paid_status'])
            self.employee_month_entries_tree.insert('', tk.END, values=(
                entry['payment_date'].strftime('%d/%m/%Y'),
                str(entry['document_type'] or '').replace('_', ' ').title(),
                self._format_currency(entry['total_earnings'] or 0), self._format_currency(entry['net_pay'] or 0),
                'Paid' if paid else 'Due', entry['paid_date'].strftime('%d/%m/%Y') if entry['paid_date'] else '—',
                self._format_currency(entry['employee_insurance'] or 0), self._format_currency(entry['employer_insurance'] or 0),
                entry['source_pdf'] or '—',
            ), tags=('paid' if paid else 'due',))

    def _render_employee_history(self, columns, rows):
        indexes = {column: index for index, column in enumerate(columns)}
        for tree in (self.employee_due_tree, self.employee_paid_tree):
            tree.delete(*tree.get_children())
        for row in rows:
            entry = {column: row[index] for column, index in indexes.items()}
            tree = self.employee_paid_tree if entry['paid_status'] else self.employee_due_tree
            tree.insert('', tk.END, values=(entry['payment_date'].strftime('%d/%m/%Y'),
                str(entry['document_type'] or '').replace('_', ' ').title(), self._format_currency(entry['net_pay'] or 0),
                entry['paid_date'].strftime('%d/%m/%Y') if entry['paid_date'] else '—', entry['source_pdf'] or '—'))

    def _employee_load_error(self, error):
        self._clear_employee_profile()
        self.employee_status_var.set("Could not load employee data. Refresh to try again.")
        self.show_toast(f"Could not load employee data: {error}", kind="warning")

    def _clear_employee_profile(self):
        self.employee_selected_code = None
        self.employee_selected_period = None
        self.employee_months = {}
        self.employee_entry_columns = []
        tokens = getattr(self, '_async_tokens', {})
        tokens['employee-profile'] = tokens.get('employee-profile', 0) + 1
        for variable in self.employee_profile_vars.values():
            variable.set('—')
        for attribute in ('employee_monthly_tree', 'employee_month_entries_tree', 'employee_due_tree', 'employee_paid_tree'):
            tree = getattr(self, attribute, None)
            if tree is not None:
                tree.delete(*tree.get_children())
        if hasattr(self, 'employee_heading_var'):
            self.employee_heading_var.set('Choose an employee')
        if hasattr(self, 'employee_month_kpis'):
            for variable in self.employee_month_kpis.values():
                variable.set('—')
            self.employee_month_title_var.set('No month selected')
