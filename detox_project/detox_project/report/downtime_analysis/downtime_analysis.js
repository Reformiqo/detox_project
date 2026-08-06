// CR-03.6 / CZ-36 — Downtime Analysis filters.
frappe.query_reports["Downtime Analysis"] = {
    filters: [
        {fieldname: "from_date", label: __("From Posting Date"),
         fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1)},
        {fieldname: "to_date", label: __("To Posting Date"),
         fieldtype: "Date", default: frappe.datetime.get_today()},
        {fieldname: "cost_center", label: __("Cost Center"),
         fieldtype: "Link", options: "Cost Center"},
        {fieldname: "project", label: __("Project"),
         fieldtype: "Link", options: "Project"},
        {fieldname: "item", label: __("Produced Item"),
         fieldtype: "Link", options: "Item"},
    ],
};
