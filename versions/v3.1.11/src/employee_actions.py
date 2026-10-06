"""Review dialogs for employee employment dates and identity merges."""

import tkinter as tk
from tkinter import ttk

import employee_management as management
from date_picker import DatePicker


class EmployeeActionsMixin:
    def _delete_employee(self):
        selection = self.employees_tree.selection()
        if len(selection) != 1 or not self._employee_change_allowed():
            return
        code = str(self.employees_tree.item(selection[0], 'values')[0])
        config = self.db_config.copy()
        self._run_async('employee-delete-preview', lambda: management.preview_delete_employee(config, code),
                        lambda preview: self._show_delete_employee(preview, config) if config == self.db_config else None,
                        lambda error: self.show_message('Delete employee', str(error), kind='warning'))

    def _show_delete_employee(self, preview, config):
        dialog = tk.Toplevel(self.root)
        dialog.title('Delete incorrect employee')
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18, style='App.TFrame')
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f"Delete {preview['code']} — {preview['name'] or 'Unnamed employee'}?",
                  style='Section.TLabel', wraplength=540).pack(anchor='w')
        text = (f"Linked payroll entries: {preview['payroll_count']} ({preview['paid_count']} marked paid)\n"
                f"Net pay removed from totals: {self._format_currency(preview['net_pay'])}\n"
                f"Linked document records: {preview['document_count']}\n\n"
                'This removes the employee and linked payroll, insurance and document records. '
                'Original PDF files stay on disk. An audit snapshot is retained; there is no automatic undo.')
        ttk.Label(frame, text=text, style='Body.TLabel', wraplength=540, justify='left').pack(anchor='w', pady=12)
        approved = tk.BooleanVar(value=not preview['payroll_count'])
        if preview['payroll_count']:
            ttk.Checkbutton(frame, text='Also delete the linked payroll entries shown above', variable=approved,
                            command=lambda: delete_btn.state(['!disabled'] if approved.get() else ['disabled'])).pack(anchor='w', pady=(0, 12))
        error = tk.StringVar()
        ttk.Label(frame, textvariable=error, style='Hint.TLabel', wraplength=540).pack(anchor='w')
        busy = [False]
        def close():
            if not busy[0]:
                dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW', close)
        def remove():
            if busy[0] or not approved.get() or config != self.db_config or not self._can_edit():
                return
            busy[0] = True
            delete_btn.state(['disabled'])
            error.set('Deleting employee…')
            def done(_count):
                busy[0] = False
                dialog.destroy()
                if config == self.db_config:
                    self._close_employee_details()
                    self._clear_employee_profile()
                    self.refresh_employees_tab()
                    self.show_toast('Incorrect employee deleted. Original PDFs are unchanged.', kind='success')
            def failed(exc):
                busy[0] = False
                error.set(f'{exc}\nClose this window and review again.')
            self._run_async('delete-employee', lambda: management.delete_employee(config, preview['code'], preview['revision'],
                            include_payroll=bool(preview['payroll_count'])), done, failed)
        buttons = ttk.Frame(frame, style='App.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        ttk.Button(buttons, text='Cancel', command=close).pack(side='right')
        delete_btn = ttk.Button(buttons, text='Delete employee', command=remove,
                                state='normal' if approved.get() else 'disabled')
        delete_btn.pack(side='right', padx=8)

    def _employee_change_allowed(self):
        if not self._can_edit():
            self.show_toast('Unlock table editing and use the editor role to change employees.', kind='warning')
            return False
        if not self.employee_selected_code:
            self.show_toast('Select an employee first.')
            return False
        return True

    def _sort_employee_directory(self, column):
        if self.employee_sort_column == column:
            self.employee_sort_descending = not self.employee_sort_descending
        else:
            self.employee_sort_column = column
            self.employee_sort_descending = False
        ordered = management.sort_employees(
            [(self.employees_tree.item(i, 'values')[0], self.employees_tree.item(i, 'values')[1], i)
             for i in self.employees_tree.get_children()], column, self.employee_sort_descending)
        for index, row in enumerate(ordered):
            self.employees_tree.move(row[2], '', index)
        self._employee_sort_headings()

    def _employee_sort_headings(self):
        for key, title in [('code', 'Code'), ('name', 'Name')]:
            arrow = (' ↓' if self.employee_sort_descending else ' ↑') if self.employee_sort_column == key else ''
            self.employees_tree.heading(key, text=title + arrow, command=lambda col=key: self._sort_employee_directory(col))

    def _edit_employment_periods(self):
        if not self._employee_change_allowed():
            return
        code, config = self.employee_selected_code, self.db_config.copy()
        self._run_async('employment-editor', lambda: management.fetch_periods(config, code),
                        lambda data: self._show_employment_editor(data, config) if config == self.db_config else None,
                        lambda error: self.show_message('Employment dates', str(error), kind='warning'))

    def _show_employment_editor(self, data, config):
        dialog = tk.Toplevel(self.root)
        dialog.title(f'Employment periods · {data["code"]}')
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18, style='App.TFrame')
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f'{data["name"]} · {data["code"]}', style='Section.TLabel', wraplength=570).pack(anchor='w')
        ttk.Label(frame, text='Choose a start date and an end date, or Ongoing.\nAdd a separate period for each rehire. End dates are inclusive.', style='Body.TLabel', wraplength=570).pack(anchor='w', pady=(8, 12))
        holder = ttk.Frame(frame, style='App.TFrame')
        holder.pack(fill='both', expand=True)
        tree = self._employee_tree(holder, [('start', 'Start date', 200), ('end', 'End date', 200)], height=4)
        periods = list(data['periods'])

        def render():
            tree.delete(*tree.get_children())
            for i, (start, end) in enumerate(periods):
                tree.insert('', 'end', iid=str(i), values=(str(start), str(end) if end else 'Ongoing'))

        render()
        inputs = ttk.Frame(frame, style='App.TFrame')
        inputs.pack(fill='x', pady=12)
        start_var, end_var = tk.StringVar(), tk.StringVar()
        for column, (label, variable) in enumerate([('Start date', start_var), ('End date (optional)', end_var)]):
            ttk.Label(inputs, text=label, style='Body.TLabel').grid(row=0, column=column, sticky='w')
            DatePicker(inputs, variable, optional=(column == 1)).grid(row=1, column=column, sticky='w', padx=(0, 24), pady=(4, 0))
        fallback = tk.BooleanVar(value=data['active'])
        style = ttk.Style(dialog)
        background = style.lookup('App.TFrame', 'background')
        style.configure('Employment.TCheckbutton', background=background)
        style.map('Employment.TCheckbutton', background=[('active', background)])
        ttk.Checkbutton(frame, text='Keep visible as active when no employment dates are set', variable=fallback, style='Employment.TCheckbutton').pack(anchor='w')
        ttk.Label(frame, text='Activity follows the selected filter period, or today when no period is selected.\nHistorical payroll stays available.', style='Hint.TLabel', wraplength=570).pack(anchor='w', pady=8)
        error_var = tk.StringVar()
        ttk.Label(frame, textvariable=error_var, style='Hint.TLabel', wraplength=570).pack(anchor='w', pady=6)
        busy = [False]

        def selected(_event=None):
            if tree.selection():
                start, end = periods[int(tree.selection()[0])]
                start_var.set(str(start))
                end_var.set(str(end) if end else '')
        tree.bind('<<TreeviewSelect>>', selected)

        def change(replace=False):
            if busy[0]:
                return
            try:
                period, = management.normalize_periods([(start_var.get(), end_var.get())])
                if replace:
                    if not tree.selection():
                        raise ValueError('Select a period to update.')
                    periods[int(tree.selection()[0])] = period
                else:
                    periods.append(period)
                periods[:] = management.normalize_periods(periods)
                render()
                error_var.set('')
            except ValueError as error:
                error_var.set(str(error))

        def remove():
            if not busy[0] and tree.selection():
                periods.pop(int(tree.selection()[0]))
                render()

        editing = ttk.Frame(frame, style='App.TFrame')
        editing.pack(fill='x', pady=4)
        for label, command in [('Add period', lambda: change()), ('Update selected', lambda: change(True)), ('Remove selected', remove)]:
            ttk.Button(editing, text=label, command=command).pack(side='left', padx=(0, 6))
        buttons = ttk.Frame(frame, style='App.TFrame')
        buttons.pack(fill='x', pady=(12, 0))

        def close():
            if not busy[0]:
                dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW', close)
        ttk.Button(buttons, text='Cancel', command=close).pack(side='right')

        def save():
            if busy[0] or config != self.db_config or not self._can_edit():
                return
            busy[0] = True
            save_btn.state(['disabled'])
            error_var.set('Saving employment periods…')
            values = list(periods)
            active = fallback.get()

            def done(_result):
                busy[0] = False
                dialog.destroy()
                if config == self.db_config:
                    self.refresh_employees_tab()
                    self.show_toast('Employment periods saved.', kind='success')

            def failed(error):
                busy[0] = False
                save_btn.state(['!disabled'])
                error_var.set(str(error))
            self._run_async('save-employment', lambda: management.save_periods(config, data['code'], values, active, data['revision']), done, failed)

        save_btn = ttk.Button(buttons, text='Save periods', command=save)
        save_btn.pack(side='right', padx=8)

    def _open_employee_merge(self):
        selection = self.employees_tree.selection()
        if len(selection) != 2:
            return
        if not self._employee_change_allowed():
            return
        rows = [self.employees_tree.item(item, 'values')[:2] for item in selection]
        self._show_employee_merge(rows, self.db_config.copy())

    def _show_employee_merge(self, rows, config):
        if len(rows) != 2 or str(rows[0][0]) == str(rows[1][0]):
            return
        rows = management.sort_employees(rows, column='code')
        codes = [str(row[0]) for row in rows]
        dialog = tk.Toplevel(self.root)
        dialog.title('Merge selected employees')
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18, style='App.TFrame')
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Which employee code should remain?', style='Section.TLabel').pack(anchor='w', pady=(0, 12))
        target_var = tk.StringVar(value='')
        choices = []
        for code, name in rows:
            choice = ttk.Radiobutton(frame, text=f'Keep {code} — {name}', variable=target_var,
                                     value=str(code), style='Merge.TRadiobutton')
            choice.pack(anchor='w', pady=6)
            choices.append(choice)
        style = ttk.Style(dialog)
        background = style.lookup('App.TFrame', 'background')
        style.configure('Merge.TRadiobutton', background=background)
        style.map('Merge.TRadiobutton', background=[('active', background)])
        explanation = tk.StringVar(value='Choose one code. The other employee will be merged into it.')
        ttk.Label(frame, textvariable=explanation, style='Body.TLabel', wraplength=560, justify='left').pack(anchor='w', pady=14)
        ttk.Label(frame, text='All payroll rows and employment periods are kept. The retained profile keeps conflicting details.\nThere is no automatic undo; restoring a database backup reverses the merge.',
                  style='Hint.TLabel', wraplength=560, justify='left').pack(anchor='w', pady=(0, 12))
        reviewed = [None]
        busy = [False]
        generation = [0]
        buttons = ttk.Frame(frame, style='App.TFrame')
        buttons.pack(fill='x')

        def close():
            if not busy[0]:
                generation[0] += 1
                dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW', close)

        def preview(*_args):
            if busy[0]:
                return
            generation[0] += 1
            token = generation[0]
            reviewed[0] = None
            merge_btn.state(['disabled'])
            target = target_var.get()
            if target not in codes:
                return
            source = next(code for code in codes if code != target)
            merge_btn.configure(text=f'Merge {source} into {target}')
            explanation.set('Checking selected employees…')

            def done(result):
                if not dialog.winfo_exists() or token != generation[0]:
                    return
                reviewed[0] = result
                text = (f"{result['source_code']} → {result['target_code']} · "
                        f"{result['source_count']} payslips will join {result['target_count']} existing payslips.\n"
                        f"Combined net pay: {self._format_currency(result['combined_net'])}")
                if result['conflicts']:
                    text += '\nDetails kept from the retained profile: ' + ', '.join(result['conflicts'])
                if result['overlaps']:
                    text += f"\n{result['overlaps']} payslips have matching dates, types and amounts. Both copies will remain."
                explanation.set(text)
                merge_btn.state(['!disabled'])

            def failed(error):
                if dialog.winfo_exists() and token == generation[0]:
                    explanation.set(str(error))
            self._run_async('merge-preview', lambda: management.preview_merge(config, source, target), done, failed)

        def merge():
            result = reviewed[0]
            if busy[0] or not result or config != self.db_config or not self._can_edit():
                return
            busy[0] = True
            merge_btn.state(['disabled'])
            for choice in choices:
                choice.state(['disabled'])
            explanation.set('Merging employees…')

            def done(_result):
                busy[0] = False
                dialog.destroy()
                if config == self.db_config:
                    self.employee_selected_code = result['target_code']
                    self.refresh_employees_tab()
                    self.show_toast('Employees merged. Old codes now import into the retained employee.', kind='success')

            def failed(error):
                busy[0] = False
                reviewed[0] = None
                for choice in choices:
                    choice.state(['!disabled'])
                explanation.set(f'{error}\nChoose the retained code again to refresh.')
            self._run_async('merge-employees', lambda: management.merge_employees(config, result['source_code'], result['target_code'], result['revision']), done, failed)

        ttk.Button(buttons, text='Cancel', command=close).pack(side='right')
        merge_btn = ttk.Button(buttons, text='Merge employees', command=merge, state='disabled')
        merge_btn.pack(side='right', padx=8)
        target_var.trace_add('write', preview)
