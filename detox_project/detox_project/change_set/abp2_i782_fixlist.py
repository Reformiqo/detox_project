# =====================================================================
# ABP2-I782 (Reformiqo fix list, 05-10-2026) — Production Plan / Stock
# Entry fixes for SEPPL:
#   1. Remove "Multiply By" (FG-qty multiplication) — each
#      Detox Production Plan Operation row stands alone: Qty x rate = Amount.
#   2. Hide (not delete) the 3 Purchase Order link locations on Stock Entry
#      that shouldn't be user-facing for this flow, and drop the submit-time
#      validation that required them.
#   3. Fix UOM conversion so changing a row's UOM (e.g. Month -> Day)
#      recalculates its rate instead of silently keeping the old one.
#   4. Show the Project's Approved Financial Model + budget dates on
#      Production Plan (read-only, display only).
#
# CODE-FIRST, same pattern as cr050607_stock_entry.py: every Custom Field,
# Property Setter and master-data row here is upserted idempotently from
# setup.py:after_migrate, so it survives an FC redeploy even though fixture
# sync (which also captures these, since module="Detox Project") runs first.
#
# RECONCILIATION (2026-10-05) — this module was first written against a
# branch that was 8 commits behind upstream/develop. Sanket Shah's work in
# that window (6361cc6, 710a98a, 9f14c2d, f927e62, bd1fafa, 281c0f9) already
# shipped a chunk of overlapping ground:
#   - 6361cc6 already comments out the VAL-10 PO-required-on-submit throw
#     this ticket's req #2 removes. We delete the dead commented block
#     instead of leaving it — same end state, cleaner diff.
#   - 710a98a + 9f14c2d already added `detox_project.api.get_item_uom_factor`
#     (item-level UOM Conversion Detail lookup) and wired it into
#     get_operation_rm_rows + the Production Plan material dialog's
#     manual_uom onchange. CRITICAL: get_item_uom_factor deliberately does
#     NOT fall back to the global UOM Conversion Factor master (its own
#     docstring: erpnext's get_conversion_factor "falls back to the global
#     ... and then to 1.0, so a UOM missing from the Item looks like a valid
#     1:1 one"). This ticket's actual complaint ("Items have only one
#     UOM... Supply of Labour = Month only") is exactly the case where NO
#     item-level UOM Conversion Detail row exists — i.e. exactly when
#     get_item_uom_factor returns None today and the dialog hard-throws
#     ("UOM X is not set on Item Y..."). get_uom_factor() below COMPOSES
#     with it (item-level first, global-master fallback second) rather than
#     duplicating or replacing it — every caller in this ticket goes through
#     get_uom_factor(), never calls the global-master lookup directly.
#   - f927e62 made every Detox Production Plan Operation field
#     allow_on_submit=1 (Table 2 edits are now legal post-submit) and added
#     before_update_after_submit re-validation (cc_project_guard.py) since
#     Frappe skips `validate` on update-after-submit. This ticket's new
#     qty/amount/conversion_factor fields get allow_on_submit=1 to match,
#     and recompute_operation_amounts is ALSO wired on
#     before_update_after_submit (see hooks.py) for the same reason —
#     otherwise a post-submit Table 2 edit would leave a stale Amount.
#   - f927e62 also added a live "Multiply By" preview in the material
#     dialog (qty_per_unit onchange) and a `_fg_total_qty()` helper in
#     production_plan_custom.js. Both are deleted as part of removing
#     Multiply By (req #1) — they have no purpose once nothing computes
#     multiply_by anymore.
#   - 9f14c2d's Budget Category feature (`budget_category` field +
#     get_project_budget_categories) is a DIFFERENT, already-shipped
#     feature — not this ticket's req #4 (read-only Project Budget / dates
#     header display) and not touched here. Worth flagging separately:
#     get_project_budget_categories filters on `financial_model.docstatus
#     < 2`, not `workflow_state = Approved` — the exact anti-pattern this
#     ticket's own text warned against. Out of scope to fix; reported to
#     the manager.
#
# Ground truth for `Detox Stock Entry Service Item` / the surrounding
# "DETOX Change Set 1" automation (3 Client Scripts + 5 Server Scripts, all
# DB-only on detox.m.frappe.cloud, never in git) came from the manager
# fetching frappe.get_doc() output directly off production on 2026-10-05.
# Those 8 scripts are NOT touched/ported here (explicit instruction) — this
# module only adds the new conversion-factor plumbing so they compose with
# that existing automation rather than fight it. See the docstring on each
# function below for exactly how.
# =====================================================================

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

from detox_project.detox_project.api import get_item_uom_factor

MODULE = "Detox Project"

# Production-Plan-linked Stock Entry types this fix's conversion logic
# applies to (mirrors MFG_TYPES in overrides/stock_entry_manufacture.py —
# duplicated rather than imported to keep this change-set file import-free
# of the overrides package, consistent with how cr050607 is structured).
MFG_TYPES = {"Manufacture", "Material Transfer for Manufacture", "Repack"}

# 2-hop fallback chain for UOM pairs the global UOM Conversion Factor master
# can't resolve directly even after seeding Month->Day and Day->Hour (i.e.
# only Month<->Hour, which has no direct master row — deliberately not
# added as its own row to avoid a 3rd near-duplicate master entry; derived
# instead).
_TIME_CHAIN = ["Month", "Day", "Hour"]


# =====================================================================
# UOM conversion (req #3) — shared by Production Plan, Stock Entry Detail,
# Detox Stock Entry Service Item and Additional Costs.
#
# get_uom_factor(item_code, uom) is THE one function every caller in this
# ticket uses. It composes (does not replace) the existing
# detox_project.api.get_item_uom_factor:
#   1. Item-level UOM Conversion Detail row (precise, per-item data) first.
#   2. Global UOM Conversion Factor master (this fix's Month/Day/Hour +
#      TON/Tonne seed) only when step 1 has nothing for that UOM.
# Both steps return the SAME direction/semantics: "how many of the Item's
# stock_uom make up 1 `uom`" (erpnext's own convention — see
# get_uom_conv_factor's docstring: uom=Kg, stock_uom=Gram -> 1000).
# =====================================================================
def _raw_master_factor(from_uom: str | None, to_uom: str | None) -> float | None:
	"""How many `to_uom` make up 1 `from_uom`, or None if unresolvable.
	Thin wrapper around core's erpnext.stock.doctype.item.item.get_uom_conv_factor
	(exact match, inverse match, single common-ancestor intermediate match
	against the GLOBAL `UOM Conversion Factor` master — e.g. Day->Hour
	already resolves today via the existing Second->Day / Second->Hour
	rows, confirmed on the local DB before writing this). This is the
	global-master step ONLY — never called directly by anything outside
	get_uom_factor(); see the module docstring for why."""
	if not from_uom or not to_uom:
		return None
	if from_uom == to_uom:
		return 1.0
	from erpnext.stock.doctype.item.item import get_uom_conv_factor

	return get_uom_conv_factor(from_uom, to_uom)


def get_conversion_factor(from_uom: str | None, to_uom: str | None) -> float | None:
	"""Global-master lookup with a 2-hop Month-Day-Hour fallback (so
	Month<->Hour resolves even though no direct master row exists for it).
	Returns None — never a guessed 1 — when nothing can be derived. This
	is the FALLBACK step inside get_uom_factor(); not item-aware on its
	own, so nothing in this ticket calls it directly against an item row
	— see get_uom_factor()."""
	direct = _raw_master_factor(from_uom, to_uom)
	if direct:
		return direct
	if from_uom in _TIME_CHAIN and to_uom in _TIME_CHAIN:
		fi, ti = _TIME_CHAIN.index(from_uom), _TIME_CHAIN.index(to_uom)
		if fi == ti:
			return 1.0
		step = 1 if fi < ti else -1
		factor = 1.0
		for i in range(fi, ti, step):
			hop = _raw_master_factor(_TIME_CHAIN[i], _TIME_CHAIN[i + step])
			if not hop:
				return None
			factor *= hop
		return factor
	return None


def get_uom_factor(item_code: str | None, uom: str | None) -> float | None:
	"""ABP2-I782 — how many of `item_code`'s stock_uom make up 1 `uom`.

	Composes with the existing detox_project.api.get_item_uom_factor
	(item-level UOM Conversion Detail — precise, wins when present) and
	only falls back to the global UOM Conversion Factor master
	(get_conversion_factor) when the item has nothing configured for that
	UOM — which is this ticket's actual complaint: most Items here have
	only one UOM configured at all (e.g. "Supply of Labour" = Month only),
	so get_item_uom_factor returns None for every alternate UOM and the
	dialog used to hard-throw instead of falling through to a conversion
	that's globally known (Month -> Day = 30 etc). Returns None when
	NEITHER source resolves — callers must not guess a factor."""
	if not item_code or not uom:
		return None
	factor = get_item_uom_factor(item_code, uom)
	if factor:
		return factor
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	if not stock_uom or stock_uom == uom:
		return None
	return get_conversion_factor(uom, stock_uom)


@frappe.whitelist()
def get_uom_factor_api(item_code: str, uom: str):
	"""Client-side entry point (Production Plan dialog/grid + Stock Entry
	UOM-change handlers) for get_uom_factor — kept as a thin whitelisted
	wrapper so there is exactly one implementation."""
	return get_uom_factor(item_code, uom)


@frappe.whitelist()
def get_plan_operation_rate(production_plan: str, item_code: str, uom: str | None = None, operation: str | None = None) -> dict:
	"""Client-side live-preview helper (Stock Entry Items / Service Items
	UOM-change handlers): the Standard Rate + Standard UOM a Production
	Plan Operation row carries for one item, plus — when `uom` is given
	and differs from the row's Standard UOM — the converted rate (via
	get_uom_factor, item-level first) so the browser can show it
	immediately instead of waiting for the next save. One round trip
	instead of two separate calls."""
	op = _plan_operation_lookup(production_plan, operation).get(item_code)
	if not op:
		return {}
	result = {"standard_rate": flt(op.standard_rate), "standard_uom": op.standard_uom}
	if uom and uom != op.standard_uom:
		factor = get_uom_factor(item_code, uom)
		if factor:
			result["conversion_factor"] = factor
			result["rate"] = flt(flt(op.standard_rate) * factor, 2)
	return result


def _plan_operation_lookup(plan: str, operation: str | None = None) -> dict:
	"""item_code -> {standard_rate, standard_uom} for a plan's Table 2
	rows, optionally narrowed to one operation."""
	if not plan:
		return {}
	filters = {"parent": plan, "parenttype": "Production Plan"}
	if operation:
		filters["operation_name"] = operation
	rows = frappe.get_all(
		"Detox Production Plan Operation",
		filters=filters,
		fields=["item_code", "standard_rate", "standard_uom"],
	)
	return {r.item_code: r for r in rows if r.item_code}


# =====================================================================
# req #1 — Production Plan Operation: Qty x rate = Amount, no FG qty.
# =====================================================================
def _effective_rate(row) -> tuple[float, float | None]:
	"""(effective_rate, conversion_factor_or_None). effective_rate is
	Standard Rate converted into Manual UOM terms when Manual UOM is set,
	differs from Standard UOM, and get_uom_factor can resolve a factor
	(item-level first, global-master fallback) — otherwise the raw
	Standard Rate (factor None, nothing guessed). effective_rate =
	standard_rate x factor, where factor = "how many Standard UOM per 1
	Manual UOM" (same direction/semantics as detox_project.api.
	get_item_uom_factor) — e.g. Standard UOM=Month, Manual UOM=Day,
	factor=1/30, effective_rate = 27000 x 1/30 = 900."""
	std_rate = flt(row.get("standard_rate"))
	item_code = row.get("item_code")
	std_uom = row.get("standard_uom")
	man_uom = row.get("manual_uom")
	if not man_uom or man_uom == std_uom or not item_code:
		return std_rate, None
	factor = get_uom_factor(item_code, man_uom)
	if not factor:
		return std_rate, None
	return flt(std_rate * factor, 2), factor


def recompute_operation_amounts(doc, method=None) -> None:
	"""ABP2-I782 req #1 + #3 — wired on Production Plan `validate` AND
	`before_update_after_submit` (every field on this child table is
	allow_on_submit=1 per f927e62, and Frappe skips `validate` on an
	update-after-submit, so without the second wiring a post-submit Table
	2 edit would leave a stale Amount — same reasoning as
	cc_project_guard.validate_production_plan_operations_after_submit,
	which this runs alongside).

	Server-side safety net mirroring production_plan_custom.js's client
	calc, so rows created via the bulk XLSX grid (CR-02) or any API path
	land with a correct Amount even without the browser's recompute. Never
	reads Table 1 (Finished Goods) quantity — that FG-multiplication was
	the 'Multiply By' bug this ticket removes. `multiply_by` itself is left
	untouched (hidden field, kept for historical data per the ticket)."""
	for row in doc.get("custom_operations") or []:
		qty = flt(row.get("qty")) or 1.0
		rate, factor = _effective_rate(row)
		row.conversion_factor = factor or 0
		row.amount = flt(qty * rate, 2)


# =====================================================================
# req #3 — Stock Entry Detail (Items) + Detox Stock Entry Service Item:
# convert rate when the row's UOM differs from the plan's Standard UOM.
# =====================================================================
def recompute_item_conversion_factors(doc, method=None) -> None:
	"""ABP2-I782 req #3 — server-side safety net for ordinary Items
	(Stock Entry Detail) source rows sourced from a Production Plan
	Operation. get_operation_rm_rows already sets the row's NATIVE
	`conversion_factor` field at fetch time (710a98a); this re-asserts it
	on save for rows whose `uom` was changed in the grid AFTER the fetch
	(no live client handler existed for that before this ticket — see
	the `uom` handler added in stock_entry_manufacture.js). Deliberately
	does NOT touch `basic_rate` or `amount`: core ERPNext already prices
	via `transfer_qty (= qty x conversion_factor) x basic_rate`, so
	basic_rate stays at the Standard UOM's rate and the native
	conversion_factor field is the only thing that needs to change —
	dividing/overwriting basic_rate as well would double-apply the
	conversion (confirmed by reasoning through 710a98a's design before
	writing this; an earlier draft of this fix did exactly that and would
	have corrupted valuation). Skips rows with `custom_purchase_order`
	set — a PO-sourced rate is already priced for the PO's own UOM."""
	plan = doc.get("production_plan")
	rows = doc.get("items") or []
	if not plan or not rows:
		return
	op_by_item = _plan_operation_lookup(plan, doc.get("custom_process_selection"))
	for row in rows:
		if not row.get("s_warehouse"):
			continue  # only source/consumption rows carry a plan standard_rate basis
		op = op_by_item.get(row.get("item_code"))
		if not op or row.get("custom_purchase_order"):
			continue
		row_uom = row.get("uom") or op.standard_uom
		if not row_uom or row_uom == op.standard_uom:
			continue
		factor = get_uom_factor(row.get("item_code"), row_uom)
		if factor:
			row.conversion_factor = factor
		# else: leave conversion_factor as-is — unresolved, don't guess.


def recompute_service_item_rates(doc, method=None) -> None:
	"""ABP2-I782 req #3 — Service Items (Non Stock) grid (`custom_service_items`,
	doctype `Detox Stock Entry Service Item`). Unlike Stock Entry Detail,
	this doctype has no core stock-ledger engine behind it (no
	transfer_qty/conversion_factor-driven valuation) — it is a flat custom
	child table (qty, uom, rate, amount), so `rate` itself must be
	converted directly: rate = standard_rate x get_uom_factor(item_code,
	uom), same direction/semantics as everywhere else in this fix.

	Wired on Stock Entry's `validate` doc_event (NOT a method on
	DetoxStockEntryServiceItem itself — verified against frappe's
	Document._validate(), which never calls a child row's own controller
	`validate()`; see the comment in that doctype's .py file).

	Ordering vs the DB-only automation (per the manager's 2026-10-05
	production pull): `validate` runs after the 'CS1 Service Item Reroute'
	Before-Validate script, so this also catches rows that arrived via
	that auto-reroute (which sets rate/uom from the plan or a PO with NO
	conversion logic — the exact bug class this ticket reports), not just
	rows typed directly into the grid. It runs before the 'CS1 Validate'
	Before-Save script's own `amount = qty * rate` pass, so that script
	just reproduces the amount we already computed here — no conflict.
	Also composes with the live 'Service Items Grid' Client Script (same
	qty*rate formula for interactive edits) for the same reason.

	Skips rows with `purchase_order` set, same reasoning as the Items-table
	fix — "their expense stays with the Service Purchase Order" (verbatim
	from the CS1 Service Item Reroute script's own user-facing message).

	NOTE: this doctype has no 'set rate manually' flag (unlike Stock Entry
	Detail's set_basic_rate_manually), so there is no way to distinguish a
	deliberately-typed override from the exact bug this ticket reports (a
	stale Month-basis rate left on a Day-uom row). Recomputing unconditionally
	for non-PO rows matches the ticket's own worked example and is the
	documented trade-off — flagged to the manager."""
	plan = doc.get("production_plan")
	rows = doc.get("custom_service_items") or []
	if not plan or not rows:
		return
	op_by_item = _plan_operation_lookup(plan, doc.get("custom_process_selection"))
	for row in rows:
		qty = flt(row.get("qty"))
		op = op_by_item.get(row.get("item_code"))
		if not op or row.get("purchase_order"):
			row.amount = flt(qty * flt(row.get("rate")), 2)
			continue
		std_rate = flt(op.get("standard_rate"))
		row_uom = row.get("uom") or op.get("standard_uom")
		if not row_uom or row_uom == op.get("standard_uom"):
			row.conversion_factor = 0
			if not row.get("rate"):
				row.rate = std_rate
		else:
			factor = get_uom_factor(row.get("item_code"), row_uom)
			if factor:
				row.conversion_factor = factor
				row.rate = flt(std_rate * factor, 2)
			# else: leave rate as-is — factor unresolved, don't guess.
		row.amount = flt(qty * flt(row.get("rate")), 2)


# =====================================================================
# req #4 — Project Budget display on Production Plan.
#
# NOT to be confused with 9f14c2d's already-shipped "Budget Category"
# feature (budget_category field on Detox Production Plan Operation,
# get_project_budget_categories) — that tags individual Table 2 rows
# against a Project Cost Category from the Financial Model's child
# tables. This is a separate, header-level, read-only display of the
# Financial Model itself + its CAPEX/OPEX date window.
#
# SEPARATE FINDING (flagged, not fixed — out of scope): 9f14c2d's
# get_project_budget_categories filters on `financial_model.docstatus < 2`,
# not `workflow_state = Approved`. The ticket's own text specifically
# warned against exactly this ("Filter on workflow_state, not docstatus,
# it is still 0"). Financial Model is workflow-driven and stays
# docstatus=0 even when Approved (confirmed against
# budgeting_tool/.../financial_model.py), so that query can surface
# categories from a Draft (never-approved) Financial Model. Reported to
# the manager; not touched here.
# =====================================================================
@frappe.whitelist()
def get_approved_financial_model(project: str) -> dict:
	"""ABP2-I782 req #4 — the Approved Financial Model for a Project, with
	the budget-type-appropriate date pair. Filters on `workflow_state`
	(NOT docstatus — see the note above). Display only — no validation,
	no effect on any calculation, called only from the Production Plan
	client script's `project` handler.

	budget_type == 'Both': no single pair of dates is authoritative: we
	show OPEX dates first, falling back to CAPEX — flagged to the manager
	as an assumption, not specified by the ticket."""
	if not project:
		return {}
	rows = frappe.get_all(
		"Financial Model",
		filters={"project": project, "workflow_state": "Approved"},
		fields=[
			"name", "budget_type",
			"capex_start_date", "capex_end_date",
			"opex_start_date", "opex_end_date",
		],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return {}
	fm = rows[0]
	if fm.budget_type == "CAPEX":
		start, end = fm.capex_start_date, fm.capex_end_date
	elif fm.budget_type == "OPEX":
		start, end = fm.opex_start_date, fm.opex_end_date
	else:  # "Both" — OPEX first, CAPEX fallback (assumption, flagged above).
		start, end = fm.opex_start_date or fm.capex_start_date, fm.opex_end_date or fm.capex_end_date
	return {
		"project_budget": fm.name,
		"budget_type": fm.budget_type,
		"budget_start_date": start,
		"budget_end_date": end,
	}


# =====================================================================
# CODE-FIRST install (call from detox_project.setup.after_migrate)
# =====================================================================
def install() -> None:
	install_custom_fields()
	install_property_setters()
	install_uom_conversion_masters()


def install_custom_fields() -> None:
	"""New Custom Fields for ABP2-I782:
	  - Production Plan: read-only Project Budget display block (req #4).
	  - Stock Entry: `custom_service_items` Table -> Detox Stock Entry
	    Service Item (formalizes the DB-only doctype's attachment point).
	  - Landed Cost Taxes and Charges: `custom_conversion_factor` (req #3).
	`Detox Production Plan Operation`'s own new fields (qty, amount,
	conversion_factor) are native fields in that doctype's JSON, not
	Custom Fields — added directly to the file since detox_project owns
	that doctype. Same for `Detox Stock Entry Service Item.conversion_factor`.

	NOTE: unlike the first draft of this fix, there is NO
	`custom_conversion_factor` Custom Field added to Stock Entry Detail —
	710a98a already wires the NATIVE `conversion_factor` field for that
	purpose (see get_operation_rm_rows / recompute_item_conversion_factors);
	adding a second, custom one would have been a confusing duplicate."""
	fields: dict[str, list[dict]] = {
		"Production Plan": [
			{
				"fieldname": "custom_budget_section",
				"label": "Project Budget",
				"fieldtype": "Section Break",
				"insert_after": "custom_project",
				"collapsible": 1,
				"module": MODULE,
			},
			{
				"fieldname": "custom_project_budget",
				"label": "Project Budget",
				"fieldtype": "Link",
				"options": "Financial Model",
				"insert_after": "custom_budget_section",
				"read_only": 1,
				"module": MODULE,
				"description": "Auto-fetched: the Approved Financial Model for this Project. Display only.",
			},
			{
				"fieldname": "custom_budget_type",
				"label": "Budget Type",
				"fieldtype": "Data",
				"insert_after": "custom_project_budget",
				"read_only": 1,
				"module": MODULE,
			},
			{
				"fieldname": "custom_budget_col_break",
				"fieldtype": "Column Break",
				"insert_after": "custom_budget_type",
				"module": MODULE,
			},
			{
				"fieldname": "custom_budget_start_date",
				"label": "Budget Start Date",
				"fieldtype": "Date",
				"insert_after": "custom_budget_col_break",
				"read_only": 1,
				"module": MODULE,
			},
			{
				"fieldname": "custom_budget_end_date",
				"label": "Budget End Date",
				"fieldtype": "Date",
				"insert_after": "custom_budget_start_date",
				"read_only": 1,
				"module": MODULE,
			},
		],
		"Stock Entry": [
			# Formalizes the DB-only live attachment point — Table field
			# "Service Items (Non Stock)", already live on production
			# inserted after `items` (per the manager's 2026-10-05 pull).
			{
				"fieldname": "custom_service_items",
				"label": "Service Items (Non Stock)",
				"fieldtype": "Table",
				"options": "Detox Stock Entry Service Item",
				"insert_after": "items",
				"module": MODULE,
			},
		],
		"Landed Cost Taxes and Charges": [
			{
				"fieldname": "custom_conversion_factor",
				"label": "Conversion Factor",
				"fieldtype": "Float",
				"precision": "6",
				"insert_after": "custom_cost_center",
				"read_only": 1,
				"module": MODULE,
				"description": "ABP2-I782 — display only. Populated when the Service Item's stock UOM differs from the row's UOM.",
			},
		],
	}

	to_create: dict[str, list[dict]] = {}
	for dt, specs in fields.items():
		if not frappe.db.exists("DocType", dt):
			continue
		to_create[dt] = specs

	create_custom_fields(to_create, update=True)
	for dt in to_create:
		try:
			frappe.clear_cache(doctype=dt)
		except Exception:
			pass
	print(
		"detox_project: abp2_i782_fixlist install_custom_fields — "
		f"{sum(len(v) for v in to_create.values())} field(s) upserted."
	)


def install_property_setters() -> None:
	"""Hide (not delete) the Purchase Order link fields per the ticket's
	item #2, on exactly the 2 locations confirmed as Custom Fields:
	  - Stock Entry Detail.custom_purchase_order / custom_purchase_order_item
	  - Landed Cost Taxes and Charges.custom_purchase_order / custom_purchase_order_item
	`Detox Stock Entry Service Item.purchase_order` ("Service Purchase
	Order") is deliberately LEFT VISIBLE — manager's call (2026-10-05):
	it is the mechanism that routes a service item's own spend to its own
	PO ("their expense stays with the Service Purchase Order" per the
	CS1 Service Item Reroute script), structurally different from the
	other 3 locations which were incidental PO plumbing for stock-item
	rows. `purchase_order_item` on that doctype is already hidden=1 as a
	native field in its own JSON (ground truth from production), so no
	Property Setter is needed there."""
	specs = [
		("Stock Entry Detail", "custom_purchase_order", "hidden", "Check", "1"),
		("Stock Entry Detail", "custom_purchase_order_item", "hidden", "Check", "1"),
		("Landed Cost Taxes and Charges", "custom_purchase_order", "hidden", "Check", "1"),
		("Landed Cost Taxes and Charges", "custom_purchase_order_item", "hidden", "Check", "1"),
	]
	for dt, field, prop, ptype, value in specs:
		if not frappe.db.exists("DocType", dt):
			continue
		_upsert_property_setter(dt, field, prop, ptype, value)

	for dt in {s[0] for s in specs}:
		try:
			frappe.clear_cache(doctype=dt)
		except Exception:
			pass
	print(f"detox_project: abp2_i782_fixlist install_property_setters — {len(specs)} PS upserted.")


def _upsert_property_setter(dt, field, prop, ptype, value) -> None:
	ps_name = f"{dt}-{field}-{prop}"
	if frappe.db.exists("Property Setter", ps_name):
		ps = frappe.get_doc("Property Setter", ps_name)
		changed = False
		if ps.value != value:
			ps.value = value
			changed = True
		if ps.get("module") != MODULE:
			ps.module = MODULE
			changed = True
		if changed:
			ps.save(ignore_permissions=True)
		return
	frappe.get_doc({
		"doctype": "Property Setter",
		"name": ps_name,
		"doctype_or_field": "DocField",
		"doc_type": dt,
		"field_name": field,
		"property": prop,
		"property_type": ptype,
		"value": value,
		"module": MODULE,
	}).insert(ignore_permissions=True)


def install_uom_conversion_masters() -> None:
	"""ABP2-I782 req #3 — seed the 2 missing `UOM Conversion Factor` rows
	plus a 1:1 TON<->Tonne bridge, idempotently (no natural unique name —
	autoname is a hash — so look up by from_uom/to_uom before inserting).
	This is the FALLBACK layer behind get_uom_factor() — only consulted
	when an Item has no per-item UOM Conversion Detail row (see module
	docstring).

	Values confirmed with the manager 2026-10-05 (originally flagged for
	client confirmation per the ticket's own "don't guess silently"
	instruction): Month->Day = 30, Day->Hour = 24. Day->Hour is actually
	already derivable today via the existing Second->Day / Second->Hour
	rows (confirmed on the local DB: 0.000277778 / 0.0000115740 = 24.00),
	but an explicit row is added anyway for auditability — Detox staff can
	see '24' directly in the master instead of an indirect, precision-
	dependent derivation that would silently change if those legacy
	Second-based rows are ever edited."""
	if not frappe.db.exists("DocType", "UOM Conversion Factor"):
		return
	rows = [
		("Time", "Month", "Day", 30.0),
		("Time", "Day", "Hour", 24.0),
		# TON and Tonne are two separate UOMs on this site (50 Items on TON,
		# 5 on Tonne) — ticket's lower-risk option ("add a 1:1 conversion")
		# over consolidating every Item onto one UOM.
		("Mass", "TON", "Tonne", 1.0),
	]
	created = updated = 0
	for category, from_uom, to_uom, value in rows:
		if not (frappe.db.exists("UOM", from_uom) and frappe.db.exists("UOM", to_uom)):
			continue
		existing = frappe.db.get_value(
			"UOM Conversion Factor", {"from_uom": from_uom, "to_uom": to_uom}, "name"
		)
		if existing:
			# Self-heal (same idiom as _upsert_property_setter): re-assert
			# the value on every migrate rather than just skip-if-exists.
			if flt(frappe.db.get_value("UOM Conversion Factor", existing, "value")) != value:
				frappe.db.set_value("UOM Conversion Factor", existing, "value", value, update_modified=False)
				updated += 1
			continue
		frappe.get_doc({
			"doctype": "UOM Conversion Factor",
			"category": category,
			"from_uom": from_uom,
			"to_uom": to_uom,
			"value": value,
		}).insert(ignore_permissions=True)
		created += 1
	print(
		"detox_project: abp2_i782_fixlist install_uom_conversion_masters — "
		f"{created} row(s) created, {updated} corrected."
	)
