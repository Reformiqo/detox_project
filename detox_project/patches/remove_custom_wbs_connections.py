import frappe


def execute():
	# Connections for WBS Element / Sub WBS Element now live in their doctype JSON.
	# Remove the old ones added via Customize Form so they don't duplicate them.
	frappe.db.delete(
		"DocType Link",
		{"parent": ["in", ["WBS Element", "Sub WBS Element"]], "custom": 1},
	)
	frappe.clear_cache(doctype="WBS Element")
	frappe.clear_cache(doctype="Sub WBS Element")
