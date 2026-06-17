import frappe
from frappe import _
from frappe.model.document import Document


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
		"""ABP2-I439 (Sahil 2026-06-10) — same fix as WBS Element:
		spent = submitted POs + submitted PIs (de-double-counted on
		PI → PO conversion). See wbs_element.refresh_spent_amounts for
		the full reasoning."""
		from frappe.utils import flt

		po_spent = flt(frappe.db.sql(
			"""
			SELECT COALESCE(SUM(wa.allocated_amount), 0)
			FROM `tabWBS Allocation` wa
			INNER JOIN `tabPurchase Order` po ON po.name = wa.parent
			WHERE wa.parenttype = 'Purchase Order'
			  AND wa.sub_wbs_element = %s
			  AND po.docstatus = 1
			""",
			self.name,
		)[0][0])

		pi_spent = flt(frappe.db.sql(
			"""
			SELECT COALESCE(SUM(wa.allocated_amount), 0)
			FROM `tabWBS Allocation` wa
			INNER JOIN `tabPurchase Invoice` pi ON pi.name = wa.parent
			WHERE wa.parenttype = 'Purchase Invoice'
			  AND wa.sub_wbs_element = %s
			  AND pi.docstatus = 1
			  AND NOT EXISTS (
			      SELECT 1
			      FROM `tabPurchase Invoice Item` pii
			      INNER JOIN `tabWBS Allocation` po_wa
			              ON po_wa.parent = pii.purchase_order
			             AND po_wa.parenttype = 'Purchase Order'
			             AND po_wa.sub_wbs_element = %s
			      WHERE pii.parent = pi.name
			        AND pii.purchase_order IS NOT NULL
			        AND pii.purchase_order != ''
			  )
			""",
			(self.name, self.name),
		)[0][0])

		self.budget_spent = po_spent + pi_spent
		self.calculate_totals()
		self.save(ignore_permissions=True)
