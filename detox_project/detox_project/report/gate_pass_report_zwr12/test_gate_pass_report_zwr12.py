import frappe
from frappe.tests import IntegrationTestCase

from detox_project.detox_project.report.gate_pass_report_zwr12 import (
	gate_pass_report_zwr12 as report,
)


class TestGatePassReportZWR12(IntegrationTestCase):
	def test_01_columns(self):
		"""ABP2-I265 added 4 columns → total is now 51.

		Spelling quirks from the original FRD are still preserved
		(Gatepass Stauts, Vehcile Exit Date, company Tare Weight) —
		those are deliberate and must not be 'corrected'.
		"""
		cols = report.get_columns()
		self.assertEqual(len(cols), 51)
		labels = [c["label"] for c in cols]
		# Header spellings preserved per FRD
		self.assertIn("Gatepass Stauts", labels)
		self.assertIn("Vehcile Exit Date", labels)
		self.assertIn("company Tare Weight", labels)
		# ABP2-I265 — new columns
		self.assertIn("QC Number", labels)
		self.assertIn("Inward Qty", labels)
		self.assertIn("Vehicle Entry Date", labels)
		self.assertIn("Waste Code Description", labels)

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
		self.assertEqual(len(cols), 51)
		self.assertEqual(data, [])

	def test_06_new_columns_in_order(self):
		"""ABP2-I265 — new columns are appended after the existing
		47, in the documented order."""
		cols = report.get_columns()
		fieldnames = [c["fieldname"] for c in cols]
		expected_new = [
			"qc_number", "inward_qty",
			"vehicle_entry_date", "waste_code_description",
		]
		# Last 4 fieldnames must match (in order)
		self.assertEqual(fieldnames[-4:], expected_new)

	def test_07_inward_qty_fetcher_sums_per_gate_pass(self):
		"""Stub-driven contract test for `_fetch_waste_inward_qty`."""
		import frappe as _frappe
		orig = _frappe.db.sql

		def stub(query, *args, **kwargs):
			if "inward_qty" in (query or "") and "tabWaste Inward" in query:
				return [
					_frappe._dict(gate_pass="GP-1", inward_qty=2.5),
					_frappe._dict(gate_pass="GP-2", inward_qty=0.75),
				]
			return orig(query, *args, **kwargs)

		_frappe.db.sql = stub
		try:
			out = report._fetch_waste_inward_qty(["GP-1", "GP-2"])
		finally:
			_frappe.db.sql = orig

		self.assertEqual(out, {"GP-1": 2.5, "GP-2": 0.75})

	def test_08_inward_qty_fetcher_empty_input(self):
		self.assertEqual(report._fetch_waste_inward_qty([]), {})
