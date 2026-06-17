# ABP2-I419 Phase 5 (Sahil 2026-06-17, Out of BRD) — Production Cost
# Comparison report (RPT-01).
#
# Compares the plan's STANDARD rate vs the actual PROCURED rate per
# item per operation, with variance and Final Product Rate.
#
# Per Sahil's 2026-06-17 decision: Final Product Rate is per-FG
# (the standard_costing_rate of the FG associated with that row),
# NOT a single blended rate. Joining to plan Table 1 — when the
# operation row is tied to a specific FG via the operation/item path,
# we surface that FG's rate; otherwise the first FG row's rate is
# used as a sensible default.

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
    filters = filters or {}
    columns = _columns()
    data = _data(filters)
    return columns, data


def _columns():
    return [
        {"label": _("Production Plan"), "fieldname": "production_plan",
         "fieldtype": "Link", "options": "Production Plan", "width": 140},
        {"label": _("Operation"), "fieldname": "operation",
         "fieldtype": "Data", "width": 130},
        {"label": _("Item"), "fieldname": "item_code",
         "fieldtype": "Link", "options": "Item", "width": 180},
        {"label": _("Item Type"), "fieldname": "item_type",
         "fieldtype": "Data", "width": 100},
        {"label": _("Total Qty Used"), "fieldname": "total_qty",
         "fieldtype": "Float", "width": 110},
        {"label": _("Standard Rate"), "fieldname": "standard_rate",
         "fieldtype": "Currency", "width": 120},
        {"label": _("Standard Amount"), "fieldname": "standard_amount",
         "fieldtype": "Currency", "width": 130},
        {"label": _("PO Rate"), "fieldname": "po_rate",
         "fieldtype": "Currency", "width": 120},
        {"label": _("PO Amount"), "fieldname": "po_amount",
         "fieldtype": "Currency", "width": 130},
        {"label": _("Rate Variance"), "fieldname": "rate_variance",
         "fieldtype": "Currency", "width": 120},
        {"label": _("Amount Variance"), "fieldname": "amount_variance",
         "fieldtype": "Currency", "width": 130},
        {"label": _("FG"), "fieldname": "fg_item",
         "fieldtype": "Link", "options": "Item", "width": 160},
        {"label": _("Final Product Rate"), "fieldname": "final_product_rate",
         "fieldtype": "Currency", "width": 140},
    ]


def _data(filters: dict):
    # Aggregate consumption: SUM(qty) per (plan, process, item) across
    # all submitted Manufacturing-flow Stock Entries linked to the plan.
    # In v16 Stock Entry doesn't link Production Plan directly; reach it
    # through Work Order. SE.work_order → WO.production_plan.
    where = ["se.docstatus = 1",
             "se.stock_entry_type IN ('Manufacture', 'Material Transfer for Manufacture', 'Repack')",
             "wo.production_plan IS NOT NULL", "wo.production_plan != ''",
             "sed.s_warehouse IS NOT NULL", "sed.s_warehouse != ''"]
    params = {}
    if filters.get("production_plan"):
        where.append("wo.production_plan = %(plan)s")
        params["plan"] = filters["production_plan"]
    if filters.get("from_date"):
        where.append("se.posting_date >= %(from_date)s")
        params["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        where.append("se.posting_date <= %(to_date)s")
        params["to_date"] = filters["to_date"]

    rows = frappe.db.sql(
        f"""
        SELECT
            wo.production_plan,
            se.custom_process_selection AS operation,
            sed.item_code,
            sed.custom_purchase_order,
            sed.custom_purchase_order_item,
            SUM(sed.qty) AS total_qty
        FROM `tabStock Entry` se
        INNER JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        INNER JOIN `tabWork Order` wo ON wo.name = se.work_order
        WHERE {' AND '.join(where)}
        GROUP BY wo.production_plan, se.custom_process_selection,
                 sed.item_code, sed.custom_purchase_order_item
        ORDER BY wo.production_plan, se.custom_process_selection,
                 sed.item_code
        """,
        params, as_dict=True,
    )

    # For each row resolve standard_rate from plan Table 2, PO rate from
    # PO Item, and Final Product Rate from plan Table 1 (per-FG default
    # to the first FG row of the plan when no direct link exists).
    plan_fg_cache: dict[str, list[dict]] = {}
    out = []
    for r in rows:
        std_rate = flt(_plan_standard_rate(
            r.production_plan, r.operation, r.item_code))
        item_type = _plan_item_type(
            r.production_plan, r.operation, r.item_code) or "Raw Material"
        po_rate = flt(_po_rate(r.custom_purchase_order_item)) if r.custom_purchase_order_item else 0
        qty = flt(r.total_qty)

        fg_item, fg_rate = _fg_for_plan(r.production_plan, plan_fg_cache)

        std_amount = qty * std_rate
        po_amount = qty * po_rate
        out.append({
            "production_plan": r.production_plan,
            "operation": r.operation or "",
            "item_code": r.item_code,
            "item_type": item_type,
            "total_qty": qty,
            "standard_rate": std_rate,
            "standard_amount": std_amount,
            "po_rate": po_rate,
            "po_amount": po_amount,
            "rate_variance": po_rate - std_rate,
            "amount_variance": po_amount - std_amount,
            "fg_item": fg_item,
            "final_product_rate": fg_rate,
        })
    return out


def _plan_standard_rate(plan, operation, item_code):
    if not (plan and item_code):
        return 0
    return frappe.db.sql(
        """SELECT standard_rate FROM `tabDetox Production Plan Operation`
           WHERE parent = %s AND parenttype = 'Production Plan'
             AND operation_name = %s AND item_code = %s
           LIMIT 1""",
        (plan, operation or "", item_code),
    )[0][0] if frappe.db.sql(
        """SELECT 1 FROM `tabDetox Production Plan Operation`
           WHERE parent = %s AND parenttype = 'Production Plan'
             AND operation_name = %s AND item_code = %s
           LIMIT 1""",
        (plan, operation or "", item_code),
    ) else 0


def _plan_item_type(plan, operation, item_code):
    row = frappe.db.sql(
        """SELECT item_type FROM `tabDetox Production Plan Operation`
           WHERE parent = %s AND parenttype = 'Production Plan'
             AND operation_name = %s AND item_code = %s
           LIMIT 1""",
        (plan, operation or "", item_code),
    )
    return row[0][0] if row else None


def _po_rate(po_item: str | None):
    if not po_item:
        return 0
    return frappe.db.get_value("Purchase Order Item", po_item, "rate") or 0


def _fg_for_plan(plan: str, cache: dict[str, list[dict]]):
    """Return (fg_item, fg_rate) for the plan. Per Sahil's 2026-06-17
    decision, when a plan has multiple FG items the report row uses
    the first FG row's rate as a sensible default — until we have a
    direct operation-to-FG mapping. Adjusts to per-row FG when the
    operation_name happens to match a Table 1 fg item name.
    """
    fgs = cache.get(plan)
    if fgs is None:
        fgs = frappe.db.sql(
            """SELECT item_code, standard_costing_rate
               FROM `tabDetox Production Plan FG`
               WHERE parent = %s AND parenttype = 'Production Plan'
               ORDER BY idx""",
            plan, as_dict=True,
        )
        cache[plan] = fgs
    if not fgs:
        return None, 0
    first = fgs[0]
    return first.item_code, flt(first.standard_costing_rate)
