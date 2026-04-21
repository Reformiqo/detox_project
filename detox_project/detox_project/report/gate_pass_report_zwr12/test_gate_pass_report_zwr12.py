import frappe
from frappe.tests import IntegrationTestCase

from detox_project.detox_project.report.gate_pass_report_zwr12 import (
	gate_pass_report_zwr12 as report,
)


class TestGatePassReportZWR12(IntegrationTestCase):
	def test_01_columns_47(self):
		cols = report.get_columns()
		self.assertEqual(len(cols), 47)
		# Spot-check header spellings preserved per FRD
		labels = [c["label"] for c in cols]
		self.assertIn("Gatepass Stauts", labels)
		self.assertIn("Vehcile Exit Date", labels)
		self.assertIn("company Tare Weight", labels)

	def test_02_column_ids_unique(self):
		cols = report.get_columns()
		ids = [c["fieldname"] for c in cols]
		self.assertEqual(len(ids), len(set(ids)))

	def test_03_validate_filters(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			report._validate_filters(frappe._dict({}))

		with self.assertRaises(frappe.exceptions.ValidationError):
			report._validate_filters(frappe._dict({"company": "X"}))

		with self.assertRaises(frappe.exceptions.ValidationError):
			report._validate_filters(
				frappe._dict({"company": "X", "from_date": "2026-04-10", "to_date": "2026-04-01"})
			)

		# Valid
		report._validate_filters(
			frappe._dict({"company": "X", "from_date": "2026-04-01", "to_date": "2026-04-10"})
		)

	def test_04_helpers(self):
		self.assertEqual(report._join(None), "")
		self.assertEqual(report._join("A"), "A")
		self.assertEqual(report._join(["A", "B"]), "A, B")
		self.assertIn("to", report._daterange("2026-04-01", "2026-04-10"))
		self.assertEqual(report._col_letter(1), "A")
		self.assertEqual(report._col_letter(27), "AA")
		self.assertEqual(report._col_letter(47), "AU")

	def test_05_execute_empty_company(self):
		"""Execute with a company that has no Gate Passes returns no rows."""
		company = frappe.db.get_value("Company", {}, "name") or ""
		if not company:
			self.skipTest("No company set up on this site")

		cols, data = report.execute(
			frappe._dict(
				{
					"company": company,
					"from_date": "1990-01-01",
					"to_date": "1990-01-02",
				}
			)
		)
		self.assertEqual(len(cols), 47)
		self.assertEqual(data, [])
