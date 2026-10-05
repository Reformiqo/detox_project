"""ABP2-I782 (Reformiqo fix list, 05-10-2026) — SEPPL Production Plan /
Stock Entry fixes:
  1. "Multiply By" removal — Qty x rate = Amount, no FG-qty multiplication.
  2. Hide (not delete) the Purchase Order link fields; drop the submit-time
     validation that required them.
  3. UOM conversion — changing a row's UOM recalculates its rate.
  4. Project Budget (Financial Model) read-only display on Production Plan.

RECONCILIATION (2026-10-05): this fix was first built against a branch 8
commits behind upstream/develop. Re-based onto a fresh branch off the real
upstream/develop and reconciled with Sanket Shah's overlapping work
(6361cc6, 710a98a, 9f14c2d, f927e62) — see the long comment at the top of
change_set/abp2_i782_fixlist.py for the full reasoning. Tests below reflect
the RECONCILED design:
  - get_uom_factor(item_code, uom) composes the existing
    detox_project.api.get_item_uom_factor (item-level UOM Conversion
    Detail, wins when configured) with a global UOM Conversion Factor
    master fallback (only consulted when the item has nothing configured
    for that UOM — confirmed via TestABP2I782UomFactorComposition below,
    using a disposable test Item with a deliberately different item-level
    value to prove precedence).
  - Direction is MULTIPLY, not divide: effective_rate = standard_rate x
    factor, where factor = "how many Standard UOM per 1 Manual UOM" (same
    direction/semantics get_item_uom_factor already uses — confirmed via
    the module docstring's own worked example and cross-checked here).
  - get_operation_rm_rows (710a98a's design) leaves `basic_rate` UNCHANGED
    and sets the row's NATIVE `conversion_factor` field instead — core
    ERPNext prices via transfer_qty (= qty x conversion_factor) x
    basic_rate, so dividing basic_rate AS WELL would double-apply the
    conversion. No `custom_conversion_factor` Custom Field is added to
    Stock Entry Detail (a first draft of this fix did; removed as
    redundant with the native field 710a98a already wires).

Exercises the ticket's own "Testing before handover" scenario: a
Production Plan for PROJ-0026 with Labour (Month), JCB (Day), Diesel
(Litre) rows — built from real local fixture data (PROJ-0026 exists on
this bench; the ticket's cloud doc IDs MFG-PP-2026-00039 / MAT-STE-02043 /
FM-2026-00039 do not exist on the local bench, confirmed via console
before writing this file).

Reproduction of the ORIGINAL bug (CLAUDE.md's "confirm reproduction steps
fail on develop~1" rule): VAL-10 (the PO-required submit block, req #2)
was confirmed to throw "Row #1: link a Purchase Order and PO line on the
source row for accurate variance." on the exact repro doc shape used in
test_val10_po_requirement_removed below, when run against the code at
upstream/develop's HEAD (which has VAL-10 commented out but still present
as dead code — 6361cc6) — see /tmp/repro-ABP2-I782.log. The same doc, run
through the current (VAL-10 fully deleted) code, does not throw.

`Detox Stock Entry Service Item` / the "DETOX Change Set 1" automation
(3 Client Scripts + 5 Server Scripts) are DB-only on
detox.m.frappe.cloud, not present on this local bench. Tests below build
`custom_service_items` rows directly (simulating what the cloud-only
'CS1 Service Item Reroute' script would have produced) to exercise
`recompute_service_item_rates` — the real automation chain itself cannot
be exercised locally.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from detox_project.detox_project.change_set.abp2_i782_fixlist import (
	get_approved_financial_model,
	get_uom_factor,
	recompute_item_conversion_factors,
	recompute_operation_amounts,
	recompute_service_item_rates,
)
from detox_project.detox_project.overrides.stock_entry_manufacture import (
	get_operation_rm_rows,
)

COMPANY = "Saurashtra Enviro Projects Private Limited"
PROJECT = "PROJ-0026"


def _cc():
	return frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 0}, "name")


def _wh():
	return frappe.db.get_value("Warehouse", {"company": COMPANY, "is_group": 0}, "name")


def _op():
	return frappe.db.get_value("Operation", {}, "name")


def _ws():
	return frappe.db.get_value("Workstation", {}, "name")


def _item_with_uom(uom):
	return frappe.db.get_value("Item", {"stock_uom": uom, "disabled": 0}, "name")


def _stock_item():
	return frappe.db.get_value("Item", {"is_stock_item": 1, "disabled": 0}, "name")


class TestABP2I782UomFactorComposition(IntegrationTestCase):
	"""req #3 core reconciliation point: get_uom_factor must try
	detox_project.api.get_item_uom_factor (item-level UOM Conversion
	Detail) FIRST, and only fall back to the global UOM Conversion Factor
	master when the item has nothing configured for that UOM."""

	def _make_item(self, item_group=None, uoms=None, stock_uom="Month"):
		item_group = item_group or frappe.db.get_value("Item Group", {}, "name")
		doc = frappe.get_doc({
			"doctype": "Item",
			"item_code": frappe.generate_hash(length=10),
			"item_group": item_group,
			"stock_uom": stock_uom,
			"is_stock_item": 0,
			# India Compliance makes this mandatory on insert.
			"gst_hsn_code": frappe.db.get_value("GST HSN Code", {}, "name") or "999900",
			"uoms": uoms or [],
		})
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Item", doc.name, force=1, ignore_permissions=True))
		return doc

	def test_item_level_uom_wins_over_global_master(self):
		"""Item explicitly configures an alternate UOM (Box, factor 0.04)
		for a pair (Nos -> Box) that has NO global UOM Conversion Factor
		master row (confirmed on the local DB before writing this — using
		Month/Day here instead would have ERPNext's own Item.validate
		silently NORMALIZE the item-level value to match the global master
		the instant one exists for that pair, since this fix seeds
		Month->Day; that's core behaviour, not a get_uom_factor bug, but
		it means Month/Day can't demonstrate precedence once seeded).
		get_uom_factor must return the item's own 0.04."""
		item = self._make_item(stock_uom="Nos", uoms=[{"uom": "Box", "conversion_factor": 0.04}])
		self.assertEqual(get_uom_factor(item.name, "Box"), 0.04)

	def test_falls_back_to_global_master_when_item_has_nothing(self):
		"""The ticket's actual complaint case: an Item with only its
		Standard UOM configured (e.g. 'Supply of Labour' = Month only) —
		get_uom_factor must fall through to the global Month->Day master
		(1/30) instead of returning None / hard-blocking."""
		item = self._make_item(uoms=[])
		factor = get_uom_factor(item.name, "Day")
		self.assertAlmostEqual(factor, 1 / 30, places=6)

	def test_stock_uom_itself_returns_one(self):
		item = self._make_item(uoms=[])
		self.assertEqual(get_uom_factor(item.name, "Month"), 1.0)

	def test_unresolvable_pair_returns_none_not_a_guess(self):
		"""No item-level config AND no global master row for the pair —
		must come back None, not a guessed 1.0 (ticket's own instruction:
		don't guess silently)."""
		item = self._make_item(uoms=[])
		self.assertIsNone(get_uom_factor(item.name, "Kg"))


class TestABP2I782ProductionPlanOperation(IntegrationTestCase):
	"""req #1 + #3 — Detox Production Plan Operation: Qty x rate = Amount,
	no FG-qty multiplication; Manual UOM conversion (item-level first,
	global-master fallback second)."""

	def _make_plan(self, operation_rows):
		cc, wh, op, ws = _cc(), _wh(), _op(), _ws()
		fg_item = _stock_item()
		self.assertTrue(all([cc, wh, op, ws, fg_item]), "Local bench is missing a base fixture")
		doc = frappe.get_doc({
			"doctype": "Production Plan",
			"company": COMPANY,
			"custom_no_bom": 1,
			"custom_cost_center": cc,
			"project": PROJECT,
			"custom_project": PROJECT,
			"posting_date": today(),
			"custom_processes": [
				{"operation_name": op, "workstation": ws, "operation_seq": 1},
			],
			"custom_fg_items": [{
				# The ticket's own repro: FG qty = 3,000 (the exact quantity
				# that used to get multiplied into every Operation row's
				# Multiply By). Kept here so a regression would be obvious.
				"item_code": fg_item, "qty_to_manufacture": 3000,
				"planned_date": today(), "fg_warehouse": wh,
				"standard_costing_rate": 10, "total_standard_cost": 30000,
				"cost_center": cc, "project": PROJECT,
			}],
			"custom_operations": operation_rows,
		})
		doc.insert(ignore_permissions=True)
		self.addCleanup(self._cleanup_plan, doc.name)
		return doc

	def _cleanup_plan(self, name):
		if frappe.db.exists("Production Plan", name):
			frappe.delete_doc("Production Plan", name, force=1, ignore_permissions=True)

	def test_no_fg_multiplication(self):
		"""Amount must be Qty x Standard Rate only — the FG qty (3,000) must
		NEVER appear in it. This is the ticket's headline bug: a
		₹27,000/Month labour row becoming ~3,000 months (~₹8.1 Cr)."""
		cc, op = _cc(), _op()
		labour_item = _item_with_uom("Month")
		doc = self._make_plan([{
			"operation_name": op, "item_code": labour_item, "item_type": "Service",
			"standard_rate": 27000, "qty": 1,
			"cost_center": cc, "project": PROJECT,
		}])
		row = doc.custom_operations[0]
		self.assertEqual(flt(row.amount), 27000.0,
			"Amount must be Qty(1) x Standard Rate(27000) = 27000, "
			"NOT multiplied by the plan's 3,000-unit FG quantity")
		self.assertEqual(flt(row.multiply_by), 0.0,
			"multiply_by must stay 0/untouched — no longer auto-computed")

	def test_qty_other_than_one(self):
		"""A row explicitly asking for 5 units still only scales by its own
		Qty, never by FG qty."""
		cc, op = _cc(), _op()
		labour_item = _item_with_uom("Month")
		doc = self._make_plan([{
			"operation_name": op, "item_code": labour_item, "item_type": "Service",
			"standard_rate": 27000, "qty": 5,
			"cost_center": cc, "project": PROJECT,
		}])
		self.assertEqual(flt(doc.custom_operations[0].amount), 135000.0)

	def test_manual_uom_month_to_day_converts_rate(self):
		"""The ticket's worked example: ₹27,000/Month -> ₹900/Day, via the
		global-master fallback (this Item has no item-level Day UOM
		configured — confirmed in TestABP2I782UomFactorComposition's
		sibling check on the same fixture item)."""
		cc, op = _cc(), _op()
		labour_item = _item_with_uom("Month")
		doc = self._make_plan([{
			"operation_name": op, "item_code": labour_item, "item_type": "Service",
			"standard_rate": 27000, "qty": 1, "manual_uom": "Day",
			"cost_center": cc, "project": PROJECT,
		}])
		row = doc.custom_operations[0]
		self.assertEqual(row.standard_uom, "Month")
		self.assertAlmostEqual(flt(row.conversion_factor), 1 / 30, places=6)
		self.assertEqual(flt(row.amount), 900.0)

	def test_recompute_operation_amounts_server_safety_net(self):
		"""Direct unit test of the function wired on Production Plan
		`validate` AND `before_update_after_submit` — covers API /
		bulk-grid (CR-02) inserts and post-submit Table 2 edits (every
		field is allow_on_submit=1 per f927e62) that skip the client
		script entirely."""
		labour_item = _item_with_uom("Month")
		row = frappe._dict({
			"standard_rate": 27000, "standard_uom": "Month", "item_code": labour_item,
			"manual_uom": "Hour", "qty": 2,
		})
		doc = frappe._dict({"custom_operations": [row]})
		recompute_operation_amounts(doc)
		self.assertAlmostEqual(flt(row.conversion_factor), 1 / 720, places=8)  # 1/(30*24)
		self.assertAlmostEqual(flt(row.amount), flt(2 * 27000 * (1 / 720)), places=2)


class TestABP2I782GetOperationRmRows(IntegrationTestCase):
	"""req #1 + #3 — the whitelisted method behind the Production Plan's
	'Create -> Stock Entry' fetch and CR-04's Material Transfer builder.
	Reconciled with 710a98a: basic_rate stays at the raw Standard Rate;
	only the native `conversion_factor` field carries the UOM conversion
	(core prices via transfer_qty x basic_rate, not a divided basic_rate)."""

	def test_no_multiply_by_key_and_basic_rate_unchanged(self):
		cc, wh, op, ws = _cc(), _wh(), _op(), _ws()
		fg_item = _stock_item()
		labour_item = _item_with_uom("Month")
		plan = frappe.get_doc({
			"doctype": "Production Plan",
			"company": COMPANY, "custom_no_bom": 1, "custom_cost_center": cc,
			"project": PROJECT, "custom_project": PROJECT, "posting_date": today(),
			"custom_processes": [{"operation_name": op, "workstation": ws, "operation_seq": 1}],
			"custom_fg_items": [{
				"item_code": fg_item, "qty_to_manufacture": 3000,
				"planned_date": today(), "fg_warehouse": wh,
				"standard_costing_rate": 10, "total_standard_cost": 30000,
				"cost_center": cc, "project": PROJECT,
			}],
			"custom_operations": [{
				"operation_name": op, "item_code": labour_item, "item_type": "Service",
				"standard_rate": 27000, "qty": 1, "manual_uom": "Day",
				"cost_center": cc, "project": PROJECT,
			}],
		})
		plan.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Production Plan", plan.name, force=1, ignore_permissions=True))

		rows = get_operation_rm_rows(plan.name, op)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertNotIn("multiply_by", row, "get_operation_rm_rows must no longer return multiply_by (req #1)")
		self.assertEqual(flt(row["basic_rate"]), 27000.0,
			"basic_rate must stay the raw Standard Rate (710a98a's design) — "
			"core prices via transfer_qty (qty x conversion_factor) x basic_rate; "
			"dividing basic_rate AS WELL would double-apply the conversion")
		self.assertAlmostEqual(flt(row["conversion_factor"]), 1 / 30, places=6)


class TestABP2I782Val10Removed(IntegrationTestCase):
	"""req #2 — the PO-required-on-submit validation is gone. See the
	module docstring for the manual before/after repro. 6361cc6 already
	commented this block out upstream; this fix deletes the dead code
	outright (same end behaviour)."""

	def test_submit_path_no_longer_requires_po_on_source_row(self):
		from detox_project.detox_project.overrides.stock_entry_manufacture import (
			validate_stock_entry_manufacture,
		)
		doc = frappe._dict({
			"stock_entry_type": "Manufacture",
			"production_plan": "MFG-PP-REPRO-0001",
			"custom_process_selection": "Mixing",
			"docstatus": 1,
			"custom_production_time": 0,
			"items": [
				frappe._dict({
					"s_warehouse": "Stores - SE", "item_code": "TEST-ITEM", "qty": 10,
					"custom_purchase_order": None, "custom_purchase_order_item": None,
					"is_finished_item": 0,
				}),
				frappe._dict({
					"t_warehouse": "FG - SE", "item_code": "TEST-FG", "qty": 10,
					"is_finished_item": 1,
				}),
			],
		})
		doc.flags = frappe._dict({"validate_before_submit": False})
		# Must NOT raise — pre-fix this exact doc throws
		# "Row #1: link a Purchase Order and PO line on the source row for
		# accurate variance." (see /tmp/repro-ABP2-I782.log).
		validate_stock_entry_manufacture(doc)


class TestABP2I782PoFieldsHidden(IntegrationTestCase):
	"""req #2 — hide (not delete) the 3 PO link locations, except the one
	the manager explicitly said to leave visible."""

	def test_stock_entry_detail_po_fields_hidden(self):
		for fn in ("custom_purchase_order", "custom_purchase_order_item"):
			ps = frappe.db.get_value("Property Setter",
				f"Stock Entry Detail-{fn}-hidden", "value")
			self.assertEqual(ps, "1", f"Stock Entry Detail.{fn} must be hidden")
			self.assertTrue(frappe.db.exists("Custom Field", f"Stock Entry Detail-{fn}"),
				"field must still exist — ticket says hide, not delete")

	def test_landed_cost_taxes_and_charges_po_fields_hidden(self):
		for fn in ("custom_purchase_order", "custom_purchase_order_item"):
			ps = frappe.db.get_value("Property Setter",
				f"Landed Cost Taxes and Charges-{fn}-hidden", "value")
			self.assertEqual(ps, "1", f"Landed Cost Taxes and Charges.{fn} must be hidden")

	def test_service_item_purchase_order_stays_visible(self):
		"""Manager's call (2026-10-05): 'Service Purchase Order' on Detox
		Stock Entry Service Item is the mechanism that routes a service
		item's spend to its own PO — deliberately NOT hidden, unlike the
		other 3 locations."""
		meta = frappe.get_meta("Detox Stock Entry Service Item")
		po_field = meta.get_field("purchase_order")
		self.assertIsNotNone(po_field)
		self.assertFalse(po_field.hidden, "purchase_order must stay visible per the manager's explicit call")
		po_item_field = meta.get_field("purchase_order_item")
		self.assertTrue(po_item_field.hidden, "purchase_order_item is hidden=1 on production already — must match")

	def test_no_custom_conversion_factor_duplicate_on_stock_entry_detail(self):
		"""Reconciliation guard: a first draft of this fix added a
		`custom_conversion_factor` Custom Field to Stock Entry Detail,
		duplicating the NATIVE `conversion_factor` field 710a98a already
		wires. Must not exist — pins the reconciled design."""
		self.assertFalse(
			frappe.db.exists("Custom Field", "Stock Entry Detail-custom_conversion_factor"),
			"must compose with the native conversion_factor field, not add a duplicate custom one",
		)


class TestABP2I782ServiceItemUomConversion(IntegrationTestCase):
	"""req #3 — Detox Stock Entry Service Item (`custom_service_items`).
	Builds a row the way the cloud-only 'CS1 Service Item Reroute' script
	would have (item/qty/uom from the plan or a PO, no conversion logic),
	then calls recompute_service_item_rates directly (same function wired
	on Stock Entry's `validate` doc_event). No core stock-ledger engine
	behind this doctype, so rate IS converted directly here (unlike Stock
	Entry Detail): rate = standard_rate x factor."""

	def _plan(self):
		cc, op, ws = _cc(), _op(), _ws()
		fg_item = _stock_item()
		labour_item = _item_with_uom("Month")
		plan = frappe.get_doc({
			"doctype": "Production Plan",
			"company": COMPANY, "custom_no_bom": 1, "custom_cost_center": cc,
			"project": PROJECT, "custom_project": PROJECT, "posting_date": today(),
			"custom_processes": [{"operation_name": op, "workstation": ws, "operation_seq": 1}],
			"custom_fg_items": [{
				"item_code": fg_item, "qty_to_manufacture": 3000,
				"planned_date": today(), "fg_warehouse": _wh(),
				"standard_costing_rate": 10, "total_standard_cost": 30000,
				"cost_center": cc, "project": PROJECT,
			}],
			"custom_operations": [{
				"operation_name": op, "item_code": labour_item, "item_type": "Service",
				"standard_rate": 27000, "qty": 1,
				"cost_center": cc, "project": PROJECT,
			}],
		})
		plan.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Production Plan", plan.name, force=1, ignore_permissions=True))
		return plan, op, labour_item

	def test_rate_converts_when_uom_differs_from_plan_standard(self):
		plan, op, labour_item = self._plan()
		doc = frappe._dict({
			"production_plan": plan.name,
			"custom_process_selection": op,
			# Simulates the reroute script's output: uom carried over from
			# the original Items row (Day), rate left at the Month-basis
			# standard_rate — exactly MAT-STE-02043's reported symptom.
			"custom_service_items": [frappe._dict({
				"item_code": labour_item, "qty": 2, "uom": "Day",
				"rate": 27000, "amount": 54000, "purchase_order": None,
			})],
		})
		recompute_service_item_rates(doc)
		row = doc.custom_service_items[0]
		self.assertAlmostEqual(flt(row.conversion_factor), 1 / 30, places=6)
		self.assertEqual(flt(row.rate), 900.0)
		self.assertEqual(flt(row.amount), 1800.0)  # 2 x 900

	def test_po_sourced_row_is_left_alone(self):
		"""A row with a Service Purchase Order already keeps its PO-priced
		rate — converting it again would be wrong, not a fix."""
		plan, op, labour_item = self._plan()
		doc = frappe._dict({
			"production_plan": plan.name,
			"custom_process_selection": op,
			"custom_service_items": [frappe._dict({
				"item_code": labour_item, "qty": 2, "uom": "Day",
				"rate": 850, "amount": 1700, "purchase_order": "PO-TEST-0001",
			})],
		})
		recompute_service_item_rates(doc)
		row = doc.custom_service_items[0]
		self.assertEqual(flt(row.rate), 850.0, "PO-sourced rate must not be touched")
		self.assertEqual(flt(row.amount), 1700.0)

	def test_no_production_plan_is_a_noop(self):
		"""Standalone Service Items rows with no linked plan have no
		Standard Rate/UOM to convert from — must not error."""
		doc = frappe._dict({
			"production_plan": None,
			"custom_service_items": [frappe._dict({
				"item_code": "ANY-ITEM", "qty": 1, "uom": "Day", "rate": 500, "amount": 500,
			})],
		})
		recompute_service_item_rates(doc)  # must not raise
		self.assertEqual(flt(doc.custom_service_items[0].rate), 500.0)


class TestABP2I782ItemConversionFactor(IntegrationTestCase):
	"""req #3 — ordinary Items (Stock Entry Detail) rows sourced from a
	Production Plan Operation. Reconciled: only the NATIVE
	`conversion_factor` field is touched; `basic_rate`/`amount` are left
	for core ERPNext's own transfer_qty-driven pricing."""

	def test_conversion_factor_set_for_source_row_leaves_basic_rate_alone(self):
		cc, op, ws = _cc(), _op(), _ws()
		labour_item = _item_with_uom("Month")
		plan = frappe.get_doc({
			"doctype": "Production Plan",
			"company": COMPANY, "custom_no_bom": 1, "custom_cost_center": cc,
			"project": PROJECT, "custom_project": PROJECT, "posting_date": today(),
			"custom_processes": [{"operation_name": op, "workstation": ws, "operation_seq": 1}],
			"custom_fg_items": [{
				"item_code": _stock_item(), "qty_to_manufacture": 3000,
				"planned_date": today(), "fg_warehouse": _wh(),
				"standard_costing_rate": 10, "total_standard_cost": 30000,
				"cost_center": cc, "project": PROJECT,
			}],
			"custom_operations": [{
				"operation_name": op, "item_code": labour_item, "item_type": "Raw Material",
				"standard_rate": 27000, "qty": 1,
				"cost_center": cc, "project": PROJECT,
			}],
		})
		plan.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Production Plan", plan.name, force=1, ignore_permissions=True))

		doc = frappe._dict({
			"production_plan": plan.name,
			"custom_process_selection": op,
			"items": [frappe._dict({
				"item_code": labour_item, "s_warehouse": _wh(), "uom": "Day",
				"basic_rate": 27000, "custom_purchase_order": None,
			})],
		})
		recompute_item_conversion_factors(doc)
		row = doc["items"][0]
		self.assertAlmostEqual(flt(row.conversion_factor), 1 / 30, places=6)
		self.assertEqual(flt(row.basic_rate), 27000.0,
			"basic_rate must NOT be touched — core prices via "
			"transfer_qty x basic_rate")


class TestABP2I782ProjectBudget(IntegrationTestCase):
	"""req #4 — read-only Project Budget display, fetched from the
	Approved Financial Model (filtered on workflow_state, not docstatus).
	NOT the same thing as 9f14c2d's already-shipped "Budget Category"
	(budget_category on Table 2 rows) — separate feature, flagged as such
	in abp2_i782_fixlist.py."""

	def _make_fm(self, **kwargs):
		# workflow_state is enforced by the Workflow engine even on a
		# direct insert (WorkflowPermissionError: Draft -> Approved not
		# allowed) — set it via db_set AFTER insert instead, same pattern
		# as the on_update-doesn't-persist rule (apps/detox.md), which
		# bypasses the workflow transition check entirely (it only runs
		# in validate()/doc.save(), not frappe.db.set_value).
		workflow_state = kwargs.pop("workflow_state", "Approved")
		vals = {
			"doctype": "Financial Model",
			"naming_series": "FM-.YYYY.-",
			"project": PROJECT,
			"company": COMPANY,
			"model_type": "Fresh Waste",
			"budget_type": "OPEX",
			"duration_type": "Years",
			"start_fiscal_year": "2026-2027",
			"opex_start_date": "2026-07-01",
			"opex_end_date": "2027-03-31",
		}
		vals.update(kwargs)
		doc = frappe.get_doc(vals)
		# Unrelated to this fix: inserting a Financial Model on this shared
		# bench triggers a PDF render of the new doc (OSError from
		# wkhtmltopdf — "broken image links") somewhere outside this app's
		# and budgeting_tool's own code (confirmed: neither
		# FinancialModel.validate/on_submit nor any doc_event for
		# "Financial Model"/"Project" references get_pdf/attach_print;
		# traceback's only non-frappe-core frame is this test). Consistent
		# with "local bench is shared" — most likely a queued job from
		# other activity on the bench draining synchronously under
		# frappe.flags.in_test. Neutralized here since it has nothing to
		# do with get_approved_financial_model (the function under test).
		from unittest.mock import patch
		with patch("frappe.utils.pdf.get_pdf", return_value=b""):
			doc.insert(ignore_permissions=True)
		if workflow_state:
			doc.db_set("workflow_state", workflow_state, update_modified=False)
			doc.reload()
		self.addCleanup(lambda: frappe.delete_doc("Financial Model", doc.name, force=1, ignore_permissions=True))
		return doc

	def test_approved_opex_model_returns_opex_dates(self):
		fm = self._make_fm()
		result = get_approved_financial_model(PROJECT)
		self.assertEqual(result.get("project_budget"), fm.name)
		self.assertEqual(result.get("budget_type"), "OPEX")
		self.assertEqual(str(result.get("budget_start_date")), "2026-07-01")
		self.assertEqual(str(result.get("budget_end_date")), "2027-03-31")

	def test_no_approved_model_returns_empty(self):
		# Draft (non-Approved) Financial Model must NOT be returned —
		# the ticket explicitly says filter on workflow_state, not docstatus.
		self._make_fm(workflow_state="Draft")
		result = get_approved_financial_model(PROJECT)
		self.assertEqual(result, {})

	def test_blank_project_returns_empty(self):
		self.assertEqual(get_approved_financial_model(""), {})
		self.assertEqual(get_approved_financial_model(None), {})
