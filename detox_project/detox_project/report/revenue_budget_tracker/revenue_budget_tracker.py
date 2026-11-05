# Copyright (c) 2026, erpera and contributors
# For license information, please see license.txt
#
# Revenue Budget vs Actual by WBS / Sub WBS (Revenue-type elements only).
#   Target    = WBS Total Revenue / Sub WBS Total Revenue
#   Committed = allocations on submitted Sales Orders
#   Actual    = allocations on submitted Sales Invoices

import frappe
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "entity", "label": "Entity", "fieldtype": "Data", "width": 180},
		{"fieldname": "entity_name", "label": "Name", "fieldtype": "Data", "width": 220},
		{"fieldname": "row_type", "label": "Type", "fieldtype": "Data", "width": 80},
		{"fieldname": "project", "label": "Project", "fieldtype": "Link", "options": "Project", "width": 120},
		{"fieldname": "category", "label": "Category", "fieldtype": "Link", "options": "Project Cost Category", "width": 150},
		{"fieldname": "revenue_budget", "label": "Total Revenue (Target)", "fieldtype": "Currency", "width": 150},
		{"fieldname": "committed", "label": "Committed (SO)", "fieldtype": "Currency", "width": 140},
		{"fieldname": "actual", "label": "Actual Revenue (SI)", "fieldtype": "Currency", "width": 140},
		{"fieldname": "variance", "label": "Balance to Recover", "fieldtype": "Currency", "width": 140},
		{"fieldname": "utilization", "label": "Achievement %", "fieldtype": "Percent", "width": 110},
		{"fieldname": "sales_orders", "label": "Sales Orders", "fieldtype": "Data", "width": 220},
		{"fieldname": "sales_invoices", "label": "Sales Invoices", "fieldtype": "Data", "width": 220},
	]


def allocation_totals(parenttype, link_field):
	"""{wbs or sub wbs: (allocated total, "SO-1, SO-2")} over submitted documents."""
	rows = frappe.db.sql(
		f"""select {link_field}, ifnull(sum(allocated_amount), 0),
			group_concat(distinct parent order by parent separator ', ')
		from `tabRevenue WBS Allocation`
		where parenttype=%s and docstatus=1 and ifnull({link_field}, '') != ''
		group by {link_field}""",
		parenttype,
	)
	return {r[0]: (flt(r[1]), r[2]) for r in rows}


def make_row(entity, entity_name, row_type, project, category, budget, so, si, indent):
	committed, so_docs = so or (0.0, "")
	actual, si_docs = si or (0.0, "")
	return {
		"entity": entity,
		"entity_name": entity_name,
		"row_type": row_type,
		"project": project,
		"category": category,
		"revenue_budget": budget,
		"committed": committed,
		"actual": actual,
		"variance": flt(budget - actual, 2),
		"utilization": flt(actual * 100.0 / budget, 2) if budget else 0.0,
		"sales_orders": so_docs or "",
		"sales_invoices": si_docs or "",
		"indent": indent,
	}


def get_data(filters):
	wbs_filters = {"custom_category_type": "Revenue"}
	for key in ("company", "project", "financial_model", "category", "status"):
		if filters.get(key):
			wbs_filters[key] = filters.get(key)
	if filters.get("wbs_element"):
		wbs_filters["name"] = filters.get("wbs_element")

	wbs_list = frappe.get_all(
		"WBS Element",
		filters=wbs_filters,
		fields=["name", "wbs_name", "project", "category", "total_revenue"],
		order_by="name asc",
	)

	subs_map = {}
	for s in frappe.get_all(
		"Sub WBS Element",
		fields=["name", "sub_wbs_name", "main_wbs_element", "project", "category", "custom_total_revenue"],
		order_by="name asc",
	):
		subs_map.setdefault(s.main_wbs_element, []).append(s)

	wbs_so = allocation_totals("Sales Order", "wbs_element")
	wbs_si = allocation_totals("Sales Invoice", "wbs_element")
	sub_so = allocation_totals("Sales Order", "sub_wbs_element")
	sub_si = allocation_totals("Sales Invoice", "sub_wbs_element")

	data = []
	for w in wbs_list:
		data.append(
			make_row(w.name, w.wbs_name, "WBS", w.project, w.category, flt(w.total_revenue), wbs_so.get(w.name), wbs_si.get(w.name), 0)
		)
		for s in subs_map.get(w.name) or []:
			data.append(
				make_row(s.name, s.sub_wbs_name, "Sub WBS", s.project, s.category, flt(s.custom_total_revenue), sub_so.get(s.name), sub_si.get(s.name), 1)
			)
	return data
