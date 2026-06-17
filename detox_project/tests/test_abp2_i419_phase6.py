"""ABP2-I419 Phase 6 — Cylinder Deposit Ledger tests."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase


class TestABP2I419Phase6(IntegrationTestCase):

    def test_cylinder_deposit_ledger_doctype_exists(self):
        self.assertTrue(
            frappe.db.exists("DocType", "Cylinder Deposit Ledger"),
        )

    def test_outstanding_report_registered(self):
        self.assertTrue(
            frappe.db.exists("Report", "Outstanding Cylinder Deposits"),
        )

    def test_item_cylinder_flags_present(self):
        for fn in ("custom_is_cylinder", "custom_deposit_amount"):
            self.assertTrue(
                frappe.db.exists("Custom Field", f"Item-{fn}"),
                f"Item.{fn} must be on the bench",
            )

    def test_validate_rejects_zero_deposit(self):
        doc = frappe.new_doc("Cylinder Deposit Ledger")
        doc.customer = "ANY"
        doc.serial_no = "TEST-SERIAL"
        doc.deposit_amount = 0
        doc.issue_date = frappe.utils.today()
        doc.status = "Outstanding"
        doc.company = "ANY"
        with self.assertRaises(frappe.ValidationError):
            doc.validate()

    def test_outstanding_report_executes(self):
        from detox_project.detox_project.report.outstanding_cylinder_deposits \
            .outstanding_cylinder_deposits import execute
        cols, data = execute({})
        self.assertEqual(len(cols), 10)
        self.assertIsInstance(data, list)

    def test_create_refund_je_throws_for_unknown_ledger(self):
        from detox_project.detox_project.doctype.cylinder_deposit_ledger \
            .cylinder_deposit_ledger import create_refund_journal_entry
        with self.assertRaises(Exception):
            create_refund_journal_entry("CYL-DEP-NONE")

    def test_dn_si_hooks_wired(self):
        from detox_project import hooks
        events = hooks.doc_events or {}
        for dt in ("Delivery Note", "Sales Invoice"):
            on_submit = events.get(dt, {}).get("on_submit")
            self.assertTrue(
                on_submit and "auto_create_deposit_entries" in (
                    on_submit if isinstance(on_submit, str) else " ".join(on_submit)
                ),
                f"{dt}.on_submit must call auto_create_deposit_entries",
            )
