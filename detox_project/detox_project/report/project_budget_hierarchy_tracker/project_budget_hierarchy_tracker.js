frappe.query_reports["Project Budget Hierarchy Tracker"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			reqd: 1,
			on_change: function () {
				let project = frappe.query_report.get_filter_value("project");
				if (project) {
					frappe.db.get_value("Project", project, "custom_financial_model").then((r) => {
						if (r.message && r.message.custom_financial_model) {
							frappe.query_report.set_filter_value(
								"financial_model",
								r.message.custom_financial_model
							);
						}
					});
				}
			},
		},
		{
			fieldname: "financial_model",
			label: __("Financial Model"),
			fieldtype: "Link",
			options: "Financial Model",
		},
		{
			fieldname: "category",
			label: __("Category"),
			fieldtype: "Link",
			options: "Project Cost Category",
		},
		{
			fieldname: "wbs_element",
			label: __("WBS Element"),
			fieldtype: "Link",
			options: "WBS Element",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nAll\nActive\nOn Hold\nCompleted",
			default: "Active",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		// For doc link columns, return raw HTML (already has <a> tags)
		if (
			["mr_docs", "po_docs", "pr_docs", "pi_docs"].includes(column.fieldname) &&
			value &&
			value.includes("<a ")
		) {
			return value;
		}

		value = default_formatter(value, row, column, data);

		if (!data) return value;

		let type = data.entity_type;

		// Color-code utilization
		if (column.fieldname === "utilization_pct" && data.utilization_pct != null) {
			let pct = data.utilization_pct;
			if (pct > 100) {
				value = `<span style="color:#dc3545;font-weight:bold">${value}</span>`;
			} else if (pct > 80) {
				value = `<span style="color:#fd7e14;font-weight:bold">${value}</span>`;
			} else {
				value = `<span style="color:#28a745">${value}</span>`;
			}
		}

		// Style entity column by type
		if (column.fieldname === "entity") {
			if (type === "Category") {
				value = `<span style="font-weight:bold;color:#004085">${value}</span>`;
			} else if (type === "Summary") {
				value = `<span style="font-weight:bold;font-size:1.05em">${value}</span>`;
			} else if (type === "Sub WBS") {
				if (data.entity_link) {
					value = `<a href="/app/sub-wbs-element/${data.entity_link}" style="color:#117a8b">${value}</a>`;
				}
			} else if (data.entity_link) {
				value = `<a href="/app/wbs-element/${data.entity_link}" style="font-weight:bold;color:#155724">${value}</a>`;
			}
		}

		return value;
	},

	initial_depth: 1,
	tree: true,
};
