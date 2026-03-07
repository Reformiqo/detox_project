frappe.ui.form.on("Material Request", {
    refresh(frm) {
        if (frm.doc.custom_wbs_element) {
            frappe.db.get_value("WBS Element", frm.doc.custom_wbs_element, [
                "wbs_name", "total_budget", "total_spent", "overall_utilization_pct"
            ]).then(r => {
                if (r.message) {
                    let wbs = r.message;
                    let pct = wbs.overall_utilization_pct || 0;
                    let color = pct > 100 ? "red" : pct > 80 ? "orange" : "green";
                    frm.dashboard.add_indicator(
                        __("WBS {0}: Budget {1} | Spent {2} ({3}%)", [
                            wbs.wbs_name,
                            format_currency(wbs.total_budget),
                            format_currency(wbs.total_spent),
                            pct.toFixed(1)
                        ]),
                        color
                    );
                }
            });
        }

        frm.set_query("custom_wbs_element", () => {
            let filters = { status: "Active" };
            if (frm.doc.project) filters.project = frm.doc.project;
            return { filters };
        });

        frm.set_query("custom_sub_wbs_element", () => {
            let filters = { status: "Active" };
            if (frm.doc.custom_wbs_element) filters.main_wbs_element = frm.doc.custom_wbs_element;
            return { filters };
        });
    },

    custom_wbs_element(frm) {
        if (frm.doc.custom_wbs_element) {
            frappe.db.get_value("WBS Element", frm.doc.custom_wbs_element, [
                "project", "company", "site", "cost_center"
            ]).then(r => {
                if (r.message) {
                    if (r.message.project && !frm.doc.project) frm.set_value("project", r.message.project);
                    if (r.message.company && !frm.doc.company) frm.set_value("company", r.message.company);
                    if (r.message.site) frm.set_value("custom_project_site", r.message.site);
                }
            });
        }
        frm.set_value("custom_sub_wbs_element", "");
    }
});
