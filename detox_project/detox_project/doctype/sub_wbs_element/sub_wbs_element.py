import frappe
from frappe import _
from frappe.model.document import Document

from detox_project.detox_project.report.project_budget_hierarchy_tracker.project_budget_hierarchy_tracker import (
	_compute_actual,
	_compute_commitment,
	_compute_rem_ord_plan,
	_derive,
)


class SubWBSElement(Document):
	def autoname(self):
		if not self.main_wbs_element:
			frappe.throw(_("Main WBS Element is required."))
		if self.parent_sub_wbs:
			base = self.parent_sub_wbs.replace("SUB ", "", 1)
			siblings = frappe.db.get_all(
				"Sub WBS Element",
				filters={"parent_sub_wbs": self.parent_sub_wbs},
				pluck="name",
			)
		else:
			base = self.main_wbs_element
			siblings = frappe.db.get_all(
				"Sub WBS Element",
				filters={
					"main_wbs_element": self.main_wbs_element,
					"parent_sub_wbs": ["is", "not set"],
				},
				pluck="name",
			)
		numbers = []
		for n in siblings:
			try:
				clean = n.replace("SUB ", "", 1)
				numbers.append(int(clean.split(".")[-1]))
			except (ValueError, IndexError):
				pass
		next_num = max(numbers) + 1 if numbers else 1
		self.name = f"SUB {base}.{next_num}"

	def validate(self):
		self.calculate_totals()
		self.validate_budget_against_parent()

	def after_insert(self):
		if not self.main_wbs_element:
			frappe.throw("Main WBS Element is required.")

		if self.parent_sub_wbs:
			# Strip "SUB " prefix to get clean base: "SUB WBS-008.1.1" → "WBS-008.1.1"
			base = self.parent_sub_wbs.replace("SUB ", "")
			siblings = frappe.db.get_all(
				"Sub WBS Element",
				filters={"parent_sub_wbs": self.parent_sub_wbs},
				fields=["name"]
			)
		else:
			# Base is WBS Element name directly: "WBS-008.1"
			base = self.main_wbs_element
			siblings = frappe.db.get_all(
				"Sub WBS Element",
				filters={
					"main_wbs_element": self.main_wbs_element,
					"parent_sub_wbs": ["is", "not set"]
				},
				fields=["name"]
			)

		expected_prefix = f"SUB {base}."

		if not self.name.startswith(expected_prefix):
			numbers = []
			for s in siblings:
				try:
					# Strip "SUB " before splitting: "SUB WBS-008.1.2" → last segment = "2"
					clean = s.name.replace("SUB ", "")
					numbers.append(int(clean.split(".")[-1]))
				except:
					pass

			next_num = max(numbers) + 1 if numbers else 1
			new_name = f"SUB {base}.{next_num}"
			frappe.rename_doc("Sub WBS Element", self.name, new_name, force=True)


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

	def onload(self):
		self.set_onload("budget_stats", self.get_budget_stats())

	def get_budget_stats(self):
		"""Same calculation as the Project Budget Hierarchy Tracker (before GST)."""
		actual = _compute_actual(self.project, self.cost_center, self.main_wbs_element, self.name)
		commitment = _compute_commitment(self.main_wbs_element, self.name)
		rem_ord_plan = _compute_rem_ord_plan(self.main_wbs_element, self.name)
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
		self.budget_spent = self.get_budget_stats()["assigned"]
		self.calculate_totals()
		self.save(ignore_permissions=True)
