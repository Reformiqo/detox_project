frappe.query_reports["Revenue Budget Tracker"] = {
    "filters": [
        { "fieldname": "company", "label": __("Company"), "fieldtype": "Link", "options": "Company" },
        { "fieldname": "project", "label": __("Project"), "fieldtype": "Link", "options": "Project" },
        { "fieldname": "financial_model", "label": __("Project Budget"), "fieldtype": "Link", "options": "Financial Model" },
        { "fieldname": "wbs_element", "label": __("WBS Element"), "fieldtype": "Link", "options": "WBS Element", "get_query": function() { return { filters: { custom_category_type: "Revenue" } }; } },
        { "fieldname": "category", "label": __("Category"), "fieldtype": "Link", "options": "Project Cost Category", "get_query": function() { return { filters: { custom_category_type: "Revenue" } }; } },
        { "fieldname": "status", "label": __("Status"), "fieldtype": "Select", "options": "\nActive\nOn Hold\nCompleted\nCancelled" }
    ]
};
