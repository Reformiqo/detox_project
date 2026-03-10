frappe.ui.form.on("Project", {
	refresh(frm) {
		// Budget indicators
		if (frm.doc.custom_total_budget) {
			let pct = frm.doc.custom_budget_utilization_pct || 0;
			let color = pct > 100 ? "red" : pct > 80 ? "orange" : "green";
			frm.dashboard.add_indicator(
				__("Budget: {0} | Spent: {1} ({2}%)", [
					format_currency(frm.doc.custom_total_budget),
					format_currency(frm.doc.custom_total_spent),
					pct.toFixed(1),
				]),
				color
			);
		}

		// Tender banner
		if (frm.doc.custom_tender_management) {
			frm.dashboard.add_comment(
				__("Tender: {0} | No: {1} | Awarded: {2}", [
					`<a href="/app/tender-management/${frm.doc.custom_tender_management}">${frm.doc.custom_tender_management}</a>`,
					frm.doc.custom_tender_number || "",
					frm.doc.custom_tender_award_date || "",
				]),
				"blue",
				true
			);
		} else if (frm.doc.custom_tender) {
			frm.dashboard.add_comment(
				__("Linked to Tender: {0}", [frm.doc.custom_tender]),
				"blue",
				true
			);
		}

		// Financial Model banner
		if (frm.doc.custom_financial_model) {
			frm.dashboard.add_comment(
				__("Financial Model: {0}", [
					`<a href="/app/financial-model/${frm.doc.custom_financial_model}">${frm.doc.custom_financial_model}</a>`,
				]),
				"blue",
				true
			);
		}

		if (!frm.is_new()) {
			frm.add_custom_button(
				__("WBS Elements"),
				() => {
					frappe.set_route("List", "WBS Element", { project: frm.doc.name });
				},
				__("View")
			);

			frm.add_custom_button(
				__("Material Requests"),
				() => {
					frappe.set_route("List", "Material Request", { project: frm.doc.name });
				},
				__("View")
			);

			frm.add_custom_button(
				__("Purchase Orders"),
				() => {
					frappe.set_route("List", "Purchase Order", { project: frm.doc.name });
				},
				__("View")
			);

			if (frm.doc.custom_financial_model) {
				frm.add_custom_button(
					__("Financial Model"),
					() => {
						frappe.set_route(
							"Form",
							"Financial Model",
							frm.doc.custom_financial_model
						);
					},
					__("View")
				);
			}

			frm.add_custom_button(
				__("Budget Plans"),
				() => {
					frappe.set_route("List", "Project Budget Plan", { project: frm.doc.name });
				},
				__("View")
			);

			frm.add_custom_button(
				__("Sub WBS Elements"),
				() => {
					frappe.set_route("List", "Sub WBS Element", { project: frm.doc.name });
				},
				__("View")
			);

			frm.add_custom_button(
				__("Material Request"),
				() => {
					frappe.new_doc("Material Request", {
						project: frm.doc.name,
						company: frm.doc.company,
					});
				},
				__("Create")
			);

			frm.add_custom_button(__("Budget Dashboard"), () => {
				show_budget_dashboard(frm);
			});

			frm.add_custom_button(
				__("Recalculate Budget"),
				() => {
					frappe.call({
						method: "detox_project.detox_project.api.recalculate_project_budget",
						args: { project: frm.doc.name },
						freeze: true,
						freeze_message: __("Recalculating budgets..."),
						callback() {
							frm.reload_doc();
						},
					});
				},
				__("Actions")
			);
		}

		if (
			!frm.is_new() &&
			frm.doc.status !== "Cancelled" &&
			frm.doc.status !== "Completed" &&
			frappe.user.has_role("Projects Manager")
		) {
			frm.add_custom_button(
				__("Cancel Project + All Budgets"),
				() => {
					frappe.prompt(
						{
							fieldname: "reason",
							fieldtype: "Small Text",
							label: "Cancellation Reason",
							reqd: 1,
						},
						(values) => {
							frappe.confirm(
								__(
									"This will cancel ALL linked Financial Models, Budget Plans, WBS Elements, and Sub WBS Elements. This cannot be undone. Continue?"
								),
								() => {
									frappe.call({
										method: "detox_project.events.tender.cascade_cancel_project",
										args: {
											project_name: frm.doc.name,
											reason: values.reason,
										},
										freeze: true,
										freeze_message: __(
											"Cascade cancelling all linked documents..."
										),
										callback() {
											frm.reload_doc();
											frappe.show_alert({
												message: __(
													"Project and all linked documents cancelled"
												),
												indicator: "orange",
											});
										},
									});
								}
							);
						},
						__("Cancel Project"),
						__("Confirm Cancel")
					);
				},
				__("Actions")
			);
		}

		// Cancellation info banner
		if (frm.doc.status === "Cancelled" && frm.doc.custom_cancellation_reason) {
			frm.set_intro(__("Cancelled: {0}", [frm.doc.custom_cancellation_reason]), "red");
		}
	},
});

function show_budget_dashboard(frm) {
	frappe.call({
		method: "detox_project.detox_project.api.get_project_budget_dashboard",
		args: { project: frm.doc.name },
		callback(r) {
			if (!r.message) return;

			let data = r.message;
			let totals = data.totals;

			let html = `
                <div class="row mb-3">
                    <div class="col-sm-3">
                        <div class="stat-label">Total Budget</div>
                        <div class="stat-value text-primary">${format_currency(
							totals.total_budget
						)}</div>
                    </div>
                    <div class="col-sm-3">
                        <div class="stat-label">Total Spent</div>
                        <div class="stat-value">${format_currency(totals.total_spent)}</div>
                    </div>
                    <div class="col-sm-3">
                        <div class="stat-label">Remaining</div>
                        <div class="stat-value text-success">${format_currency(
							totals.total_budget - totals.total_spent
						)}</div>
                    </div>
                    <div class="col-sm-3">
                        <div class="stat-label">Utilization</div>
                        <div class="stat-value ${
							totals.utilization_pct > 80 ? "text-danger" : ""
						}">${totals.utilization_pct.toFixed(1)}%</div>
                    </div>
                </div>
                <hr>
                <table class="table table-sm table-bordered">
                    <thead>
                        <tr>
                            <th>WBS Element</th>
                            <th>Type</th>
                            <th class="text-right">Budget</th>
                            <th class="text-right">Spent</th>
                            <th class="text-right">Utilization</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

			(data.wbs_elements || []).forEach((wbs) => {
				let pct = wbs.overall_utilization_pct || 0;
				let cls = pct > 100 ? "table-danger" : pct > 80 ? "table-warning" : "";
				html += `
                    <tr class="${cls}">
                        <td><a href="/app/wbs-element/${wbs.name}">${wbs.wbs_name}</a></td>
                        <td>${wbs.wbs_type || ""}</td>
                        <td class="text-right">${format_currency(wbs.total_budget)}</td>
                        <td class="text-right">${format_currency(wbs.total_spent)}</td>
                        <td class="text-right">${pct.toFixed(1)}%</td>
                    </tr>
                `;
			});

			html += `</tbody></table>`;

			let d = new frappe.ui.Dialog({
				title: __("Project Budget Dashboard"),
				size: "extra-large",
			});
			d.$body.html(html);
			d.show();
		},
	});
}
