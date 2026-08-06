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
	# {"dt": "Workflow", "filters": [["name", "in", ["Project Approval Workflow", "Financial Model Approval Workflow"]]]},
	# {"dt": "Notification", "filters": [["module", "=", "Detox Project"]]},
	# # ABP2-I419 Phase 5 — ship the Production Day Summary print format.
	# {"dt": "Print Format", "filters": [["module", "=", "Detox Project"]]},
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
	# ABP2-I483 — cascade WO header CC + Project to required_items rows
	# BEFORE Frappe's client-side check_mandatory blocks the save.
	"Work Order": "public/js/work_order_cascade.js",
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
	# ABP2-I419 Phase 4 — Subcontracting Flow A (v16 native).
	"Subcontracting Order": {
		"validate": "detox_project.detox_project.overrides.subcontracting.validate_subcontracting_doc",
	},
	"Subcontracting Receipt": {
		"validate": [
			"detox_project.detox_project.overrides.subcontracting.validate_subcontracting_doc",
			"detox_project.detox_project.overrides.subcontracting.validate_supplied_vs_consumed",
		],
	},
	# ABP2-I419 Phase 6 — Cylinder Deposit Ledger auto-create on DN / SI submit.
	"Delivery Note": {
		"on_submit": "detox_project.detox_project.doctype.cylinder_deposit_ledger.cylinder_deposit_ledger.auto_create_deposit_entries",
	},
	"Sales Invoice": {
		"on_submit": "detox_project.detox_project.doctype.cylinder_deposit_ledger.cylinder_deposit_ledger.auto_create_deposit_entries",
	},
	# ABP2-I419 Phase 2 — CC + Project mandatory + cascade across the
	# manufacturing chain. Single shared guard in
	# detox_project.detox_project.overrides.cc_project_guard.
	"Production Plan": {
		"validate": [
			"detox_project.detox_project.overrides.cc_project_guard.validate_production_plan",
			# CR-01 — planned_date >= posting_date (block), past-date warn.
			"detox_project.detox_project.change_set.cr01_production_plan_date.validate_production_plan_dates",
		],
		"on_submit": "detox_project.detox_project.overrides.cc_project_guard.cascade_pp_to_work_orders",
		# CR-01 — post-submit date revision: role gate, reason mandatory, stamp + timeline, sync draft links.
		"on_update_after_submit": "detox_project.detox_project.change_set.cr01_production_plan_date.on_update_after_submit_dates",
	},
	"Work Order": {
		# ABP2-I483 reopen (Sahil 2026-07-01): when a WO is created via
		# Production Plan → Create → Work Order, ERPNext inserts it with
		# ignore_mandatory/ignore_validate flags. Neither our validate
		# hook nor PP.on_submit fires (PP is Draft). Inherit CC + Project
		# from the parent PP on before_insert so the fresh WO has them.
		"before_insert": "detox_project.detox_project.overrides.cc_project_guard.inherit_wo_from_production_plan",
		"validate": "detox_project.detox_project.overrides.cc_project_guard.validate_work_order",
	},
	"Stock Entry": {
		"before_save": [
			"detox_project.detox_project.overrides.cc_project_guard.inherit_se_from_work_order",
			# Sahil 2026-06-17 — pull CC + Project from the linked Production
			# Plan onto the SE header + every item row, so ERPNext never falls
			# back to Company.default_cost_center.
			"detox_project.detox_project.overrides.stock_entry_manufacture.inherit_se_from_production_plan",
		],
		"validate": [
			# Same Production-Plan inheritance runs on validate too — covers
			# the case where the SE is being saved after the user manually
			# changes production_plan on the form.
			"detox_project.detox_project.overrides.stock_entry_manufacture.inherit_se_from_production_plan",
			"detox_project.detox_project.overrides.cc_project_guard.validate_stock_entry",
			# ABP2-I419 Phase 3 — Mfg-flow validations + rollup.
			"detox_project.detox_project.overrides.stock_entry_manufacture.validate_stock_entry_manufacture",
			# CR-03 — downtime capture: reason reqd when downtime>0, time order, shift cap, net>=0.
			"detox_project.detox_project.change_set.cr03_downtime.validate_downtime",
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
		# ABP2-I419 Phase 5 — overdue Production Plan alert.
		"detox_project.setup.overdue_production_plan_alert",
	],
}

# --------------------------------------------------------------------------
# After Install / Migrate
# --------------------------------------------------------------------------
after_install = "detox_project.setup.after_install"
after_migrate = "detox_project.setup.after_migrate"
