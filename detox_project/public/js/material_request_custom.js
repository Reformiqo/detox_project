// ============================================================
// CLIENT SCRIPT  |  Doctype: Material Request
// REQ 1 - Auto-fill WBS Allocations from Sub WBS Element
// REQ 2 - Roll-up item amounts into WBS Allocation rows
// REQ 3 - Single WBS auto-assign to all items
// REQ 4 - Picking a WBS fills an empty Company / Project / Cost Center,
//         and warns when the WBS belongs to another Project
// ============================================================

frappe.ui.form.on("Material Request", {
	onload(frm) {
		if (!frm.is_new()) return;

		// Opened from a WBS / Sub WBS Element (Create button or dashboard "+").
		var h = window.__detox_mr_wbs_handoff;
		window.__detox_mr_wbs_handoff = null;
		if (h && h.wbs) {
			var row = frm.add_child("custom_wbs_allocations");
			row.wbs_element = h.wbs;
			if (h.sub_wbs) row.sub_wbs_element = h.sub_wbs;
			frm.refresh_field("custom_wbs_allocations");
			mr_fill_header_from_wbs(frm, h.wbs, false);
			return;
		}

		var route_opts = frappe.route_options || {};
		var sub_wbs = route_opts.sub_wbs_element || route_opts._wbs_element;
		if (!sub_wbs) return;
		delete frappe.route_options.sub_wbs_element;
		delete frappe.route_options._wbs_element;

		// Check if it's a WBS Element or Sub WBS Element
		if (sub_wbs.startsWith("WBS-")) {
			// Direct WBS Element — add allocation row
			if (!frm.doc.custom_wbs_allocations || frm.doc.custom_wbs_allocations.length === 0) {
				var row = frm.add_child("custom_wbs_allocations");
				frappe.model.set_value(row.doctype, row.name, "wbs_element", sub_wbs);
				frm.refresh_field("custom_wbs_allocations");
			}
		} else {
			// Sub WBS Element — fetch main WBS
			frappe.db.get_value("Sub WBS Element", sub_wbs,
				["name", "main_wbs_element"], function (r) {
					if (!r || !r.main_wbs_element) return;
					frm.doc.custom_wbs_allocations = [];
					var row = frappe.model.add_child(frm.doc, "WBS Allocation", "custom_wbs_allocations");
					row.wbs_element = r.main_wbs_element;
					row.sub_wbs_element = sub_wbs;
					frm.refresh_field("custom_wbs_allocations");
				}
			);
		}
	},

	refresh(frm) {
		// Query filters for WBS Allocation child table
		frm.set_query("wbs_element", "custom_wbs_allocations", () => {
			let filters = { status: "Active" };
			if (frm.doc.project) filters.project = frm.doc.project;
			return { filters };
		});
		frm.set_query("sub_wbs_element", "custom_wbs_allocations", (frm, cdt, cdn) => {
			let row = locals[cdt][cdn];
			let filters = { status: "Active" };
			if (row.wbs_element) filters.main_wbs_element = row.wbs_element;
			return { filters };
		});

		// Item-level WBS queries
		frm.set_query("custom_wbs_element", "items", () => {
			let filters = { status: "Active" };
			if (frm.doc.project) filters.project = frm.doc.project;
			return { filters };
		});
		frm.set_query("custom_sub_wbs_element", "items", (frm, cdt, cdn) => {
			let row = locals[cdt][cdn];
			let filters = { status: "Active" };
			if (row.custom_wbs_element) filters.main_wbs_element = row.custom_wbs_element;
			return { filters };
		});

		calculate_wbs_allocated_amounts(frm);
	},
});

frappe.ui.form.on("Material Request Item", {
	custom_wbs_element(frm) { calculate_wbs_allocated_amounts(frm); },
	custom_sub_wbs_element(frm) { calculate_wbs_allocated_amounts(frm); },
	amount(frm) { handle_single_wbs_auto_assign(frm); calculate_wbs_allocated_amounts(frm); },
	rate(frm) { handle_single_wbs_auto_assign(frm); calculate_wbs_allocated_amounts(frm); },
	qty(frm) { handle_single_wbs_auto_assign(frm); calculate_wbs_allocated_amounts(frm); },
	items_remove(frm) { calculate_wbs_allocated_amounts(frm); },
});

frappe.ui.form.on("WBS Allocation", {
	wbs_element(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (frm.doctype === "Material Request" && row.wbs_element) mr_fill_header_from_wbs(frm, row.wbs_element, true);
		handle_single_wbs_auto_assign(frm);
		calculate_wbs_allocated_amounts(frm);
	},
	sub_wbs_element(frm) { handle_single_wbs_auto_assign(frm); calculate_wbs_allocated_amounts(frm); },
	custom_wbs_allocations_remove(frm) { calculate_wbs_allocated_amounts(frm); },
});

// REQ 3: If exactly ONE WBS Allocation row → assign to all items without WBS
function handle_single_wbs_auto_assign(frm) {
	var allocs = frm.doc.custom_wbs_allocations || [];
	if (allocs.length !== 1 || !allocs[0].wbs_element) return;
	var w = allocs[0], updated = false;
	(frm.doc.items || []).forEach(function (item) {
		if (!item.custom_wbs_element) {
			frappe.model.set_value(item.doctype, item.name, "custom_wbs_element", w.wbs_element);
			updated = true;
		}
		if (!item.custom_sub_wbs_element && w.sub_wbs_element) {
			frappe.model.set_value(item.doctype, item.name, "custom_sub_wbs_element", w.sub_wbs_element);
			updated = true;
		}
	});
	if (updated) frm.refresh_field("items");
}

// REQ 2: Group item amounts by (wbs_element + sub_wbs_element) → update allocation rows
function calculate_wbs_allocated_amounts(frm) {
	// ABP2-I457 (Sahil 2026-06-16) — on Submitted docs allocated_amount
	// is allow_on_submit=0. The recompute on refresh was producing
	// IEEE-754 float drift (3267826.12 → 3267826.1199999996), which
	// then hit the 'Cannot Update After Submit' guard and blocked the
	// user from opening MR-SRV-2026-00325. Skip entirely once submitted.
	if (frm.doc.docstatus !== 0) return;

	var allocs = frm.doc.custom_wbs_allocations || [];
	if (allocs.length === 1 && allocs[0].wbs_element) handle_single_wbs_auto_assign(frm);

	var map = {};
	(frm.doc.items || []).forEach(function (item) {
		var key = (item.custom_wbs_element || "") + "||" + (item.custom_sub_wbs_element || "");
		map[key] = flt((map[key] || 0) + flt(item.amount), 2);
	});

	allocs.forEach(function (alloc) {
		var key = (alloc.wbs_element || "") + "||" + (alloc.sub_wbs_element || "");
		var amt = map[key] || 0;
		// ABP2-I457 — half-paise tolerance so micro IEEE-754 drift from
		// repeated += in JS doesn't mark the row dirty when it hasn't
		// substantively changed.
		if (Math.abs(flt(alloc.allocated_amount) - amt) > 0.005) {
			frappe.model.set_value(alloc.doctype, alloc.name, "allocated_amount", amt);
		}
	});
	frm.refresh_field("custom_wbs_allocations");
}

// REQ 4: fill empty header Company / Project / Cost Center from the WBS; never overwrite.
function mr_fill_header_from_wbs(frm, wbs, warn_mismatch) {
	if (frm.doc.docstatus !== 0) return;
	frappe.db.get_value("WBS Element", wbs, ["project", "cost_center", "company"]).then(function (r) {
		var d = (r && r.message) || {};
		if (warn_mismatch && d.project && frm.doc.project && d.project !== frm.doc.project) {
			frappe.show_alert({
				message: __("WBS {0} belongs to Project {1}, but this Material Request is for Project {2}.", [wbs, d.project, frm.doc.project]),
				indicator: "orange",
			});
			return;
		}
		var chain = Promise.resolve();
		if (d.company && !frm.doc.company) chain = chain.then(function () { return frm.set_value("company", d.company); });
		if (d.project && !frm.doc.project) chain = chain.then(function () { return frm.set_value("project", d.project); });
		chain.then(function () {
			// "Cost center filter in MR" clears cost_center when project changes, so set it last.
			if (d.cost_center && !frm.doc.cost_center) return frm.set_value("cost_center", d.cost_center);
		});
	});
}
