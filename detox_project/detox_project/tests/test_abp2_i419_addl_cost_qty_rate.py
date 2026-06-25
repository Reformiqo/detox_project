"""ABP2-I419 reopen item #7 (Raj 2026-06-19) — separate Qty + Rate
columns on the Additional Cost section of Stock Entry.

The Additional Cost grid uses the shared `Landed Cost Taxes and
Charges` child doctype (also used by Landed Cost Voucher). We add
`custom_qty` (Float) + `custom_rate` (Currency) as Custom Fields on
that child, both surfaced in the grid (in_list_view=1). A client
script in public/js/stock_entry_manufacture.js auto-recomputes
`amount = qty * rate` when either changes, but ONLY when the parent
form is Stock Entry — Landed Cost Voucher behavior is untouched.

These tests pin the field config + grid placement.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestI419AddlCostQtyRate(IntegrationTestCase):

    def test_custom_qty_field_exists(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Landed Cost Taxes and Charges",
             "fieldname": "custom_qty"},
            ["fieldname", "label", "fieldtype", "insert_after",
             "in_list_view", "non_negative"],
            as_dict=True,
        )
        self.assertIsNotNone(cf, "custom_qty missing")
        self.assertEqual(cf.label, "Qty")
        self.assertEqual(cf.fieldtype, "Float")
        self.assertEqual(cf.insert_after, "expense_account",
                         "Qty must sit between Expense Account and Description")
        self.assertEqual(cf.in_list_view, 1,
                         "Qty must appear in the grid (in_list_view=1)")
        self.assertEqual(cf.non_negative, 1)

    def test_custom_rate_field_exists(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Landed Cost Taxes and Charges",
             "fieldname": "custom_rate"},
            ["fieldname", "label", "fieldtype", "insert_after",
             "in_list_view"],
            as_dict=True,
        )
        self.assertIsNotNone(cf, "custom_rate missing")
        self.assertEqual(cf.label, "Rate")
        self.assertEqual(cf.fieldtype, "Currency")
        self.assertEqual(cf.insert_after, "custom_qty",
                         "Rate must sit immediately after Qty")
        self.assertEqual(cf.in_list_view, 1)

    def test_client_script_handler_present_and_gated(self):
        """The recompute handler MUST be gated on parent doctype being
        Stock Entry — Landed Cost Taxes and Charges is shared with
        Landed Cost Voucher, and an ungated handler would change LCV
        Amount semantics."""
        from pathlib import Path
        js = Path("/home/frappe/v16/apps/detox_project/detox_project/"
                  "public/js/stock_entry_manufacture.js").read_text()
        self.assertIn(
            "Landed Cost Taxes and Charges", js,
            "stock_entry_manufacture.js must register a handler on the "
            "child doctype.",
        )
        self.assertIn(
            "_recompute_addl_cost_amount", js,
            "Recompute helper must exist.",
        )
        self.assertIn(
            'frm.doctype !== "Stock Entry"', js,
            "Handler must early-return for non-Stock-Entry parents.",
        )

    def test_recompute_only_fires_when_both_set(self):
        """Pin the contract: amount auto-fills only when BOTH qty and
        rate are non-zero. If the user enters just an Amount (legacy
        path), it must not be wiped."""
        from pathlib import Path
        js = Path("/home/frappe/v16/apps/detox_project/detox_project/"
                  "public/js/stock_entry_manufacture.js").read_text()
        self.assertIn(
            "if (qty && rate)", js,
            "Recompute must guard on both qty AND rate truthy — "
            "otherwise zero values would zero out manually-entered "
            "Amount.",
        )
