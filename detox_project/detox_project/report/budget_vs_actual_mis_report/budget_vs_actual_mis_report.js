// Copyright (c) 2026, erpera and contributors
// For license information, please see license.txt

// Row bands are CSS keyed on datatable's `.dt-row-<index>`, which it rebuilds on every re-render.
// Painting the DOM once won't do: the body is virtualised, so rows drawn on scroll come back bare.
const MIS_SCOPE = "bva-mis-report";
const MIS_STYLE_ID = "bva-mis-report-row-bands";

// Accounting style, per the Finance sheet: no currency symbol, negatives in brackets.
const ACCOUNTING_SUFFIX = { variance: "", variance_pct: "%", balance_budget: "" };

function accounting(raw, suffix) {
	// Mirror the Percent formatter: show up to 2 decimals, none on a whole number.
	const decimals = Math.min(2, (String(raw).split(".")[1] || "").length);
	const text = format_number(Math.abs(raw), null, decimals) + suffix;
	return raw < 0 ? `(${text})` : text;
}

const ROW_BACKGROUND = {
	section: "#31649c",
	total: "#fdf3d8",
	net: "#e7eef7",
};

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

		// Actual YTD is the only figure sourced outside the Financial Model.
		if (column.fieldname === "actual_ytd" && data.row_type === "item") {
			value = `<span style="color:#0d6efd">${value}</span>`;
		}

		// Colour tracks the sign, not favourability, so both blocks read the same.
		if (["variance", "variance_pct"].includes(column.fieldname)) {
			const raw = flt(data[column.fieldname]);
			if (raw !== 0) {
				value = `<span style="color:${raw < 0 ? "#dc3545" : "#198754"}">${value}</span>`;
			}
		}

		if (column.fieldname === "consumed_pct" && data.consumed_pct != null) {
			const pct = flt(data.consumed_pct);
			if (pct > 100) {
				value = `<span style="color:#dc3545;font-weight:600">${value}</span>`;
			} else if (pct > 80) {
				value = `<span style="color:#fd7e14;font-weight:600">${value}</span>`;
			}
		}

		return value;
	},

	after_datatable_render: function (datatable) {
		// `.dt-row-N` is generic, so scope every rule to this report's own datatable.
		datatable.wrapper.classList.add(MIS_SCOPE);

		const rows = (frappe.query_report && frappe.query_report.data) || [];
		const rules = [];

		rows.forEach((row, index) => {
			const background = ROW_BACKGROUND[row.row_type];
			if (!background) return;

			// !important beats datatable's own hover/selection background rules.
			rules.push(
				`.${MIS_SCOPE} .dt-row-${index} .dt-cell` +
					`{background-color:${background} !important;}`
			);
			rules.push(
				`.${MIS_SCOPE} .dt-row-${index} .dt-cell__content` +
					(row.row_type === "section"
						? "{color:#ffffff;font-weight:700;}"
						: "{font-weight:700;}")
			);
		});

		let style = document.getElementById(MIS_STYLE_ID);
		if (!style) {
			style = document.createElement("style");
			style.id = MIS_STYLE_ID;
			document.head.appendChild(style);
		}
		style.textContent = rules.join("\n");
	},
};
