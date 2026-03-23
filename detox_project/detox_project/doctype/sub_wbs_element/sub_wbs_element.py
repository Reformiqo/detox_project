import frappe
from frappe import _
from frappe.model.document import Document


class SubWBSElement(Document):
	def validate(self):
		self.calculate_totals()
		self.validate_budget_against_parent()

	def calculate_totals(self):
		if self.budget_amount:
			self.budget_utilization_pct = (self.budget_spent or 0) / self.budget_amount * 100
		else:
			self.budget_utilization_pct = 0

	def validate_budget_against_parent(self):
		if not self.main_wbs_element:
			return

		parent_budget = frappe.db.get_value("WBS Element", self.main_wbs_element, "budget_amount") or 0

		existing_sub_budget = (
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(budget_amount), 0)
				FROM `tabSub WBS Element`
				WHERE main_wbs_element = %s
				AND name != %s
				AND status != 'Cancelled'
				""",
				(self.main_wbs_element, self.name or ""),
			)[0][0]
			or 0
		)

		total_allocated = existing_sub_budget + (self.budget_amount or 0)

		if parent_budget and total_allocated > parent_budget:
			frappe.throw(
				_("Total Sub WBS budget ({0}) exceeds parent WBS budget ({1})").format(
					frappe.format_value(total_allocated, {"fieldtype": "Currency"}),
					frappe.format_value(parent_budget, {"fieldtype": "Currency"}),
				),
				title=_("Budget Limit Exceeded"),
			)

	def update_parent_wbs(self):
		if not self.main_wbs_element:
			return
		wbs = frappe.get_doc("WBS Element", self.main_wbs_element)
		wbs.refresh_spent_amounts()

	def refresh_spent_amounts(self):
		spent = (
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(wa.allocated_amount), 0)
				FROM `tabWBS Allocation` wa
				INNER JOIN `tabPurchase Order` po ON po.name = wa.parent
				WHERE wa.parenttype = 'Purchase Order'
				AND wa.sub_wbs_element = %s
				AND po.docstatus = 1
				""",
				self.name,
			)[0][0]
			or 0
		)

		# Also count old-style POs for backward compatibility
		old_spent = (
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(grand_total), 0)
				FROM `tabPurchase Order`
				WHERE custom_sub_wbs_element = %s AND docstatus = 1
				AND name NOT IN (
					SELECT DISTINCT parent FROM `tabWBS Allocation`
					WHERE parenttype = 'Purchase Order' AND sub_wbs_element = %s
				)
				""",
				(self.name, self.name),
			)[0][0]
			or 0
		)

		self.budget_spent = spent + old_spent
		self.calculate_totals()
		self.save(ignore_permissions=True)
