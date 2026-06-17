app_name = "detox_project"
app_title = "Detox Project"
app_publisher = "erpera"
app_description = "detox"
app_email = "info@erpera.io"
app_license = "mit"

required_apps = ["frappe", "erpnext"]

app_version = "2.0.0"

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Detox Project"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Detox Project"]]},
	{"dt": "Workflow", "filters": [["name", "in", ["Project Approval Workflow", "Financial Model Approval Workflow"]]]},
	{"dt": "Notification", "filters": [["module", "=", "Detox Project"]]},
]

# --------------------------------------------------------------------------
# DocType JS
# --------------------------------------------------------------------------
doctype_js = {
	"Project": "public/js/project_custom.js",
	"Material Request": "public/js/material_request_custom.js",
	"Purchase Order": "public/js/purchase_order_custom.js",
	"Purchase Invoice": "public/js/purchase_invoice_custom.js",
	"Purchase Receipt": "public/js/purchase_receipt_custom.js",
	"Sales Order": "public/js/sales_order_custom.js",
	"Quotation": "public/js/quotation_custom.js",
	# ABP2-I419 Phase 1 — Production Plan No-BOM mode client logic.
	"Production Plan": "public/js/production_plan_custom.js",
	# ABP2-I419 Phase 3 — Stock Entry Manufacture client logic.
	"Stock Entry": "public/js/stock_entry_manufacture.js",
}

# --------------------------------------------------------------------------
# App Include JS — Tender Management integration (loaded globally)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Accounting Dimensions — add section to these additional doctypes
# --------------------------------------------------------------------------
accounting_dimension_doctypes = [
	"Material Request",
	"Blanket Order",
]

app_include_js = [
	"/assets/detox_project/js/tender_management.js",
	"/assets/detox_project/js/accounting_dimensions_uncollapse.js",
]

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
		# ABP2-I439 — cancelling a PO must decrement WBS budget_spent.
		"on_cancel": "detox_project.detox_project.api.on_po_submit",
	},
	"Purchase Invoice": {
		"validate": "detox_project.detox_project.api.validate_pi_dedupe",
		"on_submit": "detox_project.detox_project.api.on_pi_submit",
		# ABP2-I439 — cancelling a PI must decrement WBS budget_spent.
		"on_cancel": "detox_project.detox_project.api.on_pi_submit",
	},
	"Purchase Receipt": {
		"validate": "detox_project.detox_project.api.validate_pr_dedupe",
		"on_submit": "detox_project.detox_project.api.on_pr_submit",
		"on_cancel": "detox_project.detox_project.api.on_pr_submit",
	},
	"Tender Management": {
		"on_update": "detox_project.events.tender.on_update",
		"before_cancel": "detox_project.events.tender.before_cancel",
	},
	# ABP2-I419 Phase 2 — CC + Project mandatory + cascade across the
	# manufacturing chain. Single shared guard in
	# detox_project.detox_project.overrides.cc_project_guard.
	"Production Plan": {
		"validate": "detox_project.detox_project.overrides.cc_project_guard.validate_production_plan",
		"on_submit": "detox_project.detox_project.overrides.cc_project_guard.cascade_pp_to_work_orders",
	},
	"Work Order": {
		"validate": "detox_project.detox_project.overrides.cc_project_guard.validate_work_order",
	},
	"Stock Entry": {
		"before_save": "detox_project.detox_project.overrides.cc_project_guard.inherit_se_from_work_order",
		"validate": [
			"detox_project.detox_project.overrides.cc_project_guard.validate_stock_entry",
			# ABP2-I419 Phase 3 — Mfg-flow validations + rollup.
			"detox_project.detox_project.overrides.stock_entry_manufacture.validate_stock_entry_manufacture",
		],
		"on_submit": "detox_project.detox_project.overrides.stock_entry_manufacture.rollup_total_produced_on_submit",
		"on_cancel": "detox_project.detox_project.overrides.stock_entry_manufacture.rollup_total_produced_on_cancel",
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
