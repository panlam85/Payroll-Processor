"""Small Tk calendar picker with optional open-ended dates."""

import calendar
from datetime import date
import tkinter as tk
from tkinter import ttk


class DatePicker(ttk.Frame):
    def __init__(self, parent, variable, *, optional=False):
        super().__init__(parent, style='App.TFrame')
        self.variable = variable
        self.optional = optional
        self.popup = None
        style = ttk.Style(self)
        style.configure('Calendar.TFrame', background='#ffffff')
        style.configure('Calendar.TLabel', background='#ffffff', foreground='#687985', font=('Helvetica', 11))
        style.layout('Calendar.TButton', [('Button.padding', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})])
        style.configure('Calendar.TButton', background='#ffffff', foreground='#182b36', font=('Helvetica', 12), padding=(3, 6), anchor='center')
        style.map('Calendar.TButton', background=[('pressed', '#d9edf3'), ('active', '#edf5f7')])
        style.configure('Selected.Calendar.TButton', background='#d9edf3', foreground='#00657d')
        style.configure('Today.Calendar.TButton', foreground='#00758d')
        self.display = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.field = ttk.Entry(self, textvariable=self.display, width=18, state='readonly', font=('Helvetica', 12), cursor='hand2')
        self.field.grid(row=0, column=0, sticky='ew')
        self.field.bind('<Button-1>', lambda _event: self.open())
        self.field.bind('<Return>', lambda _event: self.open())
        self.field.bind('<space>', lambda _event: self.open())
        self.field.bind('<Down>', lambda _event: self.open())
        self.calendar_icon = tk.PhotoImage(master=self, width=18, height=18)
        for rect in [(2, 4, 16, 5), (2, 15, 16, 16), (2, 4, 3, 16), (15, 4, 16, 16),
                     (5, 2, 6, 6), (12, 2, 13, 6), (3, 7, 15, 8),
                     (5, 10, 7, 12), (10, 10, 12, 12)]:
            self.calendar_icon.put('#516570', to=rect)
        self.button = ttk.Button(self, image=self.calendar_icon, style='Calendar.TButton', command=self.open)
        self.button.grid(row=0, column=1, padx=(4, 0))
        self._trace = variable.trace_add('write', self._refresh)
        self.bind('<Destroy>', self._destroyed, add='+')
        self._refresh()

    def _refresh(self, *_args):
        value = self.variable.get()
        try:
            label = date.fromisoformat(value).strftime('%d %b %Y')
        except ValueError:
            label = 'Ongoing' if self.optional else 'Choose date'
        self.display.set(label)

    def _destroyed(self, event):
        if event.widget is self:
            self.variable.trace_remove('write', self._trace)

    def open(self):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.lift()
            return
        try:
            selected = date.fromisoformat(self.variable.get())
        except ValueError:
            selected = date.today()
        previous_grab = self.grab_current()
        popup = self.popup = tk.Toplevel(self)
        popup.title('End date' if self.optional else 'Start date')
        popup.transient(self.winfo_toplevel())
        popup.overrideredirect(True)
        popup.resizable(False, False)
        popup.configure(background='#cbd8df')
        body = ttk.Frame(popup, padding=12, style='Calendar.TFrame')
        body.pack(fill='both', expand=True, padx=1, pady=1)
        header = ttk.Frame(body, style='Calendar.TFrame')
        header.pack(fill='x', pady=(0, 8))
        month = tk.StringVar(value=calendar.month_name[selected.month])
        year = tk.StringVar(value=str(selected.year))
        months = list(calendar.month_name)[1:]
        grid = ttk.Frame(body, style='Calendar.TFrame')
        grid.pack(fill='both', expand=True)
        error = tk.StringVar()
        owner = self.winfo_toplevel()
        escape_binding = None

        def close():
            if not popup.winfo_exists():
                return
            if escape_binding and owner.winfo_exists():
                owner.unbind('<Escape>', escape_binding)
            popup.grab_release()
            popup.destroy()
            self.popup = None
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.grab_set()
            if self.winfo_exists():
                self.button.focus_set()

        def choose(value):
            self.variable.set(value.isoformat() if value else '')
            close()

        def current():
            number = int(year.get())
            if not 1 <= number <= 9999:
                raise ValueError
            return number, months.index(month.get()) + 1

        def render(_event=None):
            try:
                y, m = current()
            except ValueError:
                error.set('Enter a year from 1 to 9999.')
                for child in grid.winfo_children():
                    child.destroy()
                return
            error.set('')
            for child in grid.winfo_children():
                child.destroy()
            for column, label in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']):
                ttk.Label(grid, text=label, anchor='center', style='Calendar.TLabel').grid(row=0, column=column, padx=3, pady=(4, 8))
            for row, week in enumerate(calendar.monthcalendar(y, m), start=1):
                for column, day in enumerate(week):
                    if day:
                        value = date(y, m, day)
                        day_style = 'Selected.Calendar.TButton' if value == selected and self.variable.get() else ('Today.Calendar.TButton' if value == date.today() else 'Calendar.TButton')
                        button = ttk.Button(grid, text=str(day), width=3, style=day_style, command=lambda d=value: choose(d))
                        button.grid(row=row, column=column, padx=1, pady=1)

        def move(delta):
            try:
                y, m = current()
                index = (y - 1) * 12 + m - 1 + delta
                if not 0 <= index < 9999 * 12:
                    return
                y, m = divmod(index, 12)
                year.set(str(y + 1))
                month.set(months[m])
                render()
            except ValueError:
                render()

        ttk.Button(header, text='‹', width=2, style='Calendar.TButton', command=lambda: move(-1)).pack(side='left')
        month_box = ttk.Combobox(header, values=months, textvariable=month, state='readonly', width=10, font=('Helvetica', 11))
        month_box.pack(side='left', padx=4)
        month_box.bind('<<ComboboxSelected>>', render)
        year_box = ttk.Spinbox(header, from_=1, to=9999, textvariable=year, width=5, font=('Helvetica', 11), command=render)
        year_box.pack(side='left', padx=4)
        year_box.bind('<KeyRelease>', render)
        year_box.bind('<FocusOut>', render)
        ttk.Button(header, text='›', width=2, style='Calendar.TButton', command=lambda: move(1)).pack(side='left')
        ttk.Label(body, textvariable=error, style='Calendar.TLabel').pack(anchor='w')
        ttk.Separator(body).pack(fill='x', pady=(4, 0))
        footer = ttk.Frame(body, style='Calendar.TFrame')
        footer.pack(fill='x', pady=(8, 0))
        ttk.Button(footer, text='Today', width=5, style='Calendar.TButton', command=lambda: choose(date.today())).pack(side='left')
        if self.optional:
            ttk.Button(footer, text='Ongoing', width=7, style='Calendar.TButton', command=lambda: choose(None)).pack(side='left', padx=6)
        ttk.Button(footer, text='Cancel', width=6, style='Calendar.TButton', command=close).pack(side='right')
        popup.protocol('WM_DELETE_WINDOW', close)
        popup.bind('<Escape>', lambda _event: close())
        escape_binding = owner.bind('<Escape>', lambda _event: close(), add='+')
        def outside(event):
            if not (popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width()
                    and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty() + popup.winfo_height()):
                close()
        popup.bind('<Button-1>', outside, add='+')
        render()
        popup.update_idletasks()
        x = min(self.winfo_rootx(), popup.winfo_screenwidth() - popup.winfo_reqwidth() - 12)
        y = min(self.winfo_rooty() + self.winfo_height(), popup.winfo_screenheight() - popup.winfo_reqheight() - 50)
        popup.geometry(f'+{max(0, x)}+{max(30, y)}')
        popup.grab_set()
        popup.focus_force()
