// ============================================================
// CLIENT SCRIPT  |  Doctype: Material Request
// The WBS Allocations table is validated against the item rows on save,
// and filled from them when empty (overrides/purchase_wbs.py).
//
// Table to item copy and amount sync: wbs_allocation_sync.js.
//
// REQ 1 - Picking a WBS fills an empty Company / Project / Cost Center,
//         and warns when the WBS belongs to another Project
// ============================================================

frappe.ui.form.on("Material Request", {
	onload(frm) {
		const h = wbs_apply_handoff(frm);
		// "Cost center filter in MR" can clear the Cost Center passed to new_doc.
		if (h) mr_fill_header_from_wbs(frm, h.wbs, false);
	},

	refresh(frm) {
		set_wbs_queries(frm);
	},
});

frappe.ui.form.on("Material Request Item", {
	custom_wbs_element(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (row.custom_wbs_element) mr_fill_header_from_wbs(frm, row.custom_wbs_element, true);
	},
});

// Child table handlers are global, so they also fire on other forms that use this table.
frappe.ui.form.on("WBS Allocation", {
	wbs_element(frm, cdt, cdn) {
		if (frm.doctype !== "Material Request") return;
		var row = locals[cdt][cdn];
		if (row.wbs_element) mr_fill_header_from_wbs(frm, row.wbs_element, true);
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

// REQ 1: fill empty header Company / Project / Cost Center from the WBS; never overwrite.
function mr_fill_header_from_wbs(frm, wbs, warn_mismatch) {
	if (frm.doc.docstatus !== 0) return;
	frappe.db.get_value("WBS Element", wbs, ["project", "cost_center", "company"]).then(function (r) {
		var d = (r && r.message) || {};
		if (warn_mismatch && d.project && frm.doc.project && d.project !== frm.doc.project) {
			frappe.show_alert({
				message: __("WBS {0} belongs to Project {1}, but this Material Request is for Project {2}.", [wbs, d.project, frm.doc.project]),
				indicator: "orange",
			}, 8);
			return;
		}
		var chain = Promise.resolve();
		if (d.company && !frm.doc.company) chain = chain.then(function () { return frm.set_value("company", d.company); });
		if (d.project && !frm.doc.project) chain = chain.then(function () { return frm.set_value("project", d.project); });
		chain.then(function () {
			// "Cost center filter in MR" clears cost_center when project changes, so set it last.
			setTimeout(function () {
				if (d.cost_center && !frm.doc.cost_center && frm.doc.docstatus === 0) frm.set_value("cost_center", d.cost_center);
			}, 400);
		});
	});
}

// Header Project, or the first item row's Project when the header is empty.
function wbs_doc_project(frm) {
	if (frm.doc.project) return frm.doc.project;
	const item = (frm.doc.items || []).find((r) => r.project);
	return item ? item.project : null;
}
