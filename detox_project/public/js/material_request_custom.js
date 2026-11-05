// ============================================================
// CLIENT SCRIPT  |  Doctype: Material Request
// The WBS Allocations table is validated against the item rows on save,
// and filled from them when empty (overrides/purchase_wbs.py).
//
// REQ 1 - New MR opened from a WBS / Sub WBS Element: that WBS becomes
//         the default for every item row.
// REQ 2 - Picking a WBS fills an empty Company / Project / Cost Center,
//         and warns when the WBS belongs to another Project
// ============================================================

frappe.ui.form.on("Material Request", {
	onload(frm) {
		if (!frm.is_new()) return;

		// Opened from a WBS / Sub WBS Element (Create button or dashboard "+").
		var h = window.__detox_mr_wbs_handoff;
		window.__detox_mr_wbs_handoff = null;
		if (h && h.wbs) {
			// Frappe reuses frm across documents, so tie the default to this one.
			frm.__default_wbs = { wbs: h.wbs, sub_wbs: h.sub_wbs, docname: frm.docname };
			(frm.doc.items || []).forEach(function (item) { set_default_item_wbs(frm, item); });
			// "Cost center filter in MR" can clear the Cost Center passed to new_doc.
			mr_fill_header_from_wbs(frm, h.wbs, false);
		}
	},

	refresh(frm) {
		set_item_wbs_queries(frm);
	},
});

frappe.ui.form.on("Material Request Item", {
	items_add(frm, cdt, cdn) { set_default_item_wbs(frm, locals[cdt][cdn]); },
	custom_wbs_element(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (row.custom_wbs_element) mr_fill_header_from_wbs(frm, row.custom_wbs_element, true);
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

function set_default_item_wbs(frm, item) {
	var d = frm.__default_wbs;
	if (!d || d.docname !== frm.docname || item.custom_wbs_element) return;
	item.custom_wbs_element = d.wbs;
	item.custom_sub_wbs_element = d.sub_wbs || "";
	frm.refresh_field("items");
}

// REQ 2: fill empty header Company / Project / Cost Center from the WBS; never overwrite.
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
