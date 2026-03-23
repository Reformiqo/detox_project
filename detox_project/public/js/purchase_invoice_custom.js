frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
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
