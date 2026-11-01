import frappe
from frappe.utils import flt

# Link Revenue WBS Elements to 9 submitted Sales Invoices (client list, Oct 2026).
# The Revenue WBS table is not editable after submit, so a Property Setter
# allows it for the duration of the patch and is removed afterwards.
# No project check: the client asked for these WBS although the invoices are
# booked under another project (PROJ-0023 / PROJ-0019).
# One Error Log shows each invoice's WBS and each WBS Element's revenue before and after.

# invoice | wbs element | allocated amount
DATA = """
SINV-GJ-26-59|WBS-002.6|18,75,000.00
SINV-GJ-26-157|WBS-002.6|18,75,000.00
SINV-GJ-26-217|WBS-002.6|18,75,000.00
SINV-AP-26-8|WBS-033.8|3,80,000.00
SINV-GJ-26-373|WBS-002.6|18,75,000.00
SINV-GJ-26-396|WBS-002.6|18,75,000.00
CNNV-GJ-26-14|WBS-002.6|-25,47,356.00
SINV-GJ-26-450|WBS-002.6|18,75,000.00
SINV-AP-26-10|WBS-019.1|2,25,97,959.24
"""

WBS_FIELDS = ["total_invoiced", "custom_revenue_actual", "custom_revenue_achievement_pct", "custom_revenue_balance"]


def execute():
	frappe.make_property_setter(
		{
			"doctype": "Sales Invoice",
			"fieldname": "custom_wbs_allocations",
			"property": "allow_on_submit",
			"value": 1,
			"property_type": "Check",
		}
	)
	frappe.clear_cache(doctype="Sales Invoice")

	try:
		link_invoices()
	finally:
		frappe.db.delete(
			"Property Setter",
			{"doc_type": "Sales Invoice", "field_name": "custom_wbs_allocations", "property": "allow_on_submit"},
		)
		frappe.clear_cache(doctype="Sales Invoice")


def link_invoices():
	rows_by_invoice = {}
	for line in DATA.strip().splitlines():
		invoice, wbs, amount = line.split("|")
		rows_by_invoice.setdefault(invoice, []).append((wbs, flt(amount.replace(",", ""))))

	# WBS to refresh: the new ones plus any WBS the invoices currently point to.
	wbs_to_refresh = {wbs for rows in rows_by_invoice.values() for wbs, _ in rows}
	for invoice in rows_by_invoice:
		wbs_to_refresh.update(
			frappe.get_all("Revenue WBS Allocation", filters={"parent": invoice, "parenttype": "Sales Invoice"}, pluck="wbs_element")
		)
	wbs_to_refresh.discard(None)

	wbs_before = {wbs: get_wbs_values(wbs) for wbs in wbs_to_refresh}

	invoice_lines = []
	skipped = []
	for invoice, rows in rows_by_invoice.items():
		if frappe.db.get_value("Sales Invoice", invoice, "docstatus") != 1:
			skipped.append(f"{invoice}: not found or not submitted")
			continue

		doc = frappe.get_doc("Sales Invoice", invoice)

		allocated = flt(sum(amount for _, amount in rows), 2)
		if abs(allocated - flt(doc.net_total, 2)) > 0.01:
			skipped.append(f"{invoice}: allocated {allocated}, net total {doc.net_total}")
			continue

		errors = [get_wbs_error(doc, wbs) for wbs, _ in rows]
		errors = [e for e in errors if e]
		if errors:
			skipped.append(f"{invoice}: {'; '.join(errors)}")
			continue

		before = ", ".join(f"{r.wbs_element} ({r.allocated_amount})" for r in doc.custom_wbs_allocations) or "none"
		after = ", ".join(f"{wbs} ({amount})" for wbs, amount in rows)

		old_rows = sorted((r.wbs_element, flt(r.allocated_amount, 2)) for r in doc.custom_wbs_allocations)
		new_rows = sorted((wbs, flt(amount, 2)) for wbs, amount in rows)
		if old_rows == new_rows:
			invoice_lines.append(f"{invoice}: {before} -> unchanged")
			continue

		doc.set("custom_wbs_allocations", [])
		for wbs, amount in rows:
			doc.append("custom_wbs_allocations", {"wbs_element": wbs, "allocated_amount": amount})
		doc.save(ignore_permissions=True)
		invoice_lines.append(f"{invoice}: {before} -> {after}")

	for wbs in wbs_to_refresh:
		refresh_wbs_revenue(wbs)

	wbs_lines = []
	for wbs in sorted(wbs_to_refresh):
		after = get_wbs_values(wbs)
		wbs_lines.append(f"{wbs}\n  Before: {format_wbs_values(wbs_before[wbs])}\n  After:  {format_wbs_values(after)}")

	message = (
		"Sales Invoice: before WBS -> after WBS\n" + "\n".join(invoice_lines)
		+ f"\n\nSkipped ({len(skipped)}):\n" + "\n".join(skipped)
		+ "\n\nWBS Element: before -> after\n" + "\n\n".join(wbs_lines)
	)
	frappe.log_error(title="Sales Invoice Revenue WBS patch (Oct 2026) - before / after", message=message)


def get_wbs_values(wbs):
	values = frappe.db.get_value("WBS Element", wbs, WBS_FIELDS, as_dict=True)
	values["invoices"] = frappe.get_all(
		"Revenue WBS Allocation",
		filters={"parenttype": "Sales Invoice", "docstatus": 1, "wbs_element": wbs},
		pluck="parent",
	)
	return values


def format_wbs_values(values):
	return (
		f"Total Invoiced {values.total_invoiced}, Revenue Actual {values.custom_revenue_actual}, "
		f"Achievement % {values.custom_revenue_achievement_pct}, Revenue Balance {values.custom_revenue_balance}, "
		f"Sales Invoices ({len(values.invoices)}): {', '.join(values.invoices)}"
	)


def get_wbs_error(doc, wbs):
	w = frappe.db.get_value("WBS Element", wbs, ["custom_category_type", "company", "status"], as_dict=True)
	if not w:
		return f"{wbs} not found"
	if w.custom_category_type != "Revenue":
		return f"{wbs} is not a Revenue WBS"
	if w.status == "Cancelled":
		return f"{wbs} is Cancelled"
	if w.company and w.company != doc.company:
		return f"{wbs} belongs to company {w.company}"


def refresh_wbs_revenue(wbs):
	# Same calculation as the "Sales Invoice - Revenue WBS Rollup (Submit)" server script.
	so_total = flt(frappe.db.sql(
		"""select ifnull(sum(allocated_amount), 0) from `tabRevenue WBS Allocation`
		where parenttype = 'Sales Order' and docstatus = 1 and wbs_element = %s""",
		wbs,
	)[0][0], 2)
	si_total = flt(frappe.db.sql(
		"""select ifnull(sum(allocated_amount), 0) from `tabRevenue WBS Allocation`
		where parenttype = 'Sales Invoice' and docstatus = 1 and wbs_element = %s""",
		wbs,
	)[0][0], 2)
	target = flt(frappe.db.get_value("WBS Element", wbs, "total_revenue"))
	pct = flt(si_total * 100.0 / target, 2) if target else 0

	frappe.db.set_value(
		"WBS Element",
		wbs,
		{
			"custom_revenue_committed": so_total,
			"custom_revenue_actual": si_total,
			"total_invoiced": si_total,
			"custom_revenue_achievement_pct": pct,
			"custom_revenue_balance": flt(target - si_total, 2),
		},
		update_modified=False,
	)
