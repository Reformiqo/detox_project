"""ABP2-I457 reopen (Sahil 2026-06-16) — kill float drift on
WBS Allocation.allocated_amount before the AOS guard runs.

The reopen screenshot showed an edit of a SUBMITTED Material Request
throwing:

  Cannot Update After Submit
  Row #1: Not allowed to change Allocated Amount after submission
  from 3267826.12 to 3267826.11999999996

Root cause: form-side accumulation lands on a float whose shortest
decimal repr is 3267826.1199999996 — a *different* IEEE 754 double
than 3267826.12, even though both look "the same" by eyeball. The DB
read returns Decimal('3267826.12') → cast to float yields the canon
3267826.12. Comparison fails, AOS throws.

Fix: `_round_allocated_amounts` quantizes every WBS Allocation row's
allocated_amount to 2 dp via Decimal before validate_update_after_submit
runs (validate hook fires first in Frappe's _save flow).

Tests below pin the rounding contract — drives _round_allocated_amounts
directly with synthetic docs because the live AOS flow needs a real
submitted MR which would force fixture pollution.
"""
import frappe
from frappe.tests import IntegrationTestCase
from decimal import Decimal


def _doc_with(*amounts):
    rows = [frappe._dict({"allocated_amount": a, "idx": i + 1})
            for i, a in enumerate(amounts)]
    return frappe._dict({"custom_wbs_allocations": rows})


class TestI457AosFloatDrift(IntegrationTestCase):

    def test_drifted_float_rounds_to_canonical(self):
        from detox_project.detox_project.api import _round_allocated_amounts
        doc = _doc_with(3267826.1199999996)
        _round_allocated_amounts(doc)
        # The fix is: after rounding, the in-memory value MUST equal
        # the float that the DB roundtrip produces, i.e. 3267826.12.
        self.assertEqual(
            doc.custom_wbs_allocations[0].allocated_amount, 3267826.12,
            "3267826.1199999996 must quantize to the canonical 3267826.12 "
            "(same float the DB read returns) so AOS comparison succeeds.")

    def test_already_round_value_is_idempotent(self):
        from detox_project.detox_project.api import _round_allocated_amounts
        doc = _doc_with(1000.50, 250.00)
        _round_allocated_amounts(doc)
        self.assertEqual(doc.custom_wbs_allocations[0].allocated_amount, 1000.50)
        self.assertEqual(doc.custom_wbs_allocations[1].allocated_amount, 250.00)
        # Run again — should be a no-op (idempotent).
        _round_allocated_amounts(doc)
        self.assertEqual(doc.custom_wbs_allocations[0].allocated_amount, 1000.50)

    def test_third_decimal_half_up(self):
        from detox_project.detox_project.api import _round_allocated_amounts
        doc = _doc_with(100.125)  # third decimal = 5 → rounds UP to 100.13
        _round_allocated_amounts(doc)
        self.assertEqual(
            doc.custom_wbs_allocations[0].allocated_amount, 100.13,
            "ROUND_HALF_UP required so 100.125 → 100.13 (not banker's-round)")

    def test_none_and_zero_handled(self):
        from detox_project.detox_project.api import _round_allocated_amounts
        # None must NOT crash, zero stays zero.
        doc = _doc_with(None, 0)
        _round_allocated_amounts(doc)
        # None left alone (skip branch), 0 rounds to 0.00.
        self.assertIsNone(doc.custom_wbs_allocations[0].allocated_amount)
        self.assertEqual(doc.custom_wbs_allocations[1].allocated_amount, 0.00)

    def test_aos_equality_holds_after_rounding(self):
        """End-to-end: simulate the DB → form → server round trip.
        The DB-side value is built from Decimal (what MariaDB returns
        for decimal(21,9)); the form-side value is the drifted float.
        After rounding, the two must compare equal — that's the contract
        that makes Frappe's AOS guard pass.
        """
        from detox_project.detox_project.api import _round_allocated_amounts
        db_side = float(Decimal("3267826.12"))         # what _fix_numeric_types gives
        form_side = 3267826.1199999996                  # what the drifted form posts
        self.assertNotEqual(db_side, form_side,
                            "Sanity: these are different floats pre-fix.")
        doc = _doc_with(form_side)
        _round_allocated_amounts(doc)
        self.assertEqual(
            doc.custom_wbs_allocations[0].allocated_amount, db_side,
            "Post-rounding the form-side value MUST equal the DB-side "
            "value or the AOS guard will throw on edit of a submitted doc.")

    def test_hook_wired_on_material_request_validate(self):
        """The fix only works if validate_material_request_budget is
        actually wired as the MR validate hook (since that's where
        _round_allocated_amounts runs)."""
        from detox_project import hooks
        mr = hooks.doc_events.get("Material Request", {})
        self.assertEqual(
            mr.get("validate"),
            "detox_project.detox_project.api.validate_material_request_budget",
            "MR.validate must point at the rounding-capable hook.")
        # And the function must call _round_allocated_amounts first.
        import inspect
        from detox_project.detox_project import api
        src = inspect.getsource(api.validate_material_request_budget)
        self.assertIn("_round_allocated_amounts(doc)", src,
                      "MR validator must call _round_allocated_amounts.")
