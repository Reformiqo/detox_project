import frappe
from frappe import _
from frappe.model.document import Document


class FinancialModel(Document):
    def validate(self):
        self.calculate_totals()
        self.validate_budget_lines()

    def calculate_totals(self):
        self.total_material_budget = sum(
            row.material_budget or 0 for row in self.budget_lines
        )
        self.total_service_budget = sum(
            row.service_budget or 0 for row in self.budget_lines
        )
        self.total_project_budget = self.total_material_budget + self.total_service_budget

        for row in self.budget_lines:
            row.total_line_budget = (row.material_budget or 0) + (row.service_budget or 0)

    def validate_budget_lines(self):
        if not self.budget_lines:
            frappe.throw(_("At least one WBS Budget Line is required"))

        names = []
        for row in self.budget_lines:
            if row.wbs_name in names:
                frappe.throw(_("Duplicate WBS Name: {0} in row {1}").format(row.wbs_name, row.idx))
            names.append(row.wbs_name)

            if (row.material_budget or 0) < 0 or (row.service_budget or 0) < 0:
                frappe.throw(_("Budget amounts cannot be negative in row {0}").format(row.idx))

    def on_submit(self):
        self.create_wbs_elements()
        self.db_set("model_status", "Approved")

    def on_cancel(self):
        self.cancel_wbs_elements()
        self.db_set("model_status", "Cancelled")

    def create_wbs_elements(self):
        for row in self.budget_lines:
            wbs = frappe.new_doc("WBS Element")
            wbs.wbs_name = row.wbs_name
            wbs.wbs_type = row.wbs_type
            wbs.financial_model = self.name
            wbs.company = self.company
            wbs.site = row.site
            wbs.cost_center = row.cost_center
            wbs.person_responsible = row.person_responsible
            wbs.priority = row.priority
            wbs.material_budget = row.material_budget
            wbs.service_budget = row.service_budget
            wbs.total_budget = row.total_line_budget
            wbs.status = "Active"
            wbs.insert(ignore_permissions=True)

        frappe.msgprint(
            _("{0} WBS Elements created from Financial Model").format(len(self.budget_lines)),
            indicator="green",
            alert=True,
        )

    def cancel_wbs_elements(self):
        wbs_elements = frappe.get_all(
            "WBS Element",
            filters={"financial_model": self.name},
            pluck="name",
        )
        for wbs_name in wbs_elements:
            frappe.db.set_value("WBS Element", wbs_name, "status", "Cancelled")
