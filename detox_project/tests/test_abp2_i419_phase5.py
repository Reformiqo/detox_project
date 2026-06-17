"""ABP2-I419 Phase 5 — Reports + Print + Scheduler tests."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase


class TestABP2I419Phase5(IntegrationTestCase):

    def test_production_cost_comparison_report_registered(self):
        self.assertTrue(
            frappe.db.exists("Report", "Production Cost Comparison"),
            "RPT-01 Production Cost Comparison should exist after migrate",
        )

    def test_production_plan_vs_actual_report_registered(self):
        self.assertTrue(
            frappe.db.exists("Report", "Production Plan vs Actual"),
            "RPT-02 Production Plan vs Actual should exist after migrate",
        )

    def test_production_day_summary_print_format_registered(self):
        self.assertTrue(
            frappe.db.exists("Print Format", "Production Day Summary"),
            "Production Day Summary print format should be on the bench",
        )

    def test_rpt_01_execute_no_filters_does_not_crash(self):
        from detox_project.detox_project.report.production_cost_comparison \
            .production_cost_comparison import execute
        columns, data = execute({})
        self.assertEqual(len(columns), 13)
        self.assertIn("final_product_rate",
                      {c["fieldname"] for c in columns})

    def test_rpt_02_execute_no_filters_does_not_crash(self):
        from detox_project.detox_project.report.production_plan_vs_actual \
            .production_plan_vs_actual import execute
        columns, data = execute({})
        self.assertEqual(len(columns), 8)
        self.assertIn("completion_pct",
                      {c["fieldname"] for c in columns})

    def test_overdue_production_plan_alert_does_not_crash(self):
        from detox_project.setup import overdue_production_plan_alert
        # Should not raise on a bench with no overdue plans.
        overdue_production_plan_alert()

    def test_scheduler_wired_in_hooks(self):
        from detox_project import hooks
        daily = (hooks.scheduler_events or {}).get("daily") or []
        self.assertIn(
            "detox_project.setup.overdue_production_plan_alert",
            daily,
            "overdue_production_plan_alert must be wired in scheduler_events.daily",
        )
