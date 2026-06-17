"""ABP2-I419 Phase 4 — Subcontracting Flow A tests."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from detox_project.detox_project.overrides.subcontracting import (
    create_service_pos_from_plan,
    validate_subcontracting_doc,
    validate_supplied_vs_consumed,
)


class TestABP2I419Phase4(IntegrationTestCase):

    def test_sub_order_cc_field_present(self):
        if not frappe.db.exists("DocType", "Subcontracting Order"):
            self.skipTest("v16 native Subcontracting Order not on bench")
        self.assertTrue(
            frappe.db.exists(
                "Custom Field", "Subcontracting Order-custom_cost_center"),
        )

    def test_sub_receipt_cc_field_present(self):
        if not frappe.db.exists("DocType", "Subcontracting Receipt"):
            self.skipTest("v16 native Subcontracting Receipt not on bench")
        self.assertTrue(
            frappe.db.exists(
                "Custom Field", "Subcontracting Receipt-custom_cost_center"),
        )

    def test_subcontract_field_gating_on_plan_operation(self):
        """Phase 1 mandatory_depends_on: when is_subcontracted=1 the four
        subcontract fields are required."""
        meta = frappe.get_meta("Detox Production Plan Operation")
        for fn in ("subcontractor", "service_item", "service_po", "return_item"):
            df = meta.get_field(fn)
            self.assertIsNotNone(df, f"{fn} should be on Detox Production Plan Operation")
            self.assertEqual(
                df.mandatory_depends_on, "eval:doc.is_subcontracted",
                f"{fn} should be mandatory when is_subcontracted=1 (VAL-04)",
            )

    def test_validate_subcontracting_doc_throws_on_blank_cc(self):
        if not frappe.db.exists("DocType", "Subcontracting Order"):
            self.skipTest("v16 native Subcontracting Order not on bench")
        doc = frappe.new_doc("Subcontracting Order")
        with self.assertRaises(frappe.ValidationError):
            validate_subcontracting_doc(doc)

    def test_create_service_pos_throws_for_unknown_plan(self):
        with self.assertRaises(Exception):
            create_service_pos_from_plan("DOES-NOT-EXIST")

    def test_validate_supplied_vs_consumed_skips_non_receipt(self):
        """Function should no-op on a non-Subcontracting-Receipt doc."""
        if not frappe.db.exists("DocType", "Subcontracting Order"):
            self.skipTest("Subcontracting Order missing")
        doc = frappe.new_doc("Subcontracting Order")
        validate_supplied_vs_consumed(doc)  # must not raise
