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

		sub_wbs_revenue_dashboard(frm);

		// Dashboard "+" opens the document prefilled from this Sub WBS.
		frm.make_methods = frm.make_methods || {};
		[
			"Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice",
			"Blanket Order", "Sales Order", "Delivery Note", "Sales Invoice",
		].forEach((doctype) => {
			frm.make_methods[doctype] = () => sub_wbs_new_linked_doc(frm, doctype);
		});

		if (frm.doc.status === "Active" && !frm.is_new()) {
			frm.add_custom_button(
				__("Material Request"),
				() => sub_wbs_new_linked_doc(frm, "Material Request"),
				__("Create")
			);
		}

		if (!frm.is_new()) {
			frm.add_custom_button(__("Refresh Spent"), () => {
				frappe.call({
					method: "detox_project.detox_project.api.refresh_sub_wbs_spent",
					args: { sub_wbs: frm.doc.name },
					freeze: true,
					freeze_message: __("Recalculating spent & utilization..."),
					callback(r) {
						if (r.message) {
							frappe.show_alert({
								message: __("Spent: {0} | Utilization: {1}%", [
									format_currency(r.message.spent),
									Math.round(r.message.utilization * 100) / 100,
								]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			});

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

	// The controller renames a new Sub WBS after insert; open it under its final name.
	after_save(frm) {
		if (frm.doc.name && frm.doc.name.startsWith("SUB WBS-")) {
			frappe.set_route("Form", "Sub WBS Element", frm.doc.name);
		} else {
			setTimeout(() => frm.reload_doc(), 500);
		}
	},

	financial_model(frm) {
		set_sub_wbs_category_filter(frm);
		if (frm.doc.category) {
			frm.set_value("category", "");
		}
	},
});

// New purchase or sales document for this Sub WBS (see wbs_new_linked_doc in wbs_element.js).
function sub_wbs_new_linked_doc(frm, doctype) {
	window.__detox_mr_wbs_handoff = { wbs: frm.doc.main_wbs_element, sub_wbs: frm.doc.name };
	frappe.db.get_value("WBS Element", frm.doc.main_wbs_element, ["company", "project", "cost_center"]).then((r) => {
		const d = (r && r.message) || {};
		const values = { company: d.company, project: d.project, cost_center: d.cost_center };
		if (doctype === "Blanket Order") values.blanket_order_type = "Selling";
		frappe.new_doc(doctype, values);
	});
}

// Revenue Sub WBS: show the Sales connections and Revenue Achieved %.
// Expense Sub WBS: show the Purchase connections.
function sub_wbs_revenue_dashboard(frm) {
	const is_revenue = frm.doc.custom_category_type === "Revenue";
	const hidden_group = is_revenue ? __("Purchase") : __("Sales");
	frm.dashboard.links_area.body.find(".form-link-title").each(function () {
		$(this).closest(".col-md-4").toggle($(this).text().trim() !== hidden_group);
	});
	if (is_revenue && !frm.is_new()) {
		const pct = flt(frm.doc.custom_revenue_achievement_pct, 2);
		frm.dashboard.add_indicator(__("Revenue Achieved: {0}%", [pct]), pct >= 100 ? "green" : "blue");
	}
}

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
