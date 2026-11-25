import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from detox_project.detox_project.report.project_budget_hierarchy_tracker.project_budget_hierarchy_tracker import (
	_compute_actual,
	_compute_commitment,
	_compute_rem_ord_plan,
	_derive,
)


class WBSElement(Document):
	def autoname(self):
		if not self.project:
			frappe.throw(_("Project is required."))
		project_num = self.project.split("-")[-1][-3:]
		base = f"WBS-{project_num}"
		existing = frappe.db.get_all(
			"WBS Element",
			filters={"project": self.project, "name": ["like", f"{base}.%"]},
			pluck="name",
		)
		numbers = []
		for n in existing:
			try:
				numbers.append(int(n.split(".")[-1]))
			except (ValueError, IndexError):
				pass
		next_num = max(numbers) + 1 if numbers else 1
		self.name = f"{base}.{next_num}"

	def validate(self):
		self.calculate_totals()
		self.validate_category_budget()
		self.validate_total_revenue()

	def after_insert(self):
		if not self.project:
			frappe.throw("Project is required.")

		project_num = self.project.split("-")[-1][-3:]
		base = f"WBS-{project_num}"

		if not self.name.startswith(base + "."):
			siblings = frappe.db.get_all(
				"WBS Element",
				filters={"project": self.project},
				fields=["name"]
			)
			numbers = []
			for s in siblings:
				try:
					numbers.append(int(s.name.split(".")[-1]))
				except:
					pass

			next_num = max(numbers) + 1 if numbers else 1
			new_name = f"{base}.{next_num}"
			frappe.rename_doc("WBS Element", self.name, new_name, force=True)


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

	def validate_category_budget(self):
		if not self.financial_model or not self.category or not self.budget_amount:
			return
		if self.budget_type not in ("CAPEX", "OPEX"):
			return

		# The same category can sit on both FM tabs, so CAPEX and OPEX are checked
		# separately: CAPEX WBS vs the CAPEX tab, OPEX WBS vs the OPEX tab.
		if self.budget_type == "CAPEX":
			allocation_sql = """
				SELECT COALESCE(SUM(amount), 0)
				FROM `tabFM Project Cost Item`
				WHERE parent = %s AND parenttype = 'Financial Model' AND category = %s
			"""
		else:
			allocation_sql = """
				SELECT COALESCE(SUM(annual_base_amount), 0)
				FROM `tabFM Expense Item`
				WHERE parent = %s AND parenttype = 'Financial Model' AND custom_category = %s
			"""
		fm_allocation = flt(frappe.db.sql(allocation_sql, (self.financial_model, self.category))[0][0])
		if not fm_allocation:
			return

		existing = flt(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(budget_amount), 0)
				FROM `tabWBS Element`
				WHERE financial_model = %s AND category = %s AND budget_type = %s
				  AND name != %s AND status != 'Cancelled'
				""",
				(self.financial_model, self.category, self.budget_type, self.name or ""),
			)[0][0]
		)
		total = existing + flt(self.budget_amount)
		if flt(total, 2) > flt(fm_allocation, 2):
			frappe.throw(
				_("Total {0} WBS budget for Category [{1}] is {2}. Exceeds FM {0} allocation of {3}.").format(
					self.budget_type,
					self.category,
					frappe.format_value(total, {"fieldtype": "Currency"}),
					frappe.format_value(fm_allocation, {"fieldtype": "Currency"}),
				)
			)

	def validate_total_revenue(self):
		# The project's WBS revenues together must fit in its Project Budget revenue.
		if not self.project or not flt(self.total_revenue) or not self.has_value_changed("total_revenue"):
			return
		project_budget = frappe.db.get_value(
			"Financial Model",
			{"project": self.project, "docstatus": ["<", 2]},
			["name", "total_annual_revenue"],
			as_dict=True,
		)
		if not project_budget:
			return
		existing = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(total_revenue), 0)
			FROM `tabWBS Element`
			WHERE project = %s AND name != %s AND status != 'Cancelled'
			""",
			(self.project, self.name or ""),
		)[0][0]
		total = flt(existing) + flt(self.total_revenue)
		if flt(total, 2) > flt(project_budget.total_annual_revenue, 2):
			frappe.throw(
				_(
					"Total Revenue of all WBS Elements in Project {0} is {1}. Exceeds Total Annual Base Revenue of {2} in Project Budget {3}."
				).format(
					self.project,
					frappe.format_value(total, {"fieldtype": "Currency"}),
					frappe.format_value(project_budget.total_annual_revenue, {"fieldtype": "Currency"}),
					project_budget.name,
				)
			)

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

	def onload(self):
		self.set_onload("budget_stats", self.get_budget_stats())

	def get_budget_stats(self):
		"""Same calculation as the Project Budget Hierarchy Tracker (before GST)."""
		actual = _compute_actual(self.project, self.cost_center, self.name)
		commitment = _compute_commitment(self.name)
		rem_ord_plan = _compute_rem_ord_plan(self.name)
		assigned, available, utilization = _derive(self.budget_amount, actual, commitment, rem_ord_plan)
		return {
			"actual": actual,
			"commitment": commitment,
			"rem_ord_plan": rem_ord_plan,
			"assigned": assigned,
			"available": available,
			"utilization": utilization,
		}

	def refresh_spent_amounts(self):
		# db_set instead of save: a failing master-data validation (FM category /
		# parent budget) must not silently skip the spent refresh.
		self.budget_spent = self.get_budget_stats()["assigned"]
		self.calculate_totals()
		self.db_set({
			"budget_spent": self.budget_spent,
			"budget_utilization_pct": self.budget_utilization_pct,
		})
		self.update_project_budget_summary()
