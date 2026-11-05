frappe.query_reports["Project Revenue and Expense Summary"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "project_status",
			label: __("Project Status"),
			fieldtype: "Select",
			options: "All\nOpen\nCompleted\nCancelled",
			default: "All",
		},
		{
			fieldname: "status",
			label: __("WBS Status"),
			fieldtype: "Select",
			options: "All\nActive\nOn Hold\nCompleted",
			default: "Active",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!data) return formatted;
		const base = window.location.pathname.startsWith("/desk") ? "/desk" : "/app";
		const status = frappe.query_report.get_filter_value("status") || "All";
		const qs = (params) =>
			Object.keys(params)
				.map((k) => encodeURIComponent(k) + "=" + encodeURIComponent(params[k]))
				.join("&");

		if (data.is_total) return `<b>${formatted}</b>`;

		// Project name opens that project's Revenue and Expense Hierarchy.
		if (column.fieldname === "project_name" && data.project) {
			const url = base + "/query-report/" + encodeURIComponent("Project Revenue and Expense Hierarchy") + "?" +
				qs({ project: data.project, view: "Both", status: status });
			return `<a href="${url}" target="_blank" style="font-weight:600;color:#004085"
				title="${__("Open the hierarchy for this project")}">${formatted}</a>`;
		}

		// Amounts open the transactions behind them (same as the hierarchy report section rows).
		const drill = {
			rev_actual: ["Revenue", "Actual"],
			rev_open: ["Revenue", "Commitment"],
			rev_pending: ["Revenue", "Pending"],
			exp_actual: ["Expense", "Actual"],
			exp_commit: ["Expense", "Commitment"],
			exp_pending: ["Expense", "Pending"],
		};
		if (drill[column.fieldname] && data.project && Math.abs(flt(value)) >= 0.005) {
			const url = base + "/query-report/" + encodeURIComponent("Project Budget Transactions") + "?" +
				qs({ project: data.project, section: drill[column.fieldname][0], measure: drill[column.fieldname][1],
					scope: "All", status: status });
			return `<a href="${url}" target="_blank" style="text-decoration: underline dotted;"
				title="${__("Open the transactions behind this amount")}">${formatted}</a>`;
		}

		if (column.fieldname === "net_actual" && value != null) {
			const color = flt(value) >= 0 ? "#155724" : "#dc3545";
			return `<span style="color:${color};font-weight:600">${formatted}</span>`;
		}
		if (["rev_achievement", "exp_utilization"].includes(column.fieldname) && value != null) {
			const pct = flt(value);
			let color;
			if (column.fieldname === "rev_achievement") {
				color = pct >= 100 ? "#28a745" : pct >= 50 ? "#fd7e14" : "#dc3545";
			} else {
				color = pct > 100 ? "#dc3545" : pct > 80 ? "#fd7e14" : "#28a745";
			}
			return `<span style="color:${color};font-weight:600">${formatted}</span>`;
		}
		return formatted;
	},
};
