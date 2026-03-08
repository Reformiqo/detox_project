$(document).ready(function () {
    if (typeof frappe === "undefined") return;

    frappe.ui.form.on("Tender Management", {
        refresh(frm) {
            if (frm.doctype !== "Tender Management") return;

            let status = frm.doc.workflow_state || frm.doc.status || frm.doc.tender_status || "";
            if (status === "Awarded" && !frm.doc.custom_linked_project) {
                frm.add_custom_button(__("Create Project"), () => {
                    frappe.call({
                        method: "detox_project.events.tender.create_project_from_tender",
                        args: { tender_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Creating Project..."),
                        callback(r) {
                            if (r.message) {
                                frm.reload_doc();
                                frappe.set_route("Form", "Project", r.message);
                            }
                        }
                    });
                }, __("Actions"));
            }

            if (frm.doc.custom_linked_project) {
                frm.dashboard.add_comment(
                    __("Linked Project: {0} ({1})", [
                        `<a href="/app/project/${frm.doc.custom_linked_project}">${frm.doc.custom_linked_project}</a>`,
                        frm.doc.custom_project_status || "Open"
                    ]),
                    "blue", true
                );

                frm.add_custom_button(__("View Project"), () => {
                    frappe.set_route("Form", "Project", frm.doc.custom_linked_project);
                }, __("View"));

                frm.add_custom_button(__("WBS Elements"), () => {
                    frappe.set_route("List", "WBS Element", {
                        project: frm.doc.custom_linked_project
                    });
                }, __("View"));
            }
        }
    });
});
