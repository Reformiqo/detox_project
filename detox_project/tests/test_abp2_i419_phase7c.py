"""ABP2-I419 Phase 7c (rolled back in Phase 7d).

Phase 7c originally enforced 'one Materials row per Operation'. Sahil
clarified 2026-06-17 (Image #9): each Operation has MULTIPLE Materials
rows (one per RM/Service item), grouped visually under that Operation.

These tests verify the rollback — duplicate operations no longer
throw — plus that the helper is preserved as a no-op so legacy
callers keep working.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from detox_project.detox_project.overrides.cc_project_guard import (
    _check_operation_uniqueness,
    validate_production_plan,
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


class TestABP2I419Phase7cRollback(IntegrationTestCase):

    def test_uniqueness_helper_is_now_a_noop(self):
        """Phase 7d rollback — the uniqueness helper no longer throws
        on duplicate operations. Kept callable for API compatibility."""
        doc = frappe._dict(custom_operations=[
            frappe._dict(operation_name="Trimming"),
            frappe._dict(operation_name="Trimming"),
        ])
        _check_operation_uniqueness(doc)  # must NOT raise

    def test_validate_no_longer_enforces_uniqueness(self):
        """A plan with multiple Materials rows for the SAME operation
        must save cleanly (Sahil's revised model — N rows per Operation)."""
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
                {"operation_name": op, "item_code": item, "item_type": "Service",
                 "standard_rate": 75, "qty_per_unit": 1, "multiply_by": 100,
                 "cost_center": cc, "project": project},
            ],
        })
        try:
            doc.insert(ignore_permissions=True)
            self.assertEqual(len(doc.custom_operations), 2)
            self.assertEqual(doc.custom_operations[0].operation_name, op)
            self.assertEqual(doc.custom_operations[1].operation_name, op)
        finally:
            if doc.name and frappe.db.exists("Production Plan", doc.name):
                frappe.delete_doc(
                    "Production Plan", doc.name,
                    force=1, ignore_permissions=True,
                )

    def test_validate_still_blocks_blank_cc_or_project(self):
        """The Phase 2 CC + Project guard still fires — only the
        Phase 7c uniqueness layer was removed."""
        doc = frappe._dict(
            custom_operations=[],
            custom_fg_items=[],
            get=lambda k, default=None: getattr(doc, k, default) or default,
        )
        # validate_production_plan reads doc.get(PP_CC_FIELD) + doc.get("project");
        # passing a dict-like doc with no CC / Project triggers _check_header.
        doc.custom_cost_center = None
        doc.project = None
        with self.assertRaises(frappe.ValidationError):
            validate_production_plan(doc)
