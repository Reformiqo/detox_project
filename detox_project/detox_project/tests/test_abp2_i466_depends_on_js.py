"""ABP2-I466 re-reopen #2/#3 (Sahil 2026-06-25) — Stock Entry
custom_cost_center depends_on / mandatory_depends_on must not use the
Python `in [list]` operator.

JavaScript's `in` operator checks for OWN PROPERTY existence on the
RHS object, so for an array literal it returns False for every string
key. Result: server-side cc_project_guard.validate_stock_entry threw
"Cost Center is mandatory on the Stock Entry" while the field itself
was HIDDEN in the browser.

Re-reopen #3 then removed the depends_on entirely (the field is now
always visible — see test_abp2_i466_followup_scope_cc), so this file
only pins `mandatory_depends_on`. See [[depends-on-must-be-pure-js]]
— third time we've hit the JS/Python `in` trap.
"""
import frappe
import re
from frappe.tests import IntegrationTestCase


_IN_SCOPE = (
    "Manufacture",
    "Material Transfer for Manufacture",
    "Repack",
    "Send to Subcontractor",
)


class TestI466DependsOnJS(IntegrationTestCase):

    def test_mandatory_depends_on_does_not_use_python_in_operator(self):
        mdo = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "mandatory_depends_on",
        )
        self.assertNotRegex(
            mdo or "",
            r"in\s*\[",
            f"mandatory_depends_on must not use the Python `in [list]` "
            f"operator — JS evaluates that as own-property check on "
            f"the array, returning False for every string. Saw: {mdo!r}",
        )

    def test_mandatory_depends_on_uses_or_chain(self):
        """`||` is the cross-language pattern — accept `||` or ` or `."""
        mdo = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "mandatory_depends_on",
        )
        self.assertTrue(mdo)
        self.assertTrue(
            "||" in mdo or " or " in mdo,
            f"mandatory_depends_on must use an OR chain (`||`) "
            f"covering each in-scope SE type. Saw: {mdo!r}",
        )

    def test_all_in_scope_types_present_in_mandatory_depends_on(self):
        mdo = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "mandatory_depends_on",
        )
        for t in _IN_SCOPE:
            self.assertIn(t, mdo)

    def test_js_expression_evaluates_true_only_for_in_scope(self):
        """Simulate the JS evaluation in Python by translating the
        expression: `||` -> ` or `, `==` stays, doc.x -> doc['x']. Then
        eval against each candidate type. Pins the actual semantics
        rather than substring presence."""
        mdo = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "mandatory_depends_on",
        )
        # Strip the "eval:" prefix and translate || -> or for Python eval.
        expr = re.sub(r"^\s*eval:\s*", "", mdo)
        py_expr = expr.replace("||", " or ").replace("&&", " and ")

        for t in _IN_SCOPE + ("Material Receipt", "Material Issue",
                              "Material Transfer", ""):
            doc = frappe._dict(stock_entry_type=t)
            result = bool(eval(py_expr, {"doc": doc}))
            expected = t in _IN_SCOPE
            self.assertEqual(
                result, expected,
                f"mandatory_depends_on must evaluate to {expected} for "
                f"stock_entry_type={t!r}, got {result}",
            )
