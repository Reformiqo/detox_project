// The WBS Allocations table is validated against the item rows on save,
// and filled from them when empty (overrides/purchase_wbs.py).

frappe.ui.form.on("Purchase Order", {
	onload(frm) {
		if (!frm.is_new()) return;

		// Opened from a WBS Element (Create > Purchase Order): that WBS becomes
		// the default for every item row.
		var h = window.__detox_mr_wbs_handoff;
		window.__detox_mr_wbs_handoff = null;
		if (h && h.wbs) {
			// Frappe reuses frm across documents, so tie the default to this one.
			frm.__default_wbs = { wbs: h.wbs, sub_wbs: h.sub_wbs, docname: frm.docname };
			(frm.doc.items || []).forEach(function (item) { set_default_item_wbs(frm, item); });
		}
	},

	refresh(frm) {
		set_item_wbs_queries(frm);
	},
});

frappe.ui.form.on("Purchase Order Item", {
	items_add(frm, cdt, cdn) { set_default_item_wbs(frm, locals[cdt][cdn]); },
});

function set_item_wbs_queries(frm) {
	frm.set_query("custom_wbs_element", "items", (doc, cdt, cdn) => {
		let row = locals[cdt][cdn];
		let filters = { status: "Active" };
		if (row.project || frm.doc.project) filters.project = row.project || frm.doc.project;
		return { filters };
	});
	frm.set_query("custom_sub_wbs_element", "items", (doc, cdt, cdn) => {
		let row = locals[cdt][cdn];
		let filters = { status: "Active" };
		if (row.custom_wbs_element) filters.main_wbs_element = row.custom_wbs_element;
		return { filters };
	});
}

function set_default_item_wbs(frm, item) {
	var d = frm.__default_wbs;
	if (!d || d.docname !== frm.docname || item.custom_wbs_element) return;
	item.custom_wbs_element = d.wbs;
	item.custom_sub_wbs_element = d.sub_wbs || "";
	frm.refresh_field("items");
}
