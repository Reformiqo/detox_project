# ABP2-I419 Phase 4 (Sahil 2026-06-17, Out of BRD) — Subcontracting
# Flow A (v16 native). FR-15..21, FR-32, VAL-04, VAL-15..16, L17.
#
# Subcontract field gating (VAL-04 — subcontractor + service_item +
# service_po + return_item mandatory when is_subcontracted=1) is
# enforced on the child DocType via mandatory_depends_on (Phase 1).
# This module adds:
#   - validate hook on Subcontracting Order / Subcontracting Receipt
#     (CC + Project mandatory, FR-22, VAL-15)
#   - create_service_pos_from_plan(plan) — whitelisted button-backed
#     auto-PO creation (FR-32, L17)
#   - validate_supplied_vs_consumed on Subcontracting Receipt (VAL-16)

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt


# --------------------------------------------------------------------------
# CC + Project enforcement on Subcontracting docs (VAL-15)
# --------------------------------------------------------------------------
def validate_subcontracting_doc(doc, method=None):
    """Shared validate for Subcontracting Order / Subcontracting Receipt.

    Header CC + Project mandatory; row CC + Project inherit from header
    when blank; throw if still blank.
    """
    header_cc = (doc.get("custom_cost_center")
                 or doc.get("cost_center"))
    header_pj = doc.get("project")
    missing = []
    if not header_cc:
        missing.append("Cost Center")
    if not header_pj:
        missing.append("Project")
    if missing:
        verb = "are" if len(missing) > 1 else "is"
        frappe.throw(
            _("{0} {1} mandatory on the {2}.").format(
                " and ".join(missing), verb, doc.doctype),
            title=_("Cost Center / Project missing"),
        )

    # Walk items + supplied_items if present.
    for tbl in ("items", "supplied_items"):
        rows = doc.get(tbl) or []
        for idx, row in enumerate(rows, start=1):
            if not row.get("cost_center") and header_cc and "cost_center" in row.as_dict():
                row.cost_center = header_cc
            if not row.get("project") and header_pj and "project" in row.as_dict():
                row.project = header_pj


def validate_supplied_vs_consumed(doc, method=None):
    """VAL-16 — supplied vs consumed mismatch warning on
    Subcontracting Receipt. Soft warning only; not a block."""
    if doc.doctype != "Subcontracting Receipt":
        return
    sent = defaultdict(float)
    consumed = defaultdict(float)
    for r in (doc.get("supplied_items") or []):
        sent[r.get("rm_item_code") or r.get("item_code")] += flt(r.get("required_qty") or r.get("total_supplied_qty"))
        consumed[r.get("rm_item_code") or r.get("item_code")] += flt(r.get("consumed_qty"))
    for item_code, sent_qty in sent.items():
        if abs(sent_qty - consumed[item_code]) > 0.001:
            frappe.msgprint(
                _("Supplied vs consumed mismatch for {0} "
                  "(supplied {1}, consumed {2}); reconcile via a "
                  "Stock Entry.").format(
                    item_code, sent_qty, consumed[item_code],
                ),
                indicator="orange",
            )


# --------------------------------------------------------------------------
# Auto-create service POs from a submitted Production Plan (L17, FR-32)
# --------------------------------------------------------------------------
@frappe.whitelist()
def create_service_pos_from_plan(plan: str) -> dict:
    """Read all Service-type Table 2 rows on the plan, group by Item's
    default supplier, create one PO per supplier. Pre-validates that
    every Service item has a default supplier (VAL-05).
    """
    if not frappe.db.exists("Production Plan", plan):
        frappe.throw(_("Production Plan {0} does not exist.").format(plan))

    plan_doc = frappe.get_doc("Production Plan", plan)
    if plan_doc.docstatus != 1:
        frappe.throw(_("Production Plan must be submitted before auto-PO."))

    service_rows = [
        op for op in (plan_doc.get("custom_operations") or [])
        if (op.item_type == "Service") and not op.service_po
    ]
    if not service_rows:
        return {"created": [], "skipped": "no service rows without service_po"}

    # VAL-05 — every Service item needs a default supplier first.
    missing_supplier = []
    item_supplier = {}
    for row in service_rows:
        supplier = frappe.db.get_value(
            "Item Default",
            {"parent": row.item_code, "parenttype": "Item"},
            "default_supplier",
        )
        if not supplier:
            missing_supplier.append(row.item_code)
        else:
            item_supplier[row.item_code] = supplier

    if missing_supplier:
        frappe.throw(
            _("These service items have no default supplier: {0}. "
              "Set a default supplier before creating POs.").format(
                ", ".join(sorted(set(missing_supplier)))),
        )

    # Group rows by supplier.
    by_supplier: dict[str, list] = defaultdict(list)
    for row in service_rows:
        by_supplier[item_supplier[row.item_code]].append(row)

    created = []
    for supplier, rows in by_supplier.items():
        po = frappe.new_doc("Purchase Order")
        po.supplier = supplier
        po.schedule_date = plan_doc.posting_date
        po.company = plan_doc.company
        po.project = plan_doc.project
        if po.meta.get_field("cost_center"):
            po.cost_center = plan_doc.get("custom_cost_center")
        for row in rows:
            item = po.append("items", {})
            item.item_code = row.item_code
            uom = row.manual_uom or row.standard_uom
            if uom:
                item.uom = uom
            item.qty = flt(row.multiply_by) or flt(row.qty_per_unit) or 1
            item.rate = flt(row.standard_rate)
            item.schedule_date = plan_doc.posting_date
            if "cost_center" in item.as_dict():
                item.cost_center = row.cost_center or plan_doc.get("custom_cost_center")
            if "project" in item.as_dict():
                item.project = row.project or plan_doc.project
        po.insert(ignore_permissions=True)
        # Link back to plan rows so a second click is a no-op.
        for row in rows:
            row.db_set("service_po", po.name, update_modified=False)
        created.append(po.name)
    return {"created": created, "count": len(created)}
