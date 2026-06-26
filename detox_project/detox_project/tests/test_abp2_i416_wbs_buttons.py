"""ABP2-I416 — Close / Reopen Budget buttons surfaced on the WBS
Element form (and a closure indicator on Sub WBS Element).

The Python whitelisted actions (`close_wbs`, `reopen_wbs`,
`close_category`, `reopen_category`) and the request-cached guards
(`is_wbs_closed`, etc.) live in `budgeting_tool.events.budget_closure`
and are covered by `test_abp2_i416_budget_closure.py` in that app.

This test module covers the UI surface that was missing per the FRD's
FR-01 / FR-02 / FR-03 (row-level Close / Reopen action). The WBS
Element form now exposes:

  • Close Budget button (visible only when status is Open)
  • Reopen Budget button (visible only when status is Closed)
  • Dashboard indicator showing current closure status
  • Banner with closed_on / closed_by / closed_reason

Sub WBS Element inherits its parent's closure via the cascade — so it
gets an indicator + banner only (no buttons).
"""
import frappe
from frappe.tests import IntegrationTestCase


_WBS_JS = (
    "/home/frappe/v16/apps/detox_project/detox_project/"
    "detox_project/doctype/wbs_element/wbs_element.js"
)
_SUB_WBS_JS = (
    "/home/frappe/v16/apps/detox_project/detox_project/"
    "detox_project/doctype/sub_wbs_element/sub_wbs_element.js"
)


class TestI416WBSButtons(IntegrationTestCase):

    def _js(self, path):
        from pathlib import Path
        return Path(path).read_text()

    def test_wbs_form_has_close_button_for_open_rows(self):
        js = self._js(_WBS_JS)
        self.assertIn('__("Close Budget")', js,
            "WBS Element form must add a 'Close Budget' button.")
        self.assertIn('"close"', js)
        self.assertIn(
            'frm.doc.custom_budget_closure_status === "Closed"', js,
            "Button visibility must depend on custom_budget_closure_status.",
        )

    def test_wbs_form_has_reopen_button_for_closed_rows(self):
        js = self._js(_WBS_JS)
        self.assertIn('__("Reopen Budget")', js,
            "WBS Element form must add a 'Reopen Budget' button.")
        self.assertIn('"reopen"', js)

    def test_wbs_form_calls_correct_server_methods(self):
        js = self._js(_WBS_JS)
        self.assertIn(
            "budgeting_tool.events.budget_closure.close_wbs", js,
            "Close button must call close_wbs server method.",
        )
        self.assertIn(
            "budgeting_tool.events.budget_closure.reopen_wbs", js,
            "Reopen button must call reopen_wbs server method.",
        )

    def test_wbs_form_requires_reason(self):
        js = self._js(_WBS_JS)
        # The prompt dialog has a `reason` field with reqd: 1.
        self.assertRegex(
            js, r'fieldname:\s*"reason"',
            "Dialog must have a reason field.",
        )
        # The reason is passed to the server call.
        self.assertIn("reason: values.reason", js)

    def test_wbs_form_shows_closure_indicator(self):
        js = self._js(_WBS_JS)
        self.assertIn("Budget Closure: Closed", js,
            "WBS form must show a dashboard indicator for closed budget.")
        self.assertIn("Budget Closure: Open", js,
            "WBS form must show a dashboard indicator for open budget.")

    def test_wbs_form_shows_closure_banner_with_audit_info(self):
        js = self._js(_WBS_JS)
        # Banner mentions closed_on / closed_by / closed_reason.
        for field in ("custom_closed_on", "custom_closed_by",
                      "custom_closed_reason"):
            self.assertIn(field, js,
                f"Banner must surface {field} so users know why "
                f"the budget is closed.")

    def test_sub_wbs_form_shows_inherited_closure_indicator(self):
        js = self._js(_SUB_WBS_JS)
        self.assertIn("Budget Closure: Closed", js,
            "Sub WBS form must surface inherited closure status.")
        self.assertIn("inherited", js.lower(),
            "Sub WBS indicator must communicate the closure is "
            "inherited from the parent WBS (cascade per FR-08).")

    def test_sub_wbs_form_has_no_close_button(self):
        """Sub WBS closure is parent-driven only. Direct Close/Reopen
        on Sub WBS would bypass the cascade and create an inconsistent
        state — buttons must NOT exist here."""
        js = self._js(_SUB_WBS_JS)
        self.assertNotIn('"close_wbs"', js,
            "Sub WBS form must NOT call close_wbs directly.")
        self.assertNotIn('"reopen_wbs"', js,
            "Sub WBS form must NOT call reopen_wbs directly.")

    def test_budget_manager_role_exists(self):
        """The Reopen action is role-gated to 'Budget Manager' per
        FR-11. The role must exist on the bench for the gate to be
        meaningful."""
        self.assertTrue(
            frappe.db.exists("Role", "Budget Manager"),
            "'Budget Manager' role must exist (FR-11).",
        )

    def test_close_wbs_python_action_is_whitelisted(self):
        """Sanity — the server-side action the button calls must be
        @frappe.whitelist()'d or the button is dead."""
        from budgeting_tool.events import budget_closure as M
        self.assertTrue(
            getattr(M.close_wbs, "whitelisted", False)
            or hasattr(M.close_wbs, "__wrapped__"),
            "close_wbs must be @frappe.whitelist()'d.",
        )
        self.assertTrue(
            getattr(M.reopen_wbs, "whitelisted", False)
            or hasattr(M.reopen_wbs, "__wrapped__"),
            "reopen_wbs must be @frappe.whitelist()'d.",
        )

    def test_wbs_closure_custom_fields_present(self):
        """The CFs the JS reads must actually exist on the bench."""
        meta = frappe.get_meta("WBS Element")
        for fn in ("custom_budget_closure_status", "custom_closed_by",
                   "custom_closed_on", "custom_closed_reason",
                   "custom_opened_by", "custom_opened_on",
                   "custom_opened_reason"):
            self.assertTrue(
                meta.has_field(fn),
                f"WBS Element.{fn} CF missing — install.py from "
                f"budgeting_tool should have created it.",
            )
        sub = frappe.get_meta("Sub WBS Element")
        for fn in ("custom_budget_closure_status", "custom_closed_by",
                   "custom_closed_on", "custom_closed_reason"):
            self.assertTrue(
                sub.has_field(fn),
                f"Sub WBS Element.{fn} CF missing.",
            )
