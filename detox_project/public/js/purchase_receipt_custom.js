// Item WBS is copied from the PO row on save. The WBS Allocations table is
// validated against the item rows, and filled from them when empty
// (overrides/purchase_wbs.py). Table to item copy and amount sync: wbs_allocation_sync.js.

frappe.ui.form.on("Purchase Receipt", {
	onload(frm) {
		wbs_apply_handoff(frm);
	},

	refresh(frm) {
		set_item_wbs_queries(frm);
	},
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
