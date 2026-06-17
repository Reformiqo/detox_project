frappe.query_reports["Outstanding Cylinder Deposits"] = {
    filters: [
        {fieldname: "customer", label: __("Customer"),
         fieldtype: "Link", options: "Customer"},
        {fieldname: "from_date", label: __("From Issue Date"),
         fieldtype: "Date"},
        {fieldname: "to_date", label: __("To Issue Date"),
         fieldtype: "Date"},
    ],
};
