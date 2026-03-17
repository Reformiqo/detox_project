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

		wbs_elements = frappe.get_all(
			"WBS Element",
			filters={"project": self.project, "status": ["!=", "Cancelled"]},
			fields=[
				"sum(budget_amount) as total_budget",
				"sum(budget_spent) as total_spent",
			],
		)

		if wbs_elements:
			data = wbs_elements[0]
			total_budget = data.total_budget or 0
			total_spent = data.total_spent or 0
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
