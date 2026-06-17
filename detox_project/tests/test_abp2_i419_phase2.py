"""ABP2-I419 Phase 2 — CC + Project enforcement + cascade tests.

Covers FR-22..25, VAL-01..02, VAL-06..07, VAL-17 and Process Logic
L05..L06:
  - Custom Fields for Stock Entry / Work Order / Work Order Item land
    on the bench.
  - Property Setters bring Work Order, PO Item, PR Item to reqd=1.
  - The shared validate hook fires on Production Plan, Work Order,
    Stock Entry (header check + row check + copy-from-header).
  - cascade_pp_to_work_orders stamps the plan's CC + project onto
    every linked Work Order.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from detox_project.detox_project.overrides.cc_project_guard import (
    cascade_pp_to_work_orders,
    validate_production_plan,
)


COMPANY = "Saurashtra Enviro Projects Private Limited"


def _bench_fixture():
    project = frappe.db.get_value("Project", {}, "name")
    cc = frappe.db.get_value(
        "Cost Center", {"company": COMPANY, "is_group": 0}, "name")
    wh = frappe.db.get_value(
        "Warehouse", {"company": COMPANY, "is_group": 0}, "name")
    item = frappe.db.get_value(
        "Item", {"is_stock_item": 1, "disabled": 0}, "name")
    return project, cc, wh, item


class TestABP2I419Phase2(IntegrationTestCase):

    # ----- Custom Fields / Property Setters wired -----

    def test_stock_entry_header_cost_center_field_exists(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            ["fieldtype", "reqd", "module"],
            as_dict=True,
        )
        self.assertIsNotNone(cf, "Stock Entry.custom_cost_center missing")
        self.assertEqual(cf.fieldtype, "Link")
        self.assertEqual(cf.reqd, 1)
        self.assertEqual(cf.module, "Detox Project")

    def test_work_order_header_cost_center_field_exists(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Work Order", "fieldname": "custom_cost_center"},
            ["fieldtype", "reqd"], as_dict=True,
        )
        self.assertIsNotNone(cf, "Work Order.custom_cost_center missing")
        self.assertEqual(cf.fieldtype, "Link")
        self.assertEqual(cf.reqd, 1)

    def test_work_order_item_has_cc_and_project_fields(self):
        for fn in ("cost_center", "project"):
            cf = frappe.db.get_value(
                "Custom Field",
                {"dt": "Work Order Item", "fieldname": fn},
                ["fieldtype", "reqd"], as_dict=True,
            )
            self.assertIsNotNone(cf, f"Work Order Item.{fn} missing")
            self.assertEqual(cf.fieldtype, "Link")
            self.assertEqual(cf.reqd, 1)

    def test_work_order_project_is_now_mandatory(self):
        v = frappe.db.get_value(
            "Property Setter",
            {"doc_type": "Work Order", "field_name": "project",
             "property": "reqd"},
            "value",
        )
        self.assertEqual(v, "1")

    def test_po_item_cc_and_project_are_now_mandatory(self):
        for f in ("cost_center", "project"):
            v = frappe.db.get_value(
                "Property Setter",
                {"doc_type": "Purchase Order Item", "field_name": f,
                 "property": "reqd"},
                "value",
            )
            self.assertEqual(v, "1", f"Purchase Order Item.{f} reqd should be 1")

    def test_pr_item_cc_and_project_are_now_mandatory(self):
        for f in ("cost_center", "project"):
            v = frappe.db.get_value(
                "Property Setter",
                {"doc_type": "Purchase Receipt Item", "field_name": f,
                 "property": "reqd"},
                "value",
            )
            self.assertEqual(v, "1", f"Purchase Receipt Item.{f} reqd should be 1")

    # ----- Validate hook behaviour -----

    def test_pp_without_cc_blocks_save(self):
        project, cc, wh, item = _bench_fixture()
        if not all([project, cc, wh, item]):
            self.skipTest("Bench lacks a fixture")
        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": COMPANY,
            "custom_no_bom": 1,
            "project": project,
            "posting_date": today(),
            "custom_fg_items": [{
                "item_code": item, "qty_to_manufacture": 100,
                "planned_date": today(), "fg_warehouse": wh,
                "standard_costing_rate": 250, "total_standard_cost": 25000,
                "cost_center": cc, "project": project,
            }],
        })
        with self.assertRaises(frappe.ValidationError) as cm:
            doc.insert(ignore_permissions=True)
        self.assertIn("Cost Center", str(cm.exception))

    def test_pp_rows_inherit_cc_and_project_from_header(self):
        """A row left blank for CC/project must inherit from the header
        and save successfully — the copy-from-header path in
        _check_rows."""
        project, cc, wh, item = _bench_fixture()
        if not all([project, cc, wh, item]):
            self.skipTest("Bench lacks a fixture")
        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": COMPANY,
            "custom_no_bom": 1,
            "custom_cost_center": cc,
            "project": project,
            "posting_date": today(),
            "custom_fg_items": [{
                "item_code": item, "qty_to_manufacture": 100,
                "planned_date": today(), "fg_warehouse": wh,
                "standard_costing_rate": 250, "total_standard_cost": 25000,
                # NO cost_center, NO project — should inherit.
            }],
        })
        try:
            doc.insert(ignore_permissions=True)
            self.assertEqual(doc.custom_fg_items[0].cost_center, cc)
            self.assertEqual(doc.custom_fg_items[0].project, project)
        finally:
            if doc.name and frappe.db.exists("Production Plan", doc.name):
                frappe.delete_doc(
                    "Production Plan", doc.name,
                    force=1, ignore_permissions=True,
                )

    # ----- Cascade -----

    def test_cascade_pp_to_work_orders_stamps_cc_and_project(self):
        """cascade_pp_to_work_orders writes the plan's CC + project onto
        every Work Order linked back to the plan (docstatus < 2).

        Direct call to the hook function with synthetic state — no need
        to actually submit a Production Plan, which has heavy ERPNext
        side-effects we don't want in a unit test.
        """
        project, cc, _, _ = _bench_fixture()
        if not all([project, cc]):
            self.skipTest("Bench lacks a fixture")

        # Build a stub Work Order pointing back at a fake plan name we
        # control. Easier to manufacture via direct SQL than the doc API
        # because Work Order's full validate path needs a BOM.
        from frappe.utils import random_string
        fake_plan = f"TEST-PP-{random_string(6)}"

        # Insert a minimal Work Order via SQL (bypass validate).
        wo_name = f"TEST-WO-{random_string(6)}"
        frappe.db.sql(
            """INSERT INTO `tabWork Order`
               (name, production_plan, docstatus, owner, modified_by,
                creation, modified, production_item, qty)
               VALUES (%s, %s, 0, 'Administrator', 'Administrator',
                       NOW(), NOW(), 'TEST-ITEM', 1)""",
            (wo_name, fake_plan),
        )
        try:
            # Call cascade with a stub plan doc that has CC + project.
            stub = frappe._dict(
                name=fake_plan,
                custom_cost_center=cc,
                project=project,
            )
            cascade_pp_to_work_orders(stub)

            updated = frappe.db.get_value(
                "Work Order", wo_name,
                ["custom_cost_center", "project"],
                as_dict=True,
            )
            self.assertEqual(updated.custom_cost_center, cc)
            self.assertEqual(updated.project, project)
        finally:
            frappe.db.sql(
                "DELETE FROM `tabWork Order` WHERE name=%s", wo_name)

    def test_cascade_ignores_cancelled_work_orders(self):
        """docstatus=2 (Cancelled) WOs should NOT receive cascaded values."""
        project, cc, _, _ = _bench_fixture()
        if not all([project, cc]):
            self.skipTest("Bench lacks a fixture")
        from frappe.utils import random_string
        fake_plan = f"TEST-PP-{random_string(6)}"
        wo_name = f"TEST-WO-{random_string(6)}"
        frappe.db.sql(
            """INSERT INTO `tabWork Order`
               (name, production_plan, docstatus, owner, modified_by,
                creation, modified, production_item, qty)
               VALUES (%s, %s, 2, 'Administrator', 'Administrator',
                       NOW(), NOW(), 'TEST-ITEM', 1)""",
            (wo_name, fake_plan),
        )
        try:
            cascade_pp_to_work_orders(frappe._dict(
                name=fake_plan,
                custom_cost_center=cc,
                project=project,
            ))
            updated = frappe.db.get_value(
                "Work Order", wo_name,
                ["custom_cost_center", "project"],
                as_dict=True,
            )
            # Cancelled WO must keep its (NULL) state, NOT be updated.
            self.assertFalse(updated.custom_cost_center)
            self.assertFalse(updated.project)
        finally:
            frappe.db.sql(
                "DELETE FROM `tabWork Order` WHERE name=%s", wo_name)
