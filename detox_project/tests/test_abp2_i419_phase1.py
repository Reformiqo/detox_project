"""ABP2-I419 Phase 1 — Production Plan No-BOM foundation tests.

Covers the foundation layer:
  - Both child DocTypes exist on the bench after migrate.
  - All Custom Fields are wired on Production Plan with the FRD's
    fieldnames and types.
  - Property Setters land (project mandatory, po_items optional).
  - A draft Production Plan can be created with custom_no_bom=1 and
    rows in both custom tables — the FRD's acceptance criterion for
    Phase 1 (FR-01 'Plan can be created, saved … with no BOM linked').

Phase 2+ behaviour (CC/Project cascade, submit-time validate, Stock
Entry customizations, reports) is NOT exercised here.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today


class TestABP2I419Phase1Foundation(IntegrationTestCase):

    def test_child_doctypes_exist(self):
        for dt in ("Detox Production Plan FG", "Detox Production Plan Operation"):
            self.assertTrue(
                frappe.db.exists("DocType", dt),
                f"Child DocType '{dt}' must exist on the bench after migrate.",
            )

    def test_production_plan_custom_fields_wired(self):
        expected = {
            "custom_no_bom": "Check",
            "custom_cost_center": "Link",
            "custom_no_bom_section": "Section Break",
            "custom_fg_items": "Table",
            "custom_operations_section": "Section Break",
            "custom_operations": "Table",
        }
        for fn, ftype in expected.items():
            cf = frappe.db.get_value(
                "Custom Field",
                {"dt": "Production Plan", "fieldname": fn},
                ["fieldtype", "module"],
                as_dict=True,
            )
            self.assertIsNotNone(
                cf, f"Custom Field Production Plan.{fn} must exist."
            )
            self.assertEqual(
                cf.fieldtype, ftype,
                f"{fn} fieldtype should be {ftype}, got {cf.fieldtype}.",
            )
            self.assertEqual(
                cf.module, "Detox Project",
                f"{fn} should belong to Detox Project module.",
            )

    def test_table_fields_target_correct_child_doctypes(self):
        self.assertEqual(
            frappe.db.get_value(
                "Custom Field",
                {"dt": "Production Plan", "fieldname": "custom_fg_items"},
                "options",
            ),
            "Detox Production Plan FG",
        )
        self.assertEqual(
            frappe.db.get_value(
                "Custom Field",
                {"dt": "Production Plan", "fieldname": "custom_operations"},
                "options",
            ),
            "Detox Production Plan Operation",
        )

    def test_project_is_mandatory_via_property_setter(self):
        ps = frappe.db.get_value(
            "Property Setter",
            {"doc_type": "Production Plan", "field_name": "project",
             "property": "reqd"},
            "value",
        )
        self.assertEqual(ps, "1",
                         "Production Plan.project must be reqd=1 (FR-22).")

    def test_po_items_is_optional_to_allow_no_bom_mode(self):
        ps = frappe.db.get_value(
            "Property Setter",
            {"doc_type": "Production Plan", "field_name": "po_items",
             "property": "reqd"},
            "value",
        )
        self.assertEqual(
            ps, "0",
            "po_items must be reqd=0 so No-BOM plans can save without "
            "a standard Assembly Items row.",
        )

    def test_can_create_draft_no_bom_plan(self):
        """End-to-end Phase 1 acceptance: a draft Production Plan in
        No-BOM mode with rows in both custom tables saves cleanly.
        Picks any in-house Cost Center / Project / Item that exist on
        the bench; skips if no fixture is available."""
        company = frappe.db.get_value(
            "Company", {}, "name") or "Saurashtra Enviro Projects Private Limited"
        project = frappe.db.get_value("Project", {}, "name")
        cc = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name")
        wh = frappe.db.get_value(
            "Warehouse", {"company": company, "is_group": 0}, "name")
        item = frappe.db.get_value(
            "Item", {"is_stock_item": 1, "disabled": 0}, "name")
        if not all([project, cc, wh, item]):
            self.skipTest("Bench lacks a fixture (Project / CC / Warehouse / Item)")

        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": company,
            "custom_no_bom": 1,
            "custom_cost_center": cc,
            "project": project,
            "posting_date": today(),
            "custom_fg_items": [{
                "item_code": item,
                "qty_to_manufacture": 100,
                "planned_date": today(),
                "fg_warehouse": wh,
                "standard_costing_rate": 250,
                "total_standard_cost": 25000,
                "cost_center": cc,
                "project": project,
            }],
            "custom_operations": [{
                "operation_name": "Filling",
                "operation_seq": 1,
                "item_code": item,
                "item_type": "Raw Material",
                "standard_rate": 50,
                "qty_per_unit": 2,
                "multiply_by": 200,
                "cost_center": cc,
                "project": project,
            }],
        })
        try:
            doc.insert(ignore_permissions=True)
            self.assertTrue(doc.name)
            self.assertEqual(doc.custom_no_bom, 1)
            self.assertEqual(len(doc.custom_fg_items), 1)
            self.assertEqual(len(doc.custom_operations), 1)
            self.assertEqual(doc.custom_fg_items[0].item_code, item)
            self.assertEqual(doc.custom_operations[0].operation_name, "Filling")
        finally:
            if doc.name and frappe.db.exists("Production Plan", doc.name):
                frappe.delete_doc(
                    "Production Plan", doc.name,
                    force=1, ignore_permissions=True,
                )

    def test_project_must_be_set_to_save(self):
        """Property Setter project.reqd=1 means saving a plan without
        a header project raises a MandatoryError."""
        company = frappe.db.get_value(
            "Company", {}, "name") or "Saurashtra Enviro Projects Private Limited"
        project = frappe.db.get_value("Project", {}, "name")
        cc = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name")
        wh = frappe.db.get_value(
            "Warehouse", {"company": company, "is_group": 0}, "name")
        item = frappe.db.get_value(
            "Item", {"is_stock_item": 1, "disabled": 0}, "name")
        if not all([project, cc, wh, item]):
            self.skipTest("Bench lacks a fixture (Project / CC / Warehouse / Item)")
        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": company,
            "custom_no_bom": 1,
            "custom_cost_center": cc,
            "posting_date": today(),
            # Intentionally NO header `project` — must blow up on save.
            "custom_fg_items": [{
                "item_code": item,
                "qty_to_manufacture": 100,
                "planned_date": today(),
                "fg_warehouse": wh,
                "standard_costing_rate": 250,
                "total_standard_cost": 25000,
                "cost_center": cc,
                "project": project,  # row project required by child reqd=1.
            }],
        })
        with self.assertRaises(frappe.MandatoryError):
            doc.insert(ignore_permissions=True)
