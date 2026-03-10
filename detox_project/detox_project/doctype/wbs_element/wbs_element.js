frappe.ui.form.on("WBS Element", {
	refresh(frm) {
		if (frm.doc.total_budget) {
			let pct = frm.doc.overall_utilization_pct || 0;
			let color = pct > 100 ? "red" : pct > 80 ? "orange" : "green";
			frm.dashboard.add_indicator(__("Budget Utilization: {0}%", [pct.toFixed(1)]), color);
			frm.dashboard.add_indicator(
				__("Budget: {0} | Spent: {1}", [
					format_currency(frm.doc.total_budget),
					format_currency(frm.doc.total_spent),
				]),
				"blue"
			);
		}

		if (frm.doc.status === "Active" && !frm.is_new()) {
			frm.add_custom_button(
				__("Material Request"),
				() => {
					frappe.new_doc("Material Request", {
						custom_wbs_element: frm.doc.name,
						project: frm.doc.project,
						company: frm.doc.company,
						custom_request_type: "Material",
					});
				},
				__("Create")
			);

			frm.add_custom_button(
				__("Service Request"),
				() => {
					frappe.new_doc("Material Request", {
						custom_wbs_element: frm.doc.name,
						project: frm.doc.project,
						company: frm.doc.company,
						custom_request_type: "Service",
					});
				},
				__("Create")
			);

			frm.add_custom_button(
				__("Sub WBS Element"),
				() => {
					frappe.new_doc("Sub WBS Element", {
						main_wbs_element: frm.doc.name,
						project: frm.doc.project,
						company: frm.doc.company,
						site: frm.doc.site,
						cost_center: frm.doc.cost_center,
					});
				},
				__("Create")
			);
		}

		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Material Requests"),
				() => {
					frappe.set_route("List", "Material Request", {
						custom_wbs_element: frm.doc.name,
					});
				},
				__("View")
			);

			frm.add_custom_button(
				__("Purchase Orders"),
				() => {
					frappe.set_route("List", "Purchase Order", {
						custom_wbs_element: frm.doc.name,
					});
				},
				__("View")
			);

			frm.add_custom_button(
				__("Sub WBS Elements"),
				() => {
					frappe.set_route("List", "Sub WBS Element", {
						main_wbs_element: frm.doc.name,
					});
				},
				__("View")
			);

			frm.add_custom_button(__("Refresh Spent"), () => {
				frappe.call({
					method: "detox_project.detox_project.api.recalculate_all_wbs_budgets",
					args: { wbs_element: frm.doc.name },
					freeze: true,
					freeze_message: __("Recalculating..."),
					callback() {
						frm.reload_doc();
					},
				});
			});
		}
	},
});
