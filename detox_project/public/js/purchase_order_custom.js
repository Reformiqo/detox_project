frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		// WBS Allocation child table queries
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

		// Auto-add WBS allocation row when created from WBS Element
		if (frm.is_new() && frappe.route_options && frappe.route_options._wbs_element) {
			let wbs = frappe.route_options._wbs_element;
			delete frappe.route_options._wbs_element;
			if (!frm.doc.custom_wbs_allocations || frm.doc.custom_wbs_allocations.length === 0) {
				let row = frm.add_child("custom_wbs_allocations");
				frappe.model.set_value(row.doctype, row.name, "wbs_element", wbs);
				frm.refresh_field("custom_wbs_allocations");
			}
		}

		// Old single-field queries (backward compat, fields are hidden)
		frm.set_query("custom_wbs_element", () => {
			let filters = { status: "Active" };
			if (frm.doc.project) filters.project = frm.doc.project;
			return { filters };
		});

		frm.set_query("custom_sub_wbs_element", () => {
			let filters = { status: "Active" };
			if (frm.doc.custom_wbs_element) filters.main_wbs_element = frm.doc.custom_wbs_element;
			return { filters };
		});
	},
});

frappe.ui.form.on("WBS Allocation", {
	wbs_element(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.wbs_element) {
			frappe.model.set_value(cdt, cdn, "sub_wbs_element", "");
		}
	},
});
