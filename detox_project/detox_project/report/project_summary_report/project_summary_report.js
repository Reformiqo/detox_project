frappe.query_reports["Project Summary Report"] = {
	filters: [
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nOpen\nCompleted\nCancelled",
		},
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{
			fieldname: "project_type",
			label: __("Project Type"),
			fieldtype: "Link",
			options: "Project Type",
		},
	],
};
