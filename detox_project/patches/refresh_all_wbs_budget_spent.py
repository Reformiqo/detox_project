import frappe


def execute():
	# Stored budget_spent was stale: MR submit/cancel never refreshed it, so
	# cancelled MRs stayed counted. Re-stamp every WBS and Sub WBS once.
	for name in frappe.get_all("Sub WBS Element", pluck="name"):
		frappe.get_doc("Sub WBS Element", name).refresh_spent_amounts()

	for name in frappe.get_all("WBS Element", pluck="name"):
		frappe.get_doc("WBS Element", name).refresh_spent_amounts()
