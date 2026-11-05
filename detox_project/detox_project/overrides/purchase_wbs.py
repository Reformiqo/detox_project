"""WBS on Material Request / Purchase Order / Purchase Receipt / Purchase Invoice.

The item rows (custom_wbs_element / custom_sub_wbs_element) are the only place
a user picks a WBS. The header table custom_wbs_allocations is read-only and is
rebuilt from the items on every save: one row per (WBS, Sub WBS), amount =
sum of item base_net_amount, in company currency like the budget
(Material Request: amount).

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
}


def before_validate(doc, method=None):
	copy_wbs_from_source_rows(doc)
	# Built here as well so the other apps' validate hooks (closed-WBS guard)
	# already see the right WBS rows.
	rebuild_wbs_allocations(doc)


def validate(doc, method=None):
	validate_item_wbs(doc)
	# Rebuilt again: net_amount is final only after ERPNext's own validate.
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


def rebuild_wbs_allocations(doc):
	amount_field = "amount" if doc.doctype == "Material Request" else "base_net_amount"

	totals = {}
	for item in doc.items:
		if not item.custom_wbs_element:
			continue
		key = (item.custom_wbs_element, item.custom_sub_wbs_element or "")
		totals[key] = totals.get(key, 0) + flt(item.get(amount_field))

	doc.set(TABLE, [])
	for (wbs, sub_wbs), amount in totals.items():
		doc.append(TABLE, {
			"wbs_element": wbs,
			"sub_wbs_element": sub_wbs,
			"allocated_amount": flt(amount, 2),
		})


def validate_wbs_allocations(doc):
	for row in doc.get(TABLE):
		if not row.allocated_amount:
			frappe.throw(
				_("WBS {0} has a zero amount. Enter the rate on its item rows.").format(
					row.sub_wbs_element or row.wbs_element),
				title=_("Zero WBS Amount"),
			)
