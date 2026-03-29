// ============================================================
// CLIENT SCRIPT  |  Doctype: Material Request
// REQ 1 - Auto-fill WBS Allocations from Sub WBS Element
// REQ 2 - Roll-up item amounts into WBS Allocation rows
// REQ 3 - Single WBS auto-assign to all items
// ============================================================

frappe.ui.form.on("Material Request", {
	onload(frm) {
		if (!frm.is_new()) return;
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
	wbs_element(frm) { handle_single_wbs_auto_assign(frm); calculate_wbs_allocated_amounts(frm); },
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
	var allocs = frm.doc.custom_wbs_allocations || [];
	if (allocs.length === 1 && allocs[0].wbs_element) handle_single_wbs_auto_assign(frm);

	var map = {};
	(frm.doc.items || []).forEach(function (item) {
		var key = (item.custom_wbs_element || "") + "||" + (item.custom_sub_wbs_element || "");
		map[key] = (map[key] || 0) + flt(item.amount);
	});

	allocs.forEach(function (alloc) {
		var key = (alloc.wbs_element || "") + "||" + (alloc.sub_wbs_element || "");
		var amt = map[key] || 0;
		if (flt(alloc.allocated_amount) !== amt) {
			frappe.model.set_value(alloc.doctype, alloc.name, "allocated_amount", amt);
		}
	});
	frm.refresh_field("custom_wbs_allocations");
}
