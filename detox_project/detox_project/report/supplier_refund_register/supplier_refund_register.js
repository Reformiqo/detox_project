// ABP2-I225 FR-12 — Supplier Refund Register filters
frappe.query_reports["Supplier Refund Register"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "supplier",
            label: __("Supplier"),
            fieldtype: "Link",
            options: "Supplier",
        },
        {
            fieldname: "refund_reason",
            label: __("Refund Reason"),
            fieldtype: "Select",
            options: [
                "",
                "Order Cancellation",
                "Goods Returned",
                "Service Not Rendered",
                "Excess / Duplicate Payment",
                "Other",
            ].join("\n"),
        },
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "Select",
            options: ["Submitted", "Cancelled", "Draft", "All"].join("\n"),
            default: "Submitted",
        },
    ],
};
