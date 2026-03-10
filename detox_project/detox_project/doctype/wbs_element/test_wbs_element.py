import frappe
from frappe.tests import IntegrationTestCase


class TestWBSElement(IntegrationTestCase):
	def test_calculate_totals(self):
		wbs = frappe.new_doc("WBS Element")
		wbs.wbs_name = "Test WBS"
		wbs.company = frappe.defaults.get_global_default("company") or "_Test Company"
		wbs.material_budget = 100000
		wbs.service_budget = 50000
		wbs.material_spent = 40000
		wbs.service_spent = 10000
		wbs.validate()

		self.assertEqual(wbs.total_budget, 150000)
		self.assertEqual(wbs.total_spent, 50000)
		self.assertAlmostEqual(wbs.overall_utilization_pct, 33.33, places=1)
		self.assertAlmostEqual(wbs.material_utilization_pct, 40.0, places=1)
		self.assertAlmostEqual(wbs.service_utilization_pct, 20.0, places=1)

	def test_zero_budget_utilization(self):
		wbs = frappe.new_doc("WBS Element")
		wbs.wbs_name = "Zero Budget WBS"
		wbs.company = frappe.defaults.get_global_default("company") or "_Test Company"
		wbs.material_budget = 0
		wbs.service_budget = 0
		wbs.validate()

		self.assertEqual(wbs.total_budget, 0)
		self.assertEqual(wbs.overall_utilization_pct, 0)
		self.assertEqual(wbs.material_utilization_pct, 0)
		self.assertEqual(wbs.service_utilization_pct, 0)
