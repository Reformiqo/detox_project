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
                    pct.toFixed(1)
                ]),
                color
            );
        }

        // Tender banner
        if (frm.doc.custom_tender) {
            frm.dashboard.add_comment(
                __("Linked to Tender: {0}", [frm.doc.custom_tender]),
                "blue", true
            );
        }

        // Financial Model banner
        if (frm.doc.custom_financial_model) {
            frm.dashboard.add_comment(
                __("Financial Model: {0}", [
                    `<a href="/app/financial-model/${frm.doc.custom_financial_model}">${frm.doc.custom_financial_model}</a>`
                ]),
                "blue", true
            );
        }

        if (!frm.is_new() && frm.doc.status === "Open") {
            frm.add_custom_button(__("WBS Elements"), () => {
                frappe.set_route("List", "WBS Element", { project: frm.doc.name });
            }, __("View"));

            frm.add_custom_button(__("Material Requests"), () => {
                frappe.set_route("List", "Material Request", { project: frm.doc.name });
            }, __("View"));

            frm.add_custom_button(__("Purchase Orders"), () => {
                frappe.set_route("List", "Purchase Order", { project: frm.doc.name });
            }, __("View"));

            if (frm.doc.custom_financial_model) {
                frm.add_custom_button(__("Financial Model"), () => {
                    frappe.set_route("Form", "Financial Model", frm.doc.custom_financial_model);
                }, __("View"));
            }

            frm.add_custom_button(__("Material Request"), () => {
                frappe.new_doc("Material Request", {
                    project: frm.doc.name,
                    company: frm.doc.company
                });
            }, __("Create"));

            frm.add_custom_button(__("Budget Dashboard"), () => {
                show_budget_dashboard(frm);
            });

            frm.add_custom_button(__("Recalculate Budget"), () => {
                frappe.call({
                    method: "detox_project.detox_project.api.recalculate_project_budget",
                    args: { project: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Recalculating budgets..."),
                    callback() { frm.reload_doc(); }
                });
            }, __("Actions"));
        }

        if (!frm.is_new() && frm.doc.status !== "Cancelled" && frappe.user.has_role("Projects Manager")) {
            frm.add_custom_button(__("Cancel Project & WBS"), () => {
                frappe.confirm(
                    __("This will cancel all linked WBS Elements and Sub WBS Elements. Continue?"),
                    () => {
                        frappe.call({
                            method: "frappe.client.set_value",
                            args: {
                                doctype: "Project",
                                name: frm.doc.name,
                                fieldname: "status",
                                value: "Cancelled"
                            },
                            callback() { frm.reload_doc(); }
                        });
                    }
                );
            }, __("Actions"));
        }
    }
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
                        <div class="stat-value text-primary">${format_currency(totals.total_budget)}</div>
                    </div>
                    <div class="col-sm-3">
                        <div class="stat-label">Total Spent</div>
                        <div class="stat-value">${format_currency(totals.total_spent)}</div>
                    </div>
                    <div class="col-sm-3">
                        <div class="stat-label">Remaining</div>
                        <div class="stat-value text-success">${format_currency(totals.total_budget - totals.total_spent)}</div>
                    </div>
                    <div class="col-sm-3">
                        <div class="stat-label">Utilization</div>
                        <div class="stat-value ${totals.utilization_pct > 80 ? 'text-danger' : ''}">${totals.utilization_pct.toFixed(1)}%</div>
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

            (data.wbs_elements || []).forEach(wbs => {
                let pct = wbs.overall_utilization_pct || 0;
                let cls = pct > 100 ? "table-danger" : pct > 80 ? "table-warning" : "";
                html += `
                    <tr class="${cls}">
                        <td><a href="/app/wbs-element/${wbs.name}">${wbs.wbs_name}</a></td>
                        <td>${wbs.wbs_type || ''}</td>
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
        }
    });
}
