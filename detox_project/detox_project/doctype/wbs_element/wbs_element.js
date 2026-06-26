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

		// ABP2-I416 — Close / Reopen Budget action on a single WBS row
		// (FR-01 / FR-02 / FR-03). Mirrors the category-level action on
		// Project Budget Plan but acts on this WBS only. Closes cascade
		// to every Sub WBS Element under this row (FR-08); reopens are
		// role-gated to 'Budget Manager' (FR-11, enforced server-side).
		_abp2_i416_setup_budget_buttons(frm);

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


// ABP2-I416 — Close / Reopen Budget for this WBS Element.
// Implements FR-01 / FR-02 (close) and FR-03 (reopen) per
// RFQ-FRD-BUDCLOSE-001. Audit fields are populated server-side via
// `budgeting_tool.events.budget_closure.close_wbs` / `reopen_wbs`.
function _abp2_i416_setup_budget_buttons(frm) {
	if (frm.is_new()) return;

	const closed = frm.doc.custom_budget_closure_status === "Closed";
	const indicator_color = closed ? "red" : "green";
	const indicator_label = closed
		? __("Budget Closure: Closed")
		: __("Budget Closure: Open");
	frm.dashboard.add_indicator(indicator_label, indicator_color);

	if (!closed) {
		// FR-01 / FR-02 — Close button visible only when Open.
		frm.add_custom_button(__("Close Budget"), () => {
			_abp2_i416_close_reopen_prompt(frm, "close");
		}, __("Category Budget"));
	} else {
		// FR-03 — Reopen button visible only when Closed.
		frm.add_custom_button(__("Reopen Budget"), () => {
			_abp2_i416_close_reopen_prompt(frm, "reopen");
		}, __("Category Budget"));

		// Add a banner showing the closure context so the user
		// knows why this WBS is read-only for budget purposes.
		const closed_on = frm.doc.custom_closed_on
			? frappe.datetime.str_to_user(frm.doc.custom_closed_on) : "";
		const closed_by = frm.doc.custom_closed_by || "";
		const reason = frm.doc.custom_closed_reason || "";
		frm.set_intro(
			__("Budget Closed on {0} by {1}. Reason: {2}",
				[closed_on, closed_by, reason]),
			"red");
	}
}

function _abp2_i416_close_reopen_prompt(frm, mode) {
	const action_label = mode === "close"
		? __("Close Budget for this WBS")
		: __("Reopen Budget for this WBS");
	const server_method = mode === "close"
		? "budgeting_tool.events.budget_closure.close_wbs"
		: "budgeting_tool.events.budget_closure.reopen_wbs";
	const reason_label = mode === "close"
		? __("Close Reason") : __("Reopen Reason");

	const dialog = new frappe.ui.Dialog({
		title: action_label,
		fields: [
			{
				fieldname: "wbs_summary",
				fieldtype: "HTML",
				options: `<div class="alert alert-info">
					<b>${frappe.utils.escape_html(frm.doc.name)}</b>
					— ${frappe.utils.escape_html(frm.doc.wbs_name || "")}
					<br>${__("Category")}: ${frappe.utils.escape_html(frm.doc.category || "—")}
					· ${__("Budget Type")}: ${frappe.utils.escape_html(frm.doc.budget_type || "—")}
					<br><i>${__("This action will cascade to every Sub WBS Element under this row.")}</i>
				</div>`,
			},
			{
				fieldname: "reason",
				label: reason_label,
				fieldtype: "Small Text",
				reqd: 1,
				description: mode === "reopen"
					? __("Reopen restricted to 'Budget Manager' role.")
					: __("Recorded on the audit trail."),
			},
		],
		primary_action_label: action_label,
		primary_action(values) {
			frappe.call({
				method: server_method,
				args: { wbs_name: frm.doc.name, reason: values.reason },
				freeze: true,
				freeze_message: mode === "close"
					? __("Closing budget and cascading to Sub WBS Elements…")
					: __("Reopening budget…"),
				callback(r) {
					if (r.message) {
						const subs = r.message.sub_wbs_affected || 0;
						frappe.show_alert({
							message: mode === "close"
								? __("Budget closed. {0} Sub WBS Element(s) cascaded.", [subs])
								: __("Budget reopened. {0} Sub WBS Element(s) cascaded.", [subs]),
							indicator: mode === "close" ? "orange" : "green",
						});
						dialog.hide();
						frm.reload_doc();
					}
				},
			});
		},
	});
	dialog.show();
}
