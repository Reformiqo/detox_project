"""ABP2-I419 Phase 7d — Per-Operation editable tables + JSON layout fix.

The heavy lifting of Phase 7d is in the Client Script
(public/js/production_plan_custom.js) — rendering per-Operation
editable cards, Dialog-based add/edit/delete, hidden canonical grid.
That UI is verified via Playwright walkthrough (Aarif's QA flow), NOT
in this test file.

These tests assert the few server-side / JSON anchors that the
Client Script depends on:
  - Process child's operation_seq is no longer in_list_view, so the
    pencil edit modal has at least one field to show.
  - Saving a plan with multiple Materials rows for the same Operation
    works (the rollback of Phase 7c).
  - The custom_operations_view HTML field is still present (the
    Client Script renders into it).
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase


class TestABP2I419Phase7d(IntegrationTestCase):

    def test_process_seq_not_in_list_view(self):
        """The pencil edit modal opens reliably only when at least one
        field is NOT in_list_view. Phase 7d removed in_list_view from
        operation_seq for this reason."""
        meta = frappe.get_meta("Detox Production Plan Process")
        df = meta.get_field("operation_seq")
        self.assertIsNotNone(df)
        self.assertEqual(
            df.in_list_view, 0,
            "operation_seq must NOT be in_list_view (Phase 7d fix for the "
            "Process row pencil edit icon)",
        )

    def test_operations_view_html_field_present(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Production Plan", "fieldname": "custom_operations_view"},
            "fieldtype",
        )
        self.assertEqual(
            cf, "HTML",
            "custom_operations_view must remain HTML — Client Script renders "
            "the per-Operation cards into it",
        )

    def test_materials_table_allows_multiple_rows_per_operation(self):
        """Sahil's Image #9 — each Operation has multiple Materials rows
        (one Raw Material + one Service, etc). Phase 7c's uniqueness
        constraint was a misread; this test pins the rollback."""
        company = "Saurashtra Enviro Projects Private Limited"
        project = frappe.db.get_value("Project", {}, "name")
        cc = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name")
        wh = frappe.db.get_value(
            "Warehouse", {"company": company, "is_group": 0}, "name")
        item = frappe.db.get_value(
            "Item", {"is_stock_item": 1, "disabled": 0}, "name")
        ws = frappe.db.get_value("Workstation", {}, "name")
        op = frappe.db.get_value("Operation", {}, "name")
        if not all([project, cc, wh, item, ws, op]):
            self.skipTest("Bench lacks a fixture")

        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": company,
            "custom_no_bom": 1,
            "custom_cost_center": cc,
            "project": project,
            "posting_date": frappe.utils.today(),
            "custom_processes": [
                {"operation_name": op, "workstation": ws, "operation_seq": 1},
            ],
            "custom_fg_items": [{
                "item_code": item, "qty_to_manufacture": 100,
                "planned_date": frappe.utils.today(), "fg_warehouse": wh,
                "standard_costing_rate": 250, "total_standard_cost": 25000,
                "cost_center": cc, "project": project,
            }],
            "custom_operations": [
                {"operation_name": op, "item_code": item,
                 "item_type": "Raw Material",
                 "standard_rate": 50, "qty_per_unit": 2, "multiply_by": 200,
                 "cost_center": cc, "project": project},
                {"operation_name": op, "item_code": item,
                 "item_type": "Service",
                 "standard_rate": 75, "qty_per_unit": 1, "multiply_by": 100,
                 "cost_center": cc, "project": project},
                {"operation_name": op, "item_code": item,
                 "item_type": "Raw Material",
                 "standard_rate": 25, "qty_per_unit": 5, "multiply_by": 500,
                 "cost_center": cc, "project": project},
            ],
        })
        try:
            doc.insert(ignore_permissions=True)
            self.assertEqual(len(doc.custom_operations), 3,
                             "Three rows for the same Operation should save")
            for row in doc.custom_operations:
                self.assertEqual(row.operation_name, op)
        finally:
            if doc.name and frappe.db.exists("Production Plan", doc.name):
                frappe.delete_doc(
                    "Production Plan", doc.name,
                    force=1, ignore_permissions=True,
                )
