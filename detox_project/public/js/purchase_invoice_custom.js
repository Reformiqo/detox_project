// WBS / Sub WBS are picked on the item rows only (copied from the PO / PR
// row on save). The WBS Allocations table is read-only and rebuilt from
// the items on save (overrides/purchase_wbs.py).

frappe.ui.form.on("Purchase Invoice", {
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
