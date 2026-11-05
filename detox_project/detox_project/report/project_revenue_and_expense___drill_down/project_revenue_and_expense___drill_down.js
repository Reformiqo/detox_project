frappe.query_reports["Project Revenue and Expense - Drill Down"] = {
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
			fieldname: "show_upto",
			label: __("Drill Down Up To"),
			fieldtype: "Select",
			options: "Project\nCost Center\nTransaction Type\nAccount\nVoucher",
			default: "Voucher",
		},
	],

	tree: true,
	name_field: "row_id",
	parent_field: "parent_row",
	initial_depth: 0,

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "net" && data.net < 0) {
			value = "<span style='color:#c0392b'>" + value + "</span>";
		}
		if (column.fieldname === "label" && data.label && String(data.label).indexOf("not tagged") !== -1) {
			value = "<span style='color:#d35400;font-weight:600'>" + value + "</span>";
		}
		if (data.indent === 0 || data.is_total) {
			value = "<b>" + value + "</b>";
		}
		return value;
	},
};
