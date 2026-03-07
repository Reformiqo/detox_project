import frappe
from frappe import _
from frappe.model.document import Document


class WBSElement(Document):
    def validate(self):
        self.calculate_totals()

    def calculate_totals(self):
        self.total_budget = (self.material_budget or 0) + (self.service_budget or 0)
        self.total_spent = (self.material_spent or 0) + (self.service_spent or 0)

        if self.material_budget:
            self.material_utilization_pct = (self.material_spent or 0) / self.material_budget * 100
        else:
            self.material_utilization_pct = 0

        if self.service_budget:
            self.service_utilization_pct = (self.service_spent or 0) / self.service_budget * 100
        else:
            self.service_utilization_pct = 0

        if self.total_budget:
            self.overall_utilization_pct = self.total_spent / self.total_budget * 100
        else:
            self.overall_utilization_pct = 0

    def update_utilization(self):
        self.calculate_totals()
        self.save(ignore_permissions=True)

    def update_project_budget_summary(self):
        if not self.project:
            return

        wbs_elements = frappe.get_all(
            "WBS Element",
            filters={"project": self.project, "status": ["!=", "Cancelled"]},
            fields=["sum(total_budget) as total_budget", "sum(total_spent) as total_spent",
                     "sum(material_budget) as material_budget", "sum(service_budget) as service_budget",
                     "sum(material_spent) as material_spent", "sum(service_spent) as service_spent"],
        )

        if wbs_elements:
            data = wbs_elements[0]
            frappe.db.set_value("Project", self.project, {
                "custom_total_budget": data.total_budget or 0,
                "custom_total_spent": data.total_spent or 0,
                "custom_material_budget": data.material_budget or 0,
                "custom_service_budget": data.service_budget or 0,
                "custom_material_spent": data.material_spent or 0,
                "custom_service_spent": data.service_spent or 0,
                "custom_budget_utilization_pct": (
                    (data.total_spent or 0) / (data.total_budget or 1) * 100
                ),
            }, update_modified=False)

    def refresh_spent_amounts(self):
        """Recalculate spent amounts from linked POs."""
        material_spent = frappe.db.sql("""
            SELECT COALESCE(SUM(po.grand_total), 0)
            FROM `tabPurchase Order` po
            WHERE po.custom_wbs_element = %s
            AND po.docstatus = 1
            AND po.custom_po_type = 'Material'
        """, self.name)[0][0] or 0

        service_spent = frappe.db.sql("""
            SELECT COALESCE(SUM(po.grand_total), 0)
            FROM `tabPurchase Order` po
            WHERE po.custom_wbs_element = %s
            AND po.docstatus = 1
            AND po.custom_po_type = 'Service'
        """, self.name)[0][0] or 0

        self.material_spent = material_spent
        self.service_spent = service_spent
        self.calculate_totals()
        self.save(ignore_permissions=True)
        self.update_project_budget_summary()
