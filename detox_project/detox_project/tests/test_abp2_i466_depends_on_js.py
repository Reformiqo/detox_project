"""ABP2-I466 re-reopen #2 (Sahil 2026-06-25) — the previous followup
set `depends_on` / `mandatory_depends_on` on Stock Entry.custom_cost_center
to `eval:doc.stock_entry_type in ['Manufacture','Material Transfer for Manufacture','Repack','Send to Subcontractor']`.

That works server-side (Python `in` is membership) but fails in the
browser: JavaScript's `in` operator checks for OWN PROPERTY existence
on the RHS object, so for an array literal it returns False for every
string key. Result: server-side cc_project_guard.validate_stock_entry
threw "Cost Center is mandatory on the Stock Entry" while the field
itself was HIDDEN in the browser — the user couldn't see the field
to fill it.

Sahil's screenshot of localhost:6005 Stock Entry form shows Project
filled (Kutch) and no Cost Center field anywhere; save throws.

These tests pin the JS-compatible OR-chain expression. See
[[depends-on-must-be-pure-js]] — third time we've hit this trap.
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

    def test_depends_on_does_not_use_python_in_operator(self):
        dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "depends_on",
        )
        self.assertNotRegex(
            dep or "",
            r"in\s*\[",
            f"depends_on must not use the Python `in [list]` operator "
            f"— JS evaluates that as own-property check on the array, "
            f"returning False for every string. Saw: {dep!r}",
        )

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
            f"operator. Saw: {mdo!r}",
        )

    def test_depends_on_uses_or_chain(self):
        """The OR-chain form (`||`) is the cross-language pattern. We
        accept either `||` or `or` — both evaluate correctly server-side
        for completeness, but `||` is the canonical JS form."""
        dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "depends_on",
        )
        self.assertTrue(dep)
        self.assertTrue(
            "||" in dep or " or " in dep,
            f"depends_on must use an OR chain (`||`) covering each "
            f"in-scope SE type. Saw: {dep!r}",
        )

    def test_all_in_scope_types_present_in_depends_on(self):
        dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "depends_on",
        )
        for t in _IN_SCOPE:
            self.assertIn(t, dep)

    def test_js_expression_evaluates_true_only_for_in_scope(self):
        """Simulate the JS evaluation in Python by translating the
        expression: `||` -> ` or `, `==` stays, doc.x -> doc['x']. Then
        eval against each candidate type. Pins the actual semantics
        rather than substring presence."""
        dep = frappe.db.get_value(
            "Custom Field",
            {"dt": "Stock Entry", "fieldname": "custom_cost_center"},
            "depends_on",
        )
        # Strip the "eval:" prefix and translate || -> or for Python eval.
        expr = re.sub(r"^\s*eval:\s*", "", dep)
        py_expr = expr.replace("||", " or ").replace("&&", " and ")

        for t in _IN_SCOPE + ("Material Receipt", "Material Issue",
                              "Material Transfer", ""):
            doc = frappe._dict(stock_entry_type=t)
            result = bool(eval(py_expr, {"doc": doc}))
            expected = t in _IN_SCOPE
            self.assertEqual(
                result, expected,
                f"depends_on must evaluate to {expected} for "
                f"stock_entry_type={t!r}, got {result}",
            )
