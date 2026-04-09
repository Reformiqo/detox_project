frappe.ui.form.on("WBS Element", {
	refresh(frm) {
		set_category_filter(frm);
		if (frm.doc.budget_amount) {
			let pct = frm.doc.budget_utilization_pct || 0;
			let color = pct > 100 ? "red" : pct > 80 ? "orange" : "green";
			frm.dashboard.add_indicator(__("Budget Utilization: {0}%", [pct.toFixed(1)]), color);
			frm.dashboard.add_indicator(
				__("Budget: {0} | Spent: {1}", [
					format_currency(frm.doc.budget_amount),
					format_currency(frm.doc.budget_spent),
				]),
				"blue"
			);
		}

		if (frm.doc.status === "Active" && !frm.is_new()) {
			frm.add_custom_button(
				__("Material Request"),
				() => {
					frappe.new_doc("Material Request", {
						project: frm.doc.project,
						company: frm.doc.company,
						custom_request_type: "Material",
					});
					// Pre-populate WBS allocation after route
					frappe.route_options = { _wbs_element: frm.doc.name };
				},
				__("Create")
			);

			frm.add_custom_button(
				__("Service Request"),
				() => {
					frappe.new_doc("Material Request", {
						project: frm.doc.project,
						company: frm.doc.company,
						custom_request_type: "Service",
					});
					frappe.route_options = { _wbs_element: frm.doc.name };
				},
				__("Create")
			);

			frm.add_custom_button(
				__("Purchase Order"),
				() => {
					frappe.new_doc("Purchase Order", {
						project: frm.doc.project,
						company: frm.doc.company,
					});
					frappe.route_options = { _wbs_element: frm.doc.name };
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

	financial_model(frm) {
		set_category_filter(frm);
		if (frm.doc.category) {
			frm.set_value("category", "");
		}
	},

	budget_type(frm) {
		set_category_filter(frm);
		if (frm.doc.category) {
			frm.set_value("category", "");
		}
	},
});

function set_category_filter(frm) {
	frm.set_query("category", () => {
		if (frm.doc.financial_model) {
			return {
				query: "detox_project.detox_project.api.get_fm_categories",
				filters: {
					financial_model: frm.doc.financial_model,
					budget_type: frm.doc.budget_type || "",
				},
			};
		}
		return { filters: { enabled: 1 } };
	});
}
