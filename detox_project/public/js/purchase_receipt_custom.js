// Item WBS is copied from the PO row on save. The WBS Allocations table is
// validated against the item rows, and filled from them when empty
// (overrides/purchase_wbs.py). Table to item copy and amount sync: wbs_allocation_sync.js.

frappe.ui.form.on("Purchase Receipt", {
	onload(frm) {
		wbs_apply_handoff(frm);
	},

	refresh(frm) {
		set_wbs_queries(frm);
	},
});

// Every WBS / Sub WBS picker (WBS Allocations table and item rows) shows only Expense WBS of the document's project.
function set_wbs_queries(frm) {
	frm.set_query("wbs_element", "custom_wbs_allocations", () => {
		let filters = { status: "Active", custom_category_type: "Expense" };
		let project = wbs_doc_project(frm);
		if (project) filters.project = project;
		return { filters };
	});
	frm.set_query("sub_wbs_element", "custom_wbs_allocations", (doc, cdt, cdn) => {
		let row = locals[cdt][cdn];
		let filters = { status: "Active", custom_category_type: "Expense" };
		if (row.wbs_element) filters.main_wbs_element = row.wbs_element;
		return { filters };
	});
	frm.set_query("custom_wbs_element", "items", (doc, cdt, cdn) => {
		let row = locals[cdt][cdn];
		let filters = { status: "Active", custom_category_type: "Expense" };
		let project = row.project || wbs_doc_project(frm);
		if (project) filters.project = project;
		return { filters };
	});
	frm.set_query("custom_sub_wbs_element", "items", (doc, cdt, cdn) => {
		let row = locals[cdt][cdn];
		let filters = { status: "Active", custom_category_type: "Expense" };
		if (row.custom_wbs_element) filters.main_wbs_element = row.custom_wbs_element;
		return { filters };
	});
}

// Header Project, or the first item row's Project when the header is empty.
function wbs_doc_project(frm) {
	if (frm.doc.project) return frm.doc.project;
	const item = (frm.doc.items || []).find((r) => r.project);
	return item ? item.project : null;
}
