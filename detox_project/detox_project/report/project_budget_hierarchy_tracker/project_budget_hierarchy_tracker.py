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
        {"fieldname": "entity", "label": _("Entity"), "fieldtype": "Data", "width": 300},
        {"fieldname": "entity_type", "label": _("Type"), "fieldtype": "Data", "width": 100},
        {"fieldname": "budget_amount", "label": _("Budget (₹)"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "budget_spent", "label": _("Spent (₹)"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "budget_remaining", "label": _("Remaining (₹)"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "utilization_pct", "label": _("Utilization %"), "fieldtype": "Percent", "width": 110},
        {"fieldname": "mr_count", "label": _("MRs"), "fieldtype": "Int", "width": 60},
        {"fieldname": "po_count", "label": _("POs"), "fieldtype": "Int", "width": 60},
        {"fieldname": "pr_count", "label": _("PRs"), "fieldtype": "Int", "width": 60},
        {"fieldname": "pi_count", "label": _("PIs"), "fieldtype": "Int", "width": 60},
    ]


def get_data(filters):
    project = filters.project
    status_filter = filters.get("status", "Active")

    # Get Financial Model from project
    fm_name = filters.get("financial_model") or frappe.db.get_value(
        "Project", project, "custom_financial_model"
    )

    data = []

    if not fm_name:
        # No FM — just show WBS elements directly
        wbs_elements = get_wbs_elements(project, None, None, status_filter)
        for wbs in wbs_elements:
            add_wbs_row(data, wbs, indent=0)
            add_sub_wbs_rows(data, wbs.name, indent=1)
        add_summary_row(data, project)
        return data

    # Get FM categories
    categories = frappe.db.sql("""
        SELECT DISTINCT pci.category, COALESCE(SUM(pci.amount), 0) as allocated
        FROM `tabFM Project Cost Item` pci
        WHERE pci.parent = %s AND pci.parenttype = 'Financial Model'
        GROUP BY pci.category
        ORDER BY pci.category
    """, fm_name, as_dict=True)

    category_filter = filters.get("category")

    for cat in categories:
        if category_filter and cat.category != category_filter:
            continue

        # Get WBS elements for this category
        wbs_elements = get_wbs_elements(project, fm_name, cat.category, status_filter)

        total_wbs_budget = sum(flt(w.budget_amount) for w in wbs_elements)

        # Category row (indent=0)
        data.append({
            "entity": cat.category,
            "entity_type": "Category",
            "budget_amount": cat.allocated,
            "budget_spent": sum(flt(w.budget_spent) for w in wbs_elements),
            "budget_remaining": cat.allocated - sum(flt(w.budget_spent) for w in wbs_elements),
            "utilization_pct": (
                sum(flt(w.budget_spent) for w in wbs_elements) / cat.allocated * 100
                if cat.allocated else 0
            ),
            "indent": 0,
        })

        # WBS rows (indent=1)
        wbs_filter = filters.get("wbs_element")
        for wbs in wbs_elements:
            if wbs_filter and wbs.name != wbs_filter:
                continue
            add_wbs_row(data, wbs, indent=1)
            add_sub_wbs_rows(data, wbs.name, indent=2)

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
        fields=["name", "wbs_name", "wbs_type", "budget_amount", "budget_spent",
                "budget_utilization_pct", "status"],
        order_by="creation",
    )


def add_wbs_row(data, wbs, indent):
    counts = get_doc_counts(wbs.name, level="wbs")
    budget = flt(wbs.budget_amount)
    spent = flt(wbs.budget_spent)
    data.append({
        "entity": wbs.wbs_name,
        "entity_type": wbs.wbs_type or "WBS",
        "entity_link": wbs.name,
        "budget_amount": budget,
        "budget_spent": spent,
        "budget_remaining": budget - spent,
        "utilization_pct": flt(wbs.budget_utilization_pct),
        "mr_count": counts.get("Material Request", 0),
        "po_count": counts.get("Purchase Order", 0),
        "pr_count": counts.get("Purchase Receipt", 0),
        "pi_count": counts.get("Purchase Invoice", 0),
        "indent": indent,
    })


def add_sub_wbs_rows(data, wbs_name, indent):
    sub_wbs_list = frappe.get_all(
        "Sub WBS Element",
        filters={"main_wbs_element": wbs_name, "status": ["!=", "Cancelled"]},
        fields=["name", "sub_wbs_name", "budget_amount", "budget_spent",
                "budget_utilization_pct"],
        order_by="creation",
    )

    for sub in sub_wbs_list:
        counts = get_doc_counts(wbs_name, sub.name, level="sub_wbs")
        budget = flt(sub.budget_amount)
        spent = flt(sub.budget_spent)
        data.append({
            "entity": sub.sub_wbs_name,
            "entity_type": "Sub WBS",
            "entity_link": sub.name,
            "budget_amount": budget,
            "budget_spent": spent,
            "budget_remaining": budget - spent,
            "utilization_pct": flt(sub.budget_utilization_pct),
            "mr_count": counts.get("Material Request", 0),
            "po_count": counts.get("Purchase Order", 0),
            "pr_count": counts.get("Purchase Receipt", 0),
            "pi_count": counts.get("Purchase Invoice", 0),
            "indent": indent,
        })


def get_doc_counts(wbs_name, sub_wbs_name=None, level="wbs"):
    """Count linked MR/PO/PR/PI via WBS Allocation child table."""
    counts = {}
    for doctype in ("Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice"):
        table_name = f"tab{doctype}"
        if level == "sub_wbs" and sub_wbs_name:
            count = frappe.db.sql("""
                SELECT COUNT(DISTINCT wa.parent)
                FROM `tabWBS Allocation` wa
                INNER JOIN `{table}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s
                AND wa.wbs_element = %s
                AND wa.sub_wbs_element = %s
                AND doc.docstatus < 2
            """.format(table=table_name), (doctype, wbs_name, sub_wbs_name))[0][0] or 0
        else:
            count = frappe.db.sql("""
                SELECT COUNT(DISTINCT wa.parent)
                FROM `tabWBS Allocation` wa
                INNER JOIN `{table}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s
                AND wa.wbs_element = %s
                AND doc.docstatus < 2
            """.format(table=table_name), (doctype, wbs_name))[0][0] or 0

        # Also count old-style (backward compat for docs not yet migrated)
        if level == "wbs":
            old_count = frappe.db.sql("""
                SELECT COUNT(*) FROM `{table}`
                WHERE custom_wbs_element = %s AND docstatus < 2
                AND name NOT IN (
                    SELECT DISTINCT parent FROM `tabWBS Allocation`
                    WHERE parenttype = %s AND wbs_element = %s
                )
            """.format(table=table_name), (wbs_name, doctype, wbs_name))[0][0] or 0
            count += old_count

        counts[doctype] = count
    return counts


def add_summary_row(data, project):
    """Add a project-level summary row at the end."""
    total_budget = 0
    total_spent = 0
    total_mr = total_po = total_pr = total_pi = 0

    for row in data:
        if row.get("indent") == 1 and row.get("entity_type") != "Sub WBS":
            # WBS-level rows
            total_budget += flt(row.get("budget_amount"))
            total_spent += flt(row.get("budget_spent"))
            total_mr += row.get("mr_count", 0)
            total_po += row.get("po_count", 0)
            total_pr += row.get("pr_count", 0)
            total_pi += row.get("pi_count", 0)
        elif row.get("indent") == 0 and row.get("entity_type") not in ("Category",):
            # Top-level WBS (no FM case)
            total_budget += flt(row.get("budget_amount"))
            total_spent += flt(row.get("budget_spent"))
            total_mr += row.get("mr_count", 0)
            total_po += row.get("po_count", 0)
            total_pr += row.get("pr_count", 0)
            total_pi += row.get("pi_count", 0)

    data.append({
        "entity": "PROJECT TOTAL",
        "entity_type": "Summary",
        "budget_amount": total_budget,
        "budget_spent": total_spent,
        "budget_remaining": total_budget - total_spent,
        "utilization_pct": (total_spent / total_budget * 100) if total_budget else 0,
        "mr_count": total_mr,
        "po_count": total_po,
        "pr_count": total_pr,
        "pi_count": total_pi,
        "indent": 0,
    })
