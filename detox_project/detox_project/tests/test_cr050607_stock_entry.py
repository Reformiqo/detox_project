"""CR-05 + CR-06 + CR-07 — Stock Entry additional-costs & cost-centre
hardening. DETOX Production Change-Set FRD (Change Set 1).

Covers the server side that fires from the Stock Entry hooks:
  CVAL-10  additional costs present but no target warehouse (before_submit)
  CVAL-11  item + additional-cost row Cost Center must equal the header
  CVAL-12  only Manufacturing Manager / Accounts Manager may allow multi-CC
  CVAL-13  header Cost Center must belong to company, not group, not disabled
  CVAL-14  non-stock service item may not be added to Items
  CVAL-15  additional-cost row completeness (reqd description/expense/amount)
  CL-16    header Cost Center cascade into blank item + additional-cost rows
  CL-20    additional-cost amount = qty x rate server recompute

The tests call the exact functions the doc_events hooks invoke
(change_set.cr050607_stock_entry.validate / before_submit / before_save /
on_update and their sub-rules) against REAL Stock Entry / child docs and
REAL masters (Item, Cost Center, Account) — no DB stubbing. Field /
Property-Setter config and the client-script glue are pinned separately.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from detox_project.detox_project.change_set import cr050607_stock_entry as cr

COMPANY = "Saurashtra Enviro Projects Private Limited"
EXPENSE_ACCOUNT = "Cost of Goods Sold - SEPPL"
CC_HEADER = "Adani - SEPPL"          # valid leaf, company match
CC_OTHER = "Jamnagar-STP - SEPPL"    # valid leaf, different from header
CC_GROUP = "Saurashtra Enviro Projects Private Limited - SEPPL"  # is_group
CC_DISABLED = "Main - SEPPL"         # disabled leaf


class TestCR050607StockEntry(IntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure the change-set custom fields / property setters / print
        # format are installed (code-first; not yet wired into
        # after_migrate — the manager wires it on integration).
        cr.install()

        # Use REAL existing items (creating one needs an HSN/SAC code on
        # this GST site). One stock item + one non-stock service item.
        cls.stock_item = frappe.db.get_value(
            "Item", {"is_stock_item": 1, "disabled": 0}, "name")
        cls.service_item = frappe.db.get_value(
            "Item", {"is_stock_item": 0, "disabled": 0}, "name")
        assert cls.stock_item, "no stock item on site to test with"
        assert cls.service_item, "no non-stock item on site to test with"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_se(self, *, stock_entry_type="Manufacture", cost_center=CC_HEADER,
                 items=None, additional_costs=None, allow_multi=0):
        doc = frappe.get_doc({
            "doctype": "Stock Entry",
            "stock_entry_type": stock_entry_type,
            "company": COMPANY,
            "cost_center": cost_center,
            "custom_allow_multiple_cost_centers": allow_multi,
            "items": items or [],
            "additional_costs": additional_costs or [],
        })
        # 16.6 has no header cost_center docfield; set it explicitly so
        # doc.get("cost_center") returns it (DB column exists).
        doc.cost_center = cost_center
        return doc

    def _fg_row(self, qty=10, t_wh="_TestFG - X", cc=None):
        return {"item_code": self.stock_item, "qty": qty, "t_warehouse": t_wh,
                "is_finished_item": 1, "uom": "Nos", "cost_center": cc}

    def _source_row(self, qty=5, s_wh="_TestWIP - X", cc=None):
        return {"item_code": self.stock_item, "qty": qty, "s_warehouse": s_wh,
                "uom": "Nos", "cost_center": cc}

    @staticmethod
    def _addl(description="Hydro testing", amount=100.0, qty=None, rate=None,
              expense=EXPENSE_ACCOUNT, cc=None):
        return {"description": description, "expense_account": expense,
                "amount": amount, "custom_qty": qty, "custom_rate": rate,
                "custom_cost_center": cc}

    # ------------------------------------------------------------------
    # CL-20 — amount = qty x rate server recompute (CR-07.2)
    # ------------------------------------------------------------------
    def test_amount_recompute_from_qty_rate(self):
        doc = self._make_se(additional_costs=[
            self._addl(amount=0, qty=250, rate=45.0),   # 11250
            self._addl(description="Lump sum", amount=500, qty=None, rate=None),
        ])
        cr.recompute_additional_cost_amounts(doc)
        self.assertEqual(doc.additional_costs[0].amount, 11250.0,
                         "amount must recompute to qty x rate")
        self.assertEqual(doc.additional_costs[1].amount, 500.0,
                         "lump-sum row (no qty/rate) must keep its amount")

    def test_recompute_runs_before_reqd_amount_passes(self):
        """A qty+rate row arriving with amount=0 (API / bulk upload) must be
        recomputed by validate() so the amount reqd check passes rather than
        the row dropping. Proves CL-20 ordering."""
        doc = self._make_se(
            items=[self._fg_row(cc=CC_HEADER)],
            additional_costs=[self._addl(amount=0, qty=10, rate=20.0)],
        )
        cr.validate(doc)  # must not raise: recompute → amount=200 → complete
        self.assertEqual(doc.additional_costs[0].amount, 200.0)

    # ------------------------------------------------------------------
    # Orchestrator — the validate() hook entrypoint must WIRE the sub-rules
    # (guards against "the check exists but never gets called")
    # ------------------------------------------------------------------
    def test_validate_orchestrator_blocks_cc_mismatch(self):
        doc = self._make_se(items=[self._fg_row(cc=CC_OTHER)])
        with self.assertRaises(frappe.ValidationError):
            cr.validate(doc)

    def test_validate_orchestrator_blocks_non_stock_item(self):
        doc = self._make_se(items=[{"item_code": self.service_item, "qty": 1,
                                    "uom": "Nos"}])
        with self.assertRaises(frappe.ValidationError):
            cr.validate(doc)

    def test_validate_orchestrator_skips_non_manufacture(self):
        """A non-Manufacture SE with a CC-mismatched row is NOT blocked by
        the manufacture-scoped CVAL-11 (short-circuit)."""
        doc = self._make_se(stock_entry_type="Material Receipt",
                            items=[self._fg_row(cc=CC_OTHER)])
        cr.validate(doc)  # no raise — out of scope

    # ------------------------------------------------------------------
    # CVAL-15 — additional-cost row completeness (CR-05.3)
    # ------------------------------------------------------------------
    def test_incomplete_addl_cost_blocked_missing_expense(self):
        doc = self._make_se(additional_costs=[
            self._addl(expense=None, amount=100),
        ])
        with self.assertRaises(frappe.ValidationError):
            cr.validate_additional_cost_rows(doc)

    def test_incomplete_addl_cost_blocked_zero_amount(self):
        doc = self._make_se(additional_costs=[self._addl(amount=0)])
        with self.assertRaises(frappe.ValidationError):
            cr.validate_additional_cost_rows(doc)

    def test_complete_addl_cost_row_passes(self):
        doc = self._make_se(additional_costs=[self._addl(amount=100)])
        cr.validate_additional_cost_rows(doc)  # no raise

    # ------------------------------------------------------------------
    # CVAL-14 — non-stock service item may not be added to Items (CR-05.4)
    # ------------------------------------------------------------------
    def test_non_stock_item_blocked_in_items(self):
        doc = self._make_se(items=[{"item_code": self.service_item, "qty": 1,
                                    "uom": "Nos"}])
        with self.assertRaises(frappe.ValidationError):
            cr.block_non_stock_items(doc)

    def test_stock_item_allowed_in_items(self):
        doc = self._make_se(items=[self._fg_row()])
        cr.block_non_stock_items(doc)  # no raise

    # ------------------------------------------------------------------
    # CVAL-10 — additional costs need a target warehouse (CR-05.5)
    # ------------------------------------------------------------------
    def test_cval10_blocks_addl_cost_without_target(self):
        doc = self._make_se(
            items=[self._source_row()],                # only a source row
            additional_costs=[self._addl(amount=100)],
        )
        with self.assertRaises(frappe.ValidationError):
            cr.before_submit(doc)

    def test_cval10_passes_with_target(self):
        doc = self._make_se(
            items=[self._source_row(), self._fg_row(cc=CC_HEADER)],
            additional_costs=[self._addl(amount=100)],
        )
        cr.before_submit(doc)  # no raise — FG row carries t_warehouse

    def test_cval10_ignores_when_no_addl_cost(self):
        doc = self._make_se(items=[self._source_row()])
        cr.before_submit(doc)  # no raise — nothing to distribute

    # ------------------------------------------------------------------
    # CL-16 — header CC cascade into blank item + additional-cost rows
    # ------------------------------------------------------------------
    def test_cascade_fills_blank_rows(self):
        doc = self._make_se(
            items=[self._fg_row(cc=None)],
            additional_costs=[self._addl(cc=None)],
        )
        cr.before_save(doc)
        self.assertEqual(doc.items[0].cost_center, CC_HEADER,
                         "blank item row must inherit header cost centre")
        self.assertEqual(doc.additional_costs[0].custom_cost_center, CC_HEADER,
                         "blank additional-cost row must inherit header cost centre")

    def test_cascade_leaves_populated_rows(self):
        doc = self._make_se(
            items=[self._fg_row(cc=CC_OTHER)],
            additional_costs=[self._addl(cc=CC_OTHER)],
        )
        cr.before_save(doc)
        self.assertEqual(doc.items[0].cost_center, CC_OTHER,
                         "populated row must NOT be overwritten by cascade")
        self.assertEqual(doc.additional_costs[0].custom_cost_center, CC_OTHER)

    def test_cascade_short_circuits_non_manufacture(self):
        doc = self._make_se(stock_entry_type="Material Receipt",
                            items=[self._fg_row(cc=None)])
        cr.before_save(doc)
        self.assertIsNone(doc.items[0].cost_center,
                          "non-Manufacture SE must be left untouched")

    # ------------------------------------------------------------------
    # CVAL-11 — row CC must equal header CC unless allow_multiple
    # ------------------------------------------------------------------
    def test_cval11_blocks_item_row_mismatch(self):
        doc = self._make_se(items=[self._fg_row(cc=CC_OTHER)])
        with self.assertRaises(frappe.ValidationError):
            cr.validate_cost_center_consistency(doc)

    def test_cval11_blocks_addl_cost_row_mismatch(self):
        doc = self._make_se(additional_costs=[self._addl(cc=CC_OTHER)])
        with self.assertRaises(frappe.ValidationError):
            cr.validate_cost_center_consistency(doc)

    def test_cval11_passes_when_rows_match_header(self):
        doc = self._make_se(
            items=[self._fg_row(cc=CC_HEADER)],
            additional_costs=[self._addl(cc=CC_HEADER)],
        )
        cr.validate_cost_center_consistency(doc)  # no raise

    def test_cval11_bypassed_when_allow_multiple(self):
        doc = self._make_se(items=[self._fg_row(cc=CC_OTHER)], allow_multi=1)
        cr.validate_cost_center_consistency(doc)  # no raise — override on

    # ------------------------------------------------------------------
    # CVAL-12 — only MM / Accounts Manager may set allow_multiple
    # ------------------------------------------------------------------
    def _as_user(self, roles):
        """Run the permission check as a non-admin user with the given roles.
        Patch frappe.get_roles + session.user so the check is deterministic
        and independent of site users (creating one trips a Contact
        mandatory-field customization on this site)."""
        orig_user = frappe.session.user
        frappe.session.user = "cr0507_test@example.com"
        return orig_user

    def test_cval12_blocks_unauthorised_user(self):
        doc = self._make_se(allow_multi=1)
        orig = self._as_user(["Stock User"])
        try:
            with patch.object(cr.frappe, "get_roles", return_value=["Stock User"]):
                with self.assertRaises(frappe.ValidationError):
                    cr.validate_allow_multiple_permission(doc)
        finally:
            frappe.session.user = orig

    def test_cval12_allows_manufacturing_manager(self):
        doc = self._make_se(allow_multi=1)
        orig = self._as_user(["Manufacturing Manager"])
        try:
            with patch.object(cr.frappe, "get_roles",
                              return_value=["Manufacturing Manager"]):
                cr.validate_allow_multiple_permission(doc)  # no raise
        finally:
            frappe.session.user = orig

    def test_cval12_allows_accounts_manager(self):
        doc = self._make_se(allow_multi=1)
        orig = self._as_user(["Accounts Manager"])
        try:
            with patch.object(cr.frappe, "get_roles",
                              return_value=["Accounts Manager"]):
                cr.validate_allow_multiple_permission(doc)  # no raise
        finally:
            frappe.session.user = orig

    def test_cval12_no_check_when_flag_off(self):
        doc = self._make_se(allow_multi=0)
        orig = self._as_user(["Stock User"])
        try:
            with patch.object(cr.frappe, "get_roles", return_value=["Stock User"]):
                cr.validate_allow_multiple_permission(doc)  # no raise — flag off
        finally:
            frappe.session.user = orig

    def test_cval12_writes_timeline_on_transition(self):
        """The exception use is recorded in the timeline once, on the
        off->on transition (on_update), and not again while it stays on."""
        # fresh doc turning the flag on -> comment written
        doc = self._make_se(allow_multi=1)
        doc.name = "TEST-CR0507-CVAL12"
        with patch.object(doc, "add_comment") as m:
            cr.on_update(doc)
        m.assert_called_once()

        # already-on (no transition) -> no duplicate comment
        doc2 = self._make_se(allow_multi=1)
        doc2.name = "TEST-CR0507-CVAL12b"
        doc2._doc_before_save = frappe._dict({"custom_allow_multiple_cost_centers": 1})
        with patch.object(doc2, "add_comment") as m2:
            cr.on_update(doc2)
        m2.assert_not_called()

    # ------------------------------------------------------------------
    # CVAL-13 — Cost Center master validity
    # ------------------------------------------------------------------
    def test_cval13_blocks_group_cost_center(self):
        doc = self._make_se(cost_center=CC_GROUP)
        with self.assertRaises(frappe.ValidationError):
            cr.validate_cost_center_master(doc)

    def test_cval13_blocks_disabled_cost_center(self):
        doc = self._make_se(cost_center=CC_DISABLED)
        with self.assertRaises(frappe.ValidationError):
            cr.validate_cost_center_master(doc)

    def test_cval13_passes_valid_cost_center(self):
        doc = self._make_se(cost_center=CC_HEADER)
        cr.validate_cost_center_master(doc)  # no raise

    # ------------------------------------------------------------------
    # Config — Custom Fields + Property Setters (CR-05.3 / CR-07.2/.3/.4)
    # ------------------------------------------------------------------
    def test_new_custom_fields_present(self):
        expect = {
            ("Landed Cost Taxes and Charges", "custom_service_item"): ("Link", "Item"),
            ("Landed Cost Taxes and Charges", "custom_uom"): ("Link", "UOM"),
            ("Landed Cost Taxes and Charges", "custom_remarks"): ("Small Text", None),
            ("Landed Cost Taxes and Charges", "custom_purchase_order"): ("Link", "Purchase Order"),
            ("Landed Cost Taxes and Charges", "custom_purchase_order_item"): ("Link", "Purchase Order Item"),
            ("Landed Cost Taxes and Charges", "custom_cost_center"): ("Link", "Cost Center"),
            ("Stock Entry", "custom_allow_multiple_cost_centers"): ("Check", None),
        }
        for (dt, fn), (ftype, options) in expect.items():
            cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fn},
                                     ["fieldtype", "options"], as_dict=True)
            self.assertIsNotNone(cf, f"{dt}.{fn} custom field missing")
            self.assertEqual(cf.fieldtype, ftype, f"{dt}.{fn} wrong fieldtype")
            if options:
                self.assertEqual(cf.options, options, f"{dt}.{fn} wrong options")

    def test_service_item_in_list_view_and_uom_readonly(self):
        si = frappe.db.get_value(
            "Custom Field",
            {"dt": "Landed Cost Taxes and Charges", "fieldname": "custom_service_item"},
            "in_list_view")
        self.assertEqual(si, 1, "custom_service_item must be in_list_view")
        ro = frappe.db.get_value(
            "Custom Field",
            {"dt": "Landed Cost Taxes and Charges", "fieldname": "custom_uom"},
            "read_only")
        self.assertEqual(ro, 1, "custom_uom must be read-only (auto-fetched)")

    def test_reqd_property_setters(self):
        for field in ("description", "expense_account", "amount"):
            val = frappe.db.get_value(
                "Property Setter",
                f"Landed Cost Taxes and Charges-{field}-reqd", "value")
            self.assertEqual(val, "1", f"{field} must be reqd=1 (CR-05.3)")

    def test_amount_read_only_depends_on(self):
        val = frappe.db.get_value(
            "Property Setter",
            "Landed Cost Taxes and Charges-amount-read_only_depends_on", "value")
        self.assertEqual(val, "eval:doc.custom_qty && doc.custom_rate",
                         "amount must be read-only when both qty & rate set (CR-07.2)")

    # ------------------------------------------------------------------
    # Client script glue (CR-07.3 / .4) — pinned like the I419 tests
    # ------------------------------------------------------------------
    def test_client_script_addl_cost_handlers(self):
        from pathlib import Path
        js = Path("/home/frappe/v16/apps/detox_project/detox_project/"
                  "public/js/stock_entry_manufacture.js").read_text()
        self.assertIn("custom_service_item: _fetch_addl_cost_service_item_uom", js)
        self.assertIn("custom_purchase_order_item: _fetch_addl_cost_po_item", js)
        self.assertIn("_wire_addl_cost_po_item_filter", js)
        # both new handlers must early-return for non-Stock-Entry parents
        self.assertIn('frm.doctype !== "Stock Entry"', js)

    # ------------------------------------------------------------------
    # CR-07.6 — Production Day Summary print format renders the charges
    # ------------------------------------------------------------------
    def test_print_format_lists_service_charges(self):
        html = frappe.db.get_value("Print Format", "Production Day Summary", "html")
        self.assertIn("Service Charges / Additional Costs", html)
        # Render against a REAL (unsaved) Stock Entry so doc.items /
        # doc.additional_costs resolve to child tables (a frappe._dict would
        # shadow .items with the dict method).
        doc = frappe.get_doc({
            "doctype": "Stock Entry", "stock_entry_type": "Manufacture",
            "company": COMPANY, "posting_date": "2026-08-06",
            "posting_time": "10:00:00", "production_plan": None, "project": None,
            "from_warehouse": None, "custom_process_selection": None,
            "custom_production_time": 0, "custom_time_uom": "Hours",
            "custom_downtime": 0, "cost_center": CC_HEADER,
            "additional_costs": [{
                "custom_service_item": self.service_item,
                "description": "Hydro testing", "custom_qty": 250,
                "custom_uom": "Nos", "custom_rate": 45.0, "amount": 11250.0,
                "expense_account": EXPENSE_ACCOUNT,
            }],
        })
        doc.total_additional_costs = 11250.0
        rendered = frappe.render_template(html, {"doc": doc})
        self.assertIn("Hydro testing", rendered)
        self.assertIn("11250.00", rendered)
        self.assertIn("45.00", rendered)
