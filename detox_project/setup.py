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
