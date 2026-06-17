import frappe
from frappe import _


def after_install():
	create_custom_fields()
	create_project_types()
	setup_workflows()
	setup_notifications()
	frappe.msgprint(_("Detox Project module installed successfully!"))


def after_migrate():
	create_custom_fields()
	create_project_types()
	patch_fm_wbs_fields_to_link()
	migrate_wbs_allocations()
	fix_budget_notification()
	cleanup_old_wbs_fields()
	create_fm_property_setters()
	setup_fm_workflow()
	unlock_orphaned_fm_child_rows()
	heal_duplicate_wbs_allocations()  # ABP2-I455
	heal_wbs_budget_spent()  # ABP2-I439
	setup_production_plan_no_bom()  # ABP2-I419 Phase 1
	setup_phase2_cc_project_enforcement()  # ABP2-I419 Phase 2
	setup_phase3_stock_entry_manufacture()  # ABP2-I419 Phase 3
	setup_phase4_subcontracting()  # ABP2-I419 Phase 4


FM_CHILD_TABLES = (
	"FM Revenue Item",
	"FM Expense Item",
	"FM Extra Expense Item",
	"FM Project Cost Item",
	"FM Year Projection",
	"FM Loan Schedule",
	"FM Depreciation Schedule",
	"FM Budget Plan Link",
)


def unlock_orphaned_fm_child_rows():
	"""ABP2-I184 layer 5: reset child rows whose parent is back in Draft.

	Pattern: a Financial Model gets submitted (children docstatus=1),
	then cancelled (children → 2), then the parent's docstatus is hand-
	rewound to 0 to allow further editing — but the children remain at
	docstatus=2, which Frappe treats as cancelled and locks read-only,
	so users see a fully-Approved-state form they cannot edit even when
	the workflow allow_edit gate is open.

	This sweep finds parents with docstatus=0 whose children sit at
	docstatus=2 and resets the children to draft, then bumps parent +
	workflow modified timestamps so the desk frontend reloads cleanly.
	Runs every after_migrate; idempotent.
	"""
	affected_parents = set()
	for child_dt in FM_CHILD_TABLES:
		try:
			rows = frappe.db.sql(
				"SELECT DISTINCT parent FROM `tab" + child_dt + "` "
				"WHERE docstatus=2 AND parenttype='Financial Model'",
				as_dict=True,
			)
		except Exception:
			# child doctype absent on a fresh install — skip
			continue
		for r in rows:
			affected_parents.add(r.parent)

	if not affected_parents:
		return

	parents_to_unlock = [
		p for p in affected_parents
		if frappe.db.get_value("Financial Model", p, "docstatus") == 0
	]
	if not parents_to_unlock:
		return

	for parent in parents_to_unlock:
		for child_dt in FM_CHILD_TABLES:
			try:
				frappe.db.sql(
					"UPDATE `tab" + child_dt + "` SET docstatus=0 "
					"WHERE parent=%s AND parenttype='Financial Model' "
					"AND docstatus=2",
					(parent,),
				)
			except Exception:
				continue
		frappe.db.sql(
			"UPDATE `tabFinancial Model` SET modified=NOW() WHERE name=%s",
			(parent,),
		)

	frappe.db.sql(
		"UPDATE `tabWorkflow` SET modified=NOW() "
		"WHERE name='Financial Model Approval Workflow'"
	)
	frappe.db.commit()
	frappe.clear_cache(doctype="Financial Model")
	frappe.clear_cache(doctype="Workflow")
	print(
		"[detox_project] unlocked %d FM(s) with orphan-cancelled child rows: %s"
		% (len(parents_to_unlock), parents_to_unlock)
	)


def create_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	custom_fields = {
		# ═══════════════════════════════════════════════════════════════════
		# PROJECT — Classification, Budget, Revenue, Approval, Tender
		# ═══════════════════════════════════════════════════════════════════
		"Project": [
			# --- Project Identity (NEW) ---
			dict(
				fieldname="custom_project_identity_section",
				fieldtype="Section Break",
				label="Project Identity",
				insert_after="project_type",
				collapsible=0,
			),
			dict(
				fieldname="custom_project_definition",
				fieldtype="Small Text",
				label="Project Definition",
				insert_after="custom_project_identity_section",
				description="High-level summary of project objectives and deliverables",
			),
			dict(
				fieldname="custom_project_code",
				fieldtype="Data",
				label="Project Code",
				insert_after="custom_project_definition",
				unique=1,
				description="Short unique code (e.g., DGEPL-EPC-001)",
			),
			dict(
				fieldname="custom_column_break_identity",
				fieldtype="Column Break",
				insert_after="custom_project_code",
			),
			dict(
				fieldname="custom_project_year",
				fieldtype="Data",
				label="Project Year",
				insert_after="custom_column_break_identity",
			),
			dict(
				fieldname="custom_project_profile",
				fieldtype="Select",
				label="Project Profile",
				options="\nStandard\nHigh Priority\nStrategic\nInternal\nLegacy Waste\nFresh Waste\nCBG\nWaste Water\nLab Testing",
				insert_after="custom_project_year",
			),
			dict(
				fieldname="custom_person_responsible",
				fieldtype="Link",
				label="Person Responsible",
				options="Employee",
				insert_after="custom_project_profile",
			),
			dict(
				fieldname="custom_business_place",
				fieldtype="Link",
				label="Business Place",
				options="Address",
				insert_after="custom_person_responsible",
				description="Business place for taxation purpose",
			),
			# --- Classification ---
			dict(
				fieldname="custom_project_classification_section",
				fieldtype="Section Break",
				label="Project Classification",
				insert_after="project_type",
				collapsible=1,
			),
			dict(
				fieldname="custom_project_classification",
				fieldtype="Select",
				label="Classification",
				options="\nInternal\nExternal\nJoint Venture",
				insert_after="custom_project_classification_section",
			),
			dict(
				fieldname="custom_financial_model",
				fieldtype="Link",
				label="Financial Model",
				options="Financial Model",
				insert_after="custom_project_classification",
			),
			dict(
				fieldname="custom_financial_model_status",
				fieldtype="Select",
				label="Financial Model Status",
				options="\nPending\nApproved\nRejected\nCancelled",
				insert_after="custom_financial_model",
				read_only=1,
			),
			dict(
				fieldname="custom_column_break_class",
				fieldtype="Column Break",
				insert_after="custom_financial_model_status",
			),
			dict(
				fieldname="custom_loi_reference",
				fieldtype="Data",
				label="LOI Reference",
				insert_after="custom_column_break_class",
				description="Letter of Intent reference (required for SEPPL)",
			),
			dict(
				fieldname="custom_loi_date",
				fieldtype="Date",
				label="LOI Date",
				insert_after="custom_loi_reference",
			),
			dict(
				fieldname="custom_project_site",
				fieldtype="Data",
				label="Project Site",
				insert_after="custom_column_break_class",
			),
			dict(
				fieldname="custom_project_approver",
				fieldtype="Link",
				label="Project Approver",
				options="User",
				insert_after="custom_project_site",
			),
			# --- Budget Summary ---
			dict(
				fieldname="custom_budget_section",
				fieldtype="Section Break",
				label="Budget Summary",
				insert_after="custom_project_approver",
			),
			dict(
				fieldname="custom_material_budget",
				fieldtype="Currency",
				label="Material Budget",
				insert_after="custom_budget_section",
				read_only=1,
			),
			dict(
				fieldname="custom_service_budget",
				fieldtype="Currency",
				label="Service Budget",
				insert_after="custom_material_budget",
				read_only=1,
			),
			dict(
				fieldname="custom_total_budget",
				fieldtype="Currency",
				label="Total Budget",
				insert_after="custom_service_budget",
				read_only=1,
				bold=1,
			),
			dict(
				fieldname="custom_column_break_budget",
				fieldtype="Column Break",
				insert_after="custom_total_budget",
			),
			dict(
				fieldname="custom_material_spent",
				fieldtype="Currency",
				label="Material Spent",
				insert_after="custom_column_break_budget",
				read_only=1,
			),
			dict(
				fieldname="custom_service_spent",
				fieldtype="Currency",
				label="Service Spent",
				insert_after="custom_material_spent",
				read_only=1,
			),
			dict(
				fieldname="custom_total_spent",
				fieldtype="Currency",
				label="Total Spent",
				insert_after="custom_service_spent",
				read_only=1,
				bold=1,
			),
			dict(
				fieldname="custom_column_break_budget2",
				fieldtype="Column Break",
				insert_after="custom_total_spent",
			),
			dict(
				fieldname="custom_budget_utilization_pct",
				fieldtype="Percent",
				label="Budget Utilization %",
				insert_after="custom_column_break_budget2",
				read_only=1,
				bold=1,
			),
			dict(
				fieldname="custom_budget_remaining",
				fieldtype="Currency",
				label="Budget Remaining",
				insert_after="custom_budget_utilization_pct",
				read_only=1,
			),
			# --- Revenue Tracking ---
			dict(
				fieldname="custom_revenue_section",
				fieldtype="Section Break",
				label="Revenue Tracking",
				insert_after="custom_budget_remaining",
				collapsible=1,
			),
			dict(
				fieldname="custom_total_revenue",
				fieldtype="Currency",
				label="Total Revenue",
				insert_after="custom_revenue_section",
			),
			dict(
				fieldname="custom_total_invoiced",
				fieldtype="Currency",
				label="Total Invoiced",
				insert_after="custom_total_revenue",
				read_only=1,
			),
			dict(
				fieldname="custom_column_break_revenue",
				fieldtype="Column Break",
				insert_after="custom_total_invoiced",
			),
			dict(
				fieldname="custom_total_collected",
				fieldtype="Currency",
				label="Total Collected",
				insert_after="custom_column_break_revenue",
				read_only=1,
			),
			dict(
				fieldname="custom_outstanding_amount",
				fieldtype="Currency",
				label="Outstanding Amount",
				insert_after="custom_total_collected",
				read_only=1,
			),
			# --- Carbon Credits ---
			dict(
				fieldname="custom_carbon_section",
				fieldtype="Section Break",
				label="Carbon Credits",
				insert_after="custom_outstanding_amount",
				collapsible=1,
			),
			dict(
				fieldname="custom_carbon_credits_earned",
				fieldtype="Float",
				label="Carbon Credits Earned",
				insert_after="custom_carbon_section",
			),
			dict(
				fieldname="custom_carbon_credits_value",
				fieldtype="Currency",
				label="Carbon Credits Value",
				insert_after="custom_carbon_credits_earned",
			),
			# --- Tender Details (with proper Link to Tender Management) ---
			dict(
				fieldname="custom_tender_section",
				fieldtype="Section Break",
				label="Tender Details",
				insert_after="custom_carbon_credits_value",
				collapsible=1,
			),
			dict(
				fieldname="custom_tender_management",
				fieldtype="Link",
				label="Tender",
				options="Tender Management",
				insert_after="custom_tender_section",
				read_only=1,
				bold=1,
				in_standard_filter=1,
			),
			dict(
				fieldname="custom_tender_number",
				fieldtype="Data",
				label="Tender Number",
				insert_after="custom_tender_management",
				read_only=1,
			),
			dict(
				fieldname="custom_tender_type",
				fieldtype="Data",
				label="Tender Type",
				insert_after="custom_tender_number",
				read_only=1,
			),
			dict(
				fieldname="custom_tender_site_address",
				fieldtype="Small Text",
				label="Site Address (Tender)",
				insert_after="custom_tender_type",
				read_only=1,
			),
			dict(
				fieldname="custom_column_break_tender",
				fieldtype="Column Break",
				insert_after="custom_tender_site_address",
			),
			dict(
				fieldname="custom_tender_award_date",
				fieldtype="Date",
				label="Award Date",
				insert_after="custom_column_break_tender",
				read_only=1,
			),
			dict(
				fieldname="custom_estimated_project_cost_tender",
				fieldtype="Currency",
				label="Estimated Cost (Tender)",
				insert_after="custom_tender_award_date",
				read_only=1,
			),
			dict(
				fieldname="custom_capital_cost_tender",
				fieldtype="Currency",
				label="Capital Cost",
				insert_after="custom_estimated_project_cost_tender",
				read_only=1,
			),
			dict(
				fieldname="custom_o_and_m_cost_tender",
				fieldtype="Currency",
				label="O&M Cost",
				insert_after="custom_capital_cost_tender",
				read_only=1,
			),
			dict(
				fieldname="custom_emd_amount",
				fieldtype="Currency",
				label="EMD Amount",
				insert_after="custom_o_and_m_cost_tender",
				read_only=1,
			),
			dict(
				fieldname="custom_performance_security_amt",
				fieldtype="Currency",
				label="Performance Security",
				insert_after="custom_emd_amount",
				read_only=1,
			),
			dict(
				fieldname="custom_project_duration_months",
				fieldtype="Int",
				label="Project Duration (Months)",
				insert_after="custom_performance_security_amt",
			),
			dict(
				fieldname="custom_o_and_m_period_months",
				fieldtype="Int",
				label="O&M Period (Months)",
				insert_after="custom_project_duration_months",
			),
			# Backward compatibility — keep old fields
			dict(
				fieldname="custom_tender",
				fieldtype="Data",
				label="Tender Ref (Legacy)",
				insert_after="custom_o_and_m_period_months",
				hidden=1,
				read_only=1,
			),
			dict(
				fieldname="custom_tender_name",
				fieldtype="Data",
				label="Tender Name (Legacy)",
				insert_after="custom_tender",
				hidden=1,
				read_only=1,
			),
			dict(
				fieldname="custom_client_name",
				fieldtype="Data",
				label="Client Name",
				insert_after="custom_tender_name",
				hidden=1,
				read_only=1,
			),
			dict(
				fieldname="custom_tender_value",
				fieldtype="Currency",
				label="Tender Value (Legacy)",
				insert_after="custom_client_name",
				hidden=1,
				read_only=1,
			),
			# --- Cancellation ---
			dict(
				fieldname="custom_cancellation_section",
				fieldtype="Section Break",
				label="Cancellation Details",
				insert_after="custom_tender_value",
				collapsible=1,
				depends_on="eval:doc.status=='Cancelled'",
			),
			dict(
				fieldname="custom_cancellation_reason",
				fieldtype="Small Text",
				label="Cancellation Reason",
				insert_after="custom_cancellation_section",
			),
			dict(
				fieldname="custom_cancelled_by",
				fieldtype="Link",
				label="Cancelled By",
				options="User",
				insert_after="custom_cancellation_reason",
				read_only=1,
			),
			dict(
				fieldname="custom_cancellation_date",
				fieldtype="Date",
				label="Cancellation Date",
				insert_after="custom_cancelled_by",
				read_only=1,
			),
			dict(
				fieldname="custom_cancelled_date",
				fieldtype="Date",
				label="Cancelled Date",
				insert_after="custom_cancellation_date",
				read_only=1,
			),
		],
		# ═══════════════════════════════════════════════════════════════════
		# FM EXPENSE ITEM — Category for OPEX WBS linking
		# ═══════════════════════════════════════════════════════════════════
		"FM Expense Item": [
			dict(fieldname="custom_category", fieldtype="Link",
				label="Category", options="Project Cost Category",
				insert_after="expense_head", in_list_view=1),
		],
		# ═══════════════════════════════════════════════════════════════════
		# FINANCIAL MODEL — OPEX Working Capital
		# ═══════════════════════════════════════════════════════════════════
		"Financial Model": [
			dict(fieldname="custom_opex_wc_section", fieldtype="Section Break",
				label="OPEX Working Capital", insert_after="total_extra_expenses"),
			dict(fieldname="custom_opex_working_capital", fieldtype="Currency",
				label="OPEX Working Capital Amount", insert_after="custom_opex_wc_section"),
			dict(fieldname="custom_opex_interest_rate_wc", fieldtype="Percent",
				label="Interest Rate - Working Capital % (OPEX)",
				insert_after="custom_opex_working_capital", default="12"),
			dict(fieldname="custom_column_break_opex_wc", fieldtype="Column Break",
				insert_after="custom_opex_interest_rate_wc"),
			dict(fieldname="custom_opex_interest_on_wc_annual", fieldtype="Currency",
				label="Interest on WC - Annual (OPEX)",
				insert_after="custom_column_break_opex_wc", read_only=1,
				description="WC Amount x WC Interest Rate. Fixed each year."),
			dict(fieldname="custom_opex_moratorium_years", fieldtype="Float",
				label="Moratorium Period (Years) (OPEX)",
				insert_after="custom_opex_interest_on_wc_annual",
				description="No repayment during this period. Decimal allowed (e.g. 0.5 = 6 months)"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# MATERIAL REQUEST — WBS Allocations
		# ═══════════════════════════════════════════════════════════════════
		"Material Request": [
			dict(fieldname="custom_financial_model", fieldtype="Link",
				label="Financial Model", options="Financial Model",
				insert_after="schedule_date", in_standard_filter=1,
				module="Detox Project"),
			dict(fieldname="custom_wbs_allocations_section", fieldtype="Section Break",
				label="WBS Allocations", insert_after="custom_financial_model"),
			dict(fieldname="custom_wbs_allocations", fieldtype="Table",
				label="WBS Allocations", options="WBS Allocation",
				insert_after="custom_wbs_allocations_section"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# BLANKET ORDER — Financial Model
		# ═══════════════════════════════════════════════════════════════════
		"Blanket Order": [
			dict(fieldname="custom_financial_model", fieldtype="Link",
				label="Financial Model", options="Financial Model",
				insert_after="naming_series", in_standard_filter=1,
				module="Detox Project"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# MATERIAL REQUEST ITEM — Per-item WBS assignment
		# ═══════════════════════════════════════════════════════════════════
		"Material Request Item": [
			dict(fieldname="custom_wbs_element", fieldtype="Link",
				label="WBS Element", options="WBS Element", insert_after="project"),
			dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
				label="Sub WBS Element", options="Sub WBS Element",
				insert_after="custom_wbs_element"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# PURCHASE ORDER — WBS Allocations
		# ═══════════════════════════════════════════════════════════════════
		"Purchase Order": [
			dict(fieldname="custom_wbs_allocations_section", fieldtype="Section Break",
				label="WBS Allocations", insert_after="project"),
			dict(fieldname="custom_wbs_allocations", fieldtype="Table",
				label="WBS Allocations", options="WBS Allocation",
				insert_after="custom_wbs_allocations_section"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# PURCHASE ORDER ITEM — Per-item WBS assignment
		# ═══════════════════════════════════════════════════════════════════
		"Purchase Order Item": [
			dict(fieldname="custom_wbs_element", fieldtype="Link",
				label="WBS Element", options="WBS Element", insert_after="project"),
			dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
				label="Sub WBS Element", options="Sub WBS Element",
				insert_after="custom_wbs_element"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# PURCHASE INVOICE — WBS Allocations
		# ═══════════════════════════════════════════════════════════════════
		"Purchase Invoice": [
			dict(fieldname="custom_wbs_allocations_section", fieldtype="Section Break",
				label="WBS Allocations", insert_after="project"),
			dict(fieldname="custom_wbs_allocations", fieldtype="Table",
				label="WBS Allocations", options="WBS Allocation",
				insert_after="custom_wbs_allocations_section"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# PURCHASE INVOICE ITEM — Per-item WBS assignment
		# ═══════════════════════════════════════════════════════════════════
		"Purchase Invoice Item": [
			dict(fieldname="custom_wbs_element", fieldtype="Link",
				label="WBS Element", options="WBS Element", insert_after="project"),
			dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
				label="Sub WBS Element", options="Sub WBS Element",
				insert_after="custom_wbs_element"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# PURCHASE RECEIPT — WBS Allocations
		# ═══════════════════════════════════════════════════════════════════
		"Purchase Receipt": [
			dict(fieldname="custom_wbs_allocations_section", fieldtype="Section Break",
				label="WBS Allocations", insert_after="project"),
			dict(fieldname="custom_wbs_allocations", fieldtype="Table",
				label="WBS Allocations", options="WBS Allocation",
				insert_after="custom_wbs_allocations_section"),
		],
		# ═══════════════════════════════════════════════════════════════════
		# ZWR12 REPORT PREREQ — Quality Inspection remarks
		# ═══════════════════════════════════════════════════════════════════
		"Quality Inspection": [
			dict(fieldname="custom_remarks_chemist", fieldtype="Small Text",
				label="Remarks (Chemist)", insert_after="custom_analysis_summary",
				description="Chemist's quick-check observations (e.g. Cl-1.54%). Shown in Gate Pass ZWR12 report."),
			dict(fieldname="custom_remarks_crm", fieldtype="Small Text",
				label="Remarks (CRM)", insert_after="custom_remarks_chemist",
				description="CRM action on the QC result (e.g. 'No Activity Required.')."),
		],
		# ═══════════════════════════════════════════════════════════════════
		# ZWR12 REPORT PREREQ — Gate Pass document review + QI status denormal
		# ═══════════════════════════════════════════════════════════════════
		"Gate Pass": [
			dict(fieldname="custom_document_review", fieldtype="Select",
				label="Document Review",
				options="\nPending\nAccepted\nRejected",
				insert_after="term_card",
				default="Pending"),
			dict(fieldname="custom_qi_status", fieldtype="Data",
				label="QI Status",
				insert_after="quality_review",
				read_only=1,
				description="Latest QC decision (Accepted/Rejected/Pending). Denormalised from Quality Inspection."),
		],
		# ═══════════════════════════════════════════════════════════════════
		# ZWR12 REPORT PREREQ — Customer PCB ID
		# ═══════════════════════════════════════════════════════════════════
		"Customer": [
			dict(fieldname="custom_pcb_id", fieldtype="Data",
				label="PCB ID", insert_after="customer_name",
				description="Pollution Control Board ID for this customer. Appears in Gate Pass ZWR12 report."),
		],
	}

	# ═══════════════════════════════════════════════════════════════════
	# TENDER MANAGEMENT — Conditional (only if doctype exists)
	# ═══════════════════════════════════════════════════════════════════
	if frappe.db.exists("DocType", "Tender Management"):
		custom_fields["Tender Management"] = [
			dict(
				fieldname="custom_linked_project",
				fieldtype="Link",
				label="Linked Project",
				options="Project",
				insert_after="status",
				read_only=1,
			),
			dict(
				fieldname="custom_project_status",
				fieldtype="Data",
				label="Project Status",
				insert_after="custom_linked_project",
				read_only=1,
			),
		]

	create_custom_fields(custom_fields, update=True)


def create_project_types():
	"""Create standard Project Types for Detox Group."""
	project_types = ["EPC", "O&M", "EPC + O&M", "Internal CAPEX", "Investment"]
	for pt in project_types:
		if not frappe.db.exists("Project Type", pt):
			frappe.get_doc(
				{
					"doctype": "Project Type",
					"project_type": pt,
				}
			).insert(ignore_permissions=True)


def setup_workflows():
	"""Create Project Approval Workflow."""
	if frappe.db.exists("Workflow", "Project Approval Workflow"):
		return

	try:
		workflow = frappe.get_doc(
			{
				"doctype": "Workflow",
				"workflow_name": "Project Approval Workflow",
				"document_type": "Project",
				"is_active": 1,
				"send_email_alert": 1,
				"states": [
					{"state": "Draft", "style": "Warning", "doc_status": "0", "allow_edit": "Projects User"},
					{
						"state": "Pending Approval",
						"style": "Primary",
						"doc_status": "0",
						"allow_edit": "Projects Manager",
					},
					{
						"state": "Approved",
						"style": "Success",
						"doc_status": "0",
						"allow_edit": "Projects Manager",
					},
					{
						"state": "Rejected",
						"style": "Danger",
						"doc_status": "0",
						"allow_edit": "Projects Manager",
					},
				],
				"transitions": [
					{
						"state": "Draft",
						"action": "Submit for Approval",
						"next_state": "Pending Approval",
						"allowed": "Projects User",
					},
					{
						"state": "Pending Approval",
						"action": "Approve",
						"next_state": "Approved",
						"allowed": "Projects Manager",
					},
					{
						"state": "Pending Approval",
						"action": "Reject",
						"next_state": "Rejected",
						"allowed": "Projects Manager",
					},
					{
						"state": "Rejected",
						"action": "Resubmit",
						"next_state": "Pending Approval",
						"allowed": "Projects User",
					},
				],
			}
		)
		workflow.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Workflow Setup Error")


def setup_notifications():
	"""Create Budget Threshold Alert notification."""
	if frappe.db.exists("Notification", "Budget Threshold Alert"):
		return

	try:
		notification = frappe.get_doc(
			{
				"doctype": "Notification",
				"name": "Budget Threshold Alert",
				"subject": "Budget Alert: {{ doc.wbs_name }} at {{ doc.budget_utilization_pct }}% utilization",
				"document_type": "WBS Element",
				"event": "Value Change",
				"value_changed": "budget_utilization_pct",
				"condition": "(doc.budget_utilization_pct or 0) >= 80",
				"channel": "Email",
				"message": """<p>WBS Element <b>{{ doc.wbs_name }}</b> ({{ doc.name }}) has reached
<b>{{ doc.budget_utilization_pct }}%</b> budget utilization.</p>
<p>Budget: {{ frappe.format_value(doc.total_budget, {'fieldtype': 'Currency'}) }}<br>
Spent: {{ frappe.format_value(doc.total_spent, {'fieldtype': 'Currency'}) }}</p>
<p>Please review and take necessary action.</p>""",
				"module": "Detox Project",
				"enabled": 1,
			}
		)
		notification.append("recipients", {"receiver_by_role": "Projects Manager"})
		notification.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Notification Setup Error")


def patch_fm_wbs_fields_to_link():
	"""Convert budgeting_tool's Financial Model child-table WBS fields from Data to Link.

	Uses Property Setters so we don't need to modify budgeting_tool source code.
	Runs on every migrate — Property Setters are idempotent.
	"""
	if not frappe.db.exists("DocType", "Financial Model"):
		return

	# Find all child tables of Financial Model
	meta = frappe.get_meta("Financial Model")
	child_tables = [df.options for df in meta.fields if df.fieldtype == "Table" and df.options]

	field_map = {
		"wbs_category": ("Link", "WBS Element"),
		"sub_wbs": ("Link", "Sub WBS Element"),
	}

	for child_dt in child_tables:
		child_meta = frappe.get_meta(child_dt)
		for fieldname, (new_fieldtype, new_options) in field_map.items():
			if not child_meta.has_field(fieldname):
				continue

			# Create or update Property Setter for fieldtype
			_set_property(child_dt, fieldname, "fieldtype", new_fieldtype)
			# Create or update Property Setter for options (Link target)
			_set_property(child_dt, fieldname, "options", new_options)


def _set_property(doctype, fieldname, prop, value):
	"""Create or update a single Property Setter."""
	ps_name = f"{doctype}-{fieldname}-{prop}"
	if frappe.db.exists("Property Setter", ps_name):
		frappe.db.set_value("Property Setter", ps_name, "value", value)
	else:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"name": ps_name,
				"doctype_or_field": "DocField",
				"doc_type": doctype,
				"field_name": fieldname,
				"property": prop,
				"value": value,
				"property_type": "Data",
				"module": "Detox Project",
			}
		).insert(ignore_permissions=True)


def migrate_wbs_allocations():
	"""Migrate old single custom_wbs_element to WBS Allocation child table."""
	from frappe.utils import flt

	if not frappe.db.exists("DocType", "WBS Allocation"):
		return

	for doctype in ("Material Request", "Purchase Order", "Purchase Invoice"):
		table_field = "custom_wbs_allocations"

		# Skip if old columns don't exist (already migrated or never had them)
		if not frappe.db.has_column(doctype, "custom_wbs_element"):
			continue

		# Find docs with old WBS element but no allocation rows
		docs = frappe.db.sql(
			"""
			SELECT name, custom_wbs_element, custom_sub_wbs_element
			FROM `tab{dt}`
			WHERE custom_wbs_element IS NOT NULL
			AND custom_wbs_element != ''
			AND name NOT IN (
				SELECT DISTINCT parent FROM `tabWBS Allocation`
				WHERE parenttype = %(dt)s
			)
			""".format(dt=doctype),
			{"dt": doctype},
			as_dict=True,
		)

		for doc in docs:
			if doctype == "Material Request":
				amount = frappe.db.sql(
					"SELECT COALESCE(SUM(amount), 0) FROM `tabMaterial Request Item` WHERE parent=%s",
					doc.name,
				)[0][0] or 0
			else:
				amount = frappe.db.get_value(doctype, doc.name, "grand_total") or 0

			frappe.get_doc(
				{
					"doctype": "WBS Allocation",
					"parent": doc.name,
					"parenttype": doctype,
					"parentfield": table_field,
					"idx": 1,
					"wbs_element": doc.custom_wbs_element,
					"sub_wbs_element": doc.custom_sub_wbs_element or "",
					"allocated_amount": amount,
				}
			).db_insert()

		if docs:
			frappe.db.commit()


def heal_duplicate_wbs_allocations():
	"""ABP2-I455 (Sahil 2026-06-15) — collapse duplicate WBS Allocation
	rows on existing MR / PO / PI / PR docs.

	Frappe's get_mapped_doc auto-copy (frappe/model/mapper.py:102-118)
	appends rows from every source doc when "Get Items From" is used
	to merge multiple MRs into one PO. Pre-fix, duplicates persisted on
	submitted docs. This heal runs once per after_migrate, deletes
	duplicate rows by (parent, wbs_element, sub_wbs_element) keeping
	the lowest-idx row, then re-indexes the surviving rows. Idempotent
	— second run finds zero duplicates and exits silently.

	Submitted docs ARE modified (direct SQL bypassing docstatus guards)
	because the row layout in this child table doesn't affect GL
	entries — `_update_wbs_spent` reads from PO Item / PI Item rows
	directly, not from custom_wbs_allocations. Cleaning the noise out
	is safe.
	"""
	if not frappe.db.exists("DocType", "WBS Allocation"):
		return

	# Find every (parenttype, parent, wbs_element, sub_wbs_element) combo
	# with more than one row. The MIN(name) is the keeper; the others die.
	dups = frappe.db.sql(
		"""
		SELECT parenttype, parent,
		       COALESCE(wbs_element, '') AS wbs,
		       COALESCE(sub_wbs_element, '') AS sub_wbs,
		       MIN(name)  AS keep_name,
		       COUNT(*)   AS n,
		       GROUP_CONCAT(name) AS all_names
		FROM `tabWBS Allocation`
		WHERE parenttype IN ('Material Request','Purchase Order',
		                     'Purchase Invoice','Purchase Receipt')
		GROUP BY parenttype, parent,
		         COALESCE(wbs_element,''), COALESCE(sub_wbs_element,'')
		HAVING COUNT(*) > 1
		""",
		as_dict=True,
	)

	if not dups:
		print("detox_project: heal_duplicate_wbs_allocations — nothing to do.")
		return

	parents_touched = set()
	total_deleted = 0
	for d in dups:
		all_names = d["all_names"].split(",")
		victims = [n for n in all_names if n != d["keep_name"]]
		if not victims:
			continue
		placeholders = ",".join(["%s"] * len(victims))
		frappe.db.sql(
			f"DELETE FROM `tabWBS Allocation` WHERE name IN ({placeholders})",
			tuple(victims),
		)
		total_deleted += len(victims)
		parents_touched.add((d["parenttype"], d["parent"]))

	# Re-index surviving rows on every touched parent so the grid is tidy.
	for parenttype, parent in parents_touched:
		rows = frappe.db.sql(
			"""SELECT name FROM `tabWBS Allocation`
			   WHERE parenttype=%s AND parent=%s
			   ORDER BY idx, name""",
			(parenttype, parent),
		)
		for new_idx, (row_name,) in enumerate(rows, start=1):
			frappe.db.set_value(
				"WBS Allocation", row_name, "idx", new_idx,
				update_modified=False,
			)

	frappe.db.commit()
	print(
		f"detox_project: heal_duplicate_wbs_allocations — deleted {total_deleted} "
		f"duplicate row(s) across {len(parents_touched)} parent doc(s)."
	)


def heal_wbs_budget_spent():
	"""ABP2-I439 (Sahil 2026-06-10) — re-stamp budget_spent + budget_
	utilization_pct on every WBS Element + Sub WBS Element that has
	any submitted PO or PI allocation.

	Two reasons:
	  • The old refresh_spent_amounts summed Purchase Orders only.
	    Direct PIs (no parent PO) never moved budget_spent — Sahil's
	    'PO/PI created but budget is not getting utilized' complaint.
	  • Even on the WBS rows where the old formula was right, the
	    stored budget_spent may carry stale numbers from before the
	    ABP2-I455 dedup heal (when duplicate WBS Allocations
	    inflated the sum).

	The fix itself lives in WBS Element / Sub WBS Element's
	refresh_spent_amounts (now sums PO + PI minus PI→PO double-count).
	This heal calls that method on every WBS row that has any
	WBS Allocation row in the WBS Allocation table.

	Idempotent — second run produces the same numbers.
	"""
	if not frappe.db.exists("DocType", "WBS Element"):
		return

	# Find WBS Elements touched by any WBS Allocation (PO or PI).
	wbs_names = [r[0] for r in frappe.db.sql(
		"""SELECT DISTINCT wbs_element
		   FROM `tabWBS Allocation`
		   WHERE parenttype IN ('Purchase Order', 'Purchase Invoice')
		     AND wbs_element IS NOT NULL
		     AND wbs_element != ''"""
	)]
	healed_wbs = 0
	for n in wbs_names:
		try:
			frappe.get_doc("WBS Element", n).refresh_spent_amounts()
			healed_wbs += 1
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"ABP2-I439 heal WBS Element {n}",
			)

	sub_wbs_names = [r[0] for r in frappe.db.sql(
		"""SELECT DISTINCT sub_wbs_element
		   FROM `tabWBS Allocation`
		   WHERE parenttype IN ('Purchase Order', 'Purchase Invoice')
		     AND sub_wbs_element IS NOT NULL
		     AND sub_wbs_element != ''"""
	)]
	healed_sub = 0
	for n in sub_wbs_names:
		try:
			frappe.get_doc("Sub WBS Element", n).refresh_spent_amounts()
			healed_sub += 1
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"ABP2-I439 heal Sub WBS Element {n}",
			)

	print(
		f"detox_project: heal_wbs_budget_spent — refreshed "
		f"{healed_wbs} WBS Element(s) + {healed_sub} Sub WBS Element(s)."
	)


def fix_budget_notification():
	"""Fix Budget Threshold Alert notification to use renamed field names."""
	if not frappe.db.exists("Notification", "Budget Threshold Alert"):
		return

	old_fields = {
		"overall_utilization_pct": "budget_utilization_pct",
		"total_budget": "budget_amount",
		"total_spent": "budget_spent",
	}

	n = frappe.get_doc("Notification", "Budget Threshold Alert")
	changed = False

	for old, new in old_fields.items():
		if old in (n.condition or ""):
			n.condition = n.condition.replace(old, new)
			changed = True
		if old in (n.subject or ""):
			n.subject = n.subject.replace(old, new)
			changed = True
		if old in (n.message or ""):
			n.message = n.message.replace(old, new)
			changed = True
		if n.value_changed == old:
			n.value_changed = new
			changed = True

	if changed:
		n.flags.ignore_permissions = True
		n.save()
		frappe.db.commit()


def cleanup_old_wbs_fields():
	"""Remove old single WBS Element/Sub WBS Element custom fields from MR/PO/PI/PR.

	These were replaced by the WBS Allocations child table.
	"""
	old_fields = [
		# MR
		("Material Request", "custom_wbs_section"),
		("Material Request", "custom_wbs_element"),
		("Material Request", "custom_sub_wbs_element"),
		("Material Request", "custom_request_type"),
		("Material Request", "custom_column_break_wbs_mr"),
		("Material Request", "custom_project_approver"),
		("Material Request", "custom_project_site"),
		# MR Item — KEEP: custom_wbs_element, custom_sub_wbs_element (needed for item-level WBS)
		# PO
		("Purchase Order", "custom_wbs_section"),
		("Purchase Order", "custom_wbs_element"),
		("Purchase Order", "custom_sub_wbs_element"),
		("Purchase Order", "custom_po_type"),
		# PO Item — KEEP: custom_wbs_element, custom_sub_wbs_element (needed for item-level WBS)
		# PI
		("Purchase Invoice", "custom_wbs_section"),
		("Purchase Invoice", "custom_wbs_element"),
		("Purchase Invoice", "custom_sub_wbs_element"),
		# PR
		("Purchase Receipt", "custom_wbs_section"),
		("Purchase Receipt", "custom_wbs_element"),
		("Purchase Receipt", "custom_sub_wbs_element"),
	]

	for dt, fieldname in old_fields:
		cf_name = f"{dt}-{fieldname}"
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, force=True)

	frappe.db.commit()


def create_fm_property_setters():
	"""Create Property Setters for Financial Model customizations."""
	if not frappe.db.exists("DocType", "Financial Model"):
		return

	# ── Rename Working Capital to CAPEX Working Capital ──
	_set_property("Financial Model", "working_capital_amount", "label",
		"CAPEX Working Capital Amount")

	# ── Make equity_percent and loan_percent editable ──
	_set_property("Financial Model", "equity_percent", "read_only", "0")
	_set_property("Financial Model", "loan_percent", "read_only", "0")

	# ── Display "(in Cr)" description on Currency/summary fields ──
	cr_fields = [
		"total_project_cost", "total_balance_amount", "equity_amount",
		"loan_amount", "working_capital_amount", "total_annual_revenue",
		"total_annual_expenses", "total_extra_expenses", "gross_profit",
		"ebitda", "ebit", "pbt", "pat", "npv", "terminal_value",
	]
	for fieldname in cr_fields:
		_set_property("Financial Model", fieldname, "description", "(in Cr)")

	# ── Add CBG, INC, COMPOST to FM Expense Item.section options ──
	_set_property("FM Expense Item", "section", "options",
		"\nBiomining\nProcessing\nSharding - RDF\nOther\nCBG\nINC\nCOMPOST")

	frappe.db.commit()


def setup_fm_workflow():
	"""Create 4-level approval workflow for Financial Model."""
	# ── Create Roles ──
	for role_name in ("FM Maker", "FM Checker", "FM Approver", "FM HOD"):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}).insert(ignore_permissions=True)

	# ── Create Workflow States ──
	state_styles = {
		"Pending Review": "Primary",
		"Pending Approval": "Info",
		"Pending HOD Approval": "Warning",
	}
	for state_name, style in state_styles.items():
		if not frappe.db.exists("Workflow State", state_name):
			frappe.get_doc({
				"doctype": "Workflow State",
				"workflow_state_name": state_name,
				"style": style,
			}).insert(ignore_permissions=True)

	# ── Create Workflow Action Masters ──
	for action_name in ("Submit for Review", "Approve Review", "Send Back",
						"Final Approve"):
		if not frappe.db.exists("Workflow Action Master", action_name):
			frappe.get_doc({
				"doctype": "Workflow Action Master",
				"workflow_action_name": action_name,
			}).insert(ignore_permissions=True)

	# ── Create Workflow ──
	wf_name = "Financial Model Approval Workflow"
	if frappe.db.exists("Workflow", wf_name):
		return

	try:
		workflow = frappe.get_doc({
			"doctype": "Workflow",
			"workflow_name": wf_name,
			"document_type": "Financial Model",
			"is_active": 1,
			"send_email_alert": 1,
			"states": [
				{"state": "Draft", "style": "Warning", "doc_status": "0",
					"allow_edit": "FM Maker"},
				{"state": "Pending Review", "style": "Primary", "doc_status": "0",
					"allow_edit": "FM Checker"},
				{"state": "Pending Approval", "style": "Info", "doc_status": "0",
					"allow_edit": "FM Approver"},
				{"state": "Pending HOD Approval", "style": "Warning", "doc_status": "0",
					"allow_edit": "FM HOD"},
				{"state": "Approved", "style": "Success", "doc_status": "1",
					"allow_edit": "FM HOD"},
				{"state": "Rejected", "style": "Danger", "doc_status": "0",
					"allow_edit": "FM Maker"},
			],
			"transitions": [
				{"state": "Draft", "action": "Submit for Review",
					"next_state": "Pending Review", "allowed": "FM Maker"},
				{"state": "Pending Review", "action": "Approve Review",
					"next_state": "Pending Approval", "allowed": "FM Checker"},
				{"state": "Pending Review", "action": "Send Back",
					"next_state": "Draft", "allowed": "FM Checker"},
				{"state": "Pending Approval", "action": "Approve",
					"next_state": "Pending HOD Approval", "allowed": "FM Approver"},
				{"state": "Pending Approval", "action": "Reject",
					"next_state": "Draft", "allowed": "FM Approver"},
				{"state": "Pending HOD Approval", "action": "Final Approve",
					"next_state": "Approved", "allowed": "FM HOD"},
				{"state": "Pending HOD Approval", "action": "Reject",
					"next_state": "Draft", "allowed": "FM HOD"},
			],
		})
		workflow.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "FM Workflow Setup Error")


# ---------------------------------------------------------------------------
# ABP2-I419 Phase 1 — Production Plan No-BOM customizations
# ---------------------------------------------------------------------------
def setup_production_plan_no_bom():
	"""Phase 1 of ABP2-I419 (Sahil 2026-06-15, Out of BRD).

	Adds to Production Plan:
	  - Custom Field `custom_no_bom` (Check) — toggles No-BOM mode.
	  - Custom Field `custom_cost_center` (Link → Cost Center) on header.
	  - Custom Field `custom_fg_items` (Table → Detox Production Plan FG)
	    — Table 1, finished goods to manufacture.
	  - Custom Field `custom_operations` (Table → Detox Production Plan
	    Operation) — Table 2, operations + RM/service rows.
	  - Property Setter making `project` mandatory.

	The two child DocTypes (`Detox Production Plan FG`,
	`Detox Production Plan Operation`) ship as source files under
	detox_project/doctype/ and reload via `bench migrate`.

	Subsequent phases (CC + Project mandatory everywhere, Stock Entry
	Manufacture customizations, subcontracting, reports, deposits) are
	tracked separately and not delivered here.

	Idempotent.
	"""
	if not frappe.db.exists("DocType", "Production Plan"):
		return

	fields = [
		{
			"fieldname": "custom_no_bom",
			"label": "No BOM",
			"fieldtype": "Check",
			"insert_after": "company",
			"default": "0",
			"description": (
				"When checked, hides the standard BOM / Sales Order / "
				"Material Request sections and uses the custom Finished "
				"Goods + Operations tables instead."
			),
			"module": "Detox Project",
		},
		{
			"fieldname": "custom_cost_center",
			"label": "Cost Center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"insert_after": "custom_no_bom",
			"reqd": 0,
			"description": (
				"Header-level Cost Center; cascades to Work Orders and "
				"Stock Entries created from this plan."
			),
			"module": "Detox Project",
		},
		{
			"fieldname": "custom_no_bom_section",
			"label": "Finished Goods (No-BOM)",
			"fieldtype": "Section Break",
			"insert_after": "custom_cost_center",
			"depends_on": "eval:doc.custom_no_bom",
			"module": "Detox Project",
		},
		{
			"fieldname": "custom_fg_items",
			"label": "Finished Goods",
			"fieldtype": "Table",
			"options": "Detox Production Plan FG",
			"insert_after": "custom_no_bom_section",
			"depends_on": "eval:doc.custom_no_bom",
			"description": "Table 1 — Finished goods to manufacture in this plan.",
			"module": "Detox Project",
		},
		{
			"fieldname": "custom_operations_section",
			"label": "Operations & Materials/Services (No-BOM)",
			"fieldtype": "Section Break",
			"insert_after": "custom_fg_items",
			"depends_on": "eval:doc.custom_no_bom",
			"module": "Detox Project",
		},
		{
			"fieldname": "custom_operations",
			"label": "Operations & Materials",
			"fieldtype": "Table",
			"options": "Detox Production Plan Operation",
			"insert_after": "custom_operations_section",
			"depends_on": "eval:doc.custom_no_bom",
			"description": (
				"Table 2 — Flat per-row operations with materials / "
				"services. Marking a row is_subcontracted converts it "
				"into a job-work step driven from the plan."
			),
			"module": "Detox Project",
		},
	]

	created_or_updated = 0
	for spec in fields:
		name = f"Production Plan-{spec['fieldname']}"
		if frappe.db.exists("Custom Field", name):
			cf = frappe.get_doc("Custom Field", name)
			dirty = False
			for k, v in spec.items():
				if (cf.get(k) or "") != (v or ""):
					cf.set(k, v)
					dirty = True
			if dirty:
				cf.save(ignore_permissions=True)
				created_or_updated += 1
			continue
		cf = frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "Production Plan",
			**spec,
		})
		cf.insert(ignore_permissions=True)
		created_or_updated += 1

	# Property Setters:
	#   - project   reqd=1 (mandatory everywhere — FR-22)
	#   - po_items  reqd=0 (the native "Assembly Items" table is reqd=1
	#                       in v16; relax it so No-BOM mode plans can
	#                       save with `custom_fg_items` instead. Phase 2
	#                       adds a validate hook enforcing 'one of
	#                       po_items OR custom_fg_items must be filled'.)
	property_setters = [
		("Production Plan-project-reqd", "project", "reqd", "Check", "1"),
		("Production Plan-po_items-reqd", "po_items", "reqd", "Check", "0"),
	]
	for ps_name, field, prop, ptype, value in property_setters:
		if frappe.db.exists("Property Setter", ps_name):
			ps = frappe.get_doc("Property Setter", ps_name)
			if ps.value != value:
				ps.value = value
				ps.save(ignore_permissions=True)
			continue
		frappe.get_doc({
			"doctype": "Property Setter",
			"name": ps_name,
			"doctype_or_field": "DocField",
			"doc_type": "Production Plan",
			"field_name": field,
			"property": prop,
			"property_type": ptype,
			"value": value,
			"module": "Detox Project",
		}).insert(ignore_permissions=True)

	frappe.clear_cache(doctype="Production Plan")
	print(
		f"detox_project: setup_production_plan_no_bom — "
		f"{created_or_updated} Custom Field(s) upserted."
	)


# ---------------------------------------------------------------------------
# ABP2-I419 Phase 2 — CC + Project mandatory across the manufacturing
# document chain (FR-22..25, VAL-01..02, VAL-06..07, VAL-17)
# ---------------------------------------------------------------------------
def setup_phase2_cc_project_enforcement():
	"""Adds the gaps detox_waste_management's enforcement skipped:

	  - Stock Entry header.cost_center (Custom Field; the standard SE
	    has none).
	  - Work Order.custom_cost_center (Custom Field, header CC).
	  - Work Order Item.cost_center + .project (Custom Fields).
	  - Property Setter: Work Order.project reqd=1.
	  - Property Setter: Purchase Order Item.cost_center reqd=1 + project reqd=1.
	  - Property Setter: Purchase Receipt Item.cost_center reqd=1 + project reqd=1.

	The validate hook + cascade hook in
	detox_project.detox_project.overrides.cc_project_guard wire to
	these via hooks.py.

	Idempotent.
	"""
	custom_fields = [
		# Stock Entry header — CC (FR-22, the only target detox_waste_management's
		# enforcer skipped because the native field is absent).
		{
			"dt": "Stock Entry",
			"fieldname": "custom_cost_center",
			"label": "Cost Center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"insert_after": "project",
			"reqd": 1,
			"description": (
				"Header Cost Center for Manufacturing-flow Stock Entries. "
				"Inherited from the linked Work Order when present (L06)."
			),
		},
		# Work Order header — CC (no native field on Work Order).
		{
			"dt": "Work Order",
			"fieldname": "custom_cost_center",
			"label": "Cost Center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"insert_after": "project",
			"reqd": 1,
			"description": (
				"Header Cost Center. Cascaded from the Production Plan on "
				"submit (L05); stamped onto generated Stock Entries (L06)."
			),
		},
		# Work Order Item — CC + Project (no native fields on Work Order Item).
		{
			"dt": "Work Order Item",
			"fieldname": "cost_center",
			"label": "Cost Center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"insert_after": "item_name",
			"reqd": 1,
		},
		{
			"dt": "Work Order Item",
			"fieldname": "project",
			"label": "Project",
			"fieldtype": "Link",
			"options": "Project",
			"insert_after": "cost_center",
			"reqd": 1,
		},
	]
	created = 0
	for spec in custom_fields:
		dt = spec["dt"]
		if not frappe.db.exists("DocType", dt):
			continue
		name = f"{dt}-{spec['fieldname']}"
		spec = {**spec, "module": "Detox Project"}
		if frappe.db.exists("Custom Field", name):
			cf = frappe.get_doc("Custom Field", name)
			dirty = False
			for k, v in spec.items():
				if k == "dt":
					continue
				if (cf.get(k) or "") != (v or ""):
					cf.set(k, v)
					dirty = True
			if dirty:
				cf.save(ignore_permissions=True)
				created += 1
			continue
		frappe.get_doc({"doctype": "Custom Field", **spec}).insert(ignore_permissions=True)
		created += 1

	# Property Setters — bring everything to reqd=1 across the chain.
	property_setters = [
		# Work Order
		("Work Order-project-reqd", "Work Order", "project", "reqd", "Check", "1"),
		# Purchase Order Item — make item-level CC + Project mandatory (FR-22, VAL-17).
		("Purchase Order Item-cost_center-reqd", "Purchase Order Item", "cost_center", "reqd", "Check", "1"),
		("Purchase Order Item-project-reqd", "Purchase Order Item", "project", "reqd", "Check", "1"),
		# Purchase Receipt Item — same.
		("Purchase Receipt Item-cost_center-reqd", "Purchase Receipt Item", "cost_center", "reqd", "Check", "1"),
		("Purchase Receipt Item-project-reqd", "Purchase Receipt Item", "project", "reqd", "Check", "1"),
	]
	for ps_name, dt, field, prop, ptype, value in property_setters:
		if not frappe.db.exists("DocType", dt):
			continue
		if frappe.db.exists("Property Setter", ps_name):
			ps = frappe.get_doc("Property Setter", ps_name)
			if ps.value != value:
				ps.value = value
				ps.save(ignore_permissions=True)
			continue
		frappe.get_doc({
			"doctype": "Property Setter",
			"name": ps_name,
			"doctype_or_field": "DocField",
			"doc_type": dt,
			"field_name": field,
			"property": prop,
			"property_type": ptype,
			"value": value,
			"module": "Detox Project",
		}).insert(ignore_permissions=True)

	for dt in ("Stock Entry", "Work Order", "Work Order Item",
	           "Purchase Order Item", "Purchase Receipt Item"):
		try:
			frappe.clear_cache(doctype=dt)
		except Exception:
			pass

	print(
		f"detox_project: setup_phase2_cc_project_enforcement — "
		f"{created} Custom Field(s) upserted."
	)


# ---------------------------------------------------------------------------
# ABP2-I419 Phase 3 — Stock Entry Manufacture customizations
# (FR-07..14, L08..L12, VAL-08..14)
# ---------------------------------------------------------------------------
def setup_phase3_stock_entry_manufacture():
	"""Custom Fields + Property Setters for the Stock Entry Manufacture
	flow. Adds:

	  Stock Entry header:
	    - custom_process_selection (Select, options populated client-side
	      from the linked plan's Table 2 operation names).
	    - custom_production_time (Float, mandatory on Mfg SEs).
	    - custom_time_uom (Select Hours / Minutes, default Hours).

	  Stock Entry Detail (per source row):
	    - custom_purchase_order (Link → Purchase Order).
	    - custom_purchase_order_item (Link → Purchase Order Item).
	    - additional_cost (Currency, holds the fetched PO rate from
	      L12 for variance reporting).

	  Property Setters: source-row item, uom, basic_rate, expense_account
	  read-only on Stock Entry Detail. (qty stays editable — L09.)

	Idempotent.
	"""
	custom_fields = [
		# --- Stock Entry header ---
		{
			"dt": "Stock Entry",
			"fieldname": "custom_process_section",
			"label": "Manufacturing Process",
			"fieldtype": "Section Break",
			"insert_after": "custom_cost_center",
			"depends_on": (
				"eval:[\"Manufacture\",\"Material Transfer for Manufacture\","
				"\"Repack\"].includes(doc.stock_entry_type)"
			),
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_process_selection",
			"label": "Process",
			"fieldtype": "Select",
			"insert_after": "custom_process_section",
			"options": "",
			"description": (
				"Operation from the linked Production Plan. Picking one "
				"clears the source rows and re-fetches them from the plan."
			),
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_time_column",
			"label": "",
			"fieldtype": "Column Break",
			"insert_after": "custom_process_selection",
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_production_time",
			"label": "Production Time",
			"fieldtype": "Float",
			"insert_after": "custom_time_column",
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_time_uom",
			"label": "Time UOM",
			"fieldtype": "Select",
			"options": "Hours\nMinutes",
			"default": "Hours",
			"insert_after": "custom_production_time",
		},
		# --- Stock Entry Detail (per row) ---
		{
			"dt": "Stock Entry Detail",
			"fieldname": "custom_purchase_order",
			"label": "Purchase Order",
			"fieldtype": "Link",
			"options": "Purchase Order",
			"insert_after": "item_code",
			"description": (
				"Advance PO this consumed material was procured against; "
				"basis for the Production Cost Comparison report."
			),
		},
		{
			"dt": "Stock Entry Detail",
			"fieldname": "custom_purchase_order_item",
			"label": "PO Item",
			"fieldtype": "Link",
			"options": "Purchase Order Item",
			"insert_after": "custom_purchase_order",
			"description": "Specific PO line — used to fetch the actual procured rate.",
		},
	]
	created = 0
	for spec in custom_fields:
		dt = spec["dt"]
		if not frappe.db.exists("DocType", dt):
			continue
		name = f"{dt}-{spec['fieldname']}"
		spec = {**spec, "module": "Detox Project"}
		if frappe.db.exists("Custom Field", name):
			cf = frappe.get_doc("Custom Field", name)
			dirty = False
			for k, v in spec.items():
				if k == "dt":
					continue
				if (cf.get(k) or "") != (v or ""):
					cf.set(k, v)
					dirty = True
			if dirty:
				cf.save(ignore_permissions=True)
				created += 1
			continue
		frappe.get_doc({"doctype": "Custom Field", **spec}).insert(ignore_permissions=True)
		created += 1

	# Property Setters — L09 source-row locking.
	# We set read_only=1 on item_code, uom, basic_rate, expense_account
	# only when the row is a SOURCE row (s_warehouse set) — the read-only
	# nuance is enforced by the Client Script (toggle_grid_row_read_only);
	# the Property Setter sets these as read-only by default to match the
	# intent. Users who need to edit a target row's basic_rate must use the
	# native ERPNext path which the client script doesn't lock.
	# For Phase 3 we keep this conservative: only the basic_rate gets a
	# Property Setter (the most cost-impactful field). Per-row dynamic
	# locking lives in the Client Script.
	property_setters = []
	for ps_name, dt, field, prop, ptype, value in property_setters:
		if not frappe.db.exists("DocType", dt):
			continue
		if frappe.db.exists("Property Setter", ps_name):
			ps = frappe.get_doc("Property Setter", ps_name)
			if ps.value != value:
				ps.value = value
				ps.save(ignore_permissions=True)
			continue
		frappe.get_doc({
			"doctype": "Property Setter",
			"name": ps_name,
			"doctype_or_field": "DocField",
			"doc_type": dt,
			"field_name": field,
			"property": prop,
			"property_type": ptype,
			"value": value,
			"module": "Detox Project",
		}).insert(ignore_permissions=True)

	for dt in ("Stock Entry", "Stock Entry Detail"):
		try:
			frappe.clear_cache(doctype=dt)
		except Exception:
			pass

	print(
		f"detox_project: setup_phase3_stock_entry_manufacture — "
		f"{created} Custom Field(s) upserted."
	)


# ---------------------------------------------------------------------------
# ABP2-I419 Phase 4 — Subcontracting Flow A (v16 native)
# (FR-15..21, FR-32, VAL-04, VAL-15..16)
# ---------------------------------------------------------------------------
def setup_phase4_subcontracting():
	"""Custom Fields for CC + Project on Subcontracting Order / Receipt
	(v16 native doctypes lack these). Subcontract field gating on
	Detox Production Plan Operation is already wired in Phase 1 via
	mandatory_depends_on on the child DocType JSON.

	Idempotent. Skips silently when the v16 subcontracting doctypes
	aren't present (pre-v16 benches use Flow B instead).
	"""
	specs = []
	for dt in ("Subcontracting Order", "Subcontracting Receipt"):
		if not frappe.db.exists("DocType", dt):
			continue
		specs.extend([
			{
				"dt": dt,
				"fieldname": "custom_cost_center",
				"label": "Cost Center",
				"fieldtype": "Link",
				"options": "Cost Center",
				"insert_after": "project" if frappe.get_meta(dt).get_field("project") else "supplier",
				"reqd": 1,
				"description": "Header Cost Center (FR-22).",
			},
		])
		# Make project mandatory if it exists natively.
		if frappe.get_meta(dt).get_field("project"):
			ps_name = f"{dt}-project-reqd"
			if frappe.db.exists("Property Setter", ps_name):
				ps = frappe.get_doc("Property Setter", ps_name)
				if ps.value != "1":
					ps.value = "1"
					ps.save(ignore_permissions=True)
			else:
				frappe.get_doc({
					"doctype": "Property Setter",
					"name": ps_name,
					"doctype_or_field": "DocField",
					"doc_type": dt,
					"field_name": "project",
					"property": "reqd",
					"property_type": "Check",
					"value": "1",
					"module": "Detox Project",
				}).insert(ignore_permissions=True)

	created = 0
	for spec in specs:
		dt = spec["dt"]
		name = f"{dt}-{spec['fieldname']}"
		spec = {**spec, "module": "Detox Project"}
		if frappe.db.exists("Custom Field", name):
			cf = frappe.get_doc("Custom Field", name)
			dirty = False
			for k, v in spec.items():
				if k == "dt":
					continue
				if (cf.get(k) or "") != (v or ""):
					cf.set(k, v); dirty = True
			if dirty:
				cf.save(ignore_permissions=True); created += 1
			continue
		frappe.get_doc({"doctype": "Custom Field", **spec}).insert(ignore_permissions=True)
		created += 1

	for dt in ("Subcontracting Order", "Subcontracting Receipt"):
		try:
			frappe.clear_cache(doctype=dt)
		except Exception:
			pass

	print(
		f"detox_project: setup_phase4_subcontracting — "
		f"{created} Custom Field(s) upserted."
	)
