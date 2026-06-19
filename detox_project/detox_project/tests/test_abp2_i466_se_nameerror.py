"""ABP2-I466 (Raj Tiwari 2026-06-18) — Stock Entry save NameError.

Raj got `NameError: name '_stock_entry_is_in_scope' is not defined`
when saving a Material Receipt SE on detox.erpera.io. Root cause:
`stock_entry_manufacture.py` referenced the symbol in
`inherit_se_from_production_plan` but never imported it from
`cc_project_guard`, where it actually lives. Every Stock Entry save
was hitting the NameError before any business logic could even run.

These tests pin both layers of the fix:
  1. The import is present so the symbol resolves at call-time.
  2. `inherit_se_from_production_plan` is a no-op for out-of-scope
     SE types (Material Receipt, Material Issue, Material Transfer)
     — confirms the early-return path Raj's payload was hitting.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestI466SeImport(IntegrationTestCase):

    def test_symbol_imported_into_manufacture_module(self):
        from detox_project.detox_project.overrides import stock_entry_manufacture as mfg
        self.assertTrue(
            hasattr(mfg, "_stock_entry_is_in_scope"),
            "_stock_entry_is_in_scope must be importable from "
            "stock_entry_manufacture (the module that calls it). "
            "Without the import, every Stock Entry save throws "
            "NameError (Raj Tiwari, 2026-06-18).",
        )

    def test_inherit_no_op_on_material_receipt(self):
        """Material Receipt SEs are out-of-scope — the guard must
        return False so inherit_se_from_production_plan exits clean
        without trying to read production_plan fields."""
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            inherit_se_from_production_plan,
            _stock_entry_is_in_scope,
        )
        doc = frappe._dict({
            "stock_entry_type": "Material Receipt",
            "purpose": "Material Receipt",
            "company": "Saurashtra Enviro Projects Private Limited",
        })
        self.assertFalse(_stock_entry_is_in_scope(doc),
                         "Material Receipt must be out of Phase 3 scope.")
        # Must NOT raise. NameError pre-fix; AttributeError if anyone
        # later swaps the guard for a doc.get that needs a real Document.
        inherit_se_from_production_plan(doc)

    def test_inherit_no_op_on_material_issue(self):
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            inherit_se_from_production_plan,
        )
        doc = frappe._dict({
            "stock_entry_type": "Material Issue",
            "purpose": "Material Issue",
        })
        inherit_se_from_production_plan(doc)  # must not raise

    def test_inherit_runs_for_in_scope_manufacture(self):
        """Sanity: when the SE IS in scope (Manufacture) and has no
        Production Plan, the function still exits cleanly via its
        second early-return."""
        from detox_project.detox_project.overrides.stock_entry_manufacture import (
            inherit_se_from_production_plan,
            _stock_entry_is_in_scope,
        )
        doc = frappe._dict({
            "stock_entry_type": "Manufacture",
            "purpose": "Manufacture",
            "production_plan": "",  # no plan
        })
        self.assertTrue(_stock_entry_is_in_scope(doc))
        inherit_se_from_production_plan(doc)  # must not raise
