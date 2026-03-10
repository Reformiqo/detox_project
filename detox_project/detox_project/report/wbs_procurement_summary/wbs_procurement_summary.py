import frappe
from frappe import _


def execute(filters=None):
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"fieldname": "wbs_element",
			"label": _("WBS Element"),
			"fieldtype": "Link",
			"options": "WBS Element",
			"width": 150,
		},
		{"fieldname": "wbs_name", "label": _("WBS Name"), "fieldtype": "Data", "width": 180},
		{
			"fieldname": "project",
			"label": _("Project"),
			"fieldtype": "Link",
			"options": "Project",
			"width": 150,
		},
		{"fieldname": "doc_type", "label": _("Document Type"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "doc_name",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "doc_type",
			"width": 180,
		},
		{"fieldname": "supplier", "label": _("Supplier"), "fieldtype": "Data", "width": 150},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "grand_total", "label": _("Amount"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	conditions = {"status": ["!=", "Cancelled"]}
	if filters and filters.get("project"):
		conditions["project"] = filters["project"]
	if filters and filters.get("wbs_element"):
		conditions["name"] = filters["wbs_element"]

	wbs_elements = frappe.get_all(
		"WBS Element",
		filters=conditions,
		fields=["name", "wbs_name", "project"],
		order_by="project, creation",
	)

	data = []
	for wbs in wbs_elements:
		for mr in frappe.get_all(
			"Material Request",
			filters={"custom_wbs_element": wbs.name, "docstatus": ["<", 2]},
			fields=["name", "transaction_date as date", "status"],
		):
			data.append(
				{
					"wbs_element": wbs.name,
					"wbs_name": wbs.wbs_name,
					"project": wbs.project,
					"doc_type": "Material Request",
					"doc_name": mr.name,
					"supplier": "",
					"date": mr.date,
					"grand_total": 0,
					"status": mr.status,
				}
			)

		for po in frappe.get_all(
			"Purchase Order",
			filters={"custom_wbs_element": wbs.name, "docstatus": 1},
			fields=["name", "supplier", "transaction_date as date", "grand_total", "status"],
		):
			data.append(
				{
					"wbs_element": wbs.name,
					"wbs_name": wbs.wbs_name,
					"project": wbs.project,
					"doc_type": "Purchase Order",
					"doc_name": po.name,
					"supplier": po.supplier,
					"date": po.date,
					"grand_total": po.grand_total,
					"status": po.status,
				}
			)

		for pi in frappe.get_all(
			"Purchase Invoice",
			filters={"custom_wbs_element": wbs.name, "docstatus": 1},
			fields=["name", "supplier", "posting_date as date", "grand_total", "status"],
		):
			data.append(
				{
					"wbs_element": wbs.name,
					"wbs_name": wbs.wbs_name,
					"project": wbs.project,
					"doc_type": "Purchase Invoice",
					"doc_name": pi.name,
					"supplier": pi.supplier,
					"date": pi.date,
					"grand_total": pi.grand_total,
					"status": pi.status,
				}
			)

	return data
