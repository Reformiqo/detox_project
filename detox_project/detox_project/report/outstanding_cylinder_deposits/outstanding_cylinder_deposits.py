# ABP2-I419 Phase 6 — Outstanding Cylinder Deposits (RPT-09).

from __future__ import annotations

import frappe
from frappe import _


def execute(filters: dict | None = None):
    filters = filters or {}
    return _columns(), _data(filters)


def _columns():
    return [
        {"label": _("Customer"), "fieldname": "customer",
         "fieldtype": "Link", "options": "Customer", "width": 200},
        {"label": _("Customer Name"), "fieldname": "customer_name",
         "fieldtype": "Data", "width": 200},
        {"label": _("Serial No"), "fieldname": "serial_no",
         "fieldtype": "Link", "options": "Serial No", "width": 160},
        {"label": _("Item"), "fieldname": "item_code",
         "fieldtype": "Link", "options": "Item", "width": 180},
        {"label": _("Deposit"), "fieldname": "deposit_amount",
         "fieldtype": "Currency", "width": 120},
        {"label": _("Issue Date"), "fieldname": "issue_date",
         "fieldtype": "Date", "width": 110},
        {"label": _("Age (days)"), "fieldname": "age_days",
         "fieldtype": "Int", "width": 100},
        {"label": _("Status"), "fieldname": "status",
         "fieldtype": "Data", "width": 110},
        {"label": _("Delivery Note"), "fieldname": "delivery_note",
         "fieldtype": "Link", "options": "Delivery Note", "width": 130},
        {"label": _("Sales Invoice"), "fieldname": "sales_invoice",
         "fieldtype": "Link", "options": "Sales Invoice", "width": 130},
    ]


def _data(filters: dict):
    conds = ["status = 'Outstanding'"]
    params: dict[str, object] = {}
    if filters.get("customer"):
        conds.append("customer = %(customer)s")
        params["customer"] = filters["customer"]
    if filters.get("from_date"):
        conds.append("issue_date >= %(from_date)s")
        params["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        conds.append("issue_date <= %(to_date)s")
        params["to_date"] = filters["to_date"]
    rows = frappe.db.sql(
        f"""SELECT customer, customer_name, serial_no, item_code,
                   deposit_amount, issue_date,
                   DATEDIFF(CURDATE(), issue_date) AS age_days,
                   status, delivery_note, sales_invoice
            FROM `tabCylinder Deposit Ledger`
            WHERE {' AND '.join(conds)}
            ORDER BY issue_date""",
        params, as_dict=True,
    )
    return rows
