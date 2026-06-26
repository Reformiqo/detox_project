"""ABP2-I466 followup → SE refactor (Sahil 2026-06-26).

The ABP2-I466 followup was about scoping the `custom_cost_center`
Custom Field's `mandatory_depends_on` and `depends_on` to the
manufacturing-flow SE types only.

That whole concern is now moot — the SE refactor (2026-06-26) DROPPED
the `custom_cost_center` Custom Field on Stock Entry entirely. ERPNext
16.25+ ships a standard `cost_center` field on the Stock Entry header
which is now canonical.

These tests just pin that the legacy CF is gone after migrate.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestI466FollowupScopeCC(IntegrationTestCase):

    def test_custom_cost_center_cf_is_gone(self):
        """Stock Entry should not have a Custom Field named
        custom_cost_center anymore — the standard field replaces it."""
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "name",
        )
        self.assertIsNone(
            cf,
            "Stock Entry-custom_cost_center CF must be dropped — "
            "drop_se_custom_cost_center_field runs on after_migrate.",
        )

    def test_runtime_guard_still_scoped_correctly(self):
        """The Python-side `_stock_entry_is_in_scope` MUST still
        identify the manufacturing-flow SE types. cc_project_guard
        now reads from the standard `cost_center` field for these
        types."""
        from detox_project.detox_project.overrides.cc_project_guard import (
            _stock_entry_is_in_scope,
        )
        for t in ("Manufacture", "Material Transfer for Manufacture",
                  "Repack", "Send to Subcontractor"):
            self.assertTrue(
                _stock_entry_is_in_scope(frappe._dict({"stock_entry_type": t})),
                f"_stock_entry_is_in_scope must return True for {t!r}",
            )
        for t in ("Material Receipt", "Material Issue", "Material Transfer"):
            self.assertFalse(
                _stock_entry_is_in_scope(frappe._dict({"stock_entry_type": t})),
                f"_stock_entry_is_in_scope must return False for {t!r}",
            )
