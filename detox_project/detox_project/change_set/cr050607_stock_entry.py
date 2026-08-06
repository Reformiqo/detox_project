# =====================================================================
# CR-05 + CR-06 + CR-07 — Stock Entry additional-costs & cost-centre
# hardening.  DETOX Production Change-Set FRD (Change Set 1).
#
# Objects delivered here:
#   CZ-42  Service-item routing block + additional-cost completeness &
#          distribution checks           (CL-15, CVAL-10, CVAL-14, CVAL-15)
#   CZ-44  Cost-centre cascade + consistency validation across header,
#          item rows and additional-cost rows   (CL-16, CVAL-11..13)
#   CZ-45  custom_allow_multiple_cost_centers (Check, role-restricted)
#   CZ-46  custom_service_item / custom_uom / custom_remarks /
#          custom_purchase_order / custom_purchase_order_item /
#          custom_cost_center on Landed Cost Taxes and Charges
#   CZ-47  reqd on description / expense_account / amount; conditional
#          read-only amount                        (CVAL-15, CR-07.2)
#   CZ-48  Additional-cost amount = qty x rate server recompute  (CL-20)
#   CZ-49  Production Day Summary print format — service-charge rows
#
# CODE-FIRST: every Custom Field, Property Setter and the Print Format
# is defined and upserted here (authoritative). `install()` is meant to
# be called from detox_project.setup.after_migrate AFTER
# setup_phase3_stock_entry_manufacture() (so the base custom_qty /
# custom_rate exist to insert_after) and AFTER setup_phase5_print_format()
# (so this enhanced Production Day Summary supersedes the base one).
# Fixture sync runs BEFORE after_migrate, so re-asserting last keeps the
# definitions correct after an FC redeploy.
#
# BASELINE THAT ALREADY EXISTS (extended, not rebuilt):
#   - custom_qty (Float) + custom_rate (Currency) on Landed Cost Taxes
#     and Charges — shipped by setup.setup_phase3_stock_entry_manufacture.
#   - _recompute_addl_cost_amount + custom_process_selection auto-fetch
#     in public/js/stock_entry_manufacture.js.
#   - CC/Project guard + Production-Plan inheritance in
#     overrides/cc_project_guard.py and overrides/stock_entry_manufacture.py.
#
# ENVIRONMENT NOTE (reported to the manager): the local bench runs
# ERPNext 16.6.1, where the Stock Entry header has NO standard
# `cost_center` docfield (the DB column exists) and Landed Cost Taxes
# and Charges has NO native `cost_center` at all. The FRD Field Spec
# calls the additional-cost-row Cost Center "STANDARD", but it does not
# exist here, so CR-06.3/CVAL-11 for additional-cost rows are backed by
# a Custom Field `custom_cost_center` added below. It is a
# tracking/consistency field only — ERPNext's additional-cost
# distribution still drives valuation & GL from the finished-goods
# rows (CR-07.5 / CZ-50 keep valuation untouched).
# =====================================================================

from __future__ import annotations

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

MODULE = "Detox Project"
ADDL_COST_CHILD = "Landed Cost Taxes and Charges"

# Manufacturing-flow Stock Entry types the FRD scopes CR-06 (cost-centre)
# and CR-05.4 (service-item routing) to.  Mirrors _stock_entry_is_in_scope
# in overrides/cc_project_guard.py so we short-circuit non-Manufacture SEs.
MFG_TYPES = {
    "Manufacture",
    "Material Transfer for Manufacture",
    "Repack",
    "Send to Subcontractor",
}

# CVAL-12 — only these roles may switch on custom_allow_multiple_cost_centers.
ALLOW_MULTI_ROLES = {"Manufacturing Manager", "Accounts Manager"}


def _in_scope(doc) -> bool:
    return (doc.get("stock_entry_type") or "").strip() in MFG_TYPES


# =====================================================================
# CODE-FIRST install (call from setup.after_migrate)
# =====================================================================
def install() -> None:
    """Upsert all CR-05/06/07 Custom Fields, Property Setters and the
    enhanced Production Day Summary print format. Idempotent."""
    install_custom_fields()
    install_property_setters()
    install_print_format()


def install_custom_fields() -> None:
    """CZ-45 + CZ-46 — new Custom Fields.

    Landed Cost Taxes and Charges (the SE 'Additional Costs' grid):
      custom_service_item, custom_uom, custom_remarks,
      custom_purchase_order, custom_purchase_order_item, custom_cost_center.
    Stock Entry header:
      custom_allow_multiple_cost_centers.
    """
    fields: dict[str, list[dict]] = {
        ADDL_COST_CHILD: [
            # CR-07.3 — what the charge is for. Traceable to a service Item.
            {
                "fieldname": "custom_service_item",
                "label": "Service Item",
                "fieldtype": "Link",
                "options": "Item",
                # Placed after the existing Rate column (custom_rate ships
                # via setup_phase3_stock_entry_manufacture). We deliberately
                # do NOT re-order custom_qty/custom_rate — their placement is
                # pinned by test_abp2_i419_addl_cost_qty_rate.
                "insert_after": "custom_rate",
                "in_list_view": 1,
                "columns": 2,
                "module": MODULE,
                "description": "Service the charge relates to (hydro-testing, filling, job work).",
            },
            # CR-07.3 — UOM auto-fetched from the service item's stock_uom
            # (read-only). Client fetch lives in stock_entry_manufacture.js.
            {
                "fieldname": "custom_uom",
                "label": "UOM",
                "fieldtype": "Link",
                "options": "UOM",
                "insert_after": "custom_service_item",
                "read_only": 1,
                "module": MODULE,
                "description": "Unit for the quantity; fetched from the service item's stock UOM.",
            },
            {
                "fieldname": "custom_remarks",
                "label": "Remarks",
                "fieldtype": "Small Text",
                "insert_after": "custom_uom",
                "module": MODULE,
            },
            # CR-07.4 — link the charge to its service Purchase Order line.
            {
                "fieldname": "custom_purchase_order",
                "label": "Purchase Order",
                "fieldtype": "Link",
                "options": "Purchase Order",
                "insert_after": "custom_remarks",
                "module": MODULE,
                "description": "Service PO this charge is billed against.",
            },
            {
                "fieldname": "custom_purchase_order_item",
                "label": "PO Item",
                "fieldtype": "Link",
                "options": "Purchase Order Item",
                "insert_after": "custom_purchase_order",
                "module": MODULE,
                "description": "Specific PO line; picking it fetches its rate into Rate.",
            },
            # CR-06.3 — additional-cost-row Cost Center. The FRD calls this
            # 'STANDARD', but Landed Cost Taxes and Charges has no native
            # cost_center on this ERPNext, so we add it as a Custom Field.
            # Cascaded from the SE header (CL-16) and consistency-checked
            # (CVAL-11). Tracking only — does not change valuation/GL.
            {
                "fieldname": "custom_cost_center",
                "label": "Cost Center",
                "fieldtype": "Link",
                "options": "Cost Center",
                "insert_after": "custom_purchase_order_item",
                "module": MODULE,
                "description": "Inherited from the Stock Entry header cost centre (CR-06).",
            },
        ],
        "Stock Entry": [
            # CZ-45 / CVAL-12 — role-restricted override to permit rows on a
            # different cost centre than the header. Default off. There is
            # no header cost_center docfield to anchor to on ERPNext 16.6,
            # so anchor on `company` (always present).
            {
                "fieldname": "custom_allow_multiple_cost_centers",
                "label": "Allow Multiple Cost Centers",
                "fieldtype": "Check",
                "default": "0",
                "insert_after": "company",
                "module": MODULE,
                "description": (
                    "When unchecked, every item and additional-cost row must "
                    "carry the header Cost Center. Only a Manufacturing "
                    "Manager or Accounts Manager may switch this on."
                ),
            },
        ],
    }

    to_create: dict[str, list[dict]] = {}
    for dt, specs in fields.items():
        if not frappe.db.exists("DocType", dt):
            continue
        to_create[dt] = specs

    # create_custom_fields(update=True) upserts each field's attributes
    # (idempotent) — the same helper used across setup.py.
    create_custom_fields(to_create, update=True)

    for dt in to_create:
        try:
            frappe.clear_cache(doctype=dt)
        except Exception:
            pass
    print(
        "detox_project: cr050607 install_custom_fields — "
        f"{sum(len(v) for v in to_create.values())} field(s) upserted."
    )


def install_property_setters() -> None:
    """CZ-47 — reqd on description / expense_account / amount and the
    conditional read-only on amount (CR-05.3, CR-07.2, CVAL-15)."""
    specs = [
        # CR-05.3 — a blank description / expense_account was a cause of
        # rows being silently dropped on save. Make them mandatory.
        (ADDL_COST_CHILD, "description", "reqd", "Check", "1"),
        (ADDL_COST_CHILD, "expense_account", "reqd", "Check", "1"),
        (ADDL_COST_CHILD, "amount", "reqd", "Check", "1"),
        # CR-07.2 — amount is auto-computed and locked once BOTH qty & rate
        # are entered; stays directly editable for lump-sum charges. Pure JS
        # eval (client scope is {doc,parent}) — no server helpers.
        (ADDL_COST_CHILD, "amount", "read_only_depends_on", "Data",
         "eval:doc.custom_qty && doc.custom_rate"),
    ]
    for dt, field, prop, ptype, value in specs:
        if not frappe.db.exists("DocType", dt):
            continue
        _upsert_property_setter(dt, field, prop, ptype, value)

    try:
        frappe.clear_cache(doctype=ADDL_COST_CHILD)
    except Exception:
        pass
    print(f"detox_project: cr050607 install_property_setters — {len(specs)} PS upserted.")


def _upsert_property_setter(dt, field, prop, ptype, value) -> None:
    ps_name = f"{dt}-{field}-{prop}"
    if frappe.db.exists("Property Setter", ps_name):
        ps = frappe.get_doc("Property Setter", ps_name)
        changed = False
        if ps.value != value:
            ps.value = value
            changed = True
        if ps.get("module") != MODULE:
            ps.module = MODULE
            changed = True
        if changed:
            ps.save(ignore_permissions=True)
        return
    frappe.get_doc({
        "doctype": "Property Setter",
        "name": ps_name,
        "doctype_or_field": "DocField",
        "doc_type": dt,
        "field_name": field,
        "property": prop,
        "property_type": ptype,
        "value": value,
        "module": MODULE,
    }).insert(ignore_permissions=True)


def install_print_format() -> None:
    """CZ-49 / CR-07.6 — upsert Production Day Summary with a service-charge
    (additional-cost) section showing Qty, Rate and Amount. Supersedes the
    base format shipped by setup.setup_phase5_print_format (so it must be
    called AFTER it in after_migrate)."""
    name = "Production Day Summary"
    if not frappe.db.exists("DocType", "Stock Entry"):
        return
    html = PRODUCTION_DAY_SUMMARY_HTML
    fields = {
        "doc_type": "Stock Entry",
        "module": MODULE,
        "html": html,
        "standard": "Yes",
        "custom_format": 1,
        "print_format_type": "Jinja",
    }
    if frappe.db.exists("Print Format", name):
        pf = frappe.get_doc("Print Format", name)
        dirty = False
        for k, v in fields.items():
            if pf.get(k) != v:
                pf.set(k, v)
                dirty = True
        if dirty:
            pf.save(ignore_permissions=True)
    else:
        frappe.get_doc({"doctype": "Print Format", "name": name, **fields}).insert(
            ignore_permissions=True
        )
    print(f"detox_project: cr050607 install_print_format — '{name}' upserted.")


# =====================================================================
# Document-event hooks (wire in hooks.py doc_events["Stock Entry"])
# =====================================================================
def before_save(doc, method=None) -> None:
    """CL-16 — cascade the header Cost Center into blank item rows and
    blank additional-cost rows. Manufacture-flow only."""
    if not _in_scope(doc):
        return
    cascade_cost_center(doc)


def validate(doc, method=None) -> None:
    """CR-05/06/07 validate pass. Runs BEFORE Frappe's _validate_mandatory
    (document.py insert/save: run_before_save_methods() then _validate()),
    so recomputing `amount` here satisfies the amount reqd=1 check for
    API / bulk-upload rows that arrive with qty+rate but no amount."""
    # CL-20 — server recompute mirrors the client script; safe for every
    # Stock Entry (only fills rows with both qty & rate).
    recompute_additional_cost_amounts(doc)

    # CVAL-15 — refuse an incomplete additional-cost row with a clear,
    # row-wise message so rows never drop silently on save. Applies to any
    # Stock Entry that carries additional costs.
    if doc.get("additional_costs"):
        validate_additional_cost_rows(doc)

    if not _in_scope(doc):
        return

    # CVAL-14 — a non-stock service item belongs in Additional Costs.
    block_non_stock_items(doc)

    # CVAL-11/12/13 — one cost-centre pass (mirrors the FRD implementation
    # note: keep the cost-centre checks together).
    validate_allow_multiple_permission(doc)     # CVAL-12
    validate_cost_center_master(doc)            # CVAL-13
    validate_cost_center_consistency(doc)       # CVAL-11


def before_submit(doc, method=None) -> None:
    """CVAL-10 — additional costs present but no target (finished-goods)
    warehouse to distribute them to. Applies to any SE carrying costs."""
    validate_additional_cost_distribution(doc)


def on_update(doc, method=None) -> None:
    """CVAL-12 audit — record every use of the multiple-cost-centre
    exception in the timeline (the block itself is enforced in validate)."""
    if not _in_scope(doc):
        return
    if not doc.get("custom_allow_multiple_cost_centers"):
        return
    before = doc.get_doc_before_save()
    was_on = bool(before.get("custom_allow_multiple_cost_centers")) if before else False
    if was_on:
        return  # already recorded on the transition — don't duplicate
    try:
        doc.add_comment(
            "Info",
            _("Multiple Cost Centers allowed on this Stock Entry by {0}.").format(
                frappe.session.user
            ),
        )
    except Exception:
        # Never let an audit-comment failure block the save.
        frappe.log_error(frappe.get_traceback(), "cr050607 CVAL-12 audit comment")


# =====================================================================
# Individual rules (kept as small, directly-callable units so tests
# exercise exactly what the hooks run — no stubbing)
# =====================================================================
def recompute_additional_cost_amounts(doc) -> None:
    """CL-20 — amount = custom_qty x custom_rate when BOTH are set. A row
    with neither keeps its manually-entered lump-sum amount (CR-07.2)."""
    for row in (doc.get("additional_costs") or []):
        qty = flt(row.get("custom_qty"))
        rate = flt(row.get("custom_rate"))
        if qty and rate:
            row.amount = qty * rate


def validate_additional_cost_rows(doc) -> None:
    """CVAL-15 — Description, Expense Account and Amount all required on
    every additional-cost row; Amount must be > 0."""
    for idx, row in enumerate(doc.get("additional_costs") or [], start=1):
        missing = []
        if not (row.get("description") or "").strip():
            missing.append("Description")
        if not row.get("expense_account"):
            missing.append("Expense Account")
        if flt(row.get("amount")) <= 0:
            missing.append("Amount")
        if missing:
            frappe.throw(
                _("Additional Cost row #{0}: Description, Expense Account and "
                  "Amount are all required (Amount must be greater than zero).").format(idx),
                title=_("Incomplete Additional Cost"),
            )


def block_non_stock_items(doc) -> None:
    """CVAL-14 / CL-15 — a non-stock (service) item may not be added to the
    items table; route it to Additional Costs."""
    for row in (doc.get("items") or []):
        item_code = row.get("item_code")
        if not item_code:
            continue
        is_stock = frappe.get_cached_value("Item", item_code, "is_stock_item")
        if is_stock == 0:
            frappe.throw(
                _("{0} is a service item and cannot be added to Items. "
                  "Enter it under Additional Costs instead.").format(item_code),
                title=_("Service item in Items"),
            )


def cascade_cost_center(doc) -> None:
    """CL-16 — copy the header Cost Center into every item row and every
    additional-cost row left blank. Populated rows are left for CVAL-11.

    Item-row cascade also runs in overrides.cc_project_guard._check_rows /
    stock_entry_manufacture.inherit_se_from_production_plan; this repeats
    it idempotently and adds the additional-cost-row cascade."""
    header_cc = doc.get("cost_center")
    if not header_cc:
        return
    for row in (doc.get("items") or []):
        if not row.get("cost_center"):
            row.cost_center = header_cc
    for row in (doc.get("additional_costs") or []):
        if not row.get("custom_cost_center"):
            row.custom_cost_center = header_cc


def validate_cost_center_consistency(doc) -> None:
    """CVAL-11 — every item row and additional-cost row must carry the same
    Cost Center as the header, unless custom_allow_multiple_cost_centers."""
    if doc.get("custom_allow_multiple_cost_centers"):
        return
    header_cc = doc.get("cost_center")
    if not header_cc:
        # Blank header is caught by cc_project_guard's mandatory check.
        return
    for idx, row in enumerate(doc.get("items") or [], start=1):
        row_cc = row.get("cost_center")
        if row_cc and row_cc != header_cc:
            frappe.throw(
                _("Row #{0}: Cost Center {1} does not match the document "
                  "Cost Center {2}.").format(idx, row_cc, header_cc),
                title=_("Cost Center mismatch"),
            )
    for idx, row in enumerate(doc.get("additional_costs") or [], start=1):
        row_cc = row.get("custom_cost_center")
        if row_cc and row_cc != header_cc:
            frappe.throw(
                _("Additional Cost row #{0}: Cost Center {1} does not match "
                  "the document Cost Center {2}.").format(idx, row_cc, header_cc),
                title=_("Cost Center mismatch"),
            )


def validate_allow_multiple_permission(doc) -> None:
    """CVAL-12 — only Manufacturing Manager or Accounts Manager may set
    custom_allow_multiple_cost_centers."""
    if not doc.get("custom_allow_multiple_cost_centers"):
        return
    user = frappe.session.user
    if user == "Administrator":
        return
    if not (set(frappe.get_roles(user)) & ALLOW_MULTI_ROLES):
        frappe.throw(
            _("Only a Manufacturing Manager or Accounts Manager can allow "
              "multiple Cost Centers on one Stock Entry."),
            title=_("Not permitted"),
        )


def validate_cost_center_master(doc) -> None:
    """CVAL-13 — the header Cost Center must belong to the document company,
    must not be a group node and must not be disabled."""
    cc = doc.get("cost_center")
    if not cc:
        return
    info = frappe.db.get_value(
        "Cost Center", cc, ["company", "is_group", "disabled"], as_dict=True
    )
    if not info:
        return  # non-existent link is handled by Frappe's link validation
    if info.company != doc.get("company") or info.is_group or info.disabled:
        frappe.throw(
            _("Cost Center {0} is not valid for Company {1}, or is a group / "
              "disabled Cost Center.").format(cc, doc.get("company")),
            title=_("Invalid Cost Center"),
        )


def validate_additional_cost_distribution(doc) -> None:
    """CVAL-10 — block submit when additional costs exist but no item row
    carries a target warehouse (nothing to distribute the cost onto)."""
    has_cost = any(
        flt(row.get("amount")) > 0 for row in (doc.get("additional_costs") or [])
    )
    if not has_cost:
        return
    has_target = any(row.get("t_warehouse") for row in (doc.get("items") or []))
    if not has_target:
        frappe.throw(
            _("Additional Costs cannot be distributed — add at least one "
              "finished goods row with a target warehouse."),
            title=_("No target for Additional Costs"),
        )


# =====================================================================
# Production Day Summary print format (CZ-49 / CR-07.6)
# Extends the base format (setup._production_day_summary_html) with a
# 'Service Charges / Additional Costs' section listing Service Item,
# Description, Qty, UOM, Rate and Amount.
# =====================================================================
PRODUCTION_DAY_SUMMARY_HTML = """<div style="font-family:Helvetica,Arial,sans-serif;">
<h2 style="margin:0">Production Day Summary</h2>
<p style="margin:0 0 10px 0;color:#666">{{ doc.name }} &mdash; {{ doc.posting_date }} {{ doc.posting_time or '' }}</p>

<table style="width:100%;border-collapse:collapse;margin-bottom:15px">
  <tr>
    <td style="padding:4px 8px;border:1px solid #ddd"><b>Production Plan</b></td><td style="padding:4px 8px;border:1px solid #ddd">{{ doc.production_plan or '-' }}</td>
    <td style="padding:4px 8px;border:1px solid #ddd"><b>Process</b></td><td style="padding:4px 8px;border:1px solid #ddd">{{ doc.get("custom_process_selection") or '-' }}</td>
  </tr>
  <tr>
    <td style="padding:4px 8px;border:1px solid #ddd"><b>Cost Center</b></td><td style="padding:4px 8px;border:1px solid #ddd">{{ doc.get("cost_center") or '-' }}</td>
    <td style="padding:4px 8px;border:1px solid #ddd"><b>Project</b></td><td style="padding:4px 8px;border:1px solid #ddd">{{ doc.project or '-' }}</td>
  </tr>
  <tr>
    <td style="padding:4px 8px;border:1px solid #ddd"><b>Production Time</b></td><td style="padding:4px 8px;border:1px solid #ddd">{{ doc.get("custom_production_time") or '-' }} {{ doc.get("custom_time_uom") or '' }}</td>
    <td style="padding:4px 8px;border:1px solid #ddd"><b>From Warehouse</b></td><td style="padding:4px 8px;border:1px solid #ddd">{{ doc.from_warehouse or '-' }}</td>
  </tr>
  <tr>
    <td style="padding:4px 8px;border:1px solid #ddd"><b>Downtime</b></td><td style="padding:4px 8px;border:1px solid #ddd">{{ doc.get("custom_downtime") or '-' }} {{ doc.get("custom_time_uom") or '' }}</td>
    <td style="padding:4px 8px;border:1px solid #ddd"></td><td style="padding:4px 8px;border:1px solid #ddd"></td>
  </tr>
</table>

<h3 style="margin:10px 0">Materials Consumed</h3>
<table style="width:100%;border-collapse:collapse">
  <thead style="background:#f5f5f5">
    <tr>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:left">Item</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:right">Qty</th>
      <th style="padding:4px 8px;border:1px solid #ddd">UOM</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:right">Rate</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:right">Amount</th>
      <th style="padding:4px 8px;border:1px solid #ddd">PO</th>
    </tr>
  </thead>
  <tbody>
  {% for r in doc.items %}
    {% if r.s_warehouse %}
    <tr>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ r.item_code }} &mdash; {{ r.item_name }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right">{{ "{:.2f}".format(r.qty or 0) }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ r.uom }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right">{{ "{:.2f}".format(r.basic_rate or 0) }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right">{{ "{:.2f}".format(r.amount or 0) }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ r.get("custom_purchase_order") or '-' }}</td>
    </tr>
    {% endif %}
  {% endfor %}
  </tbody>
</table>

<h3 style="margin:10px 0">Service Charges / Additional Costs</h3>
<table style="width:100%;border-collapse:collapse">
  <thead style="background:#f5f5f5">
    <tr>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:left">Service Item</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:left">Description</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:right">Qty</th>
      <th style="padding:4px 8px;border:1px solid #ddd">UOM</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:right">Rate</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:right">Amount</th>
    </tr>
  </thead>
  <tbody>
  {% for c in doc.additional_costs %}
    <tr>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ c.get("custom_service_item") or '-' }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ c.description or '-' }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right">{{ "{:.2f}".format(c.get("custom_qty") or 0) }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ c.get("custom_uom") or '-' }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right">{{ "{:.2f}".format(c.get("custom_rate") or 0) }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right">{{ "{:.2f}".format(c.amount or 0) }}</td>
    </tr>
  {% endfor %}
  {% if not doc.additional_costs %}
    <tr><td colspan="6" style="padding:4px 8px;border:1px solid #ddd;color:#999">No additional costs.</td></tr>
  {% endif %}
  </tbody>
  <tfoot>
    <tr>
      <td colspan="5" style="padding:4px 8px;border:1px solid #ddd;text-align:right"><b>Total Additional Costs</b></td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right"><b>{{ "{:.2f}".format(doc.total_additional_costs or 0) }}</b></td>
    </tr>
  </tfoot>
</table>

<h3 style="margin:10px 0">Finished Goods Produced</h3>
<table style="width:100%;border-collapse:collapse">
  <thead style="background:#f5f5f5">
    <tr>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:left">Item</th>
      <th style="padding:4px 8px;border:1px solid #ddd;text-align:right">Qty</th>
      <th style="padding:4px 8px;border:1px solid #ddd">UOM</th>
      <th style="padding:4px 8px;border:1px solid #ddd">Warehouse</th>
      <th style="padding:4px 8px;border:1px solid #ddd">Serial / Batch</th>
    </tr>
  </thead>
  <tbody>
  {% for r in doc.items %}
    {% if r.t_warehouse and not r.s_warehouse %}
    <tr>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ r.item_code }} &mdash; {{ r.item_name }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd;text-align:right">{{ "{:.2f}".format(r.qty or 0) }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ r.uom }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ r.t_warehouse }}</td>
      <td style="padding:4px 8px;border:1px solid #ddd">{{ r.serial_no or r.batch_no or '-' }}</td>
    </tr>
    {% endif %}
  {% endfor %}
  </tbody>
</table>

<table style="width:100%;margin-top:30px">
  <tr>
    <td style="width:33%;text-align:center;border-top:1px solid #999;padding-top:5px">Operator</td>
    <td style="width:33%;text-align:center;border-top:1px solid #999;padding-top:5px">QC</td>
    <td style="width:33%;text-align:center;border-top:1px solid #999;padding-top:5px">Supervisor</td>
  </tr>
</table>
</div>"""
