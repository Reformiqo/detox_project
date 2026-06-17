"""ABP2-I419 Phase 3 — Stock Entry Manufacture tests.

Pure-function + isolated DB tests. No full Salary Slip-style fixture
chain (HRMS-free).
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from detox_project.detox_project.overrides.stock_entry_manufacture import (
    MFG_TYPES,
    get_fg_defaults,
    get_operation_rm_rows,
    validate_stock_entry_manufacture,
)


class TestABP2I419Phase3(IntegrationTestCase):

    # ----- Custom fields wired -----

    def test_se_header_custom_fields_present(self):
        for fn in ("custom_process_selection", "custom_production_time",
                   "custom_time_uom"):
            self.assertTrue(
                frappe.db.exists(
                    "Custom Field", f"Stock Entry-{fn}"),
                f"Stock Entry.{fn} should be on the bench.",
            )

    def test_se_detail_po_fields_present(self):
        for fn in ("custom_purchase_order", "custom_purchase_order_item"):
            self.assertTrue(
                frappe.db.exists(
                    "Custom Field", f"Stock Entry Detail-{fn}"),
                f"Stock Entry Detail.{fn} should be on the bench.",
            )

    # ----- Whitelisted helpers -----

    def test_get_operation_rm_rows_returns_empty_for_unknown_plan(self):
        self.assertEqual(get_operation_rm_rows("DOES-NOT-EXIST", "X"), [])

    def test_get_fg_defaults_returns_empty_for_unknown_plan(self):
        self.assertEqual(get_fg_defaults("DOES-NOT-EXIST", "X"), {})

    def test_get_operation_rm_rows_against_real_plan(self):
        """If any Production Plan with custom_operations exists, the
        helper returns at least one row from it."""
        plan = frappe.db.sql(
            """SELECT DISTINCT parent FROM `tabDetox Production Plan Operation`
               WHERE parenttype = 'Production Plan' LIMIT 1""",
        )
        if not plan:
            self.skipTest("No Production Plan with operation rows on bench")
        plan_name = plan[0][0]
        op = frappe.db.get_value(
            "Detox Production Plan Operation",
            {"parent": plan_name, "parenttype": "Production Plan"},
            "operation_name",
        )
        rows = get_operation_rm_rows(plan_name, op)
        self.assertGreater(len(rows), 0)
        first = rows[0]
        for k in ("item_code", "uom", "basic_rate", "expense_account",
                  "cost_center", "project"):
            self.assertIn(k, first)

    # ----- Validate hook -----

    def test_validate_skips_non_mfg_types(self):
        """Material Issue should NOT touch process_selection rules."""
        doc = frappe.new_doc("Stock Entry")
        doc.stock_entry_type = "Material Issue"
        doc.production_plan = "ANY"  # would normally trigger VAL-08
        # Should not raise.
        validate_stock_entry_manufacture(doc)

    def test_validate_throws_when_process_missing(self):
        doc = frappe.new_doc("Stock Entry")
        doc.stock_entry_type = "Manufacture"
        doc.production_plan = "ANY"
        with self.assertRaises(frappe.ValidationError) as cm:
            validate_stock_entry_manufacture(doc)
        self.assertIn("Process", str(cm.exception))

    def test_validate_throws_on_production_time_out_of_range(self):
        doc = frappe.new_doc("Stock Entry")
        doc.stock_entry_type = "Manufacture"
        doc.custom_process_selection = "Filling"  # so VAL-08 passes
        doc.custom_production_time = 25  # > 24
        doc.custom_time_uom = "Hours"
        # Set production_plan so we don't fail VAL-08 first
        doc.production_plan = None
        with self.assertRaises(frappe.ValidationError) as cm:
            validate_stock_entry_manufacture(doc)
        self.assertIn("Production Time", str(cm.exception))

    def test_validate_accepts_production_time_within_range(self):
        doc = frappe.new_doc("Stock Entry")
        doc.stock_entry_type = "Manufacture"
        doc.custom_production_time = 8
        doc.custom_time_uom = "Hours"
        # Add a finished item so VAL-12 passes.
        doc.items = [frappe._dict(
            is_finished_item=1, qty=1, s_warehouse=None,
            item_code="X", t_warehouse="X",
        )]
        # No throw expected.
        validate_stock_entry_manufacture(doc)

    def test_mfg_types_constant_includes_expected(self):
        for t in ("Manufacture", "Material Transfer for Manufacture", "Repack"):
            self.assertIn(t, MFG_TYPES)
