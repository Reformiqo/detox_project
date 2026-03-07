frappe.ui.form.on("Financial Model", {
    refresh(frm) {
        if (frm.doc.total_project_budget) {
            let color = frm.doc.docstatus === 1 ? "green" : "blue";
            frm.dashboard.add_indicator(
                __("Total Budget: {0}", [format_currency(frm.doc.total_project_budget)]),
                color
            );
        }

        if (frm.doc.docstatus === 1 && frm.doc.model_status !== "Cancelled") {
            frm.add_custom_button(__("Create Project"), () => {
                frappe.call({
                    method: "detox_project.detox_project.api.create_project_from_model",
                    args: { financial_model: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Creating Project..."),
                    callback(r) {
                        if (r.message) {
                            frappe.set_route("Form", "Project", r.message);
                        }
                    }
                });
            }, __("Actions"));

            frm.add_custom_button(__("View WBS Elements"), () => {
                frappe.set_route("List", "WBS Element", {
                    financial_model: frm.doc.name
                });
            }, __("View"));
        }
    },

    validate(frm) {
        calculate_totals(frm);
    }
});

frappe.ui.form.on("WBS Budget Line", {
    material_budget(frm, cdt, cdn) {
        calculate_row_total(frm, cdt, cdn);
        calculate_totals(frm);
    },
    service_budget(frm, cdt, cdn) {
        calculate_row_total(frm, cdt, cdn);
        calculate_totals(frm);
    },
    budget_lines_remove(frm) {
        calculate_totals(frm);
    }
});

function calculate_row_total(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    frappe.model.set_value(cdt, cdn, "total_line_budget",
        (row.material_budget || 0) + (row.service_budget || 0)
    );
}

function calculate_totals(frm) {
    let total_material = 0;
    let total_service = 0;
    (frm.doc.budget_lines || []).forEach(row => {
        total_material += row.material_budget || 0;
        total_service += row.service_budget || 0;
    });
    frm.set_value("total_material_budget", total_material);
    frm.set_value("total_service_budget", total_service);
    frm.set_value("total_project_budget", total_material + total_service);
}
