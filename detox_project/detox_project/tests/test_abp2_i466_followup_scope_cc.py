"""ABP2-I466 followup (Sahil 2026-06-24) — scope custom_cost_center to
the manufacturing-flow stock_entry_types only.

Previous symptom: every Stock Entry form (incl. Material Receipt /
Issue / Transfer) showed TWO required `Cost Center *` fields side by
side — the stock `cost_center` (forced reqd=1 by
detox_waste_management.enforce_project_cost_center_mandatory) plus the
custom `custom_cost_center` added by I419 Phase 2. Bad UX +
mandatory-check throw on the second field blocked save for any user
who didn't know to fill both.

Fix: change the `custom_cost_center` declaration to reqd=0 and use
mandatory_depends_on / depends_on to scope it to the same set as
_stock_entry_is_in_scope: Manufacture, Material Transfer for
Manufacture, Repack, Send to Subcontractor.

These tests pin the field config + assert the in-scope set matches
the runtime guard so future drift between the two is caught.
"""
import frappe
from frappe.tests import IntegrationTestCase


_IN_SCOPE = {
    "Manufacture",
    "Material Transfer for Manufacture",
    "Repack",
    "Send to Subcontractor",
}


class TestI466FollowupScopeCC(IntegrationTestCase):

    def test_field_is_not_unconditionally_reqd(self):
        reqd = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "reqd",
        )
        self.assertEqual(
            reqd, 0,
            "Stock Entry.custom_cost_center must NOT be reqd=1 — that "
            "forces a second required Cost Center on every Material "
            "Receipt / Issue / Transfer form (Sahil 2026-06-24).",
        )

    def test_mandatory_depends_on_is_in_scope(self):
        mdo = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "mandatory_depends_on",
        )
        self.assertTrue(
            mdo and mdo.startswith("eval:"),
            "custom_cost_center.mandatory_depends_on must be set so the "
            "field is only mandatory on manufacturing-flow SE types.",
        )
        for t in _IN_SCOPE:
            self.assertIn(
                t, mdo,
                f"in-scope type {t!r} missing from mandatory_depends_on "
                f"({mdo!r})",
            )

    def test_depends_on_hides_field_outside_scope(self):
        dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "depends_on",
        )
        self.assertTrue(
            dep and dep.startswith("eval:"),
            "depends_on must hide the field outside the manufacturing "
            "flow, so Material Receipt users don't even see the second "
            "Cost Center.",
        )
        for t in _IN_SCOPE:
            self.assertIn(t, dep)

    def test_runtime_guard_matches_field_scope(self):
        """The Python-side `_stock_entry_is_in_scope` MUST agree with the
        field's depends_on / mandatory_depends_on set. If they drift,
        a save could pass the form check but fail the validate hook (or
        vice versa)."""
        from detox_project.detox_project.overrides.cc_project_guard import (
            _stock_entry_is_in_scope,
        )
        for t in _IN_SCOPE:
            doc = frappe._dict({"stock_entry_type": t})
            self.assertTrue(_stock_entry_is_in_scope(doc),
                            f"_stock_entry_is_in_scope must return True "
                            f"for {t!r} (matches the field scope).")
        for t in ("Material Receipt", "Material Issue", "Material Transfer"):
            doc = frappe._dict({"stock_entry_type": t})
            self.assertFalse(_stock_entry_is_in_scope(doc),
                             f"_stock_entry_is_in_scope must return False "
                             f"for {t!r} so Material Receipt skips the "
                             f"custom_cost_center mandatory check.")
