import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    return columns, data, None, chart


def get_columns():
    return [
        {"fieldname": "name", "label": _("WBS Element"), "fieldtype": "Link", "options": "WBS Element", "width": 150},
        {"fieldname": "wbs_name", "label": _("WBS Name"), "fieldtype": "Data", "width": 200},
        {"fieldname": "wbs_type", "label": _("Type"), "fieldtype": "Data", "width": 100},
        {"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 150},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 80},
        {"fieldname": "material_budget", "label": _("Material Budget"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "material_spent", "label": _("Material Spent"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "service_budget", "label": _("Service Budget"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "service_spent", "label": _("Service Spent"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "total_budget", "label": _("Total Budget"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "total_spent", "label": _("Total Spent"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "overall_utilization_pct", "label": _("Utilization %"), "fieldtype": "Percent", "width": 100},
    ]


def get_data(filters):
    conditions = {"status": ["!=", "Cancelled"]}
    if filters and filters.get("project"):
        conditions["project"] = filters["project"]
    if filters and filters.get("company"):
        conditions["company"] = filters["company"]
    if filters and filters.get("status"):
        conditions["status"] = filters["status"]

    return frappe.get_all(
        "WBS Element", filters=conditions,
        fields=["name", "wbs_name", "wbs_type", "project", "status",
                "material_budget", "material_spent", "service_budget", "service_spent",
                "total_budget", "total_spent", "overall_utilization_pct"],
        order_by="project, creation",
    )


def get_chart(data):
    if not data:
        return None
    labels = [d.wbs_name for d in data[:20]]
    return {
        "data": {
            "labels": labels,
            "datasets": [
                {"name": _("Budget"), "values": [d.total_budget or 0 for d in data[:20]]},
                {"name": _("Spent"), "values": [d.total_spent or 0 for d in data[:20]]},
            ],
        },
        "type": "bar",
        "colors": ["#318AD8", "#F47B7B"],
    }
