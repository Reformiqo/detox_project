frappe.query_reports["Project Budget Transactions"] = {
	filters: [
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project", reqd: 1 },
		{ fieldname: "section", label: __("Section"), fieldtype: "Select", options: "All\nExpense\nRevenue", default: "All" },
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
			fieldname: "sub_wbs_element",
			label: __("Sub WBS Element"),
			fieldtype: "Link",
			options: "Sub WBS Element",
			get_query: function () {
				const wbs = frappe.query_report.get_filter_value("wbs_element");
				return { filters: wbs ? { main_wbs_element: wbs } : {} };
			},
		},
		{
			fieldname: "category",
			label: __("Category"),
			fieldtype: "Link",
			options: "Project Cost Category",
		},
		{
			fieldname: "status",
			label: __("WBS Status"),
			fieldtype: "Select",
			options: "All\nActive\nOn Hold\nCompleted",
			default: "All",
		},
		{
			fieldname: "measure",
			label: __("Measure"),
			fieldtype: "Select",
			options: "Assigned (All)\nActual\nCommitment\nPending",
			default: "Assigned (All)",
		},
		{
			fieldname: "scope",
			label: __("WBS Link"),
			fieldtype: "Select",
			options: "All\nLinked to WBS\nNot linked to WBS\nDirect to WBS only\nSub WBS of another WBS",
			default: "All",
		},
	],

	onload: function (report) {
		report.page.add_inner_button(__("Open in List View"), function () {
			const rows = (frappe.query_report.data || []).filter((r) => r.ref_doctype && r.ref_name && !r.is_total);
			const by_type = {};
			rows.forEach((r) => {
				by_type[r.ref_doctype] = by_type[r.ref_doctype] || new Set();
				by_type[r.ref_doctype].add(r.ref_name);
			});
			const types = Object.keys(by_type).sort();
			if (!types.length) {
				frappe.msgprint(__("No transactions in the current result."));
				return;
			}
			if (types.length === 1) {
				open_list(types[0], Array.from(by_type[types[0]]));
				return;
			}
			const d = new frappe.ui.Dialog({ title: __("Open in List View"), fields: [{ fieldtype: "HTML", fieldname: "btns" }] });
			const $wrap = $('<div class="d-flex flex-column" style="gap:8px"></div>');
			types.forEach((dt) => {
				const names = Array.from(by_type[dt]);
				$(`<button class="btn btn-default btn-sm text-left">${__(dt)} (${names.length})</button>`)
					.on("click", () => {
						d.hide();
						open_list(dt, names);
					})
					.appendTo($wrap);
			});
			d.fields_dict.btns.$wrapper.append($wrap);
			d.show();
		});

		function open_list(doctype, names) {
			frappe.route_options = { name: ["in", names] };
			frappe.set_route("List", doctype, "List");
		}
	},

	formatter: function (value, row, column, data, default_formatter) {
		if (data && data.is_total) {
			if (column.fieldname === "ref_name") return `<b>${frappe.utils.escape_html(data.ref_name || "")}</b>`;
			return `<b>${default_formatter(value, row, column, data)}</b>`;
		}
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "measure") {
			const color = { Actual: "#155724", Commitment: "#b45309", Pending: "#6c757d" }[data.measure] || "inherit";
			return `<span style="color:${color};font-weight:600">${value}</span>`;
		}
		return value;
	},
};
