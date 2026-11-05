// WBS Allocations table on purchase and sales forms. Server side:
// overrides/purchase_wbs.py and overrides/revenue_wbs.py.
// - A new item takes the WBS of the first table row; the user changes it by hand.
// - Allocated Amount follows the amount of the items on that WBS.

// Loaded by every form below; bind the handlers only on the first load.
if (!window.wbs_allocation_sync_bound) {
window.wbs_allocation_sync_bound = true;

const WBS_SALES_DOCTYPES = ["Blanket Order", "Sales Order", "Sales Invoice"];
const WBS_DOCTYPES = ["Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice"].concat(WBS_SALES_DOCTYPES);

// Opened from a WBS / Sub WBS Element (Create button or dashboard "+"). Returns the hand-off.
window.wbs_apply_handoff = function (frm) {
	if (!frm.is_new()) return null;
	const h = window.__detox_mr_wbs_handoff;
	window.__detox_mr_wbs_handoff = null;
	if (!h || !h.wbs) return null;

	const row = frm.add_child("custom_wbs_allocations");
	// set_value, not a plain assign: WBS Budget / WBS Spent fetch from the WBS.
	frappe.model.set_value(row.doctype, row.name, "wbs_element", h.wbs).then(() => {
		if (h.sub_wbs) frappe.model.set_value(row.doctype, row.name, "sub_wbs_element", h.sub_wbs);
	});
	frm.refresh_field("custom_wbs_allocations");
	// Sales Invoice adds its first item row after onload.
	setTimeout(() => frappe.after_ajax(() => wbs_copy_single_to_first_item(frm)), 500);
	return h;
};

function wbs_copy_first_row_to_item(frm, item) {
	if (frm.doc.docstatus !== 0 || item.custom_wbs_element) return;
	const row = (frm.doc.custom_wbs_allocations || []).find((r) => r.wbs_element);
	if (!row) return;

	item.custom_wbs_element = row.wbs_element;
	item.custom_sub_wbs_element = row.sub_wbs_element || "";
	frm.refresh_field("items");
	wbs_sync_amounts(frm);
}

// The first table row reaches an item row that is already on the form.
function wbs_copy_single_to_first_item(frm) {
	if (frm.doc.docstatus !== 0) return;
	const rows = (frm.doc.custom_wbs_allocations || []).filter((r) => r.wbs_element);
	const item = (frm.doc.items || [])[0];
	if (rows.length !== 1 || !item) return;

	if (!item.custom_wbs_element) {
		item.custom_wbs_element = rows[0].wbs_element;
		item.custom_sub_wbs_element = rows[0].sub_wbs_element || "";
	} else if (item.custom_wbs_element === rows[0].wbs_element && !item.custom_sub_wbs_element) {
		item.custom_sub_wbs_element = rows[0].sub_wbs_element || "";
	}
	frm.refresh_field("items");
	wbs_sync_amounts(frm);
}

// Same amounts as get_item_amount in overrides/purchase_wbs.py.
function wbs_item_amount(frm, item) {
	if (frm.doctype === "Material Request" || frm.doctype === "Blanket Order") {
		return flt(item.qty) * flt(item.rate);
	}
	return flt(item.base_net_amount);
}

// A row with no item goes to 0; the server then blocks it on save.
function wbs_sync_amounts(frm) {
	if (frm.doc.docstatus !== 0) return;
	const items = frm.doc.items || [];
	// A sales document with no item WBS keeps the old flow (revenue_wbs_allocation.js).
	if (WBS_SALES_DOCTYPES.includes(frm.doctype) && !items.some((i) => i.custom_wbs_element)) return;

	const totals = {};
	items.forEach((item) => {
		const key = (item.custom_wbs_element || "") + "||" + (item.custom_sub_wbs_element || "");
		totals[key] = (totals[key] || 0) + wbs_item_amount(frm, item);
	});

	(frm.doc.custom_wbs_allocations || []).forEach((row) => {
		if (!row.wbs_element) return;
		const amount = flt(totals[row.wbs_element + "||" + (row.sub_wbs_element || "")], 2);
		if (row.allocated_amount == null || flt(row.allocated_amount, 2) !== amount) {
			frappe.model.set_value(row.doctype, row.name, "allocated_amount", amount);
		}
	});
}

// ERPNext recalculates the amounts in its own handlers for the same event, and
// picking an item fetches the rate from the server without firing a rate event.
function wbs_sync_amounts_delayed(frm) {
	setTimeout(() => frappe.after_ajax(() => wbs_sync_amounts(frm)), 300);
}

// The purchase forms call wbs_apply_handoff from their own scripts.
WBS_SALES_DOCTYPES.concat("Delivery Note").forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		onload(frm) { wbs_apply_handoff(frm); },
		// A stuck onload handler from another script stops the ones after it.
		refresh(frm) { wbs_apply_handoff(frm); },
	});
});

WBS_DOCTYPES.forEach((doctype) => {
	// Header discounts and exchange rate change the amounts too.
	frappe.ui.form.on(doctype, {
		validate(frm) { wbs_sync_amounts(frm); },
	});

	frappe.ui.form.on(doctype + " Item", {
		items_add(frm, cdt, cdn) { wbs_copy_first_row_to_item(frm, locals[cdt][cdn]); },
		items_remove: wbs_sync_amounts_delayed,
		item_code: wbs_sync_amounts_delayed,
		qty: wbs_sync_amounts_delayed,
		rate: wbs_sync_amounts_delayed,
		amount: wbs_sync_amounts_delayed,
		custom_wbs_element: wbs_sync_amounts_delayed,
		custom_sub_wbs_element: wbs_sync_amounts_delayed,
	});
});

// Child table handlers are global, so they also fire on other forms that use these tables.
["WBS Allocation", "Revenue WBS Allocation"].forEach((child_doctype) => {
	frappe.ui.form.on(child_doctype, {
		wbs_element(frm) {
			if (WBS_DOCTYPES.includes(frm.doctype)) wbs_copy_single_to_first_item(frm);
			if (WBS_DOCTYPES.includes(frm.doctype)) wbs_sync_amounts(frm);
		},
		sub_wbs_element(frm) {
			if (WBS_DOCTYPES.includes(frm.doctype)) wbs_copy_single_to_first_item(frm);
			if (WBS_DOCTYPES.includes(frm.doctype)) wbs_sync_amounts(frm);
		},
		custom_wbs_allocations_remove(frm) {
			if (WBS_DOCTYPES.includes(frm.doctype)) wbs_copy_single_to_first_item(frm);
		},
	});
});
}
