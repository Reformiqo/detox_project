"""Regression test for ABP2-I218.

The ZWR12 report's _fetch_waste_inward used `MIN(posting_date)` but Waste
Inward's actual field is `date`. The column rename to "Posting Date" is a
display-only Property Setter. The query crashed with OperationalError
"Unknown column 'posting_date' in 'SELECT'" the moment a Gate Pass had a
linked Waste Inward.

Tests:
  1. _fetch_waste_inward() runs without OperationalError on a GP name list
     that may or may not have linked Waste Inward rows.
  2. execute() over a date range runs end-to-end without OperationalError.
  3. The source code references `MIN(date)` and not `MIN(posting_date)`.
"""
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from detox_project.detox_project.report.gate_pass_report_zwr12 import (
	gate_pass_report_zwr12 as report,
)


class TestZWR12WasteInwardJoin(IntegrationTestCase):

	def test_fetch_waste_inward_no_operational_error(self):
		# Use real GP names if any exist — exercises the JOIN with real data.
		gp_names = frappe.get_all(
			"Gate Pass",
			filters={"docstatus": ["<", 2]},
			pluck="name",
			limit=10,
		) or ["NONEXISTENT-GP-FOR-TEST"]
		# Should not raise; OperationalError would mean the SQL is broken.
		result = report._fetch_waste_inward(gp_names)
		self.assertIsInstance(result, dict)

	def test_execute_does_not_raise_operational_error(self):
		"""Run execute() over today's date — Frappe's OperationalError is the
		regression we're guarding against. Empty data is fine."""
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No company configured on this site.")
		filters = frappe._dict({
			"company": company,
			"from_date": nowdate(),
			"to_date": nowdate(),
		})
		try:
			cols, data = report.execute(filters)
		except frappe.db.OperationalError as exc:
			self.fail(
				f"ABP2-I218: execute() must not raise OperationalError. "
				f"Got: {exc}"
			)
		# ABP2-I265 — 4 new columns appended → 51 total.
		self.assertEqual(len(cols), 51)
		self.assertIsInstance(data, list)

	def test_sql_uses_date_not_posting_date(self):
		"""Hard-coded grep — guards against future redeployments accidentally
		reverting the SQL."""
		import inspect
		src = inspect.getsource(report._fetch_waste_inward)
		self.assertIn(
			"MIN(date)", src,
			"ABP2-I218: _fetch_waste_inward must SELECT MIN(date), not MIN(posting_date).",
		)
		self.assertNotIn(
			"MIN(posting_date)", src,
			"ABP2-I218: MIN(posting_date) is the dead query — Waste Inward has no posting_date column.",
		)
