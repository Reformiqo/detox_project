frappe.query_reports["Project Revenue and Expense - Actuals"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: (function () {
				const d = frappe.datetime.str_to_obj(frappe.datetime.get_today());
				const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
				return y + "-04-01";
			})(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "view",
			label: __("View"),
			fieldtype: "Select",
			options: "Summary\nDetail\nExceptions",
			default: "Summary",
			reqd: 1,
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: "Project\nCost Center\nProject + Cost Center",
			default: "Project",
			depends_on: "eval:doc.view == 'Summary'",
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
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Cost Center", txt, {
					company: frappe.query_report.get_filter_value("company"),
					is_group: 0,
				});
			},
		},
		{
			fieldname: "transaction_type",
			label: __("Transaction Type"),
			fieldtype: "Select",
			options: "\nSales Invoice\nPurchase\nStock Consumption\nSalary\nExpense Claim\nEmployee Advance\nPayment Entry\nJournal Entry\nOther",
		},
		{
			fieldname: "ho_project",
			label: __("HO Project (for exception check)"),
			fieldtype: "Link",
			options: "Project",
			default: "PROJ-0023",
			depends_on: "eval:doc.view == 'Exceptions'",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "net_profit" && data.net_profit < 0) {
			value = "<span style='color:#c0392b'>" + value + "</span>";
		}
		if (column.fieldname === "issue" && data.issue) {
			value = "<span style='color:#c0392b;font-weight:600'>" + value + "</span>";
		}
		if ((column.fieldname === "project_name" || column.fieldname === "cost_center") && value && String(value).indexOf("not tagged") !== -1) {
			value = "<span style='color:#d35400;font-weight:600'>" + value + "</span>";
		}
		if (data.is_total) {
			value = "<b>" + value + "</b>";
		}
		return value;
	},
};
