frappe.query_reports["Project Revenue and Expense Hierarchy"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			reqd: 1,
		},
		{
			fieldname: "view",
			label: __("Show"),
			fieldtype: "Select",
			options: "Both\nExpense\nRevenue",
			default: "Both",
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
			get_query: function () {
				const project = frappe.query_report.get_filter_value("project");
				return { filters: project ? { project: project } : {} };
			},
		},
		{
			fieldname: "status",
			label: __("WBS Status"),
			fieldtype: "Select",
			options: "All\nActive\nOn Hold\nCompleted",
			default: "Active",
		},
	],

	onload: function (report) {
		// Opens the all-projects summary (one row per project: revenue, expense, net).
		report.page.add_inner_button(__("All Projects Summary"), function () {
			frappe.route_options = {
				status: frappe.query_report.get_filter_value("status") || "Active",
			};
			frappe.set_route("query-report", "Project Revenue and Expense Summary");
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!data) return formatted;
		const type = data.entity_type;

		// Drill-down: every transaction-based amount opens the documents behind it.
		const drill = { actual: "Actual", commitment: "Commitment", rem_ord_plan: "Pending", assigned: "Assigned (All)" };
		if (drill[column.fieldname] && type !== "Net" && Math.abs(flt(value)) >= 0.005) {
			const params = {
				project: frappe.query_report.get_filter_value("project"),
				section: data.section || "All",
				measure: drill[column.fieldname],
				scope: data.scope || "All",
			};
			// Carry the report filters so the drill-down covers exactly the rows behind this figure.
			const wbs_filter = frappe.query_report.get_filter_value("wbs_element");
			const category = frappe.query_report.get_filter_value("category");
			params.status = frappe.query_report.get_filter_value("status") || "All";
			if (category) params.category = category;
			if (type === "Section" && (wbs_filter || category)) params.scope = "Linked to WBS";
			if (data.wbs_element) params.wbs_element = data.wbs_element;
			else if (wbs_filter && type === "Section") params.wbs_element = wbs_filter;
			if (data.sub_wbs_element) params.sub_wbs_element = data.sub_wbs_element;
			// Encode each value exactly once (spaces as %20, not "+"), and keep the
			// desk prefix the user is on (/desk on v16, /app otherwise).
			const query = Object.keys(params)
				.map((k) => encodeURIComponent(k) + "=" + encodeURIComponent(params[k]))
				.join("&");
			const base = window.location.pathname.startsWith("/desk") ? "/desk" : "/app";
			const url = base + "/query-report/" + encodeURIComponent("Project Budget Transactions") + "?" + query;
			return `<a href="${url}" target="_blank"
				title="${__("Open the transactions behind this amount")}"
				style="text-decoration: underline dotted;">${formatted}</a>`;
		}

		if (column.fieldname === "utilization_pct" && value != null && type !== "Net") {
			const pct = flt(value);
			let color = "#28a745";
			if (data.section === "Revenue") {
				color = pct >= 100 ? "#28a745" : pct >= 50 ? "#fd7e14" : "#dc3545";
			} else if (pct > 100) {
				color = "#dc3545";
			} else if (pct > 80) {
				color = "#fd7e14";
			}
			return `<span style="color:${color};font-weight:600">${formatted}</span>`;
		}

		if (column.fieldname === "entity") {
			if (type === "Section") {
				const bg = data.section === "Revenue" ? "#155724" : "#721c24";
				return `<span style="font-weight:700;color:${bg};letter-spacing:.5px">${formatted}</span>`;
			}
			if (type === "Net") return `<span style="font-weight:700">${formatted}</span>`;
			if (type === "Not Linked") return `<span style="color:#b45309;font-style:italic">${formatted}</span>`;
			if (type === "Mismatch") return `<span style="color:#dc3545;font-style:italic">${formatted}</span>`;
			if (type === "Direct") return `<span style="color:#6c757d;font-style:italic">${formatted}</span>`;
			if (data.link_doctype && data.link_name) {
				const route = frappe.router.slug(data.link_doctype);
				const style = type === "WBS" ? "font-weight:600;color:#004085" : "color:#117a8b";
				return `<a href="/app/${route}/${encodeURIComponent(data.link_name)}" style="${style}">${formatted}</a>`;
			}
		}

		if (["Section", "Net"].includes(type)) return `<b>${formatted}</b>`;
		return formatted;
	},

	tree: true,
	initial_depth: 2,
};
