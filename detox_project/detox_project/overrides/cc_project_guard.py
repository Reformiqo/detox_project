# ABP2-I419 Phase 2 (Sahil 2026-06-17, Out of BRD) — Cost Center + Project
# mandatory-everywhere guard + Production Plan -> Work Order cascade.
# See the FRD's Functional Requirements (FR-22..25), Process Logic L05..06
# and Validations VAL-01, VAL-02, VAL-06, VAL-07.
#
# Hook surface (wired in hooks.py):
#   Production Plan:
#     validate    -> validate_production_plan
#     on_submit   -> cascade_pp_to_work_orders
#   Work Order:
#     validate    -> validate_work_order
#   Stock Entry:
#     before_save -> inherit_from_work_order   (defaults header/rows)
#     validate    -> validate_stock_entry
#
# All three validate_* funcs share the same shape: check header cost_center
# + project, then for every item-row table copy header values down to blank
# cells, then throw if anything is still blank. Single source of truth so
# 'mandatory everywhere' is guaranteed by one piece of logic
# (FRD Validations sheet implementation note).

from __future__ import annotations

import frappe
from frappe import _

# Column on Production Plan that holds the No-BOM Cost Center (added in Phase 1).
PP_CC_FIELD = "custom_cost_center"


# --------------------------------------------------------------------------
# Production Plan
# --------------------------------------------------------------------------
def validate_production_plan(doc, method=None):
	"""VAL-01 + VAL-02 — header CC + Project mandatory; copy header CC/Project
	to blank rows in custom_fg_items + custom_operations; throw if still blank.

	Sahil Image #16 add-on: doc.custom_project is the user-facing proxy
	Project field rendered next to Cost Center. Copy it into doc.project
	BEFORE the header check so server-only callers (API / import / fixture
	load) don't fail the reqd=1 + Phase 2 guard when only the proxy is set.
	"""
	custom_pj = doc.get("custom_project")
	if custom_pj and not doc.get("project"):
		doc.project = custom_pj
	elif doc.get("project") and not custom_pj:
		doc.custom_project = doc.get("project")

	header_cc = doc.get(PP_CC_FIELD)
	header_pj = doc.get("project")
	_check_header(doc, header_cc, header_pj, "Production Plan")

	for table_field in ("custom_fg_items", "custom_operations"):
		_check_rows(doc, table_field, header_cc, header_pj, "Production Plan")


def validate_production_plan_operations_after_submit(doc, method=None):
	"""VAL-01 + VAL-02 for Table 2 only, on an update-after-submit.

	Frappe skips `validate` on update-after-submit, so a materials row
	added or blanked on a submitted plan would otherwise escape the
	mandatory-everywhere guarantee. Table 1 is deliberately NOT checked
	here: its fields are not allow_on_submit, so copying the header value
	into a blank cell there would be rejected by Frappe's own post-submit
	check straight afterwards.
	"""
	_check_rows(
		doc, "custom_operations", doc.get(PP_CC_FIELD), doc.get("project"), "Production Plan"
	)


def _check_operation_uniqueness(doc) -> None:
	"""Phase 7c rolled back per Sahil 2026-06-17 (Image #9 screenshot):
	each Operation has MULTIPLE Materials rows (one per RM/Service item),
	so 'one row per Operation' was wrong. Kept as a no-op for test
	compatibility — the call site in validate_production_plan was
	removed. Each materials row's operation_name is now expected to
	repeat across rows belonging to the same Operation."""
	return


# --------------------------------------------------------------------------
# Work Order
# --------------------------------------------------------------------------
def inherit_wo_from_production_plan(doc, method=None):
	"""ABP2-I483 reopen (Sahil 2026-07-01, Image #55): when a WO is
	created via Production Plan → Create → Work Order button,
	ERPNext's PP.create_work_order() sets ignore_mandatory + ignore_validate
	and the plan itself is often still Draft. The result is a WO with
	Project blank AND Cost Center blank, forcing the user to re-type
	them on every WO — even though the parent PP has them.

	Pull CC + Project from the parent PP on before_insert so the fresh
	WO is born fully populated. Idempotent: never overrides what the
	user already set on the WO.
	"""
	if not doc.get("production_plan"):
		return
	pp_cc, pp_pj = frappe.db.get_value(
		"Production Plan", doc.production_plan,
		[PP_CC_FIELD, "project"],
	) or (None, None)
	if pp_cc and not doc.get("custom_cost_center"):
		doc.custom_cost_center = pp_cc
	if pp_pj and not doc.get("project"):
		doc.project = pp_pj


def validate_work_order(doc, method=None):
	"""VAL-06 — header cost_center + project mandatory on Work Order."""
	header_cc = doc.get("custom_cost_center") or doc.get("cost_center")
	header_pj = doc.get("project")

	# ABP2-I483 reopen (Sahil 2026-07-01, Image #53): PP-cascade only
	# stamps CC when the Production Plan had one at submit time. Fall
	# back to the Project master's default cost_center so WOs whose
	# PP was blank still get a CC and don't block the user.
	if not header_cc and header_pj:
		project_cc = frappe.db.get_value("Project", header_pj, "cost_center")
		if project_cc:
			doc.custom_cost_center = project_cc
			header_cc = project_cc

	_check_header(doc, header_cc, header_pj, "Work Order")

	# WO Item rows (required_items) — copy header CC/Project to blank cells.
	for table_field in ("required_items", "operations"):
		if not doc.get(table_field):
			continue
		_check_rows(doc, table_field, header_cc, header_pj, "Work Order")


# --------------------------------------------------------------------------
# Stock Entry
# --------------------------------------------------------------------------
def validate_stock_entry(doc, method=None):
	"""VAL-07 — header cost_center + project mandatory on Stock Entry.

	SE refactor (Sahil 2026-06-26): ERPNext 16.25+ ships a standard
	`cost_center` field on Stock Entry header. We've dropped our
	`custom_cost_center` CF; read from the standard field only.
	"""
	if not _stock_entry_is_in_scope(doc):
		return
	header_cc = doc.get("cost_center")
	header_pj = doc.get("project")
	_check_header(doc, header_cc, header_pj, "Stock Entry")

	_check_rows(doc, "items", header_cc, header_pj, "Stock Entry")


def _stock_entry_is_in_scope(doc) -> bool:
	"""Phase 2 enforcement applies to Manufacturing-flow SEs.
	Standard Material Issue / Receipt / Repack created OUTSIDE the plan
	keep their existing Detox WM enforcement; we don't double-fire here
	on Material Receipt (Opening) and similar internal flows that have
	no Production Plan context.
	"""
	purpose = (doc.get("stock_entry_type") or "").strip()
	if not purpose:
		return False
	return purpose in {
		"Manufacture",
		"Material Transfer for Manufacture",
		"Repack",
		"Send to Subcontractor",
	}


# --------------------------------------------------------------------------
# Before-save inheritance: SE pulls CC + Project from its Work Order
# (L06 — WO's CC + Project become defaults on its Stock Entries).
# --------------------------------------------------------------------------
def inherit_se_from_work_order(doc, method=None):
	if not _stock_entry_is_in_scope(doc):
		return
	wo_name = doc.get("work_order")
	if not wo_name or not frappe.db.exists("Work Order", wo_name):
		return
	wo = (
		frappe.db.get_value(
			"Work Order",
			wo_name,
			["project", "custom_cost_center"],
			as_dict=True,
		)
		or {}
	)
	# Work Order keeps its `custom_cost_center` Custom Field — no
	# standard cost_center exists on WO. Stock Entry now uses the
	# standard `cost_center` field (post-ERPNext 16.25 refactor).
	wo_cc = wo.get("custom_cost_center")
	wo_pj = wo.get("project")
	if wo_pj and not doc.get("project"):
		doc.project = wo_pj
	if wo_cc and not doc.get("cost_center"):
		doc.cost_center = wo_cc


# --------------------------------------------------------------------------
# Production Plan on_submit cascade -> Work Order (L05)
# --------------------------------------------------------------------------
def cascade_pp_to_work_orders(doc, method=None):
	"""L05 — when a Production Plan is submitted, stamp its
	custom_cost_center + project onto every Work Order already
	generated from this plan.

	Work Orders may be created EITHER from the standard 'Create Work
	Order' flow on the plan, OR later from the same plan. We update
	only those whose docstatus < 2 (not cancelled) so we don't disturb
	cancelled history.
	"""
	header_cc = doc.get(PP_CC_FIELD)
	header_pj = doc.get("project")
	if not (header_cc or header_pj):
		return

	work_orders = frappe.db.sql(
		"""SELECT name FROM `tabWork Order`
           WHERE production_plan = %s AND docstatus < 2""",
		doc.name,
		as_dict=True,
	)
	updates: dict[str, str | None] = {}
	if header_cc:
		updates["custom_cost_center"] = header_cc
	if header_pj:
		updates["project"] = header_pj
	if not updates:
		return

	for wo in work_orders:
		frappe.db.set_value("Work Order", wo.name, updates, update_modified=False)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def _check_header(doc, cc, pj, label: str) -> None:
	missing = []
	if not cc:
		missing.append("Cost Center")
	if not pj:
		missing.append("Project")
	if missing:
		verb = "are" if len(missing) > 1 else "is"
		frappe.throw(
			_("{0} {1} mandatory on the {2}.").format(" and ".join(missing), verb, label),
			title=_("Cost Center / Project missing"),
		)


def _check_rows(doc, table_field: str, header_cc, header_pj, label: str) -> None:
	rows = doc.get(table_field) or []
	for idx, row in enumerate(rows, start=1):
		if not row.get("cost_center") and header_cc:
			row.cost_center = header_cc
		if not row.get("project") and header_pj:
			row.project = header_pj
		if not row.get("cost_center") or not row.get("project"):
			frappe.throw(
				_("Row #{0}: Cost Center and Project are mandatory on every {1} row.").format(idx, label),
				title=_("Cost Center / Project missing"),
			)
