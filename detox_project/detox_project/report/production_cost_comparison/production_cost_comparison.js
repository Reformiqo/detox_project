// ABP2-I419 Phase 5 — Production Cost Comparison report filters.
frappe.query_reports["Production Cost Comparison"] = {
    filters: [
        {fieldname: "production_plan", label: __("Production Plan"),
         fieldtype: "Link", options: "Production Plan"},
        {fieldname: "from_date", label: __("From Posting Date"),
         fieldtype: "Date"},
        {fieldname: "to_date", label: __("To Posting Date"),
         fieldtype: "Date"},
    ],
    formatter(value, row, column, data, default_formatter) {
        const v = default_formatter(value, row, column, data);
        if (column.fieldname === "rate_variance" || column.fieldname === "amount_variance") {
            if (data && flt(data[column.fieldname]) > 0) {
                return `<span style="color:red;font-weight:600">${v}</span>`;
            }
            if (data && flt(data[column.fieldname]) < 0) {
                return `<span style="color:green;font-weight:600">${v}</span>`;
            }
        }
        return v;
    },
};
