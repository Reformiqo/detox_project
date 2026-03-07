import frappe
from frappe import _
from frappe.model.document import Document


class SubWBSElement(Document):
    def validate(self):
        self.calculate_totals()
        self.validate_budget_against_parent()

    def calculate_totals(self):
        self.total_budget = (self.material_budget or 0) + (self.service_budget or 0)
        self.total_spent = (self.material_spent or 0) + (self.service_spent or 0)

        if self.total_budget:
            self.overall_utilization_pct = self.total_spent / self.total_budget * 100
        else:
            self.overall_utilization_pct = 0

    def validate_budget_against_parent(self):
        if not self.main_wbs_element:
            return

        parent_budget = frappe.db.get_value(
            "WBS Element", self.main_wbs_element, "total_budget"
        ) or 0

        existing_sub_budget = frappe.db.sql("""
            SELECT COALESCE(SUM(total_budget), 0)
            FROM `tabSub WBS Element`
            WHERE main_wbs_element = %s
            AND name != %s
            AND status != 'Cancelled'
        """, (self.main_wbs_element, self.name or ""))[0][0] or 0

        total_allocated = existing_sub_budget + self.total_budget

        if parent_budget and total_allocated > parent_budget:
            frappe.msgprint(
                _("Total Sub WBS budget ({0}) exceeds parent WBS budget ({1})").format(
                    frappe.format_value(total_allocated, {"fieldtype": "Currency"}),
                    frappe.format_value(parent_budget, {"fieldtype": "Currency"}),
                ),
                indicator="orange",
                title=_("Budget Warning"),
            )

    def update_parent_wbs(self):
        if not self.main_wbs_element:
            return
        wbs = frappe.get_doc("WBS Element", self.main_wbs_element)
        wbs.refresh_spent_amounts()

    def refresh_spent_amounts(self):
        material_spent = frappe.db.sql("""
            SELECT COALESCE(SUM(po.grand_total), 0)
            FROM `tabPurchase Order` po
            WHERE po.custom_sub_wbs_element = %s
            AND po.docstatus = 1
            AND po.custom_po_type = 'Material'
        """, self.name)[0][0] or 0

        service_spent = frappe.db.sql("""
            SELECT COALESCE(SUM(po.grand_total), 0)
            FROM `tabPurchase Order` po
            WHERE po.custom_sub_wbs_element = %s
            AND po.docstatus = 1
            AND po.custom_po_type = 'Service'
        """, self.name)[0][0] or 0

        self.material_spent = material_spent
        self.service_spent = service_spent
        self.calculate_totals()
        self.save(ignore_permissions=True)
