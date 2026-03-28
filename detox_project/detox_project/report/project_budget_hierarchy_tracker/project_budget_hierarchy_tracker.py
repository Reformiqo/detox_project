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
        {"fieldname": "mr_docs", "label": _("Material Requests"), "fieldtype": "Data", "width": 200},
        {"fieldname": "po_docs", "label": _("Purchase Orders"), "fieldtype": "Data", "width": 200},
        {"fieldname": "pr_docs", "label": _("Purchase Receipts"), "fieldtype": "Data", "width": 200},
        {"fieldname": "pi_docs", "label": _("Purchase Invoices"), "fieldtype": "Data", "width": 200},
    ]


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
            add_wbs_row(data, wbs, indent=0)
            add_sub_wbs_rows(data, wbs.name, indent=1)
        add_summary_row(data, project)
        return data

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

        wbs_elements = get_wbs_elements(project, fm_name, cat.category, status_filter)

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
    docs = get_linked_docs(wbs.name, level="wbs")
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
        "mr_docs": docs.get("Material Request", ""),
        "po_docs": docs.get("Purchase Order", ""),
        "pr_docs": docs.get("Purchase Receipt", ""),
        "pi_docs": docs.get("Purchase Invoice", ""),
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
        docs = get_linked_docs(wbs_name, sub.name, level="sub_wbs")
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

    for doctype in ("Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice"):
        table_name = f"tab{doctype}"
        if level == "sub_wbs" and sub_wbs_name:
            names = frappe.db.sql("""
                SELECT DISTINCT wa.parent
                FROM `tabWBS Allocation` wa
                INNER JOIN `{table}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s
                AND wa.wbs_element = %s
                AND wa.sub_wbs_element = %s
                AND doc.docstatus < 2
                ORDER BY wa.parent
            """.format(table=table_name), (doctype, wbs_name, sub_wbs_name))
        else:
            names = frappe.db.sql("""
                SELECT DISTINCT wa.parent
                FROM `tabWBS Allocation` wa
                INNER JOIN `{table}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s
                AND wa.wbs_element = %s
                AND doc.docstatus < 2
                ORDER BY wa.parent
            """.format(table=table_name), (doctype, wbs_name))

        route = doctype_route[doctype]
        doc_names = [n[0] for n in names]
        # Format as comma-separated clickable links
        if doc_names:
            links = ", ".join(
                f'<a href="/app/{route}/{n}">{n}</a>' for n in doc_names
            )
            result[doctype] = links
        else:
            result[doctype] = ""

    return result


def add_summary_row(data, project):
    total_budget = 0
    total_spent = 0
    all_mr = set()
    all_po = set()
    all_pr = set()
    all_pi = set()

    for row in data:
        is_wbs = (
            (row.get("indent") == 1 and row.get("entity_type") != "Sub WBS")
            or (row.get("indent") == 0 and row.get("entity_type") not in ("Category",))
        )
        if is_wbs:
            total_budget += flt(row.get("budget_amount"))
            total_spent += flt(row.get("budget_spent"))

    # Count unique docs across all WBS for the project
    wbs_names = frappe.get_all("WBS Element", filters={"project": project}, pluck="name") or []
    if wbs_names:
        for doctype, key in [
            ("Material Request", "mr"), ("Purchase Order", "po"),
            ("Purchase Receipt", "pr"), ("Purchase Invoice", "pi"),
        ]:
            count = frappe.db.sql("""
                SELECT COUNT(DISTINCT wa.parent)
                FROM `tabWBS Allocation` wa
                INNER JOIN `tab{dt}` doc ON doc.name = wa.parent
                WHERE wa.parenttype = %s AND wa.wbs_element IN %s AND doc.docstatus < 2
            """.format(dt=doctype), (doctype, wbs_names))[0][0] or 0
            locals()[f"total_{key}"] = count

    data.append({
        "entity": "PROJECT TOTAL",
        "entity_type": "Summary",
        "budget_amount": total_budget,
        "budget_spent": total_spent,
        "budget_remaining": total_budget - total_spent,
        "utilization_pct": (total_spent / total_budget * 100) if total_budget else 0,
        "mr_docs": str(locals().get("total_mr", 0)) + " docs",
        "po_docs": str(locals().get("total_po", 0)) + " docs",
        "pr_docs": str(locals().get("total_pr", 0)) + " docs",
        "pi_docs": str(locals().get("total_pi", 0)) + " docs",
        "indent": 0,
    })
