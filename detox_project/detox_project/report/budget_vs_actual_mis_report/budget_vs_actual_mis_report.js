// Copyright (c) 2026, erpera and contributors
// For license information, please see license.txt

// Accounting style, per the Finance sheet: no currency symbol, negatives in brackets.
const ACCOUNTING_SUFFIX = { variance: "", variance_pct: "%", balance_budget: "" };

function accounting(raw, suffix) {
	// Mirror the Percent formatter: show up to 2 decimals, none on a whole number.
	const decimals = Math.min(2, (String(raw).split(".")[1] || "").length);
	const text = format_number(Math.abs(raw), null, decimals) + suffix;
	return raw < 0 ? `(${text})` : text;
}

frappe.query_reports["Budget vs Actual MIS Report"] = {
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
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			// Both sides of the report are company-scoped already.
			get_query: () => {
				const company = frappe.query_report.get_filter_value("company");
				return company ? { filters: { company: company } } : {};
			},
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.year_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "cost_category",
			label: __("Cost Category"),
			fieldtype: "Link",
			options: "Project Cost Category",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);

		// Spacer between the REVENUE and EXPENSE blocks.
		if (data.row_type === "blank") return "";

		// The band colour comes from the injected stylesheet, so this is plain text.
		if (data.row_type === "section") {
			return column.fieldname === "cost_category"
				? frappe.utils.escape_html(String(value || ""))
				: "";
		}

		value = default_formatter(value, row, column, data);

		if (column.fieldname in ACCOUNTING_SUFFIX && data[column.fieldname] != null) {
			value = accounting(flt(data[column.fieldname]), ACCOUNTING_SUFFIX[column.fieldname]);
		}

		return value;
	},
};
