"""Stable alert identities and the dashboard's acknowledgement controls."""

from dataclasses import dataclass
import hashlib
import json
import tkinter as tk
from tkinter import ttk

import db_storage


ALERT_COLUMNS = ("alert", "employee_name", "payment_date", "document_type",
                 "net_pay", "total_insurance")


def alert_key(kind, *identity):
    """Identify the event, independently of names, rounding and view filters."""
    payload = json.dumps([kind, *map(str, identity)], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DashboardAlert:
    key: str
    values: tuple


def anomaly_alerts(columns, rows):
    indices = {name: index for index, name in enumerate(columns)}
    return [
        DashboardAlert(
            alert_key("entry", row[indices["entry_id"]], row[indices["alert"]]),
            tuple(row[indices[name]] for name in ALERT_COLUMNS),
        ) for row in rows
    ]


def jump_alert(row):
    name, code, doc_type, period, _previous, net_pay, _delta, pct = row
    direction = "▲" if (pct or 0) >= 0 else "▼"
    return DashboardAlert(
        alert_key("jump", code, doc_type, period),
        (f"Sudden Jump {direction} {abs(float(pct or 0)):.0f}%",
         name, period, doc_type, net_pay, ""),
    )


class DashboardAlertsMixin:
    def _build_dashboard_alert_controls(self, parent):
        header = ttk.Frame(parent, style="App.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Alerts", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.dashboard_show_acknowledged_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            header, text="Show acknowledged", variable=self.dashboard_show_acknowledged_var,
            command=self._render_dashboard_alerts,
        ).grid(row=0, column=1, sticky="e")
        controls = ttk.Frame(header, style="App.TFrame")
        controls.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.dashboard_acknowledge_btn = ttk.Button(
            controls, text="Acknowledge selected", state="disabled",
            command=lambda: self._set_selected_alerts_acknowledged(True),
        )
        self.dashboard_acknowledge_btn.grid(row=0, column=0, padx=(0, 6))
        self._add_tooltip(self.dashboard_acknowledge_btn,
                          "Hide reviewed alerts, including after refresh and restart.")
        self.dashboard_restore_alert_btn = ttk.Button(
            controls, text="Restore selected", state="disabled",
            command=lambda: self._set_selected_alerts_acknowledged(False),
        )
        self.dashboard_restore_alert_btn.grid(row=0, column=1)
        self.dashboard_alert_status_var = tk.StringVar(value="Double-click an alert to view details.")
        ttk.Label(header, textvariable=self.dashboard_alert_status_var, style="Body.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0),
        )
        self._dashboard_alerts = []
        self._acknowledged_alerts = set()
        self._alert_write_pending = False

    def _render_dashboard_alerts(self):
        """Filter before showing rows, so hidden alerts cannot crowd out new ones."""
        tree = self.dashboard_anomaly_tree
        self._reset_treeview(tree, ALERT_COLUMNS)
        labels = ("Alert", "Employee", "Payslip date", "Document", "Net pay", "Total insurance")
        widths = (180, 220, 110, 160, 110, 130)
        for column, label, width in zip(ALERT_COLUMNS, labels, widths):
            tree.heading(column, text=label)
            tree.column(column, width=width)
        tree.tag_configure("acknowledged", foreground=self.theme.muted)
        show_acknowledged = self.dashboard_show_acknowledged_var.get()
        # Several queries can describe the same event. Show it only once.
        alerts = {alert.key: alert for alert in self._dashboard_alerts}
        hidden = 0
        for key, alert in alerts.items():
            acknowledged = key in self._acknowledged_alerts
            if acknowledged and not show_acknowledged:
                hidden += 1
                continue
            values = list(alert.values)
            if acknowledged:
                values[0] = f"Acknowledged · {values[0]}"
            tree.insert("", tk.END, iid=key, values=values,
                        tags=("acknowledged",) if acknowledged else ())
        self.dashboard_alert_status_var.set(
            f"{len(tree.get_children())} shown · {hidden} acknowledged hidden."
        )
        self._on_dashboard_alert_selection()

    def _on_dashboard_alert_selection(self, _event=None):
        selected = set(self.dashboard_anomaly_tree.selection())
        busy = self._alert_write_pending or not self.db_config.get("enabled")
        self.dashboard_acknowledge_btn.configure(
            state="normal" if selected - self._acknowledged_alerts and not busy else "disabled",
        )
        self.dashboard_restore_alert_btn.configure(
            state="normal" if selected & self._acknowledged_alerts and not busy else "disabled",
        )

    def _set_selected_alerts_acknowledged(self, acknowledged):
        if self._alert_write_pending or not self.db_config.get("enabled"):
            return
        keys = set(self.dashboard_anomaly_tree.selection())
        keys = keys - self._acknowledged_alerts if acknowledged else keys & self._acknowledged_alerts
        if not keys:
            return
        config = dict(self.db_config)
        self._alert_write_pending = True
        self._async_tokens["dashboard"] = self._async_tokens.get("dashboard", 0) + 1
        self._on_dashboard_alert_selection()
        self.dashboard_alert_status_var.set("Saving acknowledgement…" if acknowledged else "Restoring alerts…")

        def saved(_result):
            self._alert_write_pending = False
            if self.db_config == config:
                if acknowledged:
                    self._acknowledged_alerts.update(keys)
                else:
                    self._acknowledged_alerts.difference_update(keys)
                self._render_dashboard_alerts()
            # Re-read after any filter or database change made while saving.
            self.refresh_dashboard()

        def failed(error):
            self._alert_write_pending = False
            self._on_dashboard_alert_selection()
            self.dashboard_alert_status_var.set("Could not save. Alerts remain unchanged.")
            self.show_message("Alert acknowledgement", str(error), kind="warning")
            self.refresh_dashboard()

        self._run_async(
            "alert-acknowledge",
            lambda: db_storage.set_alerts_acknowledged(config, keys, acknowledged),
            saved, failed,
        )
