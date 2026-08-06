# =====================================================================
# CR-04 — Material Transfer for Manufacture BEFORE the Manufacture entry.
# DETOX Production Change-Set FRD (Change Set 1).
#
# Objects delivered here (all code-first; not in shared fixtures):
#   CZ-37  Custom Fields on Stock Entry
#            custom_material_transfer_ref            (Link -> Stock Entry, optional)
#            custom_allow_manufacture_without_transfer (Check, default 0)
#   CZ-38  Custom Fields on the Table-2 operations child
#          (Detox Production Plan Operation)
#            custom_transferred_qty                  (Float, read-only, rollup)
#            custom_consumed_qty                     (Float, read-only, rollup)
#   CZ-39  Server logic (this module):
#            CVAL-08 / CL-10  before_submit transfer-coverage block
#            CVAL-09 / CL-10  before_submit over-consumption block
#            CL-11            validate  WIP source-warehouse default
#            CL-12            on_submit / on_cancel transferred/consumed rollup
#   CZ-40  make_material_transfer_for_manufacture (CL-13) — whitelisted
#          builder used by the Production Plan "Create" button.
#
# CODE-FIRST: every Custom Field is defined and upserted in install(),
# which the manager wires into detox_project.setup.after_migrate. The
# doc-event functions are wired by the manager into hooks.py doc_events
# ("Stock Entry": validate / before_submit / on_submit / on_cancel).
#
# REUSE (established patterns, read before writing):
#   * get_operation_rm_rows(plan, operation) in
#     overrides/stock_entry_manufacture.py returns an operation's Table-2
#     raw-material rows — reused verbatim to build the transfer entry.
#   * _adjust_total_produced(doc, sign) in the same file is the canonical
#     SQL-UPDATE rollup keyed on production_plan + item_code; CL-12's
#     _adjust_op_qty mirrors it (adds operation_name to the key).
#   * _stock_entry_is_in_scope(doc) in overrides/cc_project_guard.py — the
#     Manufacture-flow short-circuit idiom.
#
# ENVIRONMENT NOTE (reported to the manager): the local bench runs
# ERPNext 16.6.1, where the Stock Entry header has NO standard
# `cost_center` docfield (the DB column exists). All cost_center access
# is therefore gated with meta.has_field / doc.get("cost_center").
# There is ALSO no Bulk Store / WIP warehouse field on Production Plan or
# on the Operation child, and Manufacturing Settings has no
# default_wip_warehouse on this build, so the CR-04.4 "source Bulk Store /
# target WIP pre-filled" cannot be fully auto-derived — the builder
# leaves the source warehouse for the user and best-efforts the WIP
# target. CL-11 then defaults the Manufacture source warehouse from the
# transfer entry the user actually staged into.
# =====================================================================

from __future__ import annotations

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

from detox_project.detox_project.overrides.stock_entry_manufacture import (
    get_operation_rm_rows,
)

MODULE = "Detox Project"
OPERATION_CHILD = "Detox Production Plan Operation"  # Table 2 (custom_operations)

TRANSFER_TYPE = "Material Transfer for Manufacture"
MANUFACTURE_TYPE = "Manufacture"

# CR-04.6 — only these roles may switch on the exception flag.
ALLOW_ROLES = {"Manufacturing Manager"}

# CL-12 rollup fields — a fixed whitelist so the field name can never be
# interpolated into SQL from anywhere but this constant (no injection).
_ROLLUP_FIELDS = {"custom_transferred_qty", "custom_consumed_qty"}


# =====================================================================
# Scope helpers
# =====================================================================
def _is_transfer(doc) -> bool:
    return (doc.get("stock_entry_type") or "").strip() == TRANSFER_TYPE


def _is_manufacture(doc) -> bool:
    return (doc.get("stock_entry_type") or "").strip() == MANUFACTURE_TYPE


def _is_source_row(row) -> bool:
    """A consumption/source row: not a finished good and staged from a
    warehouse. Mirrors how stock_entry_manufacture treats source rows
    (s_warehouse set) vs FG rows (is_finished_item + t_warehouse)."""
    if row.get("is_finished_item"):
        return False
    return bool(row.get("s_warehouse"))


# =====================================================================
# CODE-FIRST install (call from setup.after_migrate)
# =====================================================================
def install() -> None:
    """Upsert CR-04 Custom Fields (CZ-37 + CZ-38). Idempotent."""
    install_custom_fields()


def install_custom_fields() -> None:
    fields: dict[str, list[dict]] = {
        "Stock Entry": [
            # CZ-37 — the transfer entry this manufacture consumes against.
            # Optional; stamped for traceability by before_submit when a
            # matching transfer is found.
            {
                "fieldname": "custom_material_transfer_ref",
                "label": "Material Transfer Ref",
                "fieldtype": "Link",
                "options": "Stock Entry",
                "insert_after": "custom_process_selection",
                "read_only": 1,
                "module": MODULE,
                "description": (
                    "The Material Transfer for Manufacture entry this "
                    "Manufacture consumes against (traceability)."
                ),
            },
            # CZ-37 / CR-04.6 — role-restricted exception switch.
            {
                "fieldname": "custom_allow_manufacture_without_transfer",
                "label": "Allow Manufacture Without Transfer",
                "fieldtype": "Check",
                "default": "0",
                "insert_after": "custom_material_transfer_ref",
                "module": MODULE,
                "description": (
                    "Permits a Manufacture entry with no Material Transfer "
                    "for Manufacture behind it (corrections / opening "
                    "entries). Only a Manufacturing Manager may set it; "
                    "every use is written to the timeline."
                ),
            },
        ],
        OPERATION_CHILD: [
            # CZ-38 — qty issued to WIP against this operation across
            # submitted transfer entries (rollup, read-only).
            {
                "fieldname": "custom_transferred_qty",
                "label": "Transferred Qty",
                "fieldtype": "Float",
                "insert_after": "multiply_by",
                "read_only": 1,
                "module": MODULE,
                "description": "Issued to WIP across submitted transfer entries (CR-04.5).",
            },
            # CZ-38 — qty consumed across submitted manufacture entries.
            {
                "fieldname": "custom_consumed_qty",
                "label": "Consumed Qty",
                "fieldtype": "Float",
                "insert_after": "custom_transferred_qty",
                "read_only": 1,
                "module": MODULE,
                "description": "Consumed across submitted manufacture entries (CR-04.5).",
            },
        ],
    }

    to_create = {dt: specs for dt, specs in fields.items() if frappe.db.exists("DocType", dt)}
    create_custom_fields(to_create, update=True)
    for dt in to_create:
        try:
            frappe.clear_cache(doctype=dt)
        except Exception:
            pass
    print(
        "detox_project: cr04 install_custom_fields — "
        f"{sum(len(v) for v in to_create.values())} field(s) upserted."
    )


# =====================================================================
# CVAL-08 + CVAL-09 — before_submit on a Manufacture entry (CL-10)
# =====================================================================
def before_submit(doc, method=None) -> None:
    """Manufacture-flow only. Blocks a Manufacture entry that has no
    submitted Material Transfer for Manufacture behind it (CVAL-08) and
    blocks consuming more than was transferred to WIP (CVAL-09), unless
    the role-gated exception flag is set (CR-04.6)."""
    if not _is_manufacture(doc):
        return
    if not doc.get("production_plan"):
        # A standalone Manufacture entry with no plan has no transfer
        # context to check against; leave it to the base flow.
        return

    if doc.get("custom_allow_manufacture_without_transfer"):
        # CR-04.6 — the exception. Role-gate it and record the use; when
        # authorised, skip BOTH coverage and over-consumption.
        _enforce_exception_role(doc)
        _audit_exception_use(doc)
        return

    _validate_transfer_coverage(doc)     # CVAL-08
    _validate_over_consumption(doc)       # CVAL-09


def _enforce_exception_role(doc) -> None:
    """CR-04.6 — only a Manufacturing Manager (or Administrator) may use
    custom_allow_manufacture_without_transfer. Block otherwise."""
    user = frappe.session.user
    if user == "Administrator":
        return
    if not (set(frappe.get_roles(user)) & ALLOW_ROLES):
        frappe.throw(
            _("Only a Manufacturing Manager can allow a Manufacture entry "
              "without a Material Transfer for Manufacture."),
            title=_("Not permitted"),
        )


def _audit_exception_use(doc) -> None:
    """CR-04.6 — record every legitimate use of the exception in the
    document timeline. Never let an audit failure block the submit."""
    try:
        doc.add_comment(
            "Info",
            _("Manufacture allowed WITHOUT a Material Transfer for "
              "Manufacture on this entry by {0}.").format(frappe.session.user),
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "cr04 CR-04.6 exception audit")


def _validate_transfer_coverage(doc) -> None:
    """CVAL-08 / CL-10 — at least one submitted Material Transfer for
    Manufacture must exist for the same plan and (when set) process."""
    plan = doc.get("production_plan")
    process = (doc.get("custom_process_selection") or "").strip()
    match = _matching_transfer_name(plan, process)
    if not match:
        frappe.throw(
            _("Complete the Material Transfer for Manufacture for Plan {0} / "
              "Process {1} before submitting this Manufacture entry.").format(
                plan, process or "-"),
            title=_("Material Transfer required"),
        )
    # Stamp the reference for traceability when the user left it blank.
    if not doc.get("custom_material_transfer_ref"):
        doc.custom_material_transfer_ref = match


def _validate_over_consumption(doc) -> None:
    """CVAL-09 / CL-10 — per source item, qty consumed across the
    plan/process (already-submitted manufacture entries + this one) may
    not exceed the qty transferred to WIP for that item."""
    plan = doc.get("production_plan")
    process = (doc.get("custom_process_selection") or "").strip()
    transferred = _transferred_map(plan, process)
    consumed = _consumed_map(plan, process, exclude_se=doc.get("name"))

    # Aggregate this entry's own source rows per item so a split across
    # rows is compared as one figure against the balance.
    this_entry: dict[str, float] = {}
    for row in (doc.get("items") or []):
        if not _is_source_row(row):
            continue
        qty = flt(row.get("qty"))
        if qty <= 0:
            continue
        this_entry[row.item_code] = this_entry.get(row.item_code, 0.0) + qty

    for item_code, qty in this_entry.items():
        balance = flt(transferred.get(item_code, 0.0)) - flt(consumed.get(item_code, 0.0))
        if qty > balance:
            frappe.throw(
                _("{0}: consuming {1} exceeds the balance transferred to WIP "
                  "({2}). Transfer the shortfall before proceeding.").format(
                    item_code, qty, balance),
                title=_("Over-consumption"),
            )


# =====================================================================
# CL-11 — WIP source-warehouse default (validate)
# =====================================================================
def default_wip_source_warehouse(doc, method=None) -> None:
    """CL-11 — on a Manufacture entry, default each blank source row's
    s_warehouse to the WIP warehouse the matching transfer entry staged
    the material into, so consumption happens where it was staged.
    Only fills blanks — never overrides a user-chosen warehouse."""
    if not _is_manufacture(doc) or not doc.get("production_plan"):
        return
    plan = doc.get("production_plan")
    process = (doc.get("custom_process_selection") or "").strip()
    wip = _wip_warehouse_map(plan, process)
    if not wip:
        return
    # A single fallback WIP for rows whose item wasn't in any transfer.
    fallback = next(iter(wip.values()), None)
    for row in (doc.get("items") or []):
        if row.get("is_finished_item"):
            continue
        if row.get("s_warehouse"):
            continue
        if not row.get("item_code"):
            continue
        row.s_warehouse = wip.get(row.item_code) or fallback


# =====================================================================
# CL-12 — transferred / consumed rollup (on_submit / on_cancel)
# =====================================================================
def rollup_transferred_consumed_on_submit(doc, method=None) -> None:
    _rollup(doc, sign=+1)


def rollup_transferred_consumed_on_cancel(doc, method=None) -> None:
    _rollup(doc, sign=-1)


def _rollup(doc, sign: int) -> None:
    if not doc.get("production_plan"):
        return
    if _is_transfer(doc):
        # Every row on a transfer entry is an issue into WIP.
        _adjust_op_qty(doc, "custom_transferred_qty", sign, source_only=False)
    elif _is_manufacture(doc):
        # Only consumption (source) rows count against WIP.
        _adjust_op_qty(doc, "custom_consumed_qty", sign, source_only=True)


def _adjust_op_qty(doc, field: str, sign: int, source_only: bool) -> None:
    """Mirror overrides.stock_entry_manufacture._adjust_total_produced:
    a signed SQL UPDATE keyed on the matching Table-2 row. Keyed on
    production_plan + operation_name (custom_process_selection) +
    item_code. `field` is validated against a fixed whitelist so it can
    never be attacker-controlled."""
    if field not in _ROLLUP_FIELDS:  # defensive; callers pass constants
        frappe.throw(_("Invalid rollup field {0}").format(field))
    plan = doc.get("production_plan")
    operation = (doc.get("custom_process_selection") or "").strip()
    for row in (doc.get("items") or []):
        if source_only and not _is_source_row(row):
            continue
        if not source_only and not row.get("item_code"):
            continue
        qty = flt(row.get("qty"))
        if qty <= 0:
            continue
        # When the entry carries no process, fall back to matching on
        # item alone (an operation-agnostic transfer/manufacture).
        op_clause = "AND operation_name = %(op)s" if operation else ""
        frappe.db.sql(
            f"""UPDATE `tab{OPERATION_CHILD}`
                SET `{field}` = COALESCE(`{field}`, 0) + %(delta)s
                WHERE parent = %(plan)s
                  AND parenttype = 'Production Plan'
                  AND item_code = %(item)s
                  {op_clause}""",
            {"delta": sign * qty, "plan": plan, "item": row.item_code, "op": operation},
        )


# =====================================================================
# DB read helpers (small units so tests exercise the REAL SQL — no
# stubbing of frappe.db; a wrong column name surfaces immediately)
# =====================================================================
def _process_clause(alias: str = "") -> str:
    """A shared, lenient process filter: the transfer/manufacture covers
    the manufacture's process when the process matches, or when either
    side left the process blank (an operation-agnostic entry)."""
    col = f"{alias}.custom_process_selection" if alias else "custom_process_selection"
    return (
        f"AND (%(process)s = '' OR IFNULL({col}, '') = %(process)s "
        f"OR IFNULL({col}, '') = '')"
    )


def _matching_transfer_name(plan: str, process: str) -> str | None:
    row = frappe.db.sql(
        f"""SELECT name FROM `tabStock Entry`
            WHERE docstatus = 1
              AND stock_entry_type = %(ttype)s
              AND production_plan = %(plan)s
              {_process_clause()}
            ORDER BY creation DESC
            LIMIT 1""",
        {"ttype": TRANSFER_TYPE, "plan": plan, "process": process or ""},
    )
    return row[0][0] if row else None


def _transferred_map(plan: str, process: str) -> dict[str, float]:
    rows = frappe.db.sql(
        f"""SELECT sed.item_code, SUM(sed.qty) AS qty
            FROM `tabStock Entry Detail` sed
            JOIN `tabStock Entry` se ON se.name = sed.parent
            WHERE se.docstatus = 1
              AND se.stock_entry_type = %(ttype)s
              AND se.production_plan = %(plan)s
              {_process_clause("se")}
            GROUP BY sed.item_code""",
        {"ttype": TRANSFER_TYPE, "plan": plan, "process": process or ""},
        as_dict=True,
    )
    return {r.item_code: flt(r.qty) for r in rows}


def _consumed_map(plan: str, process: str, exclude_se: str | None) -> dict[str, float]:
    rows = frappe.db.sql(
        f"""SELECT sed.item_code, SUM(sed.qty) AS qty
            FROM `tabStock Entry Detail` sed
            JOIN `tabStock Entry` se ON se.name = sed.parent
            WHERE se.docstatus = 1
              AND se.stock_entry_type = %(mtype)s
              AND se.production_plan = %(plan)s
              AND IFNULL(sed.is_finished_item, 0) = 0
              AND IFNULL(sed.s_warehouse, '') != ''
              AND se.name != %(exclude)s
              {_process_clause("se")}
            GROUP BY sed.item_code""",
        {
            "mtype": MANUFACTURE_TYPE, "plan": plan, "process": process or "",
            "exclude": exclude_se or "__none__",
        },
        as_dict=True,
    )
    return {r.item_code: flt(r.qty) for r in rows}


def _wip_warehouse_map(plan: str, process: str) -> dict[str, str]:
    rows = frappe.db.sql(
        f"""SELECT sed.item_code, sed.t_warehouse
            FROM `tabStock Entry Detail` sed
            JOIN `tabStock Entry` se ON se.name = sed.parent
            WHERE se.docstatus = 1
              AND se.stock_entry_type = %(ttype)s
              AND se.production_plan = %(plan)s
              AND IFNULL(sed.t_warehouse, '') != ''
              {_process_clause("se")}
            ORDER BY se.creation""",
        {"ttype": TRANSFER_TYPE, "plan": plan, "process": process or ""},
        as_dict=True,
    )
    # Last transfer wins per item (most recent staging warehouse).
    return {r.item_code: r.t_warehouse for r in rows}


# =====================================================================
# CL-13 / CZ-40 — build the Material Transfer for Manufacture from a plan
# =====================================================================
@frappe.whitelist()
def make_material_transfer_for_manufacture(production_plan: str, operation: str) -> dict:
    """CL-13 — return a DRAFT Stock Entry (as a doc dict for the client to
    sync + open) of type 'Material Transfer for Manufacture' for the
    given plan operation, items pre-filled from the operation's Table-2
    raw-material rows, with company / cost_center / project inherited.

    Mirrors production_plan_custom.js `_add_stock_entry_button`, but the
    row build is server-side so it can reuse get_operation_rm_rows and be
    unit-tested. The returned dict is unsaved; the client does
    frappe.model.sync(r.message) then routes to the draft."""
    if not production_plan or not operation:
        frappe.throw(_("Production Plan and Operation are required."))
    plan = frappe.db.get_value(
        "Production Plan", production_plan,
        ["docstatus", "custom_no_bom", "company", "custom_cost_center", "project"],
        as_dict=True,
    )
    if not plan:
        frappe.throw(_("Production Plan {0} not found.").format(production_plan))
    if plan.docstatus != 1:
        frappe.throw(_("Production Plan {0} must be submitted.").format(production_plan))
    if not plan.custom_no_bom:
        frappe.throw(
            _("Material Transfer for Manufacture is only available on a "
              "No-BOM Production Plan."))

    rows = get_operation_rm_rows(production_plan, operation)
    if not rows:
        frappe.throw(
            _("No Materials / Service rows are defined for Operation '{0}' on "
              "Production Plan {1}.").format(operation, production_plan))

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = TRANSFER_TYPE
    se.production_plan = production_plan
    se.company = plan.company
    se.custom_process_selection = operation

    meta = frappe.get_meta("Stock Entry")
    # ERPNext 16.6 has no header cost_center docfield; set only when it
    # exists (the DB column is still populated by the validate hook).
    if plan.custom_cost_center and meta.has_field("cost_center"):
        se.cost_center = plan.custom_cost_center
    if plan.project:
        se.project = plan.project

    # Best-effort WIP target: no Bulk Store / WIP warehouse field exists
    # on the plan or Manufacturing Settings on this build, so the source
    # (Bulk Store) is left for the user. Company default WIP, if any.
    wip = _company_default_wip(plan.company)
    if wip:
        se.to_warehouse = wip

    for src in rows:
        row = se.append("items", {})
        row.item_code = src.get("item_code")
        row.item_name = src.get("item_name")
        row.uom = src.get("uom")
        row.stock_uom = src.get("stock_uom")
        row.basic_rate = flt(src.get("basic_rate"))
        # qty_per_unit is the meaningful per-unit default; the user scales
        # it to the batch being staged.
        row.qty = flt(src.get("qty_per_unit"))
        row.cost_center = src.get("cost_center")
        row.project = src.get("project")
        if src.get("expense_account"):
            row.expense_account = src.get("expense_account")
        if wip:
            row.t_warehouse = wip

    return se.as_dict()


def _company_default_wip(company: str) -> str | None:
    """Company default WIP warehouse if the field is present on this
    ERPNext build; otherwise None (source/target left for the user)."""
    if not company:
        return None
    meta = frappe.get_meta("Company")
    if meta.has_field("default_in_transit_warehouse"):
        wh = frappe.db.get_value("Company", company, "default_in_transit_warehouse")
        if wh:
            return wh
    return None
