// ABP2-I483 (Sahil 2026-07-01) — Cascade WO header Cost Center + Project
// to every required_items and operations row on before_save.
//
// Runs BEFORE Frappe's client-side check_mandatory so blank child rows
// get filled from the header and the "Cost Center / Project is required
// in rows 2-6" dialog never appears. The server-side validate_work_order
// hook (cc_project_guard.py) is the second line of defence and stays
// in place — this is UX polish so the user isn't asked to re-type CC
// and Project on every row.

frappe.provide("detox_project");

detox_project.wo_cascade_from_header = function (frm) {
	const header_cc = frm.doc.custom_cost_center || frm.doc.cost_center;
	const header_pj = frm.doc.project;
	if (!header_cc && !header_pj) return;

	["required_items", "operations"].forEach((table_field) => {
		const rows = frm.doc[table_field] || [];
		let touched = false;
		rows.forEach((row) => {
			if (header_cc && !row.cost_center) {
				row.cost_center = header_cc;
				touched = true;
			}
			if (header_pj && !row.project) {
				row.project = header_pj;
				touched = true;
			}
		});
		if (touched) frm.refresh_field(table_field);
	});
};

// ABP2-I483 reopen (Sahil 2026-07-01, Image #53): the Production Plan
// on_submit cascade (cc_project_guard.cascade_pp_to_work_orders) only
// stamps custom_cost_center if PP already has one. On this WO
// (MFG-WO-2026-00014) the PP submitted with a blank CC so the WO now
// shows Project auto-filled but Cost Center empty. Fall back to
// Project.cost_center (the default CC configured on the Project master)
// so the header self-heals as soon as the WO form loads.
detox_project.wo_fill_cc_from_project = function (frm) {
	if (frm.doc.custom_cost_center || frm.doc.cost_center) return;
	if (!frm.doc.project) return;
	frappe.db.get_value("Project", frm.doc.project, "cost_center").then((r) => {
		const project_cc = r && r.message && r.message.cost_center;
		if (!project_cc) return;
		// Set both header fields so downstream cascades pick it up.
		const target = frm.get_field("custom_cost_center") ? "custom_cost_center" : "cost_center";
		frm.set_value(target, project_cc);
		detox_project.wo_cascade_from_header(frm);
	});
};

frappe.ui.form.on("Work Order", {
	refresh: function (frm) {
		detox_project.wo_fill_cc_from_project(frm);
		detox_project.wo_cascade_from_header(frm);
	},
	before_save: function (frm) {
		detox_project.wo_cascade_from_header(frm);
	},
	custom_cost_center: function (frm) {
		detox_project.wo_cascade_from_header(frm);
	},
	cost_center: function (frm) {
		detox_project.wo_cascade_from_header(frm);
	},
	project: function (frm) {
		detox_project.wo_fill_cc_from_project(frm);
		detox_project.wo_cascade_from_header(frm);
	},
});

// Newly-added rows should inherit the header immediately so the grid
// preview shows the pre-filled values (matches L05/L06 semantics in
// cc_project_guard.py).
frappe.ui.form.on("Work Order Item", {
	required_items_add: function (frm) {
		detox_project.wo_cascade_from_header(frm);
	},
});

frappe.ui.form.on("Work Order Operation", {
	operations_add: function (frm) {
		detox_project.wo_cascade_from_header(frm);
	},
});
