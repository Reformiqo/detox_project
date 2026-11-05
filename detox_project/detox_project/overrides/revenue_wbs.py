"""Revenue WBS Allocation on Blanket Order / Sales Order / Delivery Note / Sales Invoice.

Ported from the SEPPL Server Scripts "<Doctype> - Revenue WBS Allocation Validate",
"Revenue WBS Rollup", "Sales Order - Revenue WBS Resync (Update Items)",
"WBS Element / Sub WBS Element - Revenue Achievement".
"""

import frappe
from frappe.utils import flt, fmt_money

TABLE = "custom_wbs_allocations"


def _base_amount(doc):
	if doc.doctype == "Blanket Order":
		return flt(doc.get("custom_net_total"))
	return flt(doc.get("net_total"))


def _project(doc):
	if doc.get("project"):
		return doc.project
	for it in doc.get("items") or []:
		if it.get("project"):
			return it.project
	return None


def _source_of(doc, item):
	"""The document an item was created from, as (doctype, name)."""
	if doc.doctype in ("Sales Invoice", "Delivery Note") and doc.get("is_return") and doc.get("return_against"):
		return doc.doctype, doc.return_against
	if doc.doctype == "Sales Order" and item.get("blanket_order"):
		return "Blanket Order", item.blanket_order
	if doc.doctype == "Sales Invoice":
		if item.get("delivery_note"):
			return "Delivery Note", item.delivery_note
		if item.get("sales_order"):
			return "Sales Order", item.sales_order
	if doc.doctype == "Delivery Note" and item.get("against_sales_order"):
		return "Sales Order", item.against_sales_order
	return None, None


def _copy_from_sources(doc):
	"""Copy the allocation from each source document, in proportion to the value taken from it."""
	src_amount = {}
	for it in doc.get("items") or []:
		sdt, sname = _source_of(doc, it)
		if sname:
			src_amount[(sdt, sname)] = src_amount.get((sdt, sname), 0.0) + flt(it.get("net_amount"))

	merged = {}
	for (sdt, sname), amount in src_amount.items():
		rows = frappe.get_all(
			"Revenue WBS Allocation",
			filters={"parenttype": sdt, "parent": sname},
			fields=["wbs_element", "sub_wbs_element", "category", "allocated_amount"],
			order_by="idx asc",
		)
		if not rows:
			continue
		total_field = "custom_net_total" if sdt == "Blanket Order" else "net_total"
		src_base = flt(frappe.db.get_value(sdt, sname, total_field))
		if not src_base:
			continue
		ratio = amount / src_base
		for r in rows:
			key = (r.wbs_element or "", r.sub_wbs_element or "", r.category or "")
			if key not in merged:
				merged[key] = {"wbs_element": r.wbs_element, "sub_wbs_element": r.sub_wbs_element, "category": r.category, "allocated_amount": 0.0}
			merged[key]["allocated_amount"] += flt(r.allocated_amount) * ratio

	for row in merged.values():
		row["allocated_amount"] = flt(row["allocated_amount"], 2)
		doc.append(TABLE, row)


def _sync_amounts(allocs, base):
	"""Keep Allocated Amount equal to the Net Total: one row takes it all, several rows re-scale."""
	if not base:
		for row in allocs:
			row.allocated_amount = 0
		return
	if len(allocs) == 1:
		allocs[0].allocated_amount = flt(base, 2)
		return

	assigned = sum(flt(row.get("allocated_amount")) for row in allocs)
	remaining = flt(base - assigned, 2)
	if remaining:
		for row in allocs:
			if not flt(row.get("allocated_amount")):
				row.allocated_amount = remaining
				break

	total_now = sum(flt(row.get("allocated_amount")) for row in allocs)
	if not total_now:
		allocs[0].allocated_amount = flt(base, 2)
		total_now = flt(base, 2)
	if abs(flt(total_now, 2) - flt(base, 2)) > 0.009:
		ratio = base / total_now
		running = 0.0
		for i, row in enumerate(allocs):
			if i == len(allocs) - 1:
				row.allocated_amount = flt(base - running, 2)
			else:
				row.allocated_amount = flt(flt(row.get("allocated_amount")) * ratio, 2)
				running += row.allocated_amount


def _validate_rows(doc, allocs, project):
	seen = []
	for row in allocs:
		label = f"Revenue WBS Allocations Row {row.idx}: "
		if not row.get("wbs_element"):
			frappe.throw(label + "WBS Element is mandatory.")
		w = frappe.db.get_value(
			"WBS Element", row.wbs_element, ["custom_category_type", "project", "company", "status", "category"], as_dict=1
		)
		if not w:
			frappe.throw(label + f"WBS Element {row.wbs_element} does not exist.")
		if w.custom_category_type != "Revenue":
			frappe.throw(label + f"WBS Element {row.wbs_element} is not a Revenue WBS. Please select a Revenue WBS Element.")
		if w.status == "Cancelled":
			frappe.throw(label + f"WBS Element {row.wbs_element} is Cancelled.")
		if project and w.project and w.project != project:
			frappe.throw(label + f"WBS Element {row.wbs_element} belongs to project {w.project}, but this document is for project {project}.")
		if doc.get("company") and w.company and w.company != doc.company:
			frappe.throw(label + f"WBS Element {row.wbs_element} belongs to company {w.company}.")

		if row.get("sub_wbs_element"):
			s = frappe.db.get_value("Sub WBS Element", row.sub_wbs_element, ["main_wbs_element", "status"], as_dict=1)
			if not s:
				frappe.throw(label + f"Sub WBS {row.sub_wbs_element} does not exist.")
			if s.main_wbs_element != row.wbs_element:
				frappe.throw(label + f"Sub WBS {row.sub_wbs_element} does not belong to WBS {row.wbs_element}.")
			if s.status == "Cancelled":
				frappe.throw(label + f"Sub WBS {row.sub_wbs_element} is Cancelled.")

		if not row.get("category") and w.category:
			row.category = w.category
		if row.get("category"):
			if frappe.db.get_value("Project Cost Category", row.category, "custom_category_type") == "Expense":
				frappe.throw(label + f"Category {row.category} is an Expense category. Please select a Revenue category.")

		key = (row.get("wbs_element") or "", row.get("sub_wbs_element") or "", row.get("category") or "")
		if key in seen:
			frappe.throw(label + "duplicate allocation for the same WBS / Sub WBS / Category.")
		seen.append(key)


def validate_allocations(doc, method=None):
	"""validate: copy the allocation from the source document, sync amounts, check every row."""
	allocs = doc.get(TABLE) or []
	base = _base_amount(doc)
	project = _project(doc)

	if doc.doctype == "Blanket Order":
		# Mandatory on a Selling Blanket Order once the project has an active Revenue WBS.
		if not allocs and doc.get("blanket_order_type") == "Selling" and project and base:
			if frappe.db.exists("WBS Element", {"project": project, "custom_category_type": "Revenue", "status": ["!=", "Cancelled"]}):
				frappe.throw(
					f"Revenue WBS Allocation is mandatory on a Selling Blanket Order for project {project}. Please add at least one row in the Revenue WBS Allocations table.",
					title="Revenue WBS Allocation Required",
				)
	elif not allocs:
		_copy_from_sources(doc)
		allocs = doc.get(TABLE) or []

	if allocs:
		_sync_amounts(allocs, base)
		_validate_rows(doc, allocs, project)


def warn_revenue_target(doc, method=None):
	"""before_submit: warn (never block) when the allocation pushes a WBS past its Total Revenue."""
	# Sales Order counts towards Revenue Committed, Sales Invoice towards Actual Revenue.
	field = "custom_revenue_committed" if doc.doctype == "Sales Order" else "custom_revenue_actual"
	what = "Revenue Committed" if doc.doctype == "Sales Order" else "Actual Revenue"

	msgs = []
	for row in doc.get(TABLE) or []:
		amt = flt(row.get("allocated_amount"))
		if amt <= 0:
			continue
		if row.get("wbs_element"):
			wv = frappe.db.get_value("WBS Element", row.wbs_element, ["total_revenue", field], as_dict=1)
			if wv and flt(wv.total_revenue) and flt(wv.get(field)) + amt > flt(wv.total_revenue) + 0.5:
				msgs.append(
					f"WBS {row.wbs_element}: {what} will be {fmt_money(flt(wv.get(field)) + amt, currency='INR')} against Total Revenue {fmt_money(wv.total_revenue, currency='INR')}."
				)
		if row.get("sub_wbs_element"):
			sv = frappe.db.get_value("Sub WBS Element", row.sub_wbs_element, ["custom_total_revenue", field], as_dict=1)
			if sv and flt(sv.custom_total_revenue) and flt(sv.get(field)) + amt > flt(sv.custom_total_revenue) + 0.5:
				msgs.append(
					f"Sub WBS {row.sub_wbs_element}: {what} will be {fmt_money(flt(sv.get(field)) + amt, currency='INR')} against Total Revenue {fmt_money(sv.custom_total_revenue, currency='INR')}."
				)
	if msgs:
		frappe.msgprint(
			"<br>".join(msgs) + "<br><br>The document has been allowed. Increase Total Revenue on the WBS if the target has changed.",
			title="Revenue target exceeded",
			indicator="orange",
		)


def _submitted_total(parenttype, link_field, name):
	return flt(
		frappe.db.sql(
			f"""select ifnull(sum(allocated_amount), 0) from `tabRevenue WBS Allocation`
			where parenttype=%s and docstatus=1 and {link_field}=%s""",
			(parenttype, name),
		)[0][0],
		2,
	)


def rollup(doc, method=None):
	"""on_submit / on_cancel / Update Items: recompute revenue totals on the WBS and Sub WBS from all submitted SO / SI."""
	wbs_set = {row.wbs_element for row in doc.get(TABLE) or [] if row.get("wbs_element")}
	sub_set = {row.sub_wbs_element for row in doc.get(TABLE) or [] if row.get("sub_wbs_element")}

	for w in wbs_set:
		so_total = _submitted_total("Sales Order", "wbs_element", w)
		si_total = _submitted_total("Sales Invoice", "wbs_element", w)
		target = flt(frappe.db.get_value("WBS Element", w, "total_revenue"))
		pct = flt(si_total * 100.0 / target, 2) if target else 0
		frappe.db.set_value(
			"WBS Element",
			w,
			{
				"custom_revenue_committed": so_total,
				"custom_revenue_actual": si_total,
				"total_invoiced": si_total,
				"custom_revenue_achievement_pct": pct,
				"custom_revenue_balance": flt(target - si_total, 2),
			},
			update_modified=False,
		)

	for w in sub_set:
		so_total = _submitted_total("Sales Order", "sub_wbs_element", w)
		si_total = _submitted_total("Sales Invoice", "sub_wbs_element", w)
		target = flt(frappe.db.get_value("Sub WBS Element", w, "custom_total_revenue"))
		pct = flt(si_total * 100.0 / target, 2) if target else 0
		frappe.db.set_value(
			"Sub WBS Element",
			w,
			{
				"custom_revenue_committed": so_total,
				"custom_revenue_actual": si_total,
				"custom_revenue_achievement_pct": pct,
				"custom_revenue_balance": flt(target - si_total, 2),
			},
			update_modified=False,
		)


def resync_after_update_items(doc, method=None):
	"""on_update_after_submit (Sales Order "Update Items"): re-scale Allocated Amount to the new Net Total, then roll up."""
	allocs = doc.get(TABLE) or []
	if not allocs:
		return
	base = flt(doc.get("net_total"))
	total_now = sum(flt(row.get("allocated_amount")) for row in allocs)
	if abs(flt(total_now, 2) - flt(base, 2)) > 0.009:
		n = len(allocs)
		running = 0.0
		for i, row in enumerate(allocs, start=1):
			if not base:
				v = 0
			elif not total_now:
				v = flt(base, 2) if i == 1 else 0
			elif i == n:
				v = flt(base - running, 2)
			else:
				v = flt(flt(row.get("allocated_amount")) * base / total_now, 2)
			running += flt(v)
			frappe.db.set_value("Revenue WBS Allocation", row.name, "allocated_amount", v, update_modified=False)
			row.allocated_amount = v
	rollup(doc)


def wbs_revenue_achievement(doc, method=None):
	"""WBS Element validate: on a Revenue WBS derive Total Invoiced, Achievement % and Balance from Actual Revenue."""
	if doc.get("custom_category_type") != "Revenue":
		return
	target = flt(doc.get("total_revenue"))
	actual = flt(doc.get("custom_revenue_actual"))
	doc.total_invoiced = actual
	doc.custom_revenue_achievement_pct = flt(actual * 100.0 / target, 2) if target else 0
	doc.custom_revenue_balance = flt(target - actual, 2)


def sub_wbs_revenue_achievement(doc, method=None):
	"""Sub WBS Element validate: on a Revenue Sub WBS derive Achievement % and Balance from Actual Revenue."""
	if doc.get("custom_category_type") != "Revenue":
		return
	target = flt(doc.get("custom_total_revenue"))
	actual = flt(doc.get("custom_revenue_actual"))
	doc.custom_revenue_achievement_pct = flt(actual * 100.0 / target, 2) if target else 0
	doc.custom_revenue_balance = flt(target - actual, 2)
