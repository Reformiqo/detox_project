"""WBS on Material Request / Purchase Order / Purchase Receipt / Purchase Invoice.

The header table custom_wbs_allocations must hold one row per (WBS, Sub WBS) on
the item rows, amount = sum of item base_net_amount, in company currency like
the budget (Material Request: amount). Rows entered by hand are validated
against the items; an empty table is filled from the items.

Item WBS is copied down the chain MR item -> PO item -> PR item -> PI item.
"""

import frappe
from frappe import _
from frappe.utils import flt

TABLE = "custom_wbs_allocations"

# Item field that points to the source item row, and that row's doctype.
# The first filled one wins.
SOURCE_ROW_FIELDS = {
	"Purchase Order": [("material_request_item", "Material Request Item")],
	"Purchase Receipt": [
		("purchase_order_item", "Purchase Order Item"),
		("material_request_item", "Material Request Item"),
	],
	"Purchase Invoice": [
		("po_detail", "Purchase Order Item"),
		("pr_detail", "Purchase Receipt Item"),
	],
	"Sales Invoice": [
		("sales_invoice_item", "Sales Invoice Item"),
		("so_detail", "Sales Order Item"),
	],
}

# Zero-value sales documents are normal (rate contracts, customer material).
ZERO_AMOUNT_ALLOWED = ("Blanket Order", "Sales Order", "Sales Invoice")


def before_validate(doc, method=None):
	copy_wbs_from_source_rows(doc)
	doc.flags.fill_wbs_allocations = not doc.get(TABLE)
	# Filled here as well so the other apps' validate hooks (closed-WBS guard)
	# already see the WBS rows.
	if doc.flags.fill_wbs_allocations:
		rebuild_wbs_allocations(doc)


def validate(doc, method=None):
	validate_item_wbs(doc)
	# Filled again: net_amount is final only after ERPNext's own validate.
	if doc.flags.fill_wbs_allocations:
		rebuild_wbs_allocations(doc)
	validate_wbs_allocations(doc)


def before_update_after_submit(doc, method=None):
	# "Update Items" on a submitted PO changes the rows without running validate.
	# Any other edit after submit must not touch the header.
	if doc.flags.ignore_validate_update_after_submit:
		rebuild_wbs_allocations(doc)


def copy_wbs_from_source_rows(doc):
	"""Fill a blank item WBS / Sub WBS from its source row, and block a row
	whose WBS differs from the source row."""
	for item in doc.items:
		source = get_source_row(doc.doctype, item)
		if not source or not source.custom_wbs_element:
			continue

		if not item.custom_wbs_element:
			item.custom_wbs_element = source.custom_wbs_element
		if not item.custom_sub_wbs_element:
			item.custom_sub_wbs_element = source.custom_sub_wbs_element

		if item.custom_wbs_element != source.custom_wbs_element or (
			source.custom_sub_wbs_element and item.custom_sub_wbs_element != source.custom_sub_wbs_element
		):
			frappe.throw(
				_("Row {0}: WBS {1} / Sub WBS {2} must match its source row ({3} / {4}).").format(
					item.idx,
					item.custom_wbs_element,
					item.custom_sub_wbs_element or "-",
					source.custom_wbs_element,
					source.custom_sub_wbs_element or "-",
				),
				title=_("WBS Mismatch"),
			)


def get_source_row(doctype, item):
	# A Sales Order row links to its Blanket Order by item code, not by row.
	if doctype == "Sales Order" and item.get("blanket_order"):
		return frappe.db.get_value(
			"Blanket Order Item",
			{"parent": item.blanket_order, "item_code": item.item_code},
			["custom_wbs_element", "custom_sub_wbs_element"],
			as_dict=True,
		)

	for field, source_doctype in SOURCE_ROW_FIELDS.get(doctype, []):
		if item.get(field):
			return frappe.db.get_value(
				source_doctype,
				item.get(field),
				["custom_wbs_element", "custom_sub_wbs_element"],
				as_dict=True,
			)
	return None


def validate_item_wbs(doc):
	missing = [str(item.idx) for item in doc.items if not item.custom_wbs_element]
	if missing and len(missing) < len(doc.items):
		frappe.throw(
			_(
				"WBS Element is missing on row(s) {0}. When one item has a WBS, every item "
				"(including freight and transport rows) must have one."
			).format(", ".join(missing)),
			title=_("WBS Missing"),
		)

	for item in doc.items:
		if item.custom_sub_wbs_element and not item.custom_wbs_element:
			frappe.throw(_("Row {0}: select the WBS Element of Sub WBS {1}.").format(
				item.idx, item.custom_sub_wbs_element))
		if not item.custom_wbs_element:
			continue

		project = item.get("project") or doc.get("project")
		wbs_project = frappe.get_cached_value("WBS Element", item.custom_wbs_element, "project")
		if project and wbs_project != project:
			frappe.throw(_("Row {0}: WBS {1} belongs to Project {2}, not {3}.").format(
				item.idx, item.custom_wbs_element, wbs_project, project))

		if item.custom_sub_wbs_element:
			main_wbs = frappe.get_cached_value(
				"Sub WBS Element", item.custom_sub_wbs_element, "main_wbs_element")
			if main_wbs != item.custom_wbs_element:
				frappe.throw(_("Row {0}: Sub WBS {1} belongs to WBS {2}, not {3}.").format(
					item.idx, item.custom_sub_wbs_element, main_wbs, item.custom_wbs_element))


def get_item_amount(doc, item):
	if doc.doctype == "Material Request":
		return flt(item.amount)
	# Blanket Order Item has no amount field; custom_net_total is also qty x rate.
	if doc.doctype == "Blanket Order":
		return flt(item.qty) * flt(item.rate)
	return flt(item.base_net_amount)


def get_item_wbs_totals(doc):
	totals = {}
	for item in doc.items:
		if not item.custom_wbs_element:
			continue
		key = (item.custom_wbs_element, item.custom_sub_wbs_element or "")
		totals[key] = totals.get(key, 0) + get_item_amount(doc, item)
	return totals


def rebuild_wbs_allocations(doc):
	doc.set(TABLE, [])
	for (wbs, sub_wbs), amount in get_item_wbs_totals(doc).items():
		doc.append(TABLE, {
			"wbs_element": wbs,
			"sub_wbs_element": sub_wbs,
			"allocated_amount": flt(amount, 2),
		})


def validate_wbs_allocations(doc):
	"""Keep the WBS Allocations table and the item rows consistent."""
	item_totals = get_item_wbs_totals(doc)

	allocated = {}
	for row in doc.get(TABLE):
		key = (row.wbs_element, row.sub_wbs_element or "")
		if key not in item_totals:
			frappe.throw(
				_("WBS Allocations row {0}: no item has WBS {1} / Sub WBS {2}. "
					"Set it on an item row or remove this row.").format(
					row.idx, row.wbs_element, row.sub_wbs_element or "-"),
				title=_("WBS Without Item"),
			)
		if key in allocated:
			frappe.throw(
				_("WBS Allocations row {0}: WBS {1} / Sub WBS {2} is entered twice. Keep one row for it.").format(
					row.idx, row.wbs_element, row.sub_wbs_element or "-"),
				title=_("Duplicate WBS"),
			)
		allocated[key] = flt(row.allocated_amount)

	for (wbs, sub_wbs), item_amount in item_totals.items():
		if not flt(item_amount, 2) and doc.doctype not in ZERO_AMOUNT_ALLOWED:
			frappe.throw(
				_("WBS {0} has a zero amount. Enter the rate on its item rows.").format(sub_wbs or wbs),
				title=_("Zero WBS Amount"),
			)
		if (wbs, sub_wbs) not in allocated:
			frappe.throw(
				_("Item rows have WBS {0} / Sub WBS {1}, but WBS Allocations has no row for it.").format(
					wbs, sub_wbs or "-"),
				title=_("WBS Mismatch"),
			)
		if flt(allocated[(wbs, sub_wbs)], 2) != flt(item_amount, 2):
			frappe.throw(
				_("WBS {0} / Sub WBS {1}: Allocated Amount {2} does not match the item amount {3}. "
					"Correct the amount, or clear the WBS Allocations table to fill it from the items.").format(
					wbs, sub_wbs or "-", flt(allocated[(wbs, sub_wbs)], 2), flt(item_amount, 2)),
				title=_("WBS Mismatch"),
			)
