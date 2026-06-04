// Copyright (c) 2026, Reformiqo and contributors
// Gate Pass Report ZWR12 — filters + custom template export

frappe.query_reports["Gate Pass Report ZWR12"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
			get_query: () => ({ filters: { is_group: 0 } }),
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Project", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "gate_pass",
			label: __("Gate Pass No"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Gate Pass", txt);
			},
		},
		{
			fieldname: "from_date",
			label: __("Date (From)"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.year_start(),
		},
		{
			fieldname: "to_date",
			label: __("Date (To)"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "exit_from",
			label: __("Vehicle Exit Date (From)"),
			fieldtype: "Date",
		},
		{
			fieldname: "exit_to",
			label: __("Vehicle Exit Date (To)"),
			fieldtype: "Date",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Customer", txt);
			},
		},
		{
			fieldname: "document_review",
			label: __("Docs status"),
			fieldtype: "MultiSelectList",
			get_data: function () {
				return [
					{ value: "Pending", description: "" },
					{ value: "Accepted", description: "" },
					{ value: "Rejected", description: "" },
				];
			},
		},
		{
			fieldname: "docstatus",
			label: __("Document Status"),
			fieldtype: "Select",
			options: "\nDraft\nSubmitted\nCancelled",
		},
		{
			// ABP2-I408 — Transaction Type filter; options mirror the
			// Gate Pass doctype `transaction_type` Select. Blank = all.
			fieldname: "transaction_type",
			label: __("Transaction Type"),
			fieldtype: "Select",
			options: "\nInbound (Waste Receipt)\nOutbound (Waste Dispatch)",
		},
	],

	onload: function (report) {
		report.page.add_inner_button(
			__("Export (ZWR12 Template)"),
			function () {
				const filters = report.get_values();
				const qs = new URLSearchParams({
					filters: JSON.stringify(filters),
				}).toString();
				const url =
					"/api/method/detox_project.detox_project.report.gate_pass_report_zwr12.gate_pass_report_zwr12.export_zwr12?" +
					qs;
				window.open(url, "_blank");
			},
			__("Actions"),
		);
	},
};
