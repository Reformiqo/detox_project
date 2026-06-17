# ABP2-I419 Phase 5 (Sahil 2026-06-17, Out of BRD) — Production Plan
# vs Actual report (RPT-02). Planned vs produced qty per FG, with
# pending qty + % completion (colour-coded by the formatter).

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
    filters = filters or {}
    return _columns(), _data(filters)


def _columns():
    return [
        {"label": _("Production Plan"), "fieldname": "production_plan",
         "fieldtype": "Link", "options": "Production Plan", "width": 140},
        {"label": _("Planned Date"), "fieldname": "planned_date",
         "fieldtype": "Date", "width": 110},
        {"label": _("FG Item"), "fieldname": "item_code",
         "fieldtype": "Link", "options": "Item", "width": 200},
        {"label": _("Warehouse"), "fieldname": "fg_warehouse",
         "fieldtype": "Link", "options": "Warehouse", "width": 160},
        {"label": _("Planned"), "fieldname": "planned",
         "fieldtype": "Float", "width": 110},
        {"label": _("Produced"), "fieldname": "produced",
         "fieldtype": "Float", "width": 110},
        {"label": _("Pending"), "fieldname": "pending",
         "fieldtype": "Float", "width": 110},
        {"label": _("Completion %"), "fieldname": "completion_pct",
         "fieldtype": "Percent", "width": 110},
    ]


def _data(filters: dict):
    where = ["pp.docstatus < 2", "fg.custom_no_bom = 0 OR pp.custom_no_bom IS NULL OR pp.custom_no_bom = 0 OR pp.custom_no_bom = 1"]
    # Effectively no docstatus restriction beyond not-cancelled.
    where = ["pp.docstatus < 2"]
    params = {}
    if filters.get("production_plan"):
        where.append("pp.name = %(plan)s"); params["plan"] = filters["production_plan"]
    if filters.get("from_date"):
        where.append("pp.posting_date >= %(from_date)s"); params["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        where.append("pp.posting_date <= %(to_date)s"); params["to_date"] = filters["to_date"]
    if filters.get("warehouse"):
        where.append("fg.fg_warehouse = %(wh)s"); params["wh"] = filters["warehouse"]

    rows = frappe.db.sql(
        f"""
        SELECT pp.name AS production_plan,
               fg.planned_date,
               fg.item_code,
               fg.fg_warehouse,
               fg.qty_to_manufacture AS planned,
               COALESCE(fg.custom_total_produced, 0) AS produced
        FROM `tabProduction Plan` pp
        INNER JOIN `tabDetox Production Plan FG` fg ON fg.parent = pp.name
                  AND fg.parenttype = 'Production Plan'
        WHERE {' AND '.join(where)}
        ORDER BY fg.planned_date, pp.name
        """,
        params, as_dict=True,
    )
    out = []
    for r in rows:
        planned = flt(r.planned)
        produced = flt(r.produced)
        pending = max(planned - produced, 0)
        pct = (produced / planned * 100) if planned else 0
        out.append({
            **r,
            "pending": pending,
            "completion_pct": pct,
        })
    return out
