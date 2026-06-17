frappe.query_reports["Production Plan vs Actual"] = {
    filters: [
        {fieldname: "production_plan", label: __("Production Plan"),
         fieldtype: "Link", options: "Production Plan"},
        {fieldname: "from_date", label: __("From Posting Date"),
         fieldtype: "Date"},
        {fieldname: "to_date", label: __("To Posting Date"),
         fieldtype: "Date"},
        {fieldname: "warehouse", label: __("FG Warehouse"),
         fieldtype: "Link", options: "Warehouse"},
    ],
    formatter(value, row, column, data, default_formatter) {
        const v = default_formatter(value, row, column, data);
        if (column.fieldname === "completion_pct" && data) {
            const pct = flt(data.completion_pct);
            const colour = pct >= 90 ? "#28a745" : (pct >= 50 ? "#ffc107" : "#dc3545");
            return `<span style="color:${colour};font-weight:600">${v}</span>`;
        }
        return v;
    },
};
