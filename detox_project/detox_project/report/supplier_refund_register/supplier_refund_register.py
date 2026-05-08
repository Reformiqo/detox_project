"""ABP2-I225 FR-12 — Supplier Refund Register.

One row per refund Payment Entry — refund PE No., Posting Date, Supplier,
Original PE, list of impacted PIs, Amount, Refund Reason, Status (docstatus
+ workflow if any).

A refund Payment Entry is one with `custom_is_refund=1`, `payment_type=Receive`,
`party_type=Supplier`. The `custom_original_payment_entry` field links to
the outward Pay PE that was being reversed.

Filters (FR-12):
  - From / To Date — default last fiscal year-to-date.
  - Company — restricts to one of the 3 detox companies.
  - Supplier — narrow to a single supplier.
  - Refund Reason — match the FRD's 5 Select options.
  - Status — Submitted (docstatus=1) / Cancelled (docstatus=2) / All.

Standalone — no joins to detox_waste_management; only depends on Custom
Fields shipped via that app's fixture (custom_is_refund,
custom_refund_reason, custom_original_payment_entry, custom_refund_date).
On sites without those fields, the report degrades to "no rows" rather
than throwing.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = _columns()
    data = _data(filters)
    return columns, data


def _columns():
    return [
        {"label": _("Refund PE"), "fieldname": "name", "fieldtype": "Link",
         "options": "Payment Entry", "width": 160},
        {"label": _("Refund Date"), "fieldname": "posting_date",
         "fieldtype": "Date", "width": 110},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link",
         "options": "Company", "width": 220},
        {"label": _("Supplier"), "fieldname": "party", "fieldtype": "Link",
         "options": "Supplier", "width": 200},
        {"label": _("Original PE"), "fieldname": "custom_original_payment_entry",
         "fieldtype": "Link", "options": "Payment Entry", "width": 160},
        {"label": _("Purchase Invoices"), "fieldname": "pis_pretty",
         "fieldtype": "Data", "width": 250},
        {"label": _("Refund Amount"), "fieldname": "paid_amount",
         "fieldtype": "Currency", "width": 130},
        {"label": _("Refund Reason"), "fieldname": "custom_refund_reason",
         "fieldtype": "Data", "width": 150},
        {"label": _("Status"), "fieldname": "status_label",
         "fieldtype": "Data", "width": 100},
    ]


def _data(filters):
    """Return the report rows.

    Robust to sites that don't yet have the refund Custom Fields — if
    `custom_is_refund` is missing on Payment Entry, return [] silently.
    """
    if not frappe.get_meta("Payment Entry").has_field("custom_is_refund"):
        return []

    where = ["pe.custom_is_refund = 1",
             "pe.payment_type = 'Receive'",
             "pe.party_type = 'Supplier'"]
    args = {}

    if filters.get("from_date"):
        where.append("pe.posting_date >= %(from_date)s")
        args["from_date"] = filters.from_date
    if filters.get("to_date"):
        where.append("pe.posting_date <= %(to_date)s")
        args["to_date"] = filters.to_date
    if filters.get("company"):
        where.append("pe.company = %(company)s")
        args["company"] = filters.company
    if filters.get("supplier"):
        where.append("pe.party = %(supplier)s")
        args["supplier"] = filters.supplier
    if filters.get("refund_reason"):
        where.append("pe.custom_refund_reason = %(refund_reason)s")
        args["refund_reason"] = filters.refund_reason

    status = (filters.get("status") or "Submitted").strip()
    if status == "Submitted":
        where.append("pe.docstatus = 1")
    elif status == "Cancelled":
        where.append("pe.docstatus = 2")
    elif status == "Draft":
        where.append("pe.docstatus = 0")
    # "All" → no filter

    where_clause = " AND ".join(where)

    parents = frappe.db.sql(f"""
        SELECT
            pe.name, pe.posting_date, pe.company, pe.party,
            pe.paid_amount, pe.custom_refund_reason,
            pe.custom_original_payment_entry, pe.docstatus
        FROM `tabPayment Entry` pe
        WHERE {where_clause}
        ORDER BY pe.posting_date DESC, pe.name DESC
    """, args, as_dict=True)

    if not parents:
        return []

    # Fetch references for all the refund PEs in a single query
    pe_names = tuple(p.name for p in parents)
    refs = frappe.db.sql("""
        SELECT parent, reference_name, allocated_amount
        FROM `tabPayment Entry Reference`
        WHERE parent IN %(pes)s
          AND parenttype = 'Payment Entry'
          AND reference_doctype = 'Purchase Invoice'
        ORDER BY parent, idx
    """, {"pes": pe_names}, as_dict=True)
    by_pe: dict[str, list[str]] = {}
    for r in refs:
        by_pe.setdefault(r.parent, []).append(
            f"{r.reference_name} ({flt(r.allocated_amount):,.2f})"
        )

    rows = []
    for p in parents:
        rows.append({
            "name": p.name,
            "posting_date": p.posting_date,
            "company": p.company,
            "party": p.party,
            "custom_original_payment_entry": p.custom_original_payment_entry,
            "pis_pretty": ", ".join(by_pe.get(p.name, [])) or "—",
            "paid_amount": flt(p.paid_amount),
            "custom_refund_reason": p.custom_refund_reason or "",
            "status_label": _docstatus_label(p.docstatus),
        })
    return rows


def _docstatus_label(ds):
    return {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(ds or 0, "Unknown")
