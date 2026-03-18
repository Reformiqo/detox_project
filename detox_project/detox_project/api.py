import frappe
from frappe import _
from frappe.utils import flt

# ---------------------------------------------------------------------------
# Document Event Hooks
# ---------------------------------------------------------------------------


def validate_project(doc, method):
	"""Validate Project — budget calc, FM status sync, LOI check."""
	if doc.custom_total_budget and doc.custom_total_spent:
		doc.custom_budget_utilization_pct = doc.custom_total_spent / doc.custom_total_budget * 100
		doc.custom_budget_remaining = flt(doc.custom_total_budget) - flt(doc.custom_total_spent)
	# Sync Financial Model status (from budgeting_tool's FM)
	if doc.custom_financial_model:
		fm_data = frappe.db.get_value(
			"Financial Model",
			doc.custom_financial_model,
			["docstatus", "total_project_cost", "project_irr"],
			as_dict=True,
		)
		if fm_data:
			if fm_data.docstatus == 1:
				doc.custom_financial_model_status = "Approved"
			elif fm_data.docstatus == 2:
				doc.custom_financial_model_status = "Cancelled"
			else:
				doc.custom_financial_model_status = "Pending"
	# SEPPL LOI warning
	if doc.company and "SEPPL" in (doc.company or ""):
		if not doc.get("custom_loi_reference"):
			frappe.msgprint(
				_("LOI Reference is recommended for SEPPL projects."), indicator="orange", alert=True
			)


def on_project_update(doc, method):
	if doc.status == "Cancelled":
		wbs_elements = frappe.get_all(
			"WBS Element",
			filters={"project": doc.name, "status": ["!=", "Cancelled"]},
			pluck="name",
		)
		for wbs_name in wbs_elements:
			frappe.db.set_value("WBS Element", wbs_name, "status", "Cancelled")

	elif doc.status == "Completed":
		wbs_elements = frappe.get_all(
			"WBS Element",
			filters={"project": doc.name, "status": "Active"},
			pluck="name",
		)
		for wbs_name in wbs_elements:
			frappe.db.set_value("WBS Element", wbs_name, "status", "Completed")


def validate_material_request_budget(doc, method):
	"""HARD block: MR amount must not exceed WBS remaining budget."""
	if not doc.custom_wbs_element:
		return

	wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
	if not wbs.budget_amount:
		return

	mr_total = sum(flt(item.amount) for item in doc.items)
	budget = flt(wbs.budget_amount)
	spent = flt(wbs.budget_spent)
	remaining = budget - spent

	# HARD BLOCK if MR exceeds remaining budget
	if mr_total > remaining and budget > 0:
		frappe.throw(
			_(
				"BUDGET EXCEEDED: This Request ({0}) exceeds remaining WBS '{1}' "
				"budget of {2}.\n\n"
				"Budget: {3} | Already Spent: {4} | Remaining: {2}\n\n"
				"Please revise the request amount or get a budget increase approved."
			).format(
				frappe.format_value(mr_total, {"fieldtype": "Currency"}),
				wbs.wbs_name,
				frappe.format_value(remaining, {"fieldtype": "Currency"}),
				frappe.format_value(budget, {"fieldtype": "Currency"}),
				frappe.format_value(spent, {"fieldtype": "Currency"}),
			),
			title=_("Budget Limit Exceeded"),
		)

	# Warning at 80% (still allows save)
	new_total = spent + mr_total
	if budget > 0:
		new_pct = new_total / budget * 100
		if new_pct >= 80 and mr_total <= remaining:
			frappe.msgprint(
				_("This Request will bring WBS '{0}' budget to {1}% utilization.").format(
					wbs.wbs_name, f"{new_pct:.1f}"
				),
				indicator="orange",
				title=_("Budget Warning"),
			)


def validate_po_budget(doc, method):
	"""HARD block: PO amount must not exceed WBS remaining budget."""
	if not doc.custom_wbs_element:
		return

	wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
	if not wbs.budget_amount:
		return

	po_total = flt(doc.grand_total)
	budget = flt(wbs.budget_amount)
	spent = flt(wbs.budget_spent)
	remaining = budget - spent

	if po_total > remaining and budget > 0:
		frappe.throw(
			_(
				"BUDGET EXCEEDED: This PO ({0}) exceeds remaining WBS '{1}' "
				"budget of {2}.\n\n"
				"Budget: {3} | Already Spent: {4} | Remaining: {2}\n\n"
				"Please revise the PO amount or request a budget increase."
			).format(
				frappe.format_value(po_total, {"fieldtype": "Currency"}),
				wbs.wbs_name,
				frappe.format_value(remaining, {"fieldtype": "Currency"}),
				frappe.format_value(budget, {"fieldtype": "Currency"}),
				frappe.format_value(spent, {"fieldtype": "Currency"}),
			),
			title=_("Budget Limit Exceeded"),
		)

	# Warning at 80%
	new_total = spent + po_total
	if budget > 0:
		new_pct = new_total / budget * 100
		if new_pct >= 80 and po_total <= remaining:
			frappe.msgprint(
				_("This PO will bring WBS '{0}' budget to {1}% utilization.").format(
					wbs.wbs_name, f"{new_pct:.1f}"
				),
				indicator="orange",
				title=_("Budget Warning"),
			)


def on_po_submit(doc, method):
	_update_wbs_spent(doc)


def on_pi_submit(doc, method):
	if not doc.custom_wbs_element:
		return
	try:
		wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
		wbs.refresh_spent_amounts()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "WBS PI Submit Update Error")


# ---------------------------------------------------------------------------
# Whitelisted APIs
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_project_from_model(financial_model):
	"""Create a Project from budgeting_tool's Financial Model."""
	fm = frappe.get_doc("Financial Model", financial_model)
	if fm.docstatus != 1:
		frappe.throw(_("Financial Model must be submitted first"))
	if fm.project:
		frappe.throw(_("Financial Model is already linked to Project {0}").format(fm.project))

	project = frappe.new_doc("Project")
	project.project_name = fm.title or fm.name
	project.company = fm.company
	project.custom_financial_model = fm.name
	project.custom_total_budget = flt(fm.total_project_cost)
	project.status = "Open"

	type_map = {
		"Legacy Waste": "EPC",
		"Fresh Waste": "EPC",
		"Waste Water": "EPC",
		"CBG": "EPC",
		"Lab Testing": "O&M",
	}
	if fm.get("model_type"):
		project.project_type = type_map.get(fm.model_type, "EPC")
		project.custom_project_profile = fm.model_type

	project.insert(ignore_permissions=True)

	# Back-link FM to Project
	frappe.db.set_value("Financial Model", fm.name, "project", project.name, update_modified=False)

	# Link any WBS Elements pre-created for this FM
	wbs_elements = frappe.get_all("WBS Element", filters={"financial_model": fm.name}, pluck="name")
	for wbs_name in wbs_elements:
		frappe.db.set_value("WBS Element", wbs_name, "project", project.name)

	frappe.msgprint(
		_("Project {0} created from Financial Model").format(project.name),
		indicator="green",
		alert=True,
	)
	return project.name


@frappe.whitelist()
def get_project_budget_dashboard(project):
	wbs_elements = frappe.get_all(
		"WBS Element",
		filters={"project": project, "status": ["!=", "Cancelled"]},
		fields=[
			"name",
			"wbs_name",
			"wbs_type",
			"status",
			"budget_amount",
			"budget_spent",
			"budget_utilization_pct",
		],
		order_by="creation",
	)

	totals = {
		"total_budget": sum(w.budget_amount or 0 for w in wbs_elements),
		"total_spent": sum(w.budget_spent or 0 for w in wbs_elements),
	}

	if totals["total_budget"]:
		totals["utilization_pct"] = totals["total_spent"] / totals["total_budget"] * 100
	else:
		totals["utilization_pct"] = 0

	return {"wbs_elements": wbs_elements, "totals": totals}


@frappe.whitelist()
def recalculate_project_budget(project):
	wbs_elements = frappe.get_all(
		"WBS Element",
		filters={"project": project, "status": ["!=", "Cancelled"]},
		pluck="name",
	)
	for wbs_name in wbs_elements:
		wbs = frappe.get_doc("WBS Element", wbs_name)
		wbs.refresh_spent_amounts()

	frappe.msgprint(
		_("Budget recalculated for {0} WBS elements").format(len(wbs_elements)),
		indicator="green",
		alert=True,
	)


@frappe.whitelist()
def recalculate_all_wbs_budgets(wbs_element=None):
	if wbs_element:
		wbs = frappe.get_doc("WBS Element", wbs_element)
		wbs.refresh_spent_amounts()
	else:
		wbs_elements = frappe.get_all(
			"WBS Element",
			filters={"status": "Active"},
			pluck="name",
		)
		for wbs_name in wbs_elements:
			wbs = frappe.get_doc("WBS Element", wbs_name)
			wbs.refresh_spent_amounts()


@frappe.whitelist()
def get_budget_utilization(project=None, wbs_element=None):
	filters = {"status": ["!=", "Cancelled"]}
	if project:
		filters["project"] = project
	if wbs_element:
		filters["name"] = wbs_element

	return frappe.get_all(
		"WBS Element",
		filters=filters,
		fields=[
			"name",
			"wbs_name",
			"wbs_type",
			"project",
			"status",
			"budget_amount",
			"budget_spent",
			"budget_utilization_pct",
		],
		order_by="project, creation",
	)


@frappe.whitelist()
def get_project_financial_summary(project):
	wbs_data = frappe.db.sql(
		"""SELECT COALESCE(SUM(budget_amount), 0) as budget,
		          COALESCE(SUM(budget_spent), 0) as spent
		   FROM `tabWBS Element`
		   WHERE project = %s AND status != 'Cancelled'""",
		project, as_dict=True,
	)

	wbs_names = frappe.get_all("WBS Element", filters={"project": project}, pluck="name") or [""]

	mr_count = frappe.db.count(
		"Material Request",
		{
			"custom_wbs_element": ["in", wbs_names],
			"docstatus": ["<", 2],
		},
	)

	po_data = frappe.db.sql(
		"""
        SELECT COUNT(*) as count, COALESCE(SUM(grand_total), 0) as total
        FROM `tabPurchase Order`
        WHERE custom_wbs_element IN (
            SELECT name FROM `tabWBS Element` WHERE project = %s
        ) AND docstatus = 1
    """,
		project,
		as_dict=True,
	)[0]

	return {
		"budget": (wbs_data[0].budget or 0) if wbs_data else 0,
		"spent": (wbs_data[0].spent or 0) if wbs_data else 0,
		"mr_count": mr_count,
		"po_count": po_data.count,
		"po_total": po_data.total,
	}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def send_budget_alerts():
	"""Daily: send alerts for WBS elements above 80% utilization."""
	wbs_elements = frappe.get_all(
		"WBS Element",
		filters={"status": "Active", "budget_utilization_pct": [">=", 80]},
		fields=[
			"name",
			"wbs_name",
			"project",
			"budget_amount",
			"budget_spent",
			"budget_utilization_pct",
			"person_responsible",
		],
	)

	if not wbs_elements:
		return

	for wbs in wbs_elements:
		recipients = []
		if wbs.person_responsible:
			email = frappe.db.get_value("Employee", wbs.person_responsible, "user_id")
			if email:
				recipients.append(email)

		if wbs.project:
			pm_email = frappe.db.get_value("Project", wbs.project, "custom_project_approver")
			if pm_email:
				recipients.append(pm_email)

		if not recipients:
			recipients = [frappe.db.get_value("User", "Administrator", "email")]

		pct = wbs.budget_utilization_pct or 0
		subject = _("Budget Alert: {0} at {1}% utilization").format(wbs.wbs_name, f"{pct:.0f}")

		frappe.sendmail(
			recipients=list(set(recipients)),
			subject=subject,
			message=_(
				"WBS Element <b>{0}</b> ({1}) has reached <b>{2}%</b> budget utilization.<br>"
				"Budget: {3}<br>Spent: {4}<br>"
				"Please review and take necessary action."
			).format(
				wbs.wbs_name,
				wbs.name,
				f"{pct:.1f}",
				frappe.format_value(wbs.budget_amount, {"fieldtype": "Currency"}),
				frappe.format_value(wbs.budget_spent, {"fieldtype": "Currency"}),
			),
			now=True,
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _update_wbs_spent(doc):
	if doc.custom_wbs_element:
		try:
			wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
			wbs.refresh_spent_amounts()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "WBS PO Submit Update Error")

	if doc.custom_sub_wbs_element:
		try:
			sub_wbs = frappe.get_doc("Sub WBS Element", doc.custom_sub_wbs_element)
			sub_wbs.refresh_spent_amounts()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Sub WBS PO Submit Update Error")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_fm_categories(doctype, txt, searchfield, start, page_len, filters):
	"""Return Project Cost Categories from a Financial Model's Project Cost Breakdown."""
	financial_model = filters.get("financial_model")
	if not financial_model:
		return []

	return frappe.db.sql(
		"""
		SELECT DISTINCT pci.category, pci.category
		FROM `tabFM Project Cost Item` pci
		WHERE pci.parent = %(financial_model)s
		AND pci.parenttype = 'Financial Model'
		AND pci.category LIKE %(txt)s
		ORDER BY pci.category
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{
			"financial_model": financial_model,
			"txt": f"%%{txt}%%",
			"page_len": page_len,
			"start": start,
		},
	)
