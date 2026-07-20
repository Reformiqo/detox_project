import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


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
		fm_allocation = (
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(amount), 0)
				FROM `tabFM Project Cost Item`
				WHERE parent = %s AND category = %s
				""",
				(self.financial_model, self.category),
			)[0][0]
			or 0
		)
		if not fm_allocation:
			return
		existing = (
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(budget_amount), 0)
				FROM `tabWBS Element`
				WHERE financial_model = %s AND category = %s AND name != %s AND status != 'Cancelled'
				""",
				(self.financial_model, self.category, self.name or ""),
			)[0][0]
			or 0
		)
		total = existing + (self.budget_amount or 0)
		if total > fm_allocation:
			frappe.throw(
				_(
					"Total WBS budget for Category [{0}] is {1}. Exceeds FM allocation of {2}."
				).format(
					self.category,
					frappe.format_value(total, {"fieldtype": "Currency"}),
					frappe.format_value(fm_allocation, {"fieldtype": "Currency"}),
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

	def refresh_spent_amounts(self):
		"""ABP2-I439 (Sahil 2026-06-10): recalculate spent as committed
		POs + booked PIs, de-double-counted.

		Before the fix this summed Purchase Orders only — direct PIs
		(no parent PO) never moved the needle, and after ABP2-I455's
		dedup heal the stale budget_spent values still carried the old
		over-counted totals.

		Formula now:
		    spent = Σ submitted PO.allocated_amount
		          + Σ submitted PI.allocated_amount
		            WHERE the PI's items don't reference any PO already
		            allocated to this WBS  (de-double-count)
		"""
		from frappe.utils import flt

		po_spent = flt(frappe.db.sql(
			"""
			SELECT COALESCE(SUM(wa.allocated_amount), 0)
			FROM `tabWBS Allocation` wa
			INNER JOIN `tabPurchase Order` po ON po.name = wa.parent
			WHERE wa.parenttype = 'Purchase Order'
			  AND wa.wbs_element = %s
			  AND po.docstatus = 1
			""",
			self.name,
		)[0][0])

		# PI sum — exclude PIs converted from a PO that's already in
		# this WBS (the PO already counted that money). NOT EXISTS
		# subquery short-circuits on the first matching PII row.
		pi_spent = flt(frappe.db.sql(
			"""
			SELECT COALESCE(SUM(wa.allocated_amount), 0)
			FROM `tabWBS Allocation` wa
			INNER JOIN `tabPurchase Invoice` pi ON pi.name = wa.parent
			WHERE wa.parenttype = 'Purchase Invoice'
			  AND wa.wbs_element = %s
			  AND pi.docstatus = 1
			  AND NOT EXISTS (
			      SELECT 1
			      FROM `tabPurchase Invoice Item` pii
			      INNER JOIN `tabWBS Allocation` po_wa
			              ON po_wa.parent = pii.purchase_order
			             AND po_wa.parenttype = 'Purchase Order'
			             AND po_wa.wbs_element = %s
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
		self.update_project_budget_summary()
