"""CR-04 — Material Transfer for Manufacture BEFORE the Manufacture entry.
DETOX Production Change-Set FRD (Change Set 1).

Exercises the exact server logic wired onto Stock Entry by the manager:
  CVAL-08 / CL-10  before_submit blocks a Manufacture with no submitted
                   Material Transfer for Manufacture behind it — unless the
                   role-gated exception flag is set (CR-04.6).
  CVAL-09 / CL-10  before_submit blocks consuming more than was transferred
                   to WIP, per item, across the plan/process.
  CL-11            validate defaults the Manufacture source warehouse to the
                   transfer's WIP warehouse.
  CL-12            on_submit / on_cancel rollup of transferred / consumed qty
                   onto the Table-2 (Detox Production Plan Operation) row.
  CL-13 / CZ-40    make_material_transfer_for_manufacture builder.
  CZ-37 / CZ-38    Custom Fields present.

Testing approach (no frappe.db stubbing — the real SQL runs so a wrong
column name surfaces immediately):
  * "Already-submitted" transfer / manufacture entries are seeded as REAL
    Stock Entry docs inserted as drafts (allow_zero_valuation_rate, so no
    valuation master is needed) then flipped to docstatus=1 with db_set —
    exactly what the CVAL/rollup SQL reads. No full submit (no SLE/GL), so
    it is deterministic on any site.
  * The Table-2 operation rows the rollup writes to live on a throwaway
    DRAFT clone of a real submitted No-BOM plan, created per test and rolled
    back by IntegrationTestCase.
  * The doc-under-test is a real, form-shaped in-memory Stock Entry; the
    hook functions are called directly (the exact functions doc_events
    invoke), never a synthetic short-circuit.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from detox_project.detox_project.change_set import cr04_material_transfer as cr
from detox_project.detox_project.overrides.stock_entry_manufacture import (
    get_operation_rm_rows,
)

JS_PATH = ("/home/frappe/v16/apps/detox_project/detox_project/"
           "public/js/production_plan_custom.js")


class TestCR04MaterialTransfer(IntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cr.install()  # code-first CFs (idempotent); manager wires after_migrate

        # A real submitted No-BOM plan that HAS operation rm rows — used
        # read-only by the CL-13 builder test.
        row = frappe.db.sql(
            """SELECT p.name AS plan, o.operation_name AS op,
                      p.company AS company, p.custom_cost_center AS cc,
                      p.project AS project
               FROM `tabProduction Plan` p
               JOIN `tabDetox Production Plan Operation` o ON o.parent = p.name
               WHERE p.docstatus = 1 AND p.custom_no_bom = 1
                 AND IFNULL(o.item_code, '') != ''
               LIMIT 1""",
            as_dict=True,
        )
        assert row, "no submitted No-BOM Production Plan with operation rows on this site"
        cls.sub_plan = row[0].plan
        cls.sub_op = row[0].op
        cls.company = row[0].company
        cls.cc = row[0].cc
        cls.project = row[0].project

        whs = frappe.db.sql_list(
            """SELECT name FROM `tabWarehouse`
               WHERE company = %s AND is_group = 0 AND disabled = 0 LIMIT 2""",
            cls.company,
        )
        assert len(whs) >= 2, "need at least two warehouses on the company"
        cls.wh_src, cls.wh_wip = whs[0], whs[1]

        items = frappe.db.sql_list(
            """SELECT name FROM `tabItem`
               WHERE is_stock_item = 1 AND disabled = 0
                 AND IFNULL(is_fixed_asset, 0) = 0 LIMIT 3""")
        assert len(items) >= 3, "need at least three stock items"
        cls.item_a, cls.item_b, cls.item_fg = items[0], items[1], items[2]

    # ------------------------------------------------------------------
    # Per-test: a throwaway DRAFT plan with two clean operation rows so
    # the CL-12 rollup has deterministic Table-2 targets. Rolled back.
    # ------------------------------------------------------------------
    def setUp(self):
        src = frappe.get_doc("Production Plan", self.sub_plan)
        clone = frappe.copy_doc(src)
        # copy_doc preserves the source docstatus (1); force a genuine draft.
        clone.docstatus = 0
        clone.custom_operations = []
        clone.append("custom_operations", {
            "operation_name": self.sub_op, "item_code": self.item_a,
            "qty_per_unit": 1, "item_type": "Raw Material",
        })
        clone.append("custom_operations", {
            "operation_name": self.sub_op, "item_code": self.item_b,
            "qty_per_unit": 1, "item_type": "Raw Material",
        })
        clone.insert(ignore_permissions=True, ignore_mandatory=True)
        self.plan = clone.name
        self.op = self.sub_op

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _seed_submitted_se(self, *, stock_entry_type, rows, process=None):
        """Insert a REAL draft Stock Entry then flip it to docstatus=1 so
        the CVAL/rollup SQL reads it. No full submit."""
        items = []
        for r in rows:
            item = {
                "item_code": r["item_code"], "qty": r["qty"],
                "cost_center": self.cc, "project": self.project,
                "basic_rate": r.get("basic_rate", 1),
                "allow_zero_valuation_rate": 1,
                "is_finished_item": r.get("is_finished_item", 0),
            }
            if r.get("s_warehouse"):
                item["s_warehouse"] = r["s_warehouse"]
            if r.get("t_warehouse"):
                item["t_warehouse"] = r["t_warehouse"]
            items.append(item)
        se = frappe.get_doc({
            "doctype": "Stock Entry", "stock_entry_type": stock_entry_type,
            "company": self.company, "production_plan": self.plan,
            "custom_process_selection": process or self.op,
            "cost_center": self.cc, "project": self.project,
            "from_warehouse": self.wh_src, "to_warehouse": self.wh_wip,
            "items": items,
        })
        se.insert(ignore_permissions=True)
        frappe.db.set_value("Stock Entry", se.name, "docstatus", 1,
                            update_modified=False)
        return se.name

    def _mfg_doc(self, *, source_rows, allow=0, process=None):
        """In-memory Manufacture SE (not inserted) for calling the hooks
        directly. source_rows: list of (item_code, qty, s_warehouse|None)."""
        items = []
        for item_code, qty, s_wh in source_rows:
            items.append({
                "item_code": item_code, "qty": qty,
                "s_warehouse": s_wh, "is_finished_item": 0, "uom": "Nos",
            })
        doc = frappe.get_doc({
            "doctype": "Stock Entry", "stock_entry_type": "Manufacture",
            "company": self.company, "production_plan": self.plan,
            "custom_process_selection": process or self.op,
            "custom_allow_manufacture_without_transfer": allow,
            "items": items,
        })
        return doc

    def _op_qty(self, item_code, field):
        return frappe.db.get_value(
            cr.OPERATION_CHILD,
            {"parent": self.plan, "operation_name": self.op, "item_code": item_code},
            field,
        )

    # ==================================================================
    # CVAL-08 — transfer coverage
    # ==================================================================
    def test_cval08_blocks_manufacture_without_transfer(self):
        doc = self._mfg_doc(source_rows=[(self.item_a, 5, self.wh_wip)])
        with self.assertRaises(frappe.ValidationError) as ctx:
            cr.before_submit(doc)
        self.assertIn("Complete the Material Transfer for Manufacture", str(ctx.exception))
        self.assertIn(self.plan, str(ctx.exception))

    def test_cval08_passes_and_stamps_ref_when_transfer_exists(self):
        self._seed_submitted_se(
            stock_entry_type=cr.TRANSFER_TYPE,
            rows=[{"item_code": self.item_a, "qty": 100,
                   "s_warehouse": self.wh_src, "t_warehouse": self.wh_wip}],
        )
        doc = self._mfg_doc(source_rows=[(self.item_a, 80, self.wh_wip)])
        cr.before_submit(doc)  # no raise — coverage + within balance
        self.assertTrue(doc.custom_material_transfer_ref,
                        "the matching transfer must be stamped for traceability")

    def test_cval08_allow_flag_bypasses_as_administrator(self):
        doc = self._mfg_doc(source_rows=[(self.item_a, 5, self.wh_wip)], allow=1)
        # Administrator is authorised; coverage is skipped and the use is
        # recorded in the timeline (audit).
        with patch.object(doc, "add_comment") as m:
            cr.before_submit(doc)  # must not raise despite no transfer
        m.assert_called_once()

    def test_cval08_allow_flag_blocked_for_non_manufacturing_manager(self):
        doc = self._mfg_doc(source_rows=[(self.item_a, 5, self.wh_wip)], allow=1)
        orig = frappe.session.user
        frappe.session.user = "cr04_test@example.com"
        try:
            with patch.object(cr.frappe, "get_roles", return_value=["Stock User"]):
                with self.assertRaises(frappe.ValidationError):
                    cr.before_submit(doc)
        finally:
            frappe.session.user = orig

    def test_cval08_allow_flag_permitted_for_manufacturing_manager(self):
        doc = self._mfg_doc(source_rows=[(self.item_a, 5, self.wh_wip)], allow=1)
        orig = frappe.session.user
        frappe.session.user = "cr04_test@example.com"
        try:
            with patch.object(cr.frappe, "get_roles",
                              return_value=["Manufacturing Manager"]):
                with patch.object(doc, "add_comment"):
                    cr.before_submit(doc)  # no raise — authorised role
        finally:
            frappe.session.user = orig

    def test_cval08_short_circuits_non_manufacture(self):
        """A non-Manufacture SE is never caught by the coverage check."""
        doc = frappe.get_doc({
            "doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
            "company": self.company, "production_plan": self.plan,
            "custom_process_selection": self.op,
            "items": [{"item_code": self.item_a, "qty": 5, "t_warehouse": self.wh_wip}],
        })
        cr.before_submit(doc)  # no raise — out of scope

    # ==================================================================
    # CVAL-09 — over-consumption
    # ==================================================================
    def test_cval09_blocks_over_consumption(self):
        self._seed_submitted_se(
            stock_entry_type=cr.TRANSFER_TYPE,
            rows=[{"item_code": self.item_a, "qty": 100,
                   "s_warehouse": self.wh_src, "t_warehouse": self.wh_wip}],
        )
        doc = self._mfg_doc(source_rows=[(self.item_a, 120, self.wh_wip)])
        with self.assertRaises(frappe.ValidationError) as ctx:
            cr.before_submit(doc)
        msg = str(ctx.exception)
        self.assertIn("exceeds the balance transferred to WIP", msg)
        self.assertIn(self.item_a, msg)

    def test_cval09_accounts_for_already_consumed(self):
        self._seed_submitted_se(
            stock_entry_type=cr.TRANSFER_TYPE,
            rows=[{"item_code": self.item_a, "qty": 100,
                   "s_warehouse": self.wh_src, "t_warehouse": self.wh_wip}],
        )
        # 70 already consumed on a prior submitted Manufacture entry.
        self._seed_submitted_se(
            stock_entry_type="Manufacture",
            rows=[
                {"item_code": self.item_a, "qty": 70, "s_warehouse": self.wh_wip},
                {"item_code": self.item_fg, "qty": 10, "t_warehouse": self.wh_wip,
                 "is_finished_item": 1},
            ],
        )
        # Balance is now 30; consuming 40 must fail.
        doc = self._mfg_doc(source_rows=[(self.item_a, 40, self.wh_wip)])
        with self.assertRaises(frappe.ValidationError):
            cr.before_submit(doc)
        # …but consuming 30 (the exact balance) passes.
        ok = self._mfg_doc(source_rows=[(self.item_a, 30, self.wh_wip)])
        cr.before_submit(ok)

    # ==================================================================
    # CL-11 — WIP source-warehouse default
    # ==================================================================
    def test_cl11_defaults_source_to_wip(self):
        self._seed_submitted_se(
            stock_entry_type=cr.TRANSFER_TYPE,
            rows=[{"item_code": self.item_a, "qty": 100,
                   "s_warehouse": self.wh_src, "t_warehouse": self.wh_wip}],
        )
        doc = self._mfg_doc(source_rows=[(self.item_a, 10, None)])  # blank s_wh
        cr.default_wip_source_warehouse(doc)
        self.assertEqual(doc.items[0].s_warehouse, self.wh_wip,
                         "blank source row must inherit the transfer's WIP warehouse")

    def test_cl11_does_not_override_user_warehouse(self):
        self._seed_submitted_se(
            stock_entry_type=cr.TRANSFER_TYPE,
            rows=[{"item_code": self.item_a, "qty": 100,
                   "s_warehouse": self.wh_src, "t_warehouse": self.wh_wip}],
        )
        doc = self._mfg_doc(source_rows=[(self.item_a, 10, self.wh_src)])
        cr.default_wip_source_warehouse(doc)
        self.assertEqual(doc.items[0].s_warehouse, self.wh_src,
                         "a user-chosen warehouse must not be overwritten")

    # ==================================================================
    # CL-12 — transferred / consumed rollup
    # ==================================================================
    def test_cl12_transfer_rollup_submit_and_cancel(self):
        doc = frappe.get_doc({
            "doctype": "Stock Entry", "stock_entry_type": cr.TRANSFER_TYPE,
            "company": self.company, "production_plan": self.plan,
            "custom_process_selection": self.op,
            "items": [
                {"item_code": self.item_a, "qty": 10,
                 "s_warehouse": self.wh_src, "t_warehouse": self.wh_wip},
                {"item_code": self.item_b, "qty": 5,
                 "s_warehouse": self.wh_src, "t_warehouse": self.wh_wip},
            ],
        })
        cr.rollup_transferred_consumed_on_submit(doc)
        self.assertEqual(self._op_qty(self.item_a, "custom_transferred_qty"), 10)
        self.assertEqual(self._op_qty(self.item_b, "custom_transferred_qty"), 5)
        # consumed untouched by a transfer entry
        self.assertEqual(self._op_qty(self.item_a, "custom_consumed_qty"), 0)

        cr.rollup_transferred_consumed_on_cancel(doc)
        self.assertEqual(self._op_qty(self.item_a, "custom_transferred_qty"), 0)
        self.assertEqual(self._op_qty(self.item_b, "custom_transferred_qty"), 0)

    def test_cl12_manufacture_rollup_counts_source_rows_only(self):
        doc = frappe.get_doc({
            "doctype": "Stock Entry", "stock_entry_type": "Manufacture",
            "company": self.company, "production_plan": self.plan,
            "custom_process_selection": self.op,
            "items": [
                {"item_code": self.item_a, "qty": 3,
                 "s_warehouse": self.wh_wip, "is_finished_item": 0},
                # a finished-good row must NOT count as consumption
                {"item_code": self.item_fg, "qty": 99,
                 "t_warehouse": self.wh_wip, "is_finished_item": 1},
            ],
        })
        cr.rollup_transferred_consumed_on_submit(doc)
        self.assertEqual(self._op_qty(self.item_a, "custom_consumed_qty"), 3)
        self.assertEqual(self._op_qty(self.item_a, "custom_transferred_qty"), 0)

        cr.rollup_transferred_consumed_on_cancel(doc)
        self.assertEqual(self._op_qty(self.item_a, "custom_consumed_qty"), 0)

    # ==================================================================
    # CL-13 / CZ-40 — builder
    # ==================================================================
    def test_cl13_builder_prefills_transfer_from_operation(self):
        built = cr.make_material_transfer_for_manufacture(self.sub_plan, self.sub_op)
        self.assertEqual(built["stock_entry_type"], cr.TRANSFER_TYPE)
        self.assertEqual(built["production_plan"], self.sub_plan)
        self.assertEqual(built["custom_process_selection"], self.sub_op)
        expected = get_operation_rm_rows(self.sub_plan, self.sub_op)
        self.assertTrue(expected, "fixture plan/operation must have rm rows")
        self.assertEqual(len(built["items"]), len(expected),
                         "every operation rm row must become a transfer row")
        self.assertEqual(
            [i["item_code"] for i in built["items"]],
            [r["item_code"] for r in expected],
        )

    def test_cl13_builder_rejects_draft_plan(self):
        # self.plan is a DRAFT clone — the builder must refuse it.
        with self.assertRaises(frappe.ValidationError):
            cr.make_material_transfer_for_manufacture(self.plan, self.op)

    # ==================================================================
    # CZ-37 / CZ-38 — custom fields present
    # ==================================================================
    def test_custom_fields_present(self):
        expect = {
            ("Stock Entry", "custom_material_transfer_ref"): ("Link", "Stock Entry"),
            ("Stock Entry", "custom_allow_manufacture_without_transfer"): ("Check", None),
            (cr.OPERATION_CHILD, "custom_transferred_qty"): ("Float", None),
            (cr.OPERATION_CHILD, "custom_consumed_qty"): ("Float", None),
        }
        for (dt, fn), (ftype, options) in expect.items():
            cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fn},
                                     ["fieldtype", "options", "read_only"], as_dict=True)
            self.assertIsNotNone(cf, f"{dt}.{fn} custom field missing")
            self.assertEqual(cf.fieldtype, ftype, f"{dt}.{fn} wrong fieldtype")
            if options:
                self.assertEqual(cf.options, options, f"{dt}.{fn} wrong options")
        # the two rollup fields must be read-only
        for fn in ("custom_transferred_qty", "custom_consumed_qty"):
            ro = frappe.db.get_value(
                "Custom Field", {"dt": cr.OPERATION_CHILD, "fieldname": fn}, "read_only")
            self.assertEqual(ro, 1, f"{fn} must be read-only (rollup)")

    # ==================================================================
    # CL-13 client glue (pinned like the I419 / CR-05..07 tests)
    # ==================================================================
    def test_client_button_wired(self):
        js = Path(JS_PATH).read_text()
        self.assertIn("_add_material_transfer_button", js)
        self.assertIn("make_material_transfer_for_manufacture", js)
        self.assertIn("Material Transfer for Manufacture", js)
