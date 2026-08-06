"""CR-01 — Production Plan date correction tests.

Source: DETOX PRODUCTION FRD CHANGE SET 01 — CR-01.1..CR-01.6, CL-02, CL-03,
CVAL-01, CVAL-02, CVAL-03, Test Scenarios TC-01/TC-03/TC-04.

The doc_events wiring (validate + on_update_after_submit) is added to
detox_project/hooks.py by the manager, so these tests call the change_set
functions directly against real, saved Production Plans — the same functions
the hooks dispatch to. The one genuinely end-to-end assertion (TC-01: a
post-submit date edit is accepted and persisted) drives the real
update_after_submit path so the allow_on_submit Property Setter is exercised
exactly as a user on the form would.
"""

from __future__ import annotations

import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from detox_project.detox_project.change_set.cr01_production_plan_date import (
	ALLOWED_DATE_REVISION_ROLES,
	CL01_CLIENT_SCRIPT_NAME,
	on_update_after_submit_dates,
	setup_cr01_production_plan_date,
	sync_downstream_dates,
	user_can_revise_planned_date,
	validate_production_plan_dates,
)
from detox_project.detox_project.report.production_plan_vs_actual.production_plan_vs_actual import (
	execute as ppva_execute,
)


class TestCR01ProductionPlanDate(IntegrationTestCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.project = frappe.db.get_value("Project", {}, "name")
		cls.cc = frappe.db.get_value(
			"Cost Center", {"company": cls.company, "is_group": 0, "disabled": 0}, "name"
		)
		cls.wh = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 0}, "name"
		)
		cls.item = frappe.db.get_value(
			"Item", {"is_stock_item": 1, "disabled": 0}, "name"
		)
		cls.op = frappe.db.get_value("Operation", {}, "name")
		# No skipTest — these masters exist on the DETOX bench; a genuine
		# absence should surface as a hard failure, not a silent skip.
		missing = [
			n for n, v in {
				"Company": cls.company, "Project": cls.project, "Cost Center": cls.cc,
				"Warehouse": cls.wh, "Item": cls.item, "Operation": cls.op,
			}.items() if not v
		]
		assert not missing, f"Test prerequisites missing on this bench: {missing}"

	def setUp(self):
		self._cleanup = []  # (doctype, name)

	def tearDown(self):
		frappe.set_user("Administrator")
		for dt, name in reversed(self._cleanup):
			try:
				if frappe.db.exists(dt, name):
					frappe.delete_doc(dt, name, force=1, ignore_permissions=True)
			except Exception:
				pass

	# ------------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------------
	def _make_plan(self, planned_date, posting_date=None, submit=False):
		doc = frappe.get_doc({
			"doctype": "Production Plan",
			"company": self.company,
			"custom_no_bom": 1,
			"custom_cost_center": self.cc,
			"project": self.project,
			"posting_date": posting_date or today(),
			"custom_fg_items": [{
				"item_code": self.item,
				"qty_to_manufacture": 10,
				"planned_date": planned_date,
				"fg_warehouse": self.wh,
				"standard_costing_rate": 100,
				"total_standard_cost": 1000,
				"cost_center": self.cc,
				"project": self.project,
			}],
			"custom_operations": [{
				"operation_name": self.op,
				"operation_seq": 1,
				"item_code": self.item,
				"item_type": "Raw Material",
				"standard_rate": 50,
				"qty_per_unit": 2,
				"multiply_by": 20,
				"cost_center": self.cc,
				"project": self.project,
			}],
		})
		doc.insert(ignore_permissions=True)
		self._cleanup.append(("Production Plan", doc.name))
		if submit:
			doc.submit()
		return doc

	def _make_work_order(self, plan_name, planned_start, docstatus=0):
		wo = frappe.get_doc({
			"doctype": "Work Order",
			"production_item": self.item,
			"qty": 5,
			"company": self.company,
			"fg_warehouse": self.wh,
			"production_plan": plan_name,
			"planned_start_date": planned_start,
		})
		wo.flags.ignore_validate = True
		wo.flags.ignore_mandatory = True
		wo.insert(ignore_permissions=True)
		self._cleanup.append(("Work Order", wo.name))
		if docstatus == 1:
			frappe.db.set_value("Work Order", wo.name, "docstatus", 1, update_modified=False)
		return wo.name

	def _make_stock_entry(self, plan_name, work_order, posting, docstatus=0):
		se = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Issue",
			"company": self.company,
			"posting_date": posting,
			"production_plan": plan_name,
			"work_order": work_order,
		})
		se.flags.ignore_validate = True
		se.flags.ignore_mandatory = True
		se.insert(ignore_permissions=True)
		self._cleanup.append(("Stock Entry", se.name))
		if docstatus == 1:
			frappe.db.set_value("Stock Entry", se.name, "docstatus", 1, update_modified=False)
		return se.name

	# ------------------------------------------------------------------
	# CZ-27 / CZ-28 — objects exist
	# ------------------------------------------------------------------
	def test_custom_fields_created(self):
		for fn, ftype in (("custom_date_change_reason", "Small Text"),
						  ("custom_last_date_revised_on", "Datetime")):
			cf = frappe.db.get_value(
				"Custom Field", {"dt": "Production Plan", "fieldname": fn},
				["fieldtype", "allow_on_submit"], as_dict=True,
			)
			self.assertIsNotNone(cf, f"Custom Field Production Plan.{fn} must exist.")
			self.assertEqual(cf.fieldtype, ftype)
			self.assertEqual(cf.allow_on_submit, 1, f"{fn} must be allow_on_submit=1.")
		self.assertEqual(
			frappe.db.get_value(
				"Custom Field",
				{"dt": "Production Plan", "fieldname": "custom_last_date_revised_on"},
				"read_only",
			), 1, "custom_last_date_revised_on must be read-only.",
		)

	def test_cl01_client_script_shipped(self):
		cs = frappe.db.get_value(
			"Client Script", CL01_CLIENT_SCRIPT_NAME,
			["dt", "view", "enabled", "script"], as_dict=True,
		)
		self.assertIsNotNone(cs, "CL-01 Client Script must exist.")
		self.assertEqual(cs.dt, "Production Plan")
		self.assertEqual(cs.enabled, 1)
		# Body drives the header->row cascade on Table 1.
		self.assertIn("custom_fg_items", cs.script)
		self.assertIn("posting_date", cs.script)

	def test_setup_is_idempotent(self):
		# Re-running the setup twice must not raise or duplicate.
		setup_cr01_production_plan_date()
		setup_cr01_production_plan_date()
		self.assertTrue(frappe.db.exists("Client Script", CL01_CLIENT_SCRIPT_NAME))
		self.assertEqual(
			frappe.db.count("Custom Field",
							{"dt": "Production Plan", "fieldname": "custom_date_change_reason"}),
			1,
		)

	def test_planned_date_allow_on_submit_property_setter(self):
		ps = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Detox Production Plan FG", "field_name": "planned_date",
			 "property": "allow_on_submit"}, "value",
		)
		self.assertEqual(ps, "1", "planned_date must be allow_on_submit=1 (CZ-27).")

	# ------------------------------------------------------------------
	# CVAL-01 — date sequence (BLOCK) / TC-03
	# ------------------------------------------------------------------
	def test_cval01_blocks_planned_before_posting(self):
		# planned_date earlier than posting_date must be blocked.
		doc = self._make_plan(
			planned_date=add_days(today(), -3), posting_date=today(),
		)
		with self.assertRaises(frappe.ValidationError):
			validate_production_plan_dates(doc)

	def test_cval01_allows_planned_on_or_after_posting(self):
		doc = self._make_plan(
			planned_date=today(), posting_date=today(),
		)
		# Must NOT raise.
		validate_production_plan_dates(doc)

	# ------------------------------------------------------------------
	# CVAL-02 — past date warns, does not block
	# ------------------------------------------------------------------
	def test_cval02_warns_on_past_date_draft(self):
		# posting_date in the past so planned_date can be past yet still
		# on/after posting (CVAL-01 satisfied), triggering only the warn.
		doc = self._make_plan(
			planned_date=add_days(today(), -3), posting_date=add_days(today(), -10),
		)
		frappe.clear_messages()
		validate_production_plan_dates(doc)  # must not raise
		log = " ".join(str(m) for m in (frappe.local.message_log or []))
		self.assertIn("in the past", log, "CVAL-02 warning should be raised for a past planned date.")

	# ------------------------------------------------------------------
	# TC-01 — post-submit edit is accepted and persisted (allow_on_submit)
	# ------------------------------------------------------------------
	def test_post_submit_date_edit_persists(self):
		d1 = add_days(today(), 5)
		d2 = add_days(today(), 12)
		doc = self._make_plan(planned_date=d1, submit=True)
		self.assertEqual(doc.docstatus, 1)
		reload = frappe.get_doc("Production Plan", doc.name)
		reload.custom_fg_items[0].planned_date = d2
		reload.custom_date_change_reason = "customer rescheduled"
		reload.save()  # real update_after_submit path
		self.assertEqual(
			getdate(frappe.db.get_value(
				"Detox Production Plan FG", reload.custom_fg_items[0].name, "planned_date")),
			getdate(d2),
			"Revised planned_date must persist through update_after_submit.",
		)

	# ------------------------------------------------------------------
	# CVAL-03 — reason mandatory on post-submit change
	# ------------------------------------------------------------------
	def test_cval03_requires_reason_on_post_submit_change(self):
		d1 = add_days(today(), 5)
		d2 = add_days(today(), 12)
		doc = self._make_plan(planned_date=d1, submit=True)
		before = frappe.get_doc("Production Plan", doc.name)
		work = frappe.get_doc("Production Plan", doc.name)
		work.custom_fg_items[0].planned_date = d2
		work.custom_date_change_reason = None
		work._doc_before_save = before
		with self.assertRaises(frappe.ValidationError):
			on_update_after_submit_dates(work)

	# ------------------------------------------------------------------
	# CL-02 — stamp + timeline comment
	# ------------------------------------------------------------------
	def test_cl02_stamps_and_comments(self):
		d1 = add_days(today(), 5)
		d2 = add_days(today(), 12)
		doc = self._make_plan(planned_date=d1, submit=True)
		before = frappe.get_doc("Production Plan", doc.name)
		work = frappe.get_doc("Production Plan", doc.name)
		work.custom_fg_items[0].planned_date = d2
		work.custom_date_change_reason = "shifted to next slot"
		work._doc_before_save = before

		on_update_after_submit_dates(work)

		stamp = frappe.db.get_value("Production Plan", doc.name, "custom_last_date_revised_on")
		self.assertTrue(stamp, "custom_last_date_revised_on must be stamped after a revision.")

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Production Plan", "reference_name": doc.name,
					 "comment_type": "Info"},
			fields=["content"],
		)
		joined = " ".join(c.content for c in comments)
		self.assertIn("revised from", joined)
		self.assertIn("shifted to next slot", joined, "Reason must be in the timeline comment.")
		self.assertIn(frappe.session.user, joined, "User must be in the timeline comment.")

	# ------------------------------------------------------------------
	# CL-03 — downstream draft sync + submitted-link report
	# ------------------------------------------------------------------
	def test_cl03_syncs_draft_downstream_only(self):
		d1 = add_days(today(), 5)
		d2 = add_days(today(), 12)
		doc = self._make_plan(planned_date=d1, submit=True)

		draft_wo = self._make_work_order(doc.name, d1, docstatus=0)
		sub_wo = self._make_work_order(doc.name, d1, docstatus=1)
		draft_se = self._make_stock_entry(doc.name, draft_wo, d1, docstatus=0)
		sub_se = self._make_stock_entry(doc.name, sub_wo, d1, docstatus=1)

		before = frappe.get_doc("Production Plan", doc.name)
		work = frappe.get_doc("Production Plan", doc.name)
		work.custom_fg_items[0].planned_date = d2
		work.custom_date_change_reason = "line reschedule"
		work._doc_before_save = before

		frappe.clear_messages()
		on_update_after_submit_dates(work)

		# Draft WO/SE follow the new date.
		self.assertEqual(
			getdate(frappe.db.get_value("Work Order", draft_wo, "planned_start_date")),
			getdate(d2), "Draft Work Order planned_start_date must sync.",
		)
		self.assertEqual(
			getdate(frappe.db.get_value("Stock Entry", draft_se, "posting_date")),
			getdate(d2), "Draft Stock Entry posting_date must sync.",
		)
		# Submitted WO/SE are never rewritten.
		self.assertEqual(
			getdate(frappe.db.get_value("Work Order", sub_wo, "planned_start_date")),
			getdate(d1), "Submitted Work Order must NOT be rewritten.",
		)
		self.assertEqual(
			getdate(frappe.db.get_value("Stock Entry", sub_se, "posting_date")),
			getdate(d1), "Submitted Stock Entry must NOT be rewritten.",
		)
		# Submitted names surfaced to the user.
		log = " ".join(str(m) for m in (frappe.local.message_log or []))
		self.assertIn(sub_wo, log, "Submitted Work Order must be listed for the user.")
		self.assertIn(sub_se, log, "Submitted Stock Entry must be listed for the user.")

	def test_sync_downstream_noop_when_no_changes(self):
		# Empty changed_map must be a clean no-op.
		doc = self._make_plan(planned_date=add_days(today(), 5), submit=True)
		sync_downstream_dates(doc.name, {})  # must not raise

	# ------------------------------------------------------------------
	# CR-01.6 — report reads planned_date live (TC-04)
	# ------------------------------------------------------------------
	def test_cr0106_report_reads_revised_date_live(self):
		d1 = add_days(today(), 5)
		d2 = add_days(today(), 20)
		doc = self._make_plan(planned_date=d1, submit=True)
		# Revise post-submit through the real save path.
		reload = frappe.get_doc("Production Plan", doc.name)
		reload.custom_fg_items[0].planned_date = d2
		reload.custom_date_change_reason = "moved out"
		reload.save()

		_cols, data = ppva_execute({"production_plan": doc.name})
		rows = [r for r in data if r.get("production_plan") == doc.name]
		self.assertTrue(rows, "Report must return the revised plan.")
		self.assertEqual(
			getdate(rows[0]["planned_date"]), getdate(d2),
			"Production Plan vs Actual must read the live (revised) planned_date, not a snapshot.",
		)

	# ------------------------------------------------------------------
	# CR-01.1 — role gate helper
	# ------------------------------------------------------------------
	def test_role_gate_allows_administrator(self):
		self.assertTrue(user_can_revise_planned_date("Administrator"))

	def test_role_gate_blocks_user_without_allowed_role(self):
		with unittest.mock.patch.object(frappe, "get_roles", return_value=["Blogger"]):
			self.assertFalse(user_can_revise_planned_date("someone@example.com"))

	def test_allowed_roles_exist_on_bench(self):
		# Guard against referencing a role that does not exist here.
		for role in ALLOWED_DATE_REVISION_ROLES:
			self.assertTrue(
				frappe.db.exists("Role", role),
				f"Allowed revision role '{role}' must exist on the bench.",
			)
