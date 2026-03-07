import frappe
from frappe import _


def execute(filters=None):
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"fieldname": "name", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 180},
        {"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 200},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        {"fieldname": "project_type", "label": _("Type"), "fieldtype": "Data", "width": 100},
        {"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 150},
        {"fieldname": "custom_total_budget", "label": _("Total Budget"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "custom_total_spent", "label": _("Total Spent"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "custom_budget_utilization_pct", "label": _("Utilization %"), "fieldtype": "Percent", "width": 100},
        {"fieldname": "wbs_count", "label": _("WBS Elements"), "fieldtype": "Int", "width": 100},
        {"fieldname": "mr_count", "label": _("Material Requests"), "fieldtype": "Int", "width": 120},
        {"fieldname": "po_count", "label": _("Purchase Orders"), "fieldtype": "Int", "width": 120},
        {"fieldname": "custom_financial_model", "label": _("Financial Model"), "fieldtype": "Link", "options": "Financial Model", "width": 150},
    ]


def get_data(filters):
    conditions = {}
    if filters and filters.get("status"):
        conditions["status"] = filters["status"]
    if filters and filters.get("company"):
        conditions["company"] = filters["company"]
    if filters and filters.get("project_type"):
        conditions["project_type"] = filters["project_type"]

    projects = frappe.get_all(
        "Project", filters=conditions,
        fields=["name", "project_name", "status", "project_type", "company",
                "custom_total_budget", "custom_total_spent",
                "custom_budget_utilization_pct", "custom_financial_model"],
        order_by="creation desc",
    )

    for project in projects:
        project["wbs_count"] = frappe.db.count("WBS Element", {"project": project.name, "status": ["!=", "Cancelled"]})
        project["mr_count"] = frappe.db.count("Material Request", {"project": project.name, "docstatus": ["<", 2]})
        project["po_count"] = frappe.db.count("Purchase Order", {"project": project.name, "docstatus": 1})

    return projects
