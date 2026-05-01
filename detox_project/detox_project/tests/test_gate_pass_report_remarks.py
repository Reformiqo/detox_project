"""Regression test for ABP2-I204.

Aarif reported that the Gate Pass Report ZWR12:
  1. Showed blank Remarks (Chemist) and Remarks (CRM) even though the
     QI form had values filled.
  2. Showed Document Review = "Pending" for a GP whose workflow state
     was already "QC Approved".

Root causes:
  - QI has FOUR remark fields with two pairs of duplicate labels:
      Chemist: `remarks` (Data) + `custom_remarks_chemist` (Small Text)
      CRM:     `custom_remarks_crm_copy` (Data) + `custom_remarks_crm` (Small Text)
    The report only queried two of the four — whichever Frappe form
    bound to first, the data could land in `remarks` or
    `custom_remarks_crm_copy` and be silently dropped from the report.
  - `custom_document_review` defaults to "Pending" and stays there
    unless the user explicitly flips it. The report rendered the raw
    value, contradicting the workflow_state.

Fix:
  - `_fetch_qi` pulls all 4 remark fields + the `remarks` standard
    field; row-builder picks the first non-empty in each pair.
  - New `_derive_document_review(custom_value, workflow_state)` helper
    returns "Accepted" when the GP has progressed past QC Approved
    even if the raw field is still "Pending"; "Cancelled" when the
    workflow is cancelled.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestGatePassReportRemarksAndDocReview(IntegrationTestCase):

    def test_derive_document_review_returns_accepted_for_qc_approved(self):
        from detox_project.detox_project.report.gate_pass_report_zwr12.gate_pass_report_zwr12 import (
            _derive_document_review,
        )
        self.assertEqual(_derive_document_review("Pending", "QC Approved"), "Accepted")
        self.assertEqual(_derive_document_review(None, "Submitted"), "Accepted")
        self.assertEqual(_derive_document_review("Pending", "Vehicle Exited"), "Accepted")

    def test_derive_document_review_keeps_explicit_value(self):
        from detox_project.detox_project.report.gate_pass_report_zwr12.gate_pass_report_zwr12 import (
            _derive_document_review,
        )
        self.assertEqual(_derive_document_review("Accepted", "QC In Progress"), "Accepted")
        self.assertEqual(_derive_document_review("Rejected", "Submitted"), "Rejected")

    def test_derive_document_review_handles_cancelled(self):
        from detox_project.detox_project.report.gate_pass_report_zwr12.gate_pass_report_zwr12 import (
            _derive_document_review,
        )
        self.assertEqual(_derive_document_review("Pending", "Cancelled"), "Cancelled")
        self.assertEqual(_derive_document_review("Accepted", "Cancelled"), "Cancelled")

    def test_derive_document_review_falls_back_to_pending(self):
        from detox_project.detox_project.report.gate_pass_report_zwr12.gate_pass_report_zwr12 import (
            _derive_document_review,
        )
        self.assertEqual(_derive_document_review("", "Draft"), "Pending")
        self.assertEqual(_derive_document_review(None, "Vehicle Entered"), "Pending")

    def test_fetch_qi_includes_all_four_remark_field_candidates(self):
        """The SQL inside _fetch_qi must reference whichever of the four
        remark fields exist on this site."""
        from detox_project.detox_project.report.gate_pass_report_zwr12.gate_pass_report_zwr12 import (
            _fetch_qi,
        )
        import inspect
        src = inspect.getsource(_fetch_qi)
        for f in ("custom_remarks_chemist", "custom_remarks_crm",
                  "custom_remarks_crm_copy", "remarks"):
            self.assertIn(
                f, src,
                f"_fetch_qi must consider field {f!r} so the report doesn't "
                f"silently drop QI remark data on a site that uses that field.",
            )
