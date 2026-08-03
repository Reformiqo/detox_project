"""ABP2-I515 — replicate Project Budget Plan's linked-doctype config to DGEPL.

The Project Budget Plan doctype itself is app-owned (budgeting_tool) and already
identical on DGEPL; the gap was SEPPL's site-created (module=NULL) config on the
LINKED doctypes (Financial Model / WBS Element / Sub WBS Element / WBS Allocation).
Those Property Setters / Custom Fields / Client Scripts are now shipped as
Detox Project fixtures so they deploy to DGEPL reproducibly.

WBS / Sub-WBS naming is handled by APP CODE (autoname/after_insert in the
controllers; PR #4), NOT by UI Server Scripts — so we deliberately do NOT ship the
legacy naming Server Scripts, and `disable_legacy_wbs_naming_scripts()` disables the
non-idempotent legacy v1 so it can't double-rename against the app code.
"""
import json
import os

import frappe
from frappe.tests import IntegrationTestCase

APP_PATH = frappe.get_app_path("detox_project")
FIXT = os.path.join(APP_PATH, "fixtures")
TARGET_DTS = {"Financial Model", "WBS Element", "Sub WBS Element", "WBS Allocation"}


def _load(name):
	with open(os.path.join(FIXT, name)) as f:
		return json.load(f)


class TestABP2I515PBPLinkedFixtures(IntegrationTestCase):
	def test_all_fixture_files_parse(self):
		for f in ("property_setter.json", "custom_field.json", "client_script.json"):
			self.assertTrue(os.path.exists(os.path.join(FIXT, f)), f"missing fixture {f}")
			self.assertIsInstance(_load(f), list)

	def test_no_server_script_fixture_shipped(self):
		"""Naming is app code (PR #4); shipping the UI naming Server Scripts
		would duplicate it. There must be no server_script fixture and hooks
		must not export Server Script."""
		self.assertFalse(os.path.exists(os.path.join(FIXT, "server_script.json")))
		from detox_project import hooks

		self.assertNotIn("Server Script", {fx["dt"] for fx in hooks.fixtures})

	def test_app_code_owns_wbs_naming(self):
		"""The controllers name WBS / Sub-WBS (autoname + after_insert)."""
		from detox_project.detox_project.doctype.wbs_element.wbs_element import WBSElement
		from detox_project.detox_project.doctype.sub_wbs_element.sub_wbs_element import (
			SubWBSElement,
		)

		for cls in (WBSElement, SubWBSElement):
			self.assertTrue(callable(getattr(cls, "autoname", None)))
			self.assertTrue(callable(getattr(cls, "after_insert", None)))

	def test_legacy_naming_disable_helper_exists(self):
		from detox_project import setup

		self.assertTrue(callable(getattr(setup, "disable_legacy_wbs_naming_scripts", None)))
		self.assertIn("disable_legacy_wbs_naming_scripts", setup.after_migrate.__code__.co_names)

	def test_property_setters_target_real_doctypes_and_fields(self):
		ps = _load("property_setter.json")
		mine = [p for p in ps if p["doc_type"] in TARGET_DTS]
		self.assertGreaterEqual(len(mine), 36, "expected the SEPPL site PS to be present")
		# no fragile per-site dashboard-link props leaked in
		for p in ps:
			self.assertNotIn(p["property"], ("links_order", "link_fieldname"))
		for p in mine:
			self.assertEqual(p.get("module"), "Detox Project")
			self.assertTrue(frappe.db.exists("DocType", p["doc_type"]))
			# field-level PS must point at a field that exists (custom or standard)
			if p["doctype_or_field"] == "DocField" and p.get("field_name"):
				self.assertTrue(
					frappe.get_meta(p["doc_type"]).has_field(p["field_name"]),
					f"{p['doc_type']}.{p['field_name']} does not exist",
				)

	def test_wbs_element_field_order_preserves_dgepl_app_fields(self):
		"""SEPPL's WBS Element field_order omits DGEPL's app fields
		material_budget/service_budget — the fixture must append them so the
		deploy does not drop them from the layout."""
		ps = _load("property_setter.json")
		fo = next(p for p in ps if p["doc_type"] == "WBS Element" and p["property"] == "field_order")
		order = json.loads(fo["value"])
		for extra in ("material_budget", "service_budget"):
			self.assertIn(extra, order)

	def test_custom_sub_wbs_budget_field_present(self):
		cf = _load("custom_field.json")
		row = next((c for c in cf if c["dt"] == "WBS Allocation" and c["fieldname"] == "custom_sub_wbs_budget"), None)
		self.assertIsNotNone(row, "custom_sub_wbs_budget fixture missing")
		self.assertEqual(row.get("module"), "Detox Project")
		self.assertEqual(row["fieldtype"], "Currency")

	def test_client_scripts_exact_enabled_state(self):
		"""UI-glue client scripts only. The legacy 'Sub WBS Naming Series'
		redirect is OFF (superseded by v2); the v2 redirect + Refresh button +
		FM show/hide are ON. All target a linked doctype and are Detox Project
		owned."""
		cs = {c["name"]: c for c in _load("client_script.json")}
		self.assertEqual(cs["Sub WBS Naming Series"]["enabled"], 0)
		self.assertEqual(cs["sub wbs naming series v2"]["enabled"], 1)
		self.assertEqual(cs["Sub WBS Refresh button"]["enabled"], 1)
		self.assertEqual(cs["hide_show_financial_model"]["enabled"], 1)
		for c in cs.values():
			self.assertIn(c["dt"], TARGET_DTS)
			self.assertEqual(c.get("module"), "Detox Project")

	def test_hooks_ships_client_scripts(self):
		from detox_project import hooks

		self.assertIn("Client Script", {fx["dt"] for fx in hooks.fixtures})
