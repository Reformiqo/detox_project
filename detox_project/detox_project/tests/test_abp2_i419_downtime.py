"""ABP2-I419 reopen #3 (Raj 2026-06-19) — capture Downtime at the
Stock Entry level.

A Float Custom Field `custom_downtime` on Stock Entry header, inserted
right after `custom_end_time` so it sits inside the Manufacturing
Process section (which itself depends_on the manufacturing-flow SE
types). Same UOM as Production Time via the existing `custom_time_uom`
field.

These tests pin the field config + presence in the Production Day
Summary print template.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestI419Downtime(IntegrationTestCase):

    def test_downtime_custom_field_exists(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_downtime"},
            ["fieldname", "label", "fieldtype", "insert_after",
             "non_negative", "default"],
            as_dict=True,
        )
        self.assertIsNotNone(cf, "custom_downtime CF missing on Stock Entry")
        self.assertEqual(cf.label, "Downtime")
        self.assertEqual(cf.fieldtype, "Float")
        self.assertEqual(
            cf.insert_after, "custom_end_time",
            "Downtime must sit immediately after End Time inside the "
            "Manufacturing Process section.",
        )
        self.assertEqual(cf.non_negative, 1, "Downtime cannot be negative")
        self.assertEqual(cf.default, "0")

    def test_downtime_inherits_section_visibility(self):
        """The field has no depends_on of its own — it inherits from
        the Manufacturing Process section (`custom_process_section`),
        which scopes on stock_entry_type. This means non-MFG SE types
        (Material Receipt / Issue / Transfer) don't see the field even
        though the field itself has no depends_on."""
        dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_downtime"},
            "depends_on",
        )
        self.assertFalse(
            dep,
            "Downtime must NOT have its own depends_on — it inherits "
            "from the parent Manufacturing Process section.",
        )
        section_dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_process_section"},
            "depends_on",
        )
        self.assertTrue(
            section_dep,
            "Manufacturing Process section is missing its depends_on — "
            "Downtime would render on every SE type without it.",
        )

    def test_downtime_in_production_day_summary_print(self):
        html = frappe.db.get_value(
            "Print Format", "Production Day Summary", "html",
        )
        self.assertIn(
            "Downtime", html,
            "Production Day Summary print template must show Downtime "
            "(Raj 2026-06-19).",
        )
        self.assertIn(
            "custom_downtime", html,
            "Print template must reference the field name, not just "
            "the label.",
        )
