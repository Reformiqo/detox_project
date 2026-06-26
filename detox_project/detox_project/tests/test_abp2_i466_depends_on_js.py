"""ABP2-I466 depends_on JS test → SE refactor (Sahil 2026-06-26).

This file used to pin the depends_on / mandatory_depends_on
expression syntax on Stock Entry.custom_cost_center (the JS/Python
`in [...]` trap). The whole Custom Field has been dropped now (the
standard ERPNext cost_center field replaces it), so the depends_on
contract is gone too.

Kept as a sentinel: assert the CF is gone so we notice if a future
refactor accidentally re-creates it.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestI466DependsOnJS(IntegrationTestCase):

    def test_stock_entry_custom_cost_center_cf_does_not_exist(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "name",
        )
        self.assertIsNone(
            cf,
            "Stock Entry-custom_cost_center CF must stay dropped — "
            "ERPNext 16.25+ ships the standard cost_center field "
            "which is canonical now.",
        )
