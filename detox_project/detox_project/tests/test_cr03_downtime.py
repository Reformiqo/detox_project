"""CR-03 — Downtime capture at Stock Entry level.

Exercises the exact reproduction paths from the Change-Set FRD test
scenarios:
  * TC-09  Manufacture entry with two downtime rows -> per-row duration,
           header downtime = sum, net run time reduced.
  * TC-10  Downtime without a reason is refused (CVAL-05).
  * TC-11  Production 20h + downtime 6h is refused (CVAL-07).
plus CVAL-06 (to_time > from_time), net-run-time non-negativity, the
cost-centre inheritance, the field layout (CZ-33) and the Downtime
Analysis report (CZ-36) running against the real schema.

The validations/computations live in
detox_project.detox_project.change_set.cr03_downtime.validate_downtime,
the exact function that the manager wires onto Stock Entry `validate`.
The tests call it on a real, form-shaped Manufacture Stock Entry doc
(not a synthetic short-circuit), so they cover the user's flow without
fighting ERPNext's full stock-valuation validate for a fixture SE.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from detox_project.detox_project.change_set.cr03_downtime import validate_downtime
from detox_project.detox_project.report.downtime_analysis.downtime_analysis import (
    execute as downtime_analysis_execute,
)

REASON_BREAKDOWN = "Test CR03 Compressor Breakdown"
REASON_POWER = "Test CR03 Power Failure"


def _ensure_reason(name: str, category: str, is_planned: int = 0):
    if not frappe.db.exists("Downtime Reason", name):
        frappe.get_doc({
            "doctype": "Downtime Reason",
            "reason_name": name,
            "category": category,
            "is_planned": is_planned,
        }).insert(ignore_permissions=True)


class TestCR03Downtime(IntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _ensure_reason(REASON_BREAKDOWN, "Breakdown")
        _ensure_reason(REASON_POWER, "Power")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _mfg_se(self, production_time=8.0, time_uom="Hours",
                downtime_uom="Hours", rows=None, downtime=None,
                items=None):
        doc = frappe.get_doc({
            "doctype": "Stock Entry",
            "stock_entry_type": "Manufacture",
            "custom_production_time": production_time,
            "custom_time_uom": time_uom,
            "custom_downtime_uom": downtime_uom,
            "custom_downtime_details": rows or [],
            "items": items or [],
        })
        if downtime is not None:
            doc.custom_downtime = downtime
        return doc

    # ------------------------------------------------------------------ #
    # Masters + layout (CZ-34, CZ-35, CZ-33)
    # ------------------------------------------------------------------ #
    def test_downtime_reason_master(self):
        meta = frappe.get_meta("Downtime Reason")
        self.assertEqual(meta.autoname, "field:reason_name")
        cat = meta.get_field("category")
        for opt in ("Breakdown", "Power", "Material Shortage",
                    "Changeover", "Quality", "Planned", "Other"):
            self.assertIn(opt, (cat.options or "").split("\n"))
        self.assertTrue(meta.get_field("is_planned").fieldtype == "Check")
        self.assertTrue(meta.get_field("disabled").fieldtype == "Check")

    def test_child_doctype_fields(self):
        meta = frappe.get_meta("Production Downtime Detail")
        self.assertEqual(meta.get_field("downtime_reason").options, "Downtime Reason")
        self.assertEqual(meta.get_field("downtime_reason").reqd, 1)
        cat = meta.get_field("category")
        self.assertEqual(cat.fetch_from, "downtime_reason.category")
        self.assertEqual(cat.read_only, 1)
        self.assertEqual(meta.get_field("cost_center").read_only, 1)
        self.assertEqual(
            meta.get_field("duration").read_only_depends_on,
            "eval:doc.from_time && doc.to_time",
        )

    def test_header_field_layout(self):
        meta = frappe.get_meta("Stock Entry")
        # Downtime fields all live in the gated Downtime section.
        cur = None
        section_of = {}
        gated = {}
        for df in meta.fields:
            if df.fieldtype == "Section Break":
                cur = df.fieldname
                gated[cur] = df.depends_on
            else:
                section_of[df.fieldname] = cur
        for fn in ("custom_downtime", "custom_downtime_uom",
                   "custom_downtime_details", "custom_downtime_remarks",
                   "custom_net_run_time"):
            self.assertEqual(
                section_of.get(fn), "custom_downtime_section",
                f"{fn} must sit inside custom_downtime_section",
            )
        self.assertIn(
            'Manufacture',
            gated.get("custom_downtime_section") or "",
            "Downtime section must be gated on stock_entry_type == Manufacture",
        )
        # Section must be closed by an ungated section so it can't swallow
        # standard fields for non-Manufacture types (blast-radius guard).
        names = [df.fieldname for df in meta.fields]
        after = names[names.index("custom_net_run_time") + 1:]
        next_sb = next(df for df in meta.fields
                       if df.fieldtype == "Section Break"
                       and df.fieldname in after)
        self.assertFalse(
            next_sb.depends_on,
            "The section right after the downtime block must be ungated "
            "so it closes the gated Downtime section.",
        )
        # custom_downtime read-only when detail rows exist.
        self.assertEqual(
            meta.get_field("custom_downtime").read_only_depends_on,
            "eval:doc.custom_downtime_details && doc.custom_downtime_details.length > 0",
        )
        self.assertEqual(meta.get_field("custom_net_run_time").read_only, 1)
        self.assertEqual(
            meta.get_field("custom_downtime_uom").options, "Hours\nMinutes")

    # ------------------------------------------------------------------ #
    # TC-09 — two rows compute duration, sum, net (CL-07/08/09)
    # ------------------------------------------------------------------ #
    def test_tc09_two_rows_compute(self):
        se = self._mfg_se(
            production_time=8.0,
            rows=[
                {"downtime_reason": REASON_BREAKDOWN,
                 "from_time": "2026-08-06 08:00:00",
                 "to_time": "2026-08-06 09:30:00"},   # 1.5h
                {"downtime_reason": REASON_POWER,
                 "from_time": "2026-08-06 10:00:00",
                 "to_time": "2026-08-06 10:30:00"},   # 0.5h
            ],
        )
        validate_downtime(se, "validate")
        self.assertAlmostEqual(se.custom_downtime_details[0].duration, 1.5, places=4)
        self.assertAlmostEqual(se.custom_downtime_details[1].duration, 0.5, places=4)
        self.assertAlmostEqual(se.custom_downtime, 2.0, places=4)          # CL-08 sum
        self.assertAlmostEqual(se.custom_net_run_time, 6.0, places=4)      # CL-09 8-2

    def test_tc09_minutes_uom_normalises_net(self):
        # production 8 Hours, downtime rows in Minutes -> net normalised.
        se = self._mfg_se(
            production_time=8.0, time_uom="Hours", downtime_uom="Minutes",
            rows=[{"downtime_reason": REASON_BREAKDOWN, "duration": 90}],  # 90 min
        )
        validate_downtime(se, "validate")
        self.assertAlmostEqual(se.custom_downtime, 90.0, places=4)
        # 8h = 480min; 480-90 = 390min -> 6.5h in the production UOM.
        self.assertAlmostEqual(se.custom_net_run_time, 6.5, places=4)

    # ------------------------------------------------------------------ #
    # TC-10 — reason mandatory (CVAL-05)
    # ------------------------------------------------------------------ #
    def test_tc10_row_without_reason_blocked(self):
        se = self._mfg_se(rows=[{"duration": 2.0}])  # no downtime_reason
        with self.assertRaises(frappe.ValidationError):
            validate_downtime(se, "validate")

    def test_tc10_header_downtime_without_rows_blocked(self):
        se = self._mfg_se(rows=[], downtime=3.0)  # manual downtime, no rows
        with self.assertRaises(frappe.ValidationError):
            validate_downtime(se, "validate")

    # ------------------------------------------------------------------ #
    # TC-11 — shift length cap (CVAL-07)
    # ------------------------------------------------------------------ #
    def test_tc11_shift_length_exceeded_blocked(self):
        se = self._mfg_se(
            production_time=20.0,
            rows=[{"downtime_reason": REASON_BREAKDOWN, "duration": 6.0}],
        )  # 20 + 6 = 26h > 24h
        with self.assertRaises(frappe.ValidationError):
            validate_downtime(se, "validate")

    # ------------------------------------------------------------------ #
    # CVAL-06 + net non-negative
    # ------------------------------------------------------------------ #
    def test_cval06_to_before_from_blocked(self):
        se = self._mfg_se(rows=[{
            "downtime_reason": REASON_BREAKDOWN,
            "from_time": "2026-08-06 10:00:00",
            "to_time": "2026-08-06 09:00:00",   # earlier than from
        }])
        with self.assertRaises(frappe.ValidationError):
            validate_downtime(se, "validate")

    def test_net_run_time_negative_blocked(self):
        se = self._mfg_se(
            production_time=1.0,
            rows=[{"downtime_reason": REASON_BREAKDOWN, "duration": 3.0}],
        )  # downtime 3h > production 1h -> net would be negative
        with self.assertRaises(frappe.ValidationError):
            validate_downtime(se, "validate")

    # ------------------------------------------------------------------ #
    # Cost-centre inheritance
    # ------------------------------------------------------------------ #
    def test_cost_center_inherited_from_item_row(self):
        cc = frappe.db.get_value("Cost Center", {"is_group": 0, "disabled": 0}, "name")
        self.assertTrue(cc, "Site must have at least one usable Cost Center")
        se = self._mfg_se(
            rows=[{"downtime_reason": REASON_BREAKDOWN, "duration": 1.0}],
            items=[{"item_code": "__cc_probe__", "cost_center": cc, "qty": 1}],
        )
        validate_downtime(se, "validate")
        self.assertEqual(se.custom_downtime_details[0].cost_center, cc)

    # ------------------------------------------------------------------ #
    # Report runs against the real schema (CZ-36)
    # ------------------------------------------------------------------ #
    def test_downtime_analysis_report_executes(self):
        columns, data = downtime_analysis_execute({
            "from_date": "2026-01-01",
            "to_date": "2026-12-31",
        })
        fieldnames = {c["fieldname"] for c in columns}
        self.assertEqual(
            fieldnames,
            {"downtime_reason", "category", "is_planned", "events", "downtime_hours"},
        )
        self.assertIsInstance(data, list)
