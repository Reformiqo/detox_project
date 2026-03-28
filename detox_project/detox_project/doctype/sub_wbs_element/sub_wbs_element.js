frappe.ui.form.on("Sub WBS Element", {
	refresh(frm) {
		set_sub_wbs_category_filter(frm);
		if (frm.doc.budget_amount) {
			let pct = frm.doc.budget_utilization_pct || 0;
			let color = pct > 100 ? "red" : pct > 80 ? "orange" : "green";
			frm.dashboard.add_indicator(__("Utilization: {0}%", [pct.toFixed(1)]), color);
		}

		if (frm.doc.status === "Active" && !frm.is_new()) {
			frm.add_custom_button(
				__("Material Request"),
				() => {
					frappe.new_doc("Material Request", {
						project: frm.doc.project,
						company: frm.doc.company,
					});
					frappe.route_options = { _wbs_element: frm.doc.main_wbs_element };
				},
				__("Create")
			);
		}

		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Purchase Orders"),
				() => {
					frappe.set_route("List", "Purchase Order", {
						custom_sub_wbs_element: frm.doc.name,
					});
				},
				__("View")
			);
		}

		frm.set_query("parent_sub_wbs", () => {
			return {
				filters: {
					main_wbs_element: frm.doc.main_wbs_element,
					name: ["!=", frm.doc.name],
				},
			};
		});
	},

	financial_model(frm) {
		set_sub_wbs_category_filter(frm);
		if (frm.doc.category) {
			frm.set_value("category", "");
		}
	},
});

function set_sub_wbs_category_filter(frm) {
	frm.set_query("category", () => {
		if (frm.doc.financial_model) {
			return {
				query: "detox_project.detox_project.api.get_fm_categories",
				filters: { financial_model: frm.doc.financial_model },
			};
		}
		return { filters: { enabled: 1 } };
	});
}
