frappe.ui.form.on("Sub WBS Element", {
    refresh(frm) {
        if (frm.doc.total_budget) {
            let pct = frm.doc.overall_utilization_pct || 0;
            let color = pct > 100 ? "red" : pct > 80 ? "orange" : "green";
            frm.dashboard.add_indicator(
                __("Utilization: {0}%", [pct.toFixed(1)]),
                color
            );
        }

        if (frm.doc.status === "Active" && !frm.is_new()) {
            frm.add_custom_button(__("Material Request"), () => {
                frappe.new_doc("Material Request", {
                    custom_wbs_element: frm.doc.main_wbs_element,
                    custom_sub_wbs_element: frm.doc.name,
                    project: frm.doc.project,
                    company: frm.doc.company
                });
            }, __("Create"));
        }

        if (!frm.is_new()) {
            frm.add_custom_button(__("Purchase Orders"), () => {
                frappe.set_route("List", "Purchase Order", {
                    custom_sub_wbs_element: frm.doc.name
                });
            }, __("View"));
        }

        frm.set_query("parent_sub_wbs", () => {
            return {
                filters: {
                    main_wbs_element: frm.doc.main_wbs_element,
                    name: ["!=", frm.doc.name]
                }
            };
        });
    }
});
