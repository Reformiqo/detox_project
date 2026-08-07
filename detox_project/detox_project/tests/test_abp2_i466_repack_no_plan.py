"""ABP2-I466 re-reopen (Sahil 2026-06-25, MAT-STE-00502) — a standalone
Repack (no Production Plan linked) was being blocked on submit by

    'Purchase Order missing on source row. Row #1: link a Purchase
     Order and PO line on the source row for accurate variance.'

That VAL-10 check in `validate_stock_entry_manufacture` only makes
sense when the SE is plan-driven: the variance is against the POs
that fed the Production Plan. A standalone Repack has no PO context
to vary against, so the throw is wrong.

Fix: gate VAL-10 on `doc.production_plan` being present.

No-BOM plan reopen (2026-08-07): even plan-driven SEs must not be
blocked when source rows carry no PO — VAL-10 is now a soft
`frappe.msgprint` warning, never a throw. Linked rows keep the full
variance flow.

These tests pin the new gate so a future refactor doesn't slip back
into blocking submits.
"""
import frappe
from frappe.tests import IntegrationTestCase


def _make_doc(stock_entry_type, production_plan, items):
    return frappe._dict(
        stock_entry_type=stock_entry_type,
        production_plan=production_plan,
        docstatus=0,
        _action="submit",
        custom_production_time=0,
        custom_process_selection="P1",  # bypass VAL-08
        items=[frappe._dict(r) for r in items],
        flags=frappe._dict(),
    )


class TestI466RepackNoPlan(IntegrationTestCase):

    def test_repack_without_plan_submit_passes(self):
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            validate_stock_entry_manufacture,
        )
        doc = _make_doc(
            "Repack",
            production_plan=None,
            items=[{"s_warehouse": "WH-A", "qty": 10,
                    "custom_purchase_order": None,
                    "custom_purchase_order_item": None}],
        )
        # Must NOT throw — variance check is plan-gated now.
        validate_stock_entry_manufacture(doc)

    def test_plan_driven_missing_po_warns_but_does_not_block(self):
        """No-BOM plan flow: a plan-driven SE whose source row has no PO
        link must still pass validation (soft warning only)."""
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            validate_stock_entry_manufacture,
        )
        doc = _make_doc(
            "Repack",
            production_plan="PP-001",
            items=[{"s_warehouse": "WH-A", "qty": 10,
                    "custom_purchase_order": None,
                    "custom_purchase_order_item": None}],
        )
        frappe.clear_messages()
        # Must NOT throw — VAL-10 is a soft warning now.
        validate_stock_entry_manufacture(doc)
        messages = " ".join(str(m) for m in (frappe.message_log or []))
        self.assertIn("Purchase Order", messages)

    def test_plan_driven_with_po_linked_no_warning(self):
        """When the PO link IS present the flow is untouched — no
        warning, no throw."""
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            validate_stock_entry_manufacture,
        )
        doc = _make_doc(
            "Repack",
            production_plan="PP-001",
            items=[{"s_warehouse": "WH-A", "qty": 10,
                    "custom_purchase_order": "PO-001",
                    "custom_purchase_order_item": "PO-001-ROW1"}],
        )
        frappe.clear_messages()
        validate_stock_entry_manufacture(doc)
        messages = " ".join(str(m) for m in (frappe.message_log or []))
        self.assertNotIn("Purchase Order not linked", messages)

    def test_manufacture_without_plan_submit_passes(self):
        """A standalone Manufacture SE (no plan) should also skip the
        PO-on-source-row gate. It must still satisfy VAL-12 (has FG
        with qty > 0), so include one finished item to isolate the
        VAL-10 gate."""
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            validate_stock_entry_manufacture,
        )
        doc = _make_doc(
            "Manufacture",
            production_plan=None,
            items=[
                {"s_warehouse": "WH-A", "qty": 10,
                 "is_finished_item": 0,
                 "custom_purchase_order": None,
                 "custom_purchase_order_item": None},
                {"s_warehouse": None, "qty": 5, "is_finished_item": 1},
            ],
        )
        validate_stock_entry_manufacture(doc)

    def test_material_transfer_for_manufacture_without_plan_passes(self):
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            validate_stock_entry_manufacture,
        )
        doc = _make_doc(
            "Material Transfer for Manufacture",
            production_plan=None,
            items=[{"s_warehouse": "WH-A", "qty": 10,
                    "custom_purchase_order": None,
                    "custom_purchase_order_item": None}],
        )
        validate_stock_entry_manufacture(doc)

    def test_out_of_scope_type_unaffected(self):
        """Material Receipt is not in MFG_TYPES — the function short
        -circuits regardless of PP / PO / docstatus."""
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            validate_stock_entry_manufacture,
        )
        doc = _make_doc(
            "Material Receipt",
            production_plan="PP-001",  # irrelevant
            items=[{"s_warehouse": None, "qty": 10}],
        )
        validate_stock_entry_manufacture(doc)
