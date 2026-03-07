app_name = "detox_project"
app_title = "Detox Project"
app_publisher = "erpera"
app_description = "detox"
app_email = "info@erpera.io"
app_license = "mit"

required_apps = ["frappe", "erpnext"]

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Detox Project"]]},
    {"dt": "Property Setter", "filters": [["module", "=", "Detox Project"]]},
    {"dt": "Workflow", "filters": [["name", "in", ["Project Approval Workflow"]]]},
    {"dt": "Notification", "filters": [["module", "=", "Detox Project"]]},
]

# --------------------------------------------------------------------------
# DocType JS
# --------------------------------------------------------------------------
doctype_js = {
    "Project": "public/js/project_custom.js",
    "Material Request": "public/js/material_request_custom.js",
    "Purchase Order": "public/js/purchase_order_custom.js",
}

# --------------------------------------------------------------------------
# App Include JS — Tender Management integration (loaded globally)
# --------------------------------------------------------------------------
app_include_js = ["/assets/detox_project/js/tender_management.js"]

# --------------------------------------------------------------------------
# Document Events
# --------------------------------------------------------------------------
doc_events = {
    "Project": {
        "validate": "detox_project.detox_project.api.validate_project",
        "on_update": "detox_project.detox_project.api.on_project_update",
    },
    "Material Request": {
        "validate": "detox_project.detox_project.api.validate_material_request_budget",
    },
    "Purchase Order": {
        "validate": "detox_project.detox_project.api.validate_po_budget",
        "on_submit": "detox_project.detox_project.api.on_po_submit",
    },
    "Purchase Invoice": {
        "on_submit": "detox_project.detox_project.api.on_pi_submit",
    },
    "Tender Management": {
        "on_update": "detox_project.events.tender.on_update",
        "before_cancel": "detox_project.events.tender.before_cancel",
    },
}

# --------------------------------------------------------------------------
# Scheduled Tasks
# --------------------------------------------------------------------------
scheduler_events = {
    "daily": [
        "detox_project.detox_project.api.send_budget_alerts",
    ],
}

# --------------------------------------------------------------------------
# After Install / Migrate
# --------------------------------------------------------------------------
after_install = "detox_project.setup.after_install"
after_migrate = "detox_project.setup.after_migrate"
