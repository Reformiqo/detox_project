import frappe
from frappe.model.document import Document


class WBSBudgetLine(Document):
    def validate(self):
        self.total_line_budget = (self.material_budget or 0) + (self.service_budget or 0)
