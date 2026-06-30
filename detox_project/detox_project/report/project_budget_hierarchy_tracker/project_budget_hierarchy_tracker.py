"""Project Budget Hierarchy Tracker.

ABP2-I439 #2 (Sahil 2026-06-30 FRD) — replaced the old
Budget / Spent / Remaining / Utilization layout with the SAP-style
hierarchy from the attached FRD:

  Budget   |  Actual  |  Commitment  |  RemOrdPlan  |  Assigned  |  Available  |  Utilization %

Definitions (from FRD "Field Logic" tab):
  • Actual       = Σ GL Entry (debit − credit), docstatus = 1,
                   project = report project, voucher in PI/JE/SE,
                   cost_center = WBS.cost_center.
  • Commitment   = Σ over POs linked to this WBS, of
                   (allocated_amount × open_fraction)
                   where open_fraction = max(0, (PO total − Σ billed_amt) / PO total)
                   and PO is docstatus=1, status NOT in
                   (Completed, Closed, Cancelled, Delivered).
  • RemOrdPlan   = Σ over MRs linked to this WBS, same shape with
                   (allocated_amount × outstanding_fraction)
                   where outstanding_fraction =
                   max(0, (MR total − Σ ordered_qty × rate) / MR total)
                   and MR is docstatus=1, status in
                   (Pending, Partially Ordered).
  • Assigned     = Actual + Commitment + RemOrdPlan (derived).
  • Available    = Budget − Assigned (derived).
  • Utilization% = Assigned / Budget × 100 (derived).

WBS → linked-doc mapping uses the existing `WBS Allocation` child
table on MR / PO / PR / PI (fieldname `custom_wbs_allocations`),
which carries `wbs_element`, `sub_wbs_element`, `allocated_amount`.
"""
import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.project:
        frappe.throw(_("Project is mandatory"))

    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {"fieldname": "entity", "label": _("Entity"),
         "fieldtype": "Data", "width": 280},
        {"fieldname": "entity_type", "label": _("Type"),
         "fieldtype": "Data", "width": 100},
        {"fieldname": "budget_amount", "label": _("Budget (₹)"),
         "fieldtype": "Currency", "width": 140},
        {"fieldname": "actual", "label": _("Actual (₹)"),
         "fieldtype": "Currency", "width": 140},
        {"fieldname": "commitment", "label": _("Commitment (₹)"),
         "fieldtype": "Currency", "width": 140},
        {"fieldname": "rem_ord_plan", "label": _("RemOrdPlan (₹)"),
         "fieldtype": "Currency", "width": 140},
        {"fieldname": "assigned", "label": _("Assigned (₹)"),
         "fieldtype": "Currency", "width": 140},
        {"fieldname": "available", "label": _("Available (₹)"),
         "fieldtype": "Currency", "width": 140},
        {"fieldname": "utilization_pct", "label": _("Utilization %"),
         "fieldtype": "Percent", "width": 110},
        {"fieldname": "mr_docs", "label": _("Material Requests"),
         "fieldtype": "Data", "width": 200},
        {"fieldname": "po_docs", "label": _("Purchase Orders"),
         "fieldtype": "Data", "width": 200},
        {"fieldname": "pr_docs", "label": _("Purchase Receipts"),
         "fieldtype": "Data", "width": 200},
        {"fieldname": "pi_docs", "label": _("Purchase Invoices"),
         "fieldtype": "Data", "width": 200},
    ]


# ────────────────────────────────────────────────────────────────────
# Computation helpers — Actual / Commitment / RemOrdPlan
# ────────────────────────────────────────────────────────────────────


def _compute_actual(project, cost_center):
    """Actual = Σ GL Entry debit − credit filtered to project + CC."""
    if not cost_center:
        return 0.0
    row = frappe.db.sql(
        """
        SELECT COALESCE(SUM(debit - credit), 0)
        FROM `tabGL Entry`
        WHERE docstatus = 1
          AND is_cancelled = 0
          AND project = %s
          AND cost_center = %s
        """,
        (project, cost_center),
    )
    return flt(row[0][0]) if row else 0.0


def _compute_commitment(wbs_element, sub_wbs_element=None):
    """Commitment for a WBS = Σ over POs allocated to it, of
    (allocated_amount × open_fraction).

    Open fraction is computed at PO level so partial billing on a
    multi-WBS PO is split proportionally — every WBS getting a share
    of the PO sees its share of the unbilled portion.
    """
    where_wbs = "wa.wbs_element = %s"
    args = [wbs_element]
    if sub_wbs_element:
        where_wbs += " AND wa.sub_wbs_element = %s"
        args.append(sub_wbs_element)
    else:
        # Header-level WBS row (no sub) — match only the
        # parent-WBS allocations, not the per-Sub ones.
        where_wbs += " AND (wa.sub_wbs_element IS NULL OR wa.sub_wbs_element = '')"

    rows = frappe.db.sql(
        f"""
        SELECT po.name,
               po.grand_total,
               COALESCE((
                   SELECT SUM(poi.billed_amt)
                   FROM `tabPurchase Order Item` poi
                   WHERE poi.parent = po.name
               ), 0) AS billed,
               wa.allocated_amount
        FROM `tabWBS Allocation` wa
        INNER JOIN `tabPurchase Order` po ON po.name = wa.parent
        WHERE wa.parenttype = 'Purchase Order'
          AND po.docstatus = 1
          AND po.status NOT IN ('Completed', 'Closed', 'Cancelled',
                                'Delivered')
          AND {where_wbs}
        """,
        tuple(args),
        as_dict=True,
    )
    total = 0.0
    for r in rows:
        po_total = flt(r.grand_total)
        billed = flt(r.billed)
        if po_total <= 0:
            continue
        open_fraction = max(0.0, (po_total - billed) / po_total)
        total += flt(r.allocated_amount) * open_fraction
    return total


def _compute_rem_ord_plan(wbs_element, sub_wbs_element=None):
    """RemOrdPlan for a WBS = Σ over MRs allocated to it, of
    (allocated_amount × outstanding_fraction).

    Outstanding fraction = (MR total − Σ ordered_qty × rate) / MR total,
    floored at 0.
    """
    where_wbs = "wa.wbs_element = %s"
    args = [wbs_element]
    if sub_wbs_element:
        where_wbs += " AND wa.sub_wbs_element = %s"
        args.append(sub_wbs_element)
    else:
        where_wbs += " AND (wa.sub_wbs_element IS NULL OR wa.sub_wbs_element = '')"

    rows = frappe.db.sql(
        f"""
        SELECT mr.name,
               COALESCE((
                   SELECT SUM(mri.amount)
                   FROM `tabMaterial Request Item` mri
                   WHERE mri.parent = mr.name
               ), 0) AS mr_total,
               COALESCE((
                   SELECT SUM(mri.ordered_qty * mri.rate)
                   FROM `tabMaterial Request Item` mri
                   WHERE mri.parent = mr.name
               ), 0) AS ordered,
               wa.allocated_amount
        FROM `tabWBS Allocation` wa
        INNER JOIN `tabMaterial Request` mr ON mr.name = wa.parent
        WHERE wa.parenttype = 'Material Request'
          AND mr.docstatus = 1
          AND mr.status IN ('Pending', 'Partially Ordered')
          AND {where_wbs}
        """,
        tuple(args),
        as_dict=True,
    )
    total = 0.0
    for r in rows:
        mr_total = flt(r.mr_total)
        ordered = flt(r.ordered)
        if mr_total <= 0:
            continue
        outstanding_fraction = max(0.0, (mr_total - ordered) / mr_total)
        total += flt(r.allocated_amount) * outstanding_fraction
    return total


def _derive(budget, actual, commitment, rem_ord_plan):
    """Compute Assigned / Available / Utilization % from the four
    inputs. Centralised so every row computes them the same way."""
    assigned = flt(actual) + flt(commitment) + flt(rem_ord_plan)
    available = flt(budget) - assigned
    utilization_pct = (assigned / flt(budget) * 100) if flt(budget) else 0
    return assigned, available, utilization_pct


# ────────────────────────────────────────────────────────────────────
# Main data builder
# ────────────────────────────────────────────────────────────────────


def get_data(filters):
    project = filters.project
    status_filter = filters.get("status", "Active")

    fm_name = filters.get("financial_model") or frappe.db.get_value(
        "Project", project, "custom_financial_model"
    )

    data = []

    if not fm_name:
        wbs_elements = get_wbs_elements(project, None, None, status_filter)
        for wbs in wbs_elements:
            add_wbs_row(data, project, wbs, indent=0)
            add_sub_wbs_rows(data, project, wbs.name, indent=1)
        add_summary_row(data, project)
        return data

    categories = frappe.db.sql(
        """
        SELECT DISTINCT pci.category, COALESCE(SUM(pci.amount), 0) AS allocated
        FROM `tabFM Project Cost Item` pci
        WHERE pci.parent = %s AND pci.parenttype = 'Financial Model'
        GROUP BY pci.category
        ORDER BY pci.category
        """,
        fm_name, as_dict=True,
    )

    category_filter = filters.get("category")

    for cat in categories:
        if category_filter and cat.category != category_filter:
            continue

        wbs_elements = get_wbs_elements(project, fm_name, cat.category, status_filter)

        # Category roll-up: sum WBS-level Actual / Commitment / RemOrdPlan.
        cat_actual = sum(_compute_actual(project, w.cost_center) for w in wbs_elements)
        cat_commitment = sum(_compute_commitment(w.name) for w in wbs_elements)
        cat_rop = sum(_compute_rem_ord_plan(w.name) for w in wbs_elements)
        assigned, available, util = _derive(
            cat.allocated, cat_actual, cat_commitment, cat_rop)

        data.append({
            "entity": cat.category,
            "entity_type": "Category",
            "budget_amount": cat.allocated,
            "actual": cat_actual,
            "commitment": cat_commitment,
            "rem_ord_plan": cat_rop,
            "assigned": assigned,
            "available": available,
            "utilization_pct": util,
            "indent": 0,
        })

        wbs_filter = filters.get("wbs_element")
        for wbs in wbs_elements:
            if wbs_filter and wbs.name != wbs_filter:
                continue
            add_wbs_row(data, project, wbs, indent=1)
            add_sub_wbs_rows(data, project, wbs.name, indent=2)

    add_summary_row(data, project)
    return data


def get_wbs_elements(project, fm_name, category, status_filter):
    filters = {"project": project, "status": ["!=", "Cancelled"]}
    if fm_name:
        filters["financial_model"] = fm_name
    if category:
        filters["category"] = category
    if status_filter and status_filter != "All":
        filters["status"] = status_filter

    return frappe.get_all(
        "WBS Element",
        filters=filters,
        fields=["name", "wbs_name", "wbs_type", "budget_amount",
                "cost_center", "status"],
        order_by="creation",
    )


def add_wbs_row(data, project, wbs, indent):
    docs = get_linked_docs(wbs.name, level="wbs")
    budget = flt(wbs.budget_amount)
    actual = _compute_actual(project, wbs.cost_center)
    commitment = _compute_commitment(wbs.name)
    rop = _compute_rem_ord_plan(wbs.name)
    assigned, available, util = _derive(budget, actual, commitment, rop)
    data.append({
        "entity": wbs.wbs_name,
        "entity_type": wbs.wbs_type or "WBS",
        "entity_link": wbs.name,
        "budget_amount": budget,
        "actual": actual,
        "commitment": commitment,
        "rem_ord_plan": rop,
        "assigned": assigned,
        "available": available,
        "utilization_pct": util,
        "mr_docs": docs.get("Material Request", ""),
        "po_docs": docs.get("Purchase Order", ""),
        "pr_docs": docs.get("Purchase Receipt", ""),
        "pi_docs": docs.get("Purchase Invoice", ""),
        "indent": indent,
    })


def add_sub_wbs_rows(data, project, wbs_name, indent):
    sub_wbs_list = frappe.get_all(
        "Sub WBS Element",
        filters={"main_wbs_element": wbs_name, "status": ["!=", "Cancelled"]},
        fields=["name", "sub_wbs_name", "budget_amount", "cost_center"],
        order_by="creation",
    )

    for sub in sub_wbs_list:
        docs = get_linked_docs(wbs_name, sub.name, level="sub_wbs")
        budget = flt(sub.budget_amount)
        actual = _compute_actual(project, sub.cost_center)
        commitment = _compute_commitment(wbs_name, sub.name)
        rop = _compute_rem_ord_plan(wbs_name, sub.name)
        assigned, available, util = _derive(budget, actual, commitment, rop)
        data.append({
            "entity": sub.sub_wbs_name,
            "entity_type": "Sub WBS",
            "entity_link": sub.name,
            "budget_amount": budget,
            "actual": actual,
            "commitment": commitment,
            "rem_ord_plan": rop,
            "assigned": assigned,
            "available": available,
            "utilization_pct": util,
            "mr_docs": docs.get("Material Request", ""),
            "po_docs": docs.get("Purchase Order", ""),
            "pr_docs": docs.get("Purchase Receipt", ""),
            "pi_docs": docs.get("Purchase Invoice", ""),
            "indent": indent,
        })


def get_linked_docs(wbs_name, sub_wbs_name=None, level="wbs"):
    """Get linked MR/PO/PR/PI document names via WBS Allocation child table."""
    result = {}
    doctype_route = {
        "Material Request": "material-request",
        "Purchase Order": "purchase-order",
        "Purchase Receipt": "purchase-receipt",
        "Purchase Invoice": "purchase-invoice",
    }

    for doctype in ("Material Request", "Purchase Order",
                    "Purchase Receipt", "Purchase Invoice"):
        table_name = f"tab{doctype}"
        if level == "sub_wbs" and sub_wbs_name:
            names = frappe.db.sql(
                """
                SELECT DISTINCT wa.parent
                FROM `tabWBS Allocation` wa
                INNER JOIN `{table}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s
                  AND wa.wbs_element = %s
                  AND wa.sub_wbs_element = %s
                  AND doc.docstatus < 2
                ORDER BY wa.parent
                """.format(table=table_name),
                (doctype, wbs_name, sub_wbs_name),
            )
        else:
            names = frappe.db.sql(
                """
                SELECT DISTINCT wa.parent
                FROM `tabWBS Allocation` wa
                INNER JOIN `{table}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s
                  AND wa.wbs_element = %s
                  AND doc.docstatus < 2
                ORDER BY wa.parent
                """.format(table=table_name),
                (doctype, wbs_name),
            )

        route = doctype_route[doctype]
        doc_names = [n[0] for n in names]
        if doc_names:
            links = ", ".join(
                f'<a href="/app/{route}/{n}">{n}</a>' for n in doc_names
            )
            result[doctype] = links
        else:
            result[doctype] = ""

    return result


def add_summary_row(data, project):
    total_budget = 0.0
    total_actual = 0.0
    total_commitment = 0.0
    total_rop = 0.0

    for row in data:
        is_wbs = (
            (row.get("indent") == 1 and row.get("entity_type") != "Sub WBS")
            or (row.get("indent") == 0 and row.get("entity_type") not in ("Category",))
        )
        if is_wbs:
            total_budget += flt(row.get("budget_amount"))
            total_actual += flt(row.get("actual"))
            total_commitment += flt(row.get("commitment"))
            total_rop += flt(row.get("rem_ord_plan"))

    assigned, available, util = _derive(
        total_budget, total_actual, total_commitment, total_rop)

    # Linked-doc counts across the project.
    wbs_names = frappe.get_all(
        "WBS Element", filters={"project": project}, pluck="name") or []
    counts = {"mr": 0, "po": 0, "pr": 0, "pi": 0}
    if wbs_names:
        for dt, key in [
            ("Material Request", "mr"), ("Purchase Order", "po"),
            ("Purchase Receipt", "pr"), ("Purchase Invoice", "pi"),
        ]:
            counts[key] = frappe.db.sql(
                """
                SELECT COUNT(DISTINCT wa.parent)
                FROM `tabWBS Allocation` wa
                INNER JOIN `tab{dt}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s
                  AND wa.wbs_element IN %s
                  AND doc.docstatus < 2
                """.format(dt=dt),
                (dt, wbs_names),
            )[0][0] or 0

    data.append({
        "entity": "PROJECT TOTAL",
        "entity_type": "Summary",
        "budget_amount": total_budget,
        "actual": total_actual,
        "commitment": total_commitment,
        "rem_ord_plan": total_rop,
        "assigned": assigned,
        "available": available,
        "utilization_pct": util,
        "mr_docs": f"{counts['mr']} docs",
        "po_docs": f"{counts['po']} docs",
        "pr_docs": f"{counts['pr']} docs",
        "pi_docs": f"{counts['pi']} docs",
        "indent": 0,
    })
