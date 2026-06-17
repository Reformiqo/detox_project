"""ABP2-I419 Phase 7c — Process → Materials autosync + Operation uniqueness."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from detox_project.detox_project.overrides.cc_project_guard import (
    _check_operation_uniqueness,
)


COMPANY = "Saurashtra Enviro Projects Private Limited"


def _fixture():
    project = frappe.db.get_value("Project", {}, "name")
    cc = frappe.db.get_value(
        "Cost Center", {"company": COMPANY, "is_group": 0}, "name")
    wh = frappe.db.get_value(
        "Warehouse", {"company": COMPANY, "is_group": 0}, "name")
    item = frappe.db.get_value(
        "Item", {"is_stock_item": 1, "disabled": 0}, "name")
    ws = frappe.db.get_value("Workstation", {}, "name")
    op_rows = [r[0] for r in frappe.db.sql(
        "SELECT name FROM `tabOperation` LIMIT 2")]
    return project, cc, wh, item, ws, op_rows


class TestABP2I419Phase7c(IntegrationTestCase):

    def test_uniqueness_helper_passes_on_distinct_operations(self):
        if len(_fixture()[5]) < 2:
            self.skipTest("Need at least 2 Operations on the bench")
        op1, op2 = _fixture()[5][:2]
        doc = frappe._dict(custom_operations=[
            frappe._dict(operation_name=op1),
            frappe._dict(operation_name=op2),
        ])
        # No throw expected.
        _check_operation_uniqueness(doc)

    def test_uniqueness_helper_throws_on_duplicate(self):
        ops = _fixture()[5]
        if not ops:
            self.skipTest("Bench has no Operation master rows")
        op1 = ops[0]
        doc = frappe._dict(custom_operations=[
            frappe._dict(operation_name=op1),
            frappe._dict(operation_name=op1),
        ])
        with self.assertRaises(frappe.ValidationError) as cm:
            _check_operation_uniqueness(doc)
        msg = str(cm.exception)
        self.assertIn(op1, msg)
        self.assertIn("only once", msg)

    def test_save_blocks_duplicate_operation_in_materials(self):
        project, cc, wh, item, ws, ops = _fixture()
        if not all([project, cc, wh, item, ws]) or not ops:
            self.skipTest("Bench lacks a fixture")
        op = ops[0]
        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": COMPANY,
            "custom_no_bom": 1,
            "custom_cost_center": cc,
            "project": project,
            "posting_date": today(),
            "custom_processes": [
                {"operation_name": op, "workstation": ws, "operation_seq": 1},
            ],
            "custom_fg_items": [{
                "item_code": item, "qty_to_manufacture": 100,
                "planned_date": today(), "fg_warehouse": wh,
                "standard_costing_rate": 250, "total_standard_cost": 25000,
                "cost_center": cc, "project": project,
            }],
            "custom_operations": [
                {"operation_name": op, "item_code": item, "item_type": "Raw Material",
                 "standard_rate": 50, "qty_per_unit": 2, "multiply_by": 200,
                 "cost_center": cc, "project": project},
                {"operation_name": op, "item_code": item, "item_type": "Raw Material",
                 "standard_rate": 75, "qty_per_unit": 1, "multiply_by": 100,
                 "cost_center": cc, "project": project},
            ],
        })
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_save_passes_with_one_row_per_operation(self):
        project, cc, wh, item, ws, ops = _fixture()
        if not all([project, cc, wh, item, ws]) or not ops:
            self.skipTest("Bench lacks a fixture")
        op = ops[0]
        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": COMPANY,
            "custom_no_bom": 1,
            "custom_cost_center": cc,
            "project": project,
            "posting_date": today(),
            "custom_processes": [
                {"operation_name": op, "workstation": ws, "operation_seq": 1},
            ],
            "custom_fg_items": [{
                "item_code": item, "qty_to_manufacture": 100,
                "planned_date": today(), "fg_warehouse": wh,
                "standard_costing_rate": 250, "total_standard_cost": 25000,
                "cost_center": cc, "project": project,
            }],
            "custom_operations": [
                {"operation_name": op, "item_code": item, "item_type": "Raw Material",
                 "standard_rate": 50, "qty_per_unit": 2, "multiply_by": 200,
                 "cost_center": cc, "project": project},
            ],
        })
        try:
            doc.insert(ignore_permissions=True)
            self.assertEqual(len(doc.custom_operations), 1)
            self.assertEqual(doc.custom_operations[0].operation_name, op)
        finally:
            if doc.name and frappe.db.exists("Production Plan", doc.name):
                frappe.delete_doc(
                    "Production Plan", doc.name,
                    force=1, ignore_permissions=True,
                )

    def test_blank_operation_rows_dont_collide(self):
        """Rows with blank operation_name should NOT trigger the
        duplicate check (the row guard for CC/Project will reject
        them separately if they're persisted)."""
        doc = frappe._dict(custom_operations=[
            frappe._dict(operation_name=""),
            frappe._dict(operation_name=""),
        ])
        _check_operation_uniqueness(doc)  # must not raise
