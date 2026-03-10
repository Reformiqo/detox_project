import frappe
from frappe import _
from frappe.utils import cint, flt, today


def on_update(doc, method):
	"""Detect workflow state changes on Tender Management."""
	old_doc = doc.get_doc_before_save()
	if not old_doc:
		return

	old_ws = (old_doc.get("workflow_state") or old_doc.get("status") or "").strip()
	new_ws = (doc.get("workflow_state") or doc.get("status") or "").strip()

	if old_ws == new_ws:
		return

	if new_ws == "Awarded":
		if not doc.get("custom_linked_project"):
			_create_project_from_tender(doc)
	elif new_ws in ("Lost", "Rejected"):
		_cancel_project_cascade(doc, reason=f"Tender {new_ws}")
	elif new_ws == "Tender Closed":
		_complete_project(doc)


def before_cancel(doc, method):
	_cancel_project_cascade(doc, reason="Tender Cancelled (Amended)")


def _create_project_from_tender(doc):
	"""Create a fully-linked ERPNext Project from Tender data."""
	existing = frappe.db.get_value("Project", {"custom_tender_management": doc.name}, "name")
	if existing:
		frappe.msgprint(
			_("Project <b>{0}</b> already exists for this Tender.").format(existing), indicator="blue"
		)
		return

	project = frappe.new_doc("Project")

	# Core fields
	project.project_name = doc.get("project_name") or doc.get("tender_name") or doc.name
	project.company = _get_company_from_tender(doc)
	project.status = "Open"
	project.is_active = "Yes"
	project.project_type = _map_tender_to_project_type(doc)

	# Duration
	duration_months = cint(doc.get("project_duration_in_months")) or 0
	om_months = cint(doc.get("o_and_m_period_in_months")) or 0
	total_months = duration_months + om_months

	if doc.get("award_date"):
		project.expected_start_date = doc.award_date
		if total_months:
			project.expected_end_date = frappe.utils.add_months(doc.award_date, total_months)

	# Scope
	scope = doc.get("scope_of_project") or ""
	project.notes = f"Auto-created from Tender: {doc.name}\n\nScope: {scope}"

	# Custom fields
	project.custom_project_definition = scope
	project.custom_project_site = doc.get("site_address") or ""
	project.custom_project_profile = _map_scope_to_profile(doc)
	project.custom_project_classification = "External"

	# Tender linkage (NEW proper Link fields)
	project.custom_tender_management = doc.name
	project.custom_tender_number = doc.get("tender_number") or ""
	project.custom_tender_type = doc.get("tender_type") or ""
	project.custom_tender_site_address = doc.get("site_address") or ""
	project.custom_tender_award_date = doc.get("award_date")
	project.custom_estimated_project_cost_tender = flt(doc.get("estimated_project_cost"))
	project.custom_capital_cost_tender = flt(doc.get("capital_cost"))
	project.custom_o_and_m_cost_tender = flt(doc.get("o_and_m_cost"))
	project.custom_emd_amount = flt(doc.get("emd_amount"))
	project.custom_performance_security_amt = flt(doc.get("performance_security_amt"))
	project.custom_project_duration_months = duration_months
	project.custom_o_and_m_period_months = om_months

	# Budget from tender costs
	project.custom_total_budget = flt(doc.get("capital_cost")) + flt(doc.get("o_and_m_cost"))

	# Legacy fields (backward compat)
	project.custom_tender = doc.name
	project.custom_tender_name = doc.get("tender_name") or doc.get("project_name") or doc.name
	project.custom_client_name = doc.get("client") or doc.get("customer") or ""
	project.custom_tender_value = flt(doc.get("estimated_project_cost") or doc.get("tender_value"))

	project.flags.from_tender = True
	project.insert(ignore_permissions=True)

	# Back-link on Tender
	frappe.db.set_value(
		doc.doctype,
		doc.name,
		{
			"custom_linked_project": project.name,
			"custom_project_status": "Open",
		},
		update_modified=False,
	)

	frappe.msgprint(
		_("Project <b><a href='/app/project/{0}'>{0}</a></b> created from Tender.").format(project.name),
		indicator="green",
		title=_("Project Created"),
	)


def _cancel_project_cascade(doc, reason=""):
	"""Cancel Project + cascade to FM/PBP/WBS/Sub-WBS."""
	project_name = doc.get("custom_linked_project")
	if not project_name or not frappe.db.exists("Project", project_name):
		return

	# Step 1: Cancel submitted Financial Models (budgeting_tool app) with cascade flag
	if frappe.db.exists("DocType", "Financial Model"):
		fms = frappe.get_all(
			"Financial Model", filters={"project": project_name, "docstatus": 1}, pluck="name"
		)
		for fm_name in fms:
			try:
				fm_doc = frappe.get_doc("Financial Model", fm_name)
				fm_doc.flags.from_cascade = True
				fm_doc.cancel()
			except Exception as e:
				frappe.log_error(title=f"Cascade Cancel FM Error - {fm_name}", message=str(e))

	# Step 2: Cancel Budget Plans (budgeting_tool app) with cascade flag
	if frappe.db.exists("DocType", "Project Budget Plan"):
		pbps = frappe.get_all(
			"Project Budget Plan", filters={"project": project_name, "docstatus": 1}, pluck="name"
		)
		for pbp_name in pbps:
			try:
				pbp_doc = frappe.get_doc("Project Budget Plan", pbp_name)
				pbp_doc.flags.from_cascade = True
				pbp_doc.cancel()
			except Exception as e:
				frappe.log_error(title=f"Cascade Cancel PBP Error - {pbp_name}", message=str(e))

	# Step 3: Cancel WBS Elements
	for wbs_name in frappe.get_all(
		"WBS Element", filters={"project": project_name, "status": ["!=", "Cancelled"]}, pluck="name"
	):
		frappe.db.set_value("WBS Element", wbs_name, "status", "Cancelled", update_modified=True)

	# Step 4: Cancel Sub WBS Elements
	for sub_name in frappe.get_all(
		"Sub WBS Element", filters={"project": project_name, "status": ["!=", "Cancelled"]}, pluck="name"
	):
		frappe.db.set_value("Sub WBS Element", sub_name, "status", "Cancelled", update_modified=True)

	# Step 5: Set Project status
	frappe.db.set_value(
		"Project",
		project_name,
		{
			"status": "Cancelled",
			"custom_cancellation_reason": reason,
			"custom_cancellation_date": today(),
			"custom_cancelled_date": today(),
		},
		update_modified=True,
	)

	# Step 6: Update Tender tracking
	frappe.db.set_value(doc.doctype, doc.name, "custom_project_status", "Cancelled", update_modified=False)

	frappe.msgprint(
		_("Project <b>{0}</b> and all linked documents cancelled.").format(project_name),
		indicator="orange",
		title=_("Cascade Cancel Complete"),
	)


def _complete_project(doc):
	project_name = doc.get("custom_linked_project")
	if not project_name or not frappe.db.exists("Project", project_name):
		return

	frappe.db.set_value("Project", project_name, "status", "Completed", update_modified=True)

	for wbs_name in frappe.get_all(
		"WBS Element", filters={"project": project_name, "status": "Active"}, pluck="name"
	):
		frappe.db.set_value("WBS Element", wbs_name, "status", "Completed")

	frappe.db.set_value(doc.doctype, doc.name, "custom_project_status", "Completed", update_modified=False)

	frappe.msgprint(_("Project <b>{0}</b> marked as Completed.").format(project_name), indicator="green")


def _get_company_from_tender(doc):
	company = doc.get("company")
	if company:
		return company
	companies = frappe.get_all("Company", filters={"is_group": 0}, limit=1, pluck="name")
	return companies[0] if companies else frappe.defaults.get_global_default("company")


def _map_tender_to_project_type(doc):
	scope = (doc.get("scope_of_project") or "").lower()
	if "epc" in scope and "o&m" in scope:
		return "EPC + O&M"
	elif "epc" in scope:
		return "EPC"
	elif "o&m" in scope or "operation" in scope:
		return "O&M"
	return "EPC"


def _map_scope_to_profile(doc):
	scope = (doc.get("scope_of_project") or "").lower()
	if "legacy" in scope or "biomining" in scope or "bio-remediation" in scope:
		return "Legacy Waste"
	elif "fresh" in scope:
		return "Fresh Waste"
	elif "cbg" in scope or "biogas" in scope:
		return "CBG"
	elif "waste water" in scope or "wastewater" in scope:
		return "Waste Water"
	elif "lab" in scope or "testing" in scope:
		return "Lab Testing"
	return ""


@frappe.whitelist()
def create_project_from_tender(tender_name):
	"""Manual project creation button on Tender form."""
	doc = frappe.get_doc("Tender Management", tender_name)
	existing = frappe.db.get_value("Project", {"custom_tender_management": tender_name}, "name")
	if existing:
		frappe.throw(_("Project <b>{0}</b> already exists for this Tender.").format(existing))
	_create_project_from_tender(doc)
	return doc.get("custom_linked_project")


@frappe.whitelist()
def cascade_cancel_project(project_name, reason="Manual Cancellation"):
	"""Manual cascade cancel from Project form."""
	tender_name = frappe.db.get_value("Project", project_name, "custom_tender_management")
	if tender_name and frappe.db.exists("Tender Management", tender_name):
		doc = frappe.get_doc("Tender Management", tender_name)
		_cancel_project_cascade(doc, reason=reason)
	else:
		# No tender linked — cancel directly
		if frappe.db.exists("DocType", "Financial Model"):
			for fm_name in frappe.get_all(
				"Financial Model", filters={"project": project_name, "docstatus": 1}, pluck="name"
			):
				try:
					fm_doc = frappe.get_doc("Financial Model", fm_name)
					fm_doc.flags.from_cascade = True
					fm_doc.cancel()
				except Exception as e:
					frappe.log_error(title=f"Cascade Cancel FM Error - {fm_name}", message=str(e))

		if frappe.db.exists("DocType", "Project Budget Plan"):
			for pbp_name in frappe.get_all(
				"Project Budget Plan", filters={"project": project_name, "docstatus": 1}, pluck="name"
			):
				try:
					pbp_doc = frappe.get_doc("Project Budget Plan", pbp_name)
					pbp_doc.flags.from_cascade = True
					pbp_doc.cancel()
				except Exception as e:
					frappe.log_error(title=f"Cascade Cancel PBP Error - {pbp_name}", message=str(e))

		for wbs_name in frappe.get_all(
			"WBS Element", filters={"project": project_name, "status": ["!=", "Cancelled"]}, pluck="name"
		):
			frappe.db.set_value("WBS Element", wbs_name, "status", "Cancelled")

		for sub_name in frappe.get_all(
			"Sub WBS Element", filters={"project": project_name, "status": ["!=", "Cancelled"]}, pluck="name"
		):
			frappe.db.set_value("Sub WBS Element", sub_name, "status", "Cancelled")

		frappe.db.set_value(
			"Project",
			project_name,
			{
				"status": "Cancelled",
				"custom_cancellation_reason": reason,
				"custom_cancellation_date": today(),
				"custom_cancelled_date": today(),
			},
			update_modified=True,
		)

	return "ok"
