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

	custom_wbs_element(frm) {
		if (frm.doc.custom_wbs_element) {
			frappe.db
				.get_value("WBS Element", frm.doc.custom_wbs_element, ["project", "company"])
				.then((r) => {
					if (r.message && r.message.project && !frm.doc.project) {
						frm.set_value("project", r.message.project);
					}
				});
		}
		frm.set_value("custom_sub_wbs_element", "");
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
