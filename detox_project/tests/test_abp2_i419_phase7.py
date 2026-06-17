"""ABP2-I419 Phase 7 — Process header table + per-Operation RM grouping."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase


class TestABP2I419Phase7(IntegrationTestCase):

    def test_process_child_doctype_exists(self):
        self.assertTrue(
            frappe.db.exists("DocType", "Detox Production Plan Process"),
        )

    def test_process_table_has_operation_and_workstation(self):
        meta = frappe.get_meta("Detox Production Plan Process")
        for fn in ("operation_name", "workstation"):
            df = meta.get_field(fn)
            self.assertIsNotNone(df, f"Detox Production Plan Process.{fn} must exist")
            self.assertEqual(df.reqd, 1, f"{fn} must be reqd=1")
            self.assertEqual(
                df.fieldtype, "Link",
                f"{fn} must be a Link field (Phase 7b)",
            )
        self.assertEqual(
            meta.get_field("workstation").options, "Workstation",
            "workstation must link to native ERPNext Workstation",
        )
        self.assertEqual(
            meta.get_field("operation_name").options, "Operation",
            "operation_name must link to ERPNext Operation master (Phase 7b)",
        )

    def test_materials_table_operation_is_link_to_operation(self):
        df = frappe.get_meta("Detox Production Plan Operation").get_field(
            "operation_name")
        self.assertEqual(df.fieldtype, "Link",
                         "Materials row operation_name must be Link (Phase 7b)")
        self.assertEqual(df.options, "Operation")

    def test_pp_custom_processes_field_present(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Production Plan", "fieldname": "custom_processes"},
            ["fieldtype", "options", "module"], as_dict=True,
        )
        self.assertIsNotNone(cf, "PP.custom_processes missing")
        self.assertEqual(cf.fieldtype, "Table")
        self.assertEqual(cf.options, "Detox Production Plan Process")
        self.assertEqual(cf.module, "Detox Project")

    def test_pp_operations_view_html_field_present(self):
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Production Plan", "fieldname": "custom_operations_view"},
            ["fieldtype", "depends_on"], as_dict=True,
        )
        self.assertIsNotNone(cf, "PP.custom_operations_view missing")
        self.assertEqual(cf.fieldtype, "HTML")
        self.assertEqual(cf.depends_on, "eval:doc.custom_no_bom")

    def test_can_save_plan_with_processes_and_grouped_ops(self):
        company = "Saurashtra Enviro Projects Private Limited"
        project = frappe.db.get_value("Project", {}, "name")
        cc = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name")
        wh = frappe.db.get_value(
            "Warehouse", {"company": company, "is_group": 0}, "name")
        item = frappe.db.get_value(
            "Item", {"is_stock_item": 1, "disabled": 0}, "name")
        ws = frappe.db.get_value("Workstation", {}, "name")
        # Phase 7b — operation_name is now Link → Operation, so we need
        # actual Operation master records to populate it.
        op_names = [r[0] for r in frappe.db.sql(
            "SELECT name FROM `tabOperation` LIMIT 2")]
        if not all([project, cc, wh, item, ws]) or len(op_names) < 1:
            self.skipTest("Bench lacks a fixture (Project / CC / WH / Item / Workstation / Operation)")
        op1 = op_names[0]
        op2 = op_names[1] if len(op_names) > 1 else op1

        doc = frappe.get_doc({
            "doctype": "Production Plan",
            "company": company,
            "custom_no_bom": 1,
            "custom_cost_center": cc,
            "project": project,
            "posting_date": frappe.utils.today(),
            "custom_processes": [
                {"operation_name": op1, "workstation": ws, "operation_seq": 1},
            ] + ([{"operation_name": op2, "workstation": ws, "operation_seq": 2}]
                 if op2 != op1 else []),
            "custom_fg_items": [{
                "item_code": item, "qty_to_manufacture": 100,
                "planned_date": frappe.utils.today(), "fg_warehouse": wh,
                "standard_costing_rate": 250, "total_standard_cost": 25000,
                "cost_center": cc, "project": project,
            }],
            "custom_operations": [
                {"operation_name": op1, "item_code": item, "item_type": "Raw Material",
                 "standard_rate": 50, "qty_per_unit": 2, "multiply_by": 200,
                 "cost_center": cc, "project": project},
            ],
        })
        try:
            doc.insert(ignore_permissions=True)
            self.assertGreaterEqual(len(doc.custom_processes), 1)
            self.assertEqual(doc.custom_processes[0].operation_name, op1)
            self.assertEqual(doc.custom_processes[0].workstation, ws)
            self.assertEqual(doc.custom_operations[0].operation_name, op1)
        finally:
            if doc.name and frappe.db.exists("Production Plan", doc.name):
                frappe.delete_doc(
                    "Production Plan", doc.name,
                    force=1, ignore_permissions=True,
                )
