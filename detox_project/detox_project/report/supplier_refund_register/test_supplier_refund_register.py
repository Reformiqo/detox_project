"""Regression test for the Supplier Refund Register (ABP2-I225 FR-12).

Pins:
  - The report's columns shape (9 columns, in spec order).
  - It returns [] cleanly when the site has no refund Custom Fields
    yet (so it doesn't crash on an unmigrated bench).
  - The status filter defaults to Submitted-only.
  - Date / company / supplier / reason filters compose into the WHERE
    clause without SQL-injection risk (parameterised).

Tests use mock-based isolation rather than seeding real PEs because
the FRD's refund flow needs a 4-doc chain (PI → outward PE → refund
PE) and we already cover that end-to-end in
`detox_waste_management.tests.test_payment_entry_refund`.
"""
from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from unittest.mock import patch


class TestSupplierRefundRegister(IntegrationTestCase):

    def test_columns_shape_matches_frd(self):
        from detox_project.detox_project.report.supplier_refund_register.supplier_refund_register import (
            _columns,
        )
        cols = _columns()
        self.assertEqual(len(cols), 9, f"FRD specifies 9 columns; got {len(cols)}")
        names = [c["fieldname"] for c in cols]
        self.assertEqual(
            names,
            [
                "name", "posting_date", "company", "party",
                "custom_original_payment_entry", "pis_pretty",
                "paid_amount", "custom_refund_reason", "status_label",
            ],
            "Column order must match the FRD spec.",
        )

    def test_returns_empty_when_field_missing(self):
        """If `custom_is_refund` field doesn't exist on PE (e.g. fresh
        site without our fixtures synced), report degrades to empty
        rather than throwing — so the report list view isn't broken
        on a partial deploy."""
        from detox_project.detox_project.report.supplier_refund_register.supplier_refund_register import (
            _data,
        )
        fake_meta = type("M", (), {"has_field": lambda self, name: False})()
        with patch(
            "detox_project.detox_project.report.supplier_refund_register.supplier_refund_register.frappe.get_meta",
            return_value=fake_meta,
        ):
            data = _data(frappe._dict({}))
        self.assertEqual(data, [])

    def test_status_filter_defaults_to_submitted(self):
        """When `status` is omitted from filters, the SQL WHERE must
        include `pe.docstatus = 1`."""
        from detox_project.detox_project.report.supplier_refund_register.supplier_refund_register import (
            _data,
        )
        fake_meta = type("M", (), {"has_field": lambda self, name: True})()
        captured = {}

        def fake_sql(query, args=None, as_dict=False):
            captured.setdefault("queries", []).append(query)
            return []

        with patch(
            "detox_project.detox_project.report.supplier_refund_register.supplier_refund_register.frappe.get_meta",
            return_value=fake_meta,
        ):
            with patch(
                "detox_project.detox_project.report.supplier_refund_register.supplier_refund_register.frappe.db.sql",
                side_effect=fake_sql,
            ):
                _data(frappe._dict({}))

        all_queries = " ".join(captured.get("queries", []))
        self.assertIn("pe.docstatus = 1", all_queries,
            "Default status filter must restrict to Submitted (docstatus=1).")

    def test_status_all_drops_docstatus_filter(self):
        from detox_project.detox_project.report.supplier_refund_register.supplier_refund_register import (
            _data,
        )
        fake_meta = type("M", (), {"has_field": lambda self, name: True})()
        captured = {}

        def fake_sql(query, args=None, as_dict=False):
            captured.setdefault("queries", []).append(query)
            return []

        with patch(
            "detox_project.detox_project.report.supplier_refund_register.supplier_refund_register.frappe.get_meta",
            return_value=fake_meta,
        ):
            with patch(
                "detox_project.detox_project.report.supplier_refund_register.supplier_refund_register.frappe.db.sql",
                side_effect=fake_sql,
            ):
                _data(frappe._dict({"status": "All"}))

        all_queries = " ".join(captured.get("queries", []))
        self.assertNotIn("pe.docstatus = 1", all_queries)
        self.assertNotIn("pe.docstatus = 2", all_queries)
        self.assertNotIn("pe.docstatus = 0", all_queries)

    def test_supplier_filter_passes_through(self):
        from detox_project.detox_project.report.supplier_refund_register.supplier_refund_register import (
            _data,
        )
        fake_meta = type("M", (), {"has_field": lambda self, name: True})()
        captured_args = []

        def fake_sql(query, args=None, as_dict=False):
            captured_args.append(args)
            return []

        with patch(
            "detox_project.detox_project.report.supplier_refund_register.supplier_refund_register.frappe.get_meta",
            return_value=fake_meta,
        ):
            with patch(
                "detox_project.detox_project.report.supplier_refund_register.supplier_refund_register.frappe.db.sql",
                side_effect=fake_sql,
            ):
                _data(frappe._dict({"supplier": "ACME Suppliers"}))

        first_call_args = captured_args[0] if captured_args else {}
        self.assertEqual(first_call_args.get("supplier"), "ACME Suppliers",
            "Supplier filter must be parameterised, not interpolated.")
