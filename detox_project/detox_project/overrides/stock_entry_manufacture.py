# ABP2-I419 Phase 3 (Sahil 2026-06-17, Out of BRD) — Stock Entry
# Manufacture customizations. Implements the FRD's Process Logic L08..L12
# (process auto-fetch, target defaults, expense/PO rate fetch) and the
# server side of Validations VAL-08..14.
#
# Wired in hooks.py:
#   Stock Entry:
#     validate -> validate_stock_entry_manufacture
# (the CC/Project guard from Phase 2 stays wired separately).

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


# Stock Entry types covered by Phase 3 logic.
MFG_TYPES = {
    "Manufacture",
    "Material Transfer for Manufacture",
    "Repack",
}


# --------------------------------------------------------------------------
# Whitelisted helper for the Client Script's auto-fetch.
# --------------------------------------------------------------------------
@frappe.whitelist()
def get_operation_rm_rows(production_plan: str, operation: str) -> list[dict]:
    """L08 — return RM/Service rows on the plan for the given operation.

    Used by the SE Manufacture Client Script: when the user picks a
    Process on the SE header, the client clears `items` then calls this
    method to repopulate with the operation's source rows (item, UOM,
    rate, qty_per_unit) — qty starts blank for the user to enter.
    """
    if not production_plan or not operation:
        return []
    rows = frappe.db.sql(
        """SELECT op.item_code, op.item_type, op.standard_uom, op.manual_uom,
                  op.standard_rate, op.qty_per_unit, op.multiply_by,
                  op.cost_center, op.project
           FROM `tabDetox Production Plan Operation` op
           WHERE op.parent = %s
             AND op.parenttype = 'Production Plan'
             AND op.operation_name = %s
           ORDER BY op.idx""",
        (production_plan, operation), as_dict=True,
    )
    enriched = []
    for r in rows:
        uom = r.manual_uom or r.standard_uom
        # Default expense account from Item master (L11).
        expense_account = _default_expense_account(r.item_code)
        # Item name for display.
        item_name = frappe.db.get_value("Item", r.item_code, "item_name") or r.item_code
        enriched.append({
            "item_code": r.item_code,
            "item_name": item_name,
            "item_type": r.item_type,
            "uom": uom,
            "stock_uom": r.standard_uom,
            "basic_rate": flt(r.standard_rate),
            "qty_per_unit": flt(r.qty_per_unit),
            "multiply_by": flt(r.multiply_by),
            "expense_account": expense_account,
            "cost_center": r.cost_center,
            "project": r.project,
        })
    return enriched


def _default_expense_account(item_code: str) -> str | None:
    """Pull the default expense account from Item master (L11)."""
    if not item_code:
        return None
    row = frappe.db.sql(
        """SELECT expense_account FROM `tabItem Default`
           WHERE parent = %s
             AND parenttype = 'Item'
             AND IFNULL(expense_account, '') != ''
           LIMIT 1""",
        item_code,
    )
    return row[0][0] if row else None


@frappe.whitelist()
def get_plan_processes(production_plan: str) -> list[dict]:
    """Sahil Image #30 — the Process dropdown on the SE was empty
    because client-side frappe.db.get_list on the child DocType
    'Detox Production Plan Process' hit permission walls (the user
    has no direct read permission on the child; child perms inherit
    from parent only when accessed via the parent's bag). A
    server-side whitelisted SQL bypasses the issue and returns the
    plan's declared Operations + their Workstation."""
    if not production_plan:
        return []
    return frappe.db.sql(
        """SELECT operation_name, workstation, operation_seq
           FROM `tabDetox Production Plan Process`
           WHERE parent = %s AND parenttype = 'Production Plan'
           ORDER BY operation_seq, idx""",
        production_plan, as_dict=True,
    )


@frappe.whitelist()
def get_fg_defaults(production_plan: str, item_code: str) -> dict:
    """L10 — when a target FG row's item_code is set, return the
    matching Table 1 row's fg_warehouse + standard_costing_rate so the
    Client Script can stamp t_warehouse + basic_rate."""
    if not production_plan or not item_code:
        return {}
    row = frappe.db.sql(
        """SELECT fg_warehouse, standard_costing_rate
           FROM `tabDetox Production Plan FG`
           WHERE parent = %s
             AND parenttype = 'Production Plan'
             AND item_code = %s
           LIMIT 1""",
        (production_plan, item_code), as_dict=True,
    )
    if not row:
        return {}
    return {
        "t_warehouse": row[0].fg_warehouse,
        "basic_rate": flt(row[0].standard_costing_rate),
    }


# --------------------------------------------------------------------------
# Inherit dimensions from the linked Production Plan
# --------------------------------------------------------------------------
def inherit_se_from_production_plan(doc, method=None):
    """Sahil 2026-06-17 — when the SE is linked to a Production Plan,
    pull CC + Project off the plan onto the SE header AND propagate to
    every item row that's missing a cost_center. This stops ERPNext's
    get_default_cost_center from ever needing to fall back to
    Company.default_cost_center (the source of the 'Please set default
    Default Cost Center in Company …' throw).

    Fires on validate so it runs BEFORE ERPNext's standard validation.

    Also folds in the hidden `cost_center` proxy field (added so legacy
    Client Scripts can set_value 'cost_center' without erroring) —
    whatever lands there is copied into custom_cost_center.
    """
    if not _stock_entry_is_in_scope(doc):
        return

    # Fold the proxy value first, in case the plan path doesn't fire.
    proxy_cc = doc.get("cost_center")
    if proxy_cc and not doc.get("custom_cost_center"):
        doc.custom_cost_center = proxy_cc

    plan_name = doc.get("production_plan")
    if not plan_name or not frappe.db.exists("Production Plan", plan_name):
        return
    plan = frappe.db.get_value(
        "Production Plan", plan_name,
        ["custom_cost_center", "project"],
        as_dict=True,
    ) or {}
    cc = plan.get("custom_cost_center")
    pj = plan.get("project")
    if cc and not doc.get("custom_cost_center"):
        doc.custom_cost_center = cc
    if pj and not doc.get("project"):
        doc.project = pj
    # Propagate to every item row — blank rows inherit, populated rows
    # are left alone.
    final_cc = doc.get("custom_cost_center") or cc
    final_pj = doc.get("project") or pj
    for row in (doc.get("items") or []):
        if final_cc and not row.get("cost_center"):
            row.cost_center = final_cc
        if final_pj and not row.get("project"):
            row.project = final_pj


# --------------------------------------------------------------------------
# Validate hook
# --------------------------------------------------------------------------
def validate_stock_entry_manufacture(doc, method=None):
    """Phase 3 validations (VAL-08, VAL-10, VAL-11, VAL-12, VAL-13).

    All fire ONLY on Manufacturing-flow SEs. CC + Project enforcement
    stays in cc_project_guard.validate_stock_entry.
    """
    purpose = (doc.get("stock_entry_type") or "").strip()
    if purpose not in MFG_TYPES:
        return

    # VAL-08 — process_selection mandatory before save / submit.
    if doc.get("production_plan") and not doc.get("custom_process_selection"):
        frappe.throw(
            _("Select a Process before adding production rows."),
            title=_("Process Selection missing"),
        )

    # VAL-11 — production_time bounds.
    pt = flt(doc.get("custom_production_time"))
    if pt:
        uom = (doc.get("custom_time_uom") or "Hours").strip()
        cap = 24.0 if uom == "Hours" else 24 * 60.0
        if pt <= 0 or pt >= cap:
            frappe.throw(
                _("Production Time must be greater than 0 and within a "
                  "single day for the selected unit ({0}).").format(uom),
                title=_("Production Time out of range"),
            )

    # VAL-12 — at least one finished/semi-finished target row with qty > 0
    # on a Manufacture entry.
    if purpose == "Manufacture":
        has_fg = any(
            row.get("is_finished_item") and flt(row.get("qty")) > 0
            for row in (doc.get("items") or [])
        )
        if not has_fg:
            frappe.throw(
                _("Enter at least one finished good with quantity to record "
                  "production."),
                title=_("Finished Good missing"),
            )

    # VAL-10 — every source row must carry a PO link on submit. Block
    # Service rows hard, warn on RM (we use ValidationError block for
    # both — adjust if Sahil reopens with a softer policy).
    is_submit_path = (
        doc.docstatus == 1
        or getattr(doc, "_action", None) == "submit"
        or getattr(doc.flags, "validate_before_submit", False)
    )
    if is_submit_path:
        for idx, row in enumerate(doc.get("items") or [], start=1):
            # Source rows have s_warehouse set.
            if not row.get("s_warehouse"):
                continue
            if not row.get("custom_purchase_order") or not row.get("custom_purchase_order_item"):
                frappe.throw(
                    _("Row #{0}: link a Purchase Order and PO line on the "
                      "source row for accurate variance.").format(idx),
                    title=_("Purchase Order missing on source row"),
                )

    # VAL-13 — over-production warning (cumulative produced > planned).
    # Read total_produced from the matching Table 1 row; soft warning only.
    if purpose == "Manufacture" and doc.get("production_plan"):
        _warn_on_over_production(doc)


def _warn_on_over_production(doc) -> None:
    plan = doc.get("production_plan")
    if not plan:
        return
    # Per FG row in the SE, look up Table 1 planned qty + total_produced.
    for row in (doc.get("items") or []):
        if not row.get("is_finished_item"):
            continue
        qty = flt(row.get("qty"))
        if qty <= 0:
            continue
        planned = frappe.db.sql(
            """SELECT qty_to_manufacture, custom_total_produced
               FROM `tabDetox Production Plan FG`
               WHERE parent = %s AND parenttype = 'Production Plan'
                 AND item_code = %s
               LIMIT 1""",
            (plan, row.item_code), as_dict=True,
        )
        if not planned:
            continue
        plan_qty = flt(planned[0].qty_to_manufacture)
        produced = flt(planned[0].custom_total_produced)
        if (produced + qty) > plan_qty:
            frappe.msgprint(
                _("This entry exceeds the planned quantity for {0} "
                  "({1}/{2}).").format(
                    row.item_code, produced + qty, plan_qty,
                ),
                title=_("Over-production"),
                indicator="orange",
            )


# --------------------------------------------------------------------------
# total_produced rollup — L07 (kept in Phase 3 alongside the related
# validations; called from Stock Entry on_submit / on_cancel).
# --------------------------------------------------------------------------
def rollup_total_produced_on_submit(doc, method=None):
    purpose = (doc.get("stock_entry_type") or "").strip()
    if purpose not in MFG_TYPES or not doc.get("production_plan"):
        return
    _adjust_total_produced(doc, sign=+1)


def rollup_total_produced_on_cancel(doc, method=None):
    purpose = (doc.get("stock_entry_type") or "").strip()
    if purpose not in MFG_TYPES or not doc.get("production_plan"):
        return
    _adjust_total_produced(doc, sign=-1)


def _adjust_total_produced(doc, sign: int) -> None:
    plan = doc.get("production_plan")
    for row in (doc.get("items") or []):
        if not row.get("is_finished_item"):
            continue
        qty = flt(row.get("qty"))
        if qty <= 0:
            continue
        # Update Table 1 row matching this FG item.
        frappe.db.sql(
            """UPDATE `tabDetox Production Plan FG`
               SET custom_total_produced = COALESCE(custom_total_produced, 0) + %s
               WHERE parent = %s AND parenttype = 'Production Plan'
                 AND item_code = %s""",
            (sign * qty, plan, row.item_code),
        )
