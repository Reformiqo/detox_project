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


# ─────────────────────────────────────────────────────────────────────
# ABP2-I362 (Aarif 2026-05-27) — Document Review must reflect the
# field the form actually updates (gp.document_review_status), not the
# stale Custom Field gp.custom_document_review the prior report query
# was reading.
# ─────────────────────────────────────────────────────────────────────

class TestABP2I362DocumentReviewRealtime(IntegrationTestCase):

	# Snapshot keys we mutate during each scenario
	_FIELDS = ("document_review_status", "custom_document_review",
	           "workflow_state")

	def setUp(self):
		# Pick any GP we can poke; restore everything in tearDown.
		self.gp_name = frappe.db.get_value("Gate Pass", {}, "name")
		if not self.gp_name:
			self.skipTest("No Gate Pass on this site to use as fixture.")
		self._orig = {
			k: frappe.db.get_value("Gate Pass", self.gp_name, k)
			for k in self._FIELDS
		}
		self.company = frappe.db.get_value("Company", {}, "name")

	def tearDown(self):
		if getattr(self, "gp_name", None):
			for k, v in (getattr(self, "_orig", {}) or {}).items():
				frappe.db.set_value("Gate Pass", self.gp_name, k, v,
				                    update_modified=False)
			frappe.db.commit()

	def _force_state(self, drs, cdr, ws):
		frappe.db.set_value("Gate Pass", self.gp_name,
		                    "document_review_status", drs,
		                    update_modified=False)
		frappe.db.set_value("Gate Pass", self.gp_name,
		                    "custom_document_review", cdr,
		                    update_modified=False)
		frappe.db.set_value("Gate Pass", self.gp_name,
		                    "workflow_state", ws,
		                    update_modified=False)
		frappe.db.commit()

	def _run(self):
		flt = frappe._dict(
			company=self.company,
			from_date="2026-01-01", to_date="2026-12-31",
			gate_pass=[self.gp_name],
		)
		_cols, data = report.execute(filters=flt)
		for r in data:
			if r.get("gate_pass_no") == self.gp_name:
				return r.get("document_review")
		return None

	def test_form_side_accepted_reflects_in_report(self):
		"""Aarif's exact scenario: user updates document_review_status
		to Accepted on the form while the stale custom_document_review
		stays at Pending. Report MUST show Accepted."""
		self._force_state("Accepted", "Pending", "Vehicle Entered")
		self.assertEqual(self._run(), "Accepted")

	def test_form_side_rejected_reflects_in_report(self):
		self._force_state("Rejected", "Pending", "Vehicle Entered")
		self.assertEqual(self._run(), "Rejected")

	def test_custom_field_fallback_still_works(self):
		"""For older Gate Passes that were tagged via the legacy
		custom_document_review CF, the report must still show that
		value when the doctype field is still at Pending."""
		self._force_state("Pending", "Accepted", "Vehicle Entered")
		self.assertEqual(self._run(), "Accepted")

	def test_both_pending_with_neutral_state_stays_pending(self):
		"""Both review fields at Pending AND workflow state hasn't
		reached one of the ACCEPTED_STATES → report leaves it Pending."""
		self._force_state("Pending", "Pending", "Vehicle Entered")
		self.assertEqual(self._run(), "Pending")

	def test_both_pending_after_qc_approval_derives_accepted(self):
		"""Both review fields at Pending but the workflow has passed
		QC Approval (or beyond) → _derive_document_review surfaces
		Accepted (existing ABP2-I204 behaviour, preserved)."""
		self._force_state("Pending", "Pending", "Vehicle Exited")
		self.assertEqual(self._run(), "Accepted")

	def test_doctype_field_wins_over_custom_field_when_both_set(self):
		"""If the doctype field says Accepted but the CF still says
		Rejected (legacy stale value), the report must pick the
		doctype field — that's the one the user actually edited."""
		self._force_state("Accepted", "Rejected", "Vehicle Entered")
		self.assertEqual(self._run(), "Accepted")
