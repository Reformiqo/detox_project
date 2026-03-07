frappe.query_reports["WBS Procurement Summary"] = {
    filters: [
        { fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
        {
            fieldname: "wbs_element", label: __("WBS Element"), fieldtype: "Link", options: "WBS Element",
            get_query: function () {
                let project = frappe.query_report.get_filter_value("project");
                return project ? { filters: { project: project } } : {};
            }
        }
    ]
};
