"""ABP2-I466 followup (Sahil 2026-06-24) — scope custom_cost_center
MANDATORY-NESS to the manufacturing-flow stock_entry_types only.

The original followup also HID the field outside that scope on the
premise that there was a second Cost Center field on Material Receipt
/ Issue / Transfer forms. ABP2-I466 re-reopen #3 (Sahil 2026-06-25)
established that premise was a misdiagnosis — meta probe confirms
`custom_cost_center` is the ONLY Cost Center field on Stock Entry
header (no standard `cost_center` exists there, no other Custom
Field). Hiding the field left non-MFG types with no Cost Center
anywhere.

Current state pinned by these tests:
  - reqd=0 (the I466 followup result — not unconditionally required)
  - mandatory_depends_on scoped to MFG_TYPES (red asterisk + cc_project
    guard server-side throw)
  - depends_on EMPTY (field always visible — re-reopen #3)
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
            "would force a required Cost Center on every Material "
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

    def test_depends_on_is_empty_field_always_visible(self):
        """Re-reopen #3 (Sahil 2026-06-25): the user must see the Cost
        Center field on every Stock Entry type. depends_on MUST be
        empty — never scope this field's visibility."""
        dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "depends_on",
        )
        self.assertFalse(
            dep,
            f"depends_on must be empty so the field is visible on every "
            f"Stock Entry type. Scoping the VISIBILITY hides the field "
            f"from non-MFG forms — those users have no other Cost "
            f"Center field anywhere. Saw: {dep!r}",
        )

    def test_runtime_guard_matches_field_scope(self):
        """The Python-side `_stock_entry_is_in_scope` MUST agree with the
        field's mandatory_depends_on set. If they drift, a save could
        pass the form check but fail the validate hook (or vice versa)."""
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
