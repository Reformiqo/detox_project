# CR-03.6 / CZ-36 — Downtime Analysis (Script Report).
#
# Reason-wise (and, via the Category column, category-wise) downtime
# hours from the Production Downtime Detail rows on Stock Entry
# (Manufacture) documents, filtered by date, cost centre, project and
# produced item. Row durations are stored in each entry's Downtime UOM
# (Hours / Minutes) and normalised to hours here.

from __future__ import annotations

import frappe
from frappe import _


def execute(filters: dict | None = None):
    filters = filters or {}
    return _columns(), _data(filters)


def _columns():
    return [
        {"label": _("Downtime Reason"), "fieldname": "downtime_reason",
         "fieldtype": "Link", "options": "Downtime Reason", "width": 240},
        {"label": _("Category"), "fieldname": "category",
         "fieldtype": "Data", "width": 150},
        {"label": _("Planned"), "fieldname": "is_planned",
         "fieldtype": "Check", "width": 80},
        {"label": _("Events"), "fieldname": "events",
         "fieldtype": "Int", "width": 90},
        {"label": _("Downtime (Hrs)"), "fieldname": "downtime_hours",
         "fieldtype": "Float", "precision": 2, "width": 140},
    ]


def _data(filters: dict):
    conditions = ["se.docstatus < 2", "se.stock_entry_type = 'Manufacture'"]
    params: dict = {}

    if filters.get("from_date"):
        conditions.append("se.posting_date >= %(from_date)s")
        params["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        conditions.append("se.posting_date <= %(to_date)s")
        params["to_date"] = filters["to_date"]
    if filters.get("cost_center"):
        conditions.append("pdd.cost_center = %(cost_center)s")
        params["cost_center"] = filters["cost_center"]
    if filters.get("project"):
        conditions.append("se.project = %(project)s")
        params["project"] = filters["project"]
    if filters.get("item"):
        # Downtime rows have no item — filter on the entry that produced it.
        conditions.append(
            "EXISTS (SELECT 1 FROM `tabStock Entry Detail` sed "
            "WHERE sed.parent = se.name AND sed.item_code = %(item)s)"
        )
        params["item"] = filters["item"]

    where = " AND ".join(conditions)

    # Duration is stored in each entry's Downtime UOM — normalise to hours.
    rows = frappe.db.sql(
        f"""
        SELECT
            pdd.downtime_reason                                  AS downtime_reason,
            COALESCE(dr.category, pdd.category)                  AS category,
            MAX(COALESCE(dr.is_planned, 0))                      AS is_planned,
            COUNT(pdd.name)                                      AS events,
            SUM(CASE WHEN se.custom_downtime_uom = 'Minutes'
                     THEN pdd.duration / 60.0
                     ELSE pdd.duration END)                      AS downtime_hours
        FROM `tabProduction Downtime Detail` pdd
        INNER JOIN `tabStock Entry` se
            ON se.name = pdd.parent AND pdd.parenttype = 'Stock Entry'
        LEFT JOIN `tabDowntime Reason` dr
            ON dr.name = pdd.downtime_reason
        WHERE {where}
        GROUP BY pdd.downtime_reason, COALESCE(dr.category, pdd.category)
        ORDER BY downtime_hours DESC
        """,
        params,
        as_dict=True,
    )
    return rows
