import frappe
from frappe.tests import IntegrationTestCase


class TestSubWBSElement(IntegrationTestCase):
	def test_calculate_totals(self):
		sub_wbs = frappe.new_doc("Sub WBS Element")
		sub_wbs.sub_wbs_name = "Test Sub WBS"
		sub_wbs.company = frappe.defaults.get_global_default("company") or "_Test Company"
		sub_wbs.material_budget = 50000
		sub_wbs.service_budget = 25000
		sub_wbs.material_spent = 10000
		sub_wbs.service_spent = 5000
		sub_wbs.calculate_totals()

		self.assertEqual(sub_wbs.total_budget, 75000)
		self.assertEqual(sub_wbs.total_spent, 15000)
		self.assertAlmostEqual(sub_wbs.overall_utilization_pct, 20.0, places=1)

	def test_zero_budget(self):
		sub_wbs = frappe.new_doc("Sub WBS Element")
		sub_wbs.sub_wbs_name = "Empty Sub WBS"
		sub_wbs.company = frappe.defaults.get_global_default("company") or "_Test Company"
		sub_wbs.material_budget = 0
		sub_wbs.service_budget = 0
		sub_wbs.calculate_totals()

		self.assertEqual(sub_wbs.total_budget, 0)
		self.assertEqual(sub_wbs.overall_utilization_pct, 0)
