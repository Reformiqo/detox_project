import frappe
from frappe import _
from frappe.model.document import Document


class WBSElement(Document):
	def validate(self):
		self.calculate_totals()

	def on_update(self):
		self.update_project_budget_summary()

	def calculate_totals(self):
		if self.budget_amount:
			self.budget_utilization_pct = (self.budget_spent or 0) / self.budget_amount * 100
		else:
			self.budget_utilization_pct = 0

	def update_utilization(self):
		self.calculate_totals()
		self.save(ignore_permissions=True)

	def update_project_budget_summary(self):
		if not self.project:
			return

		result = frappe.db.sql(
			"""SELECT COALESCE(SUM(budget_amount), 0) as total_budget,
			          COALESCE(SUM(budget_spent), 0) as total_spent
			   FROM `tabWBS Element`
			   WHERE project = %s AND status != 'Cancelled'""",
			self.project, as_dict=True,
		)

		if result:
			total_budget = result[0].total_budget or 0
			total_spent = result[0].total_spent or 0
			frappe.db.set_value(
				"Project",
				self.project,
				{
					"custom_total_budget": total_budget,
					"custom_total_spent": total_spent,
					"custom_budget_utilization_pct": (
						total_spent / total_budget * 100 if total_budget else 0
					),
				},
				update_modified=False,
			)

	def refresh_spent_amounts(self):
		"""Recalculate spent amounts from linked POs."""
		spent = (
			frappe.db.sql(
				"""
            SELECT COALESCE(SUM(po.grand_total), 0)
            FROM `tabPurchase Order` po
            WHERE po.custom_wbs_element = %s
            AND po.docstatus = 1
        """,
				self.name,
			)[0][0]
			or 0
		)

		self.budget_spent = spent
		self.calculate_totals()
		self.save(ignore_permissions=True)
		self.update_project_budget_summary()
