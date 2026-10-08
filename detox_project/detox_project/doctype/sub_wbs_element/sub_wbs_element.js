frappe.ui.form.on("Sub WBS Element", {
	refresh(frm) {
		set_sub_wbs_category_filter(frm);
		let stats = frm.doc.__onload && frm.doc.__onload.budget_stats;
		if (frm.doc.budget_amount && stats) {
			let pct = stats.utilization;
			let color = pct >= 100 ? "red" : pct > 80 ? "orange" : "green";
			frm.dashboard.add_indicator(__("Budget Utilization: {0}%", [pct.toFixed(2)]), color);
			// Non-breaking spaces so each stat stays on one line.
			const add_stat = (label, value, color) =>
				frm.dashboard.add_indicator(
					`${label}: ${format_currency(value)}`.replaceAll(" ", "\u00a0"),
					color
				);
			add_stat(__("Budget"), frm.doc.budget_amount, "blue");
			add_stat(__("Actual"), stats.actual, "blue");
			add_stat(__("Commitment"), stats.commitment, "blue");
			add_stat(__("RemOrdPlan"), stats.rem_ord_plan, "blue");
			add_stat(__("Assigned"), stats.assigned, color);
			add_stat(__("Available"), stats.available, "blue");
		}

		// ABP2-I416 — surface the inherited closure status. Sub WBS
		// closure is parent-driven (cascade from WBS Element close)
		// per FR-08, so we don't expose Close/Reopen buttons here —
		// just the indicator so users can see why MR/PO/PI are blocked.
		if (!frm.is_new()) {
			const closed = frm.doc.custom_budget_closure_status === "Closed";
			frm.dashboard.add_indicator(
				closed ? __("Budget Closure: Closed (inherited)")
				       : __("Budget Closure: Open"),
				closed ? "red" : "green");
			if (closed && frm.doc.custom_closed_reason) {
				const on = frm.doc.custom_closed_on
					? frappe.datetime.str_to_user(frm.doc.custom_closed_on) : "";
				const by = frm.doc.custom_closed_by || "";
				frm.set_intro(
					__("Budget Closed on {0} by {1} via parent WBS. Reason: {2}",
						[on, by, frm.doc.custom_closed_reason]),
					"red");
			}
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
