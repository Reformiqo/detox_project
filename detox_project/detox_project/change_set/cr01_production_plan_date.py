"""CR-01 — Production Plan date correction (DETOX Production Change-Set 01).

Source: DETOX PRODUCTION FRD CHANGE SET 01.xlsx
  - Change Requirements  CR-01.1 .. CR-01.6
  - Field Specifications "PRODUCTION PLAN — DATE FIELDS"
  - Process Logic        CL-01 (client), CL-02, CL-03
  - Validations          CVAL-01, CVAL-02, CVAL-03
  - Customizations       CZ-27 (Property Setter), CZ-28 (Custom Fields),
                         CZ-29 (Client Script), CZ-30 (Server logic)

The FRD nominates a "manufacturing_custom" app that does NOT exist on the
DETOX benches; the No-BOM Production Plan build already lives in
detox_project (custom_fg_items = Table 1, custom_operations = Table 2), so
CR-01 is delivered here alongside it.

Conventions (project rules):
  - Custom Fields + Property Setters are CODE-FIRST — created by
    ``setup_cr01_production_plan_date`` which is invoked from
    ``detox_project.setup.after_migrate`` (idempotent, survives redeploy).
  - The CL-01 header-date cascade ships as a file-backed **Client Script**
    document exported via the ``Client Script`` fixture (module
    "Detox Project"), NOT as a doctype_js hook (``bench build`` silently
    fails on FC worker containers).
  - Post-save field writes use ``db_set`` (on_update does NOT persist plain
    attribute assignment on this bench).

Table 1 is the child DocType ``Detox Production Plan FG``; its
``planned_date`` field is the plan's per-item scheduled date.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import formatdate, getdate, now_datetime, today


# Table 1 = custom_fg_items -> child DocType "Detox Production Plan FG".
FG_CHILD_DOCTYPE = "Detox Production Plan FG"
FG_TABLE_FIELD = "custom_fg_items"

# CL-01 header-date cascade — file-backed as a Client Script DOCUMENT (NOT a
# doctype_js hook; bench build silently fails on FC worker containers). Created
# code-first by setup_cr01_production_plan_date so it deploys on migrate and
# survives redeploy. Kept as a module constant so the body lives in git.
CL01_CLIENT_SCRIPT_NAME = "PP Header Date Cascade (CR-01)"
CL01_CLIENT_SCRIPT_BODY = """// CR-01 / CL-01 — Header posting_date cascade to Table 1 (custom_fg_items).
// Source: DETOX PRODUCTION FRD CHANGE SET 01 — Process Logic CL-01, CR-01.2.
// When the header posting_date changes, every Table 1 row STILL holding the
// PREVIOUS header date follows the change; rows whose date was manually
// overridden are left untouched. A confirm dialog names the affected rows.
frappe.ui.form.on("Production Plan", {
    onload(frm) {
        // Baseline the previous header date so a later edit can tell which
        // rows were still tracking it.
        frm._cr01_prev_posting_date = frm.doc.posting_date;
    },
    refresh(frm) {
        if (frm._cr01_prev_posting_date === undefined) {
            frm._cr01_prev_posting_date = frm.doc.posting_date;
        }
        // On a submitted plan the grid is editable (Table allow_on_submit=1)
        // so the planned_date cell can be revised. Hide Add Row so users are
        // not misled into adding rows that the server would reject on save.
        if (frm.doc.docstatus === 1 && frm.fields_dict.custom_fg_items) {
            frm.fields_dict.custom_fg_items.grid.cannot_add_rows = true;
        }
    },
    posting_date(frm) {
        const new_date = frm.doc.posting_date;
        const old_date = frm._cr01_prev_posting_date;
        if (!old_date || old_date === new_date) {
            frm._cr01_prev_posting_date = new_date;
            return;
        }
        const rows = (frm.doc.custom_fg_items || []).filter(
            (r) => r.planned_date === old_date
        );
        if (!rows.length) {
            frm._cr01_prev_posting_date = new_date;
            return;
        }
        const names = rows
            .map((r) => `#${r.idx} ${r.item_code || ""}`.trim())
            .join(", ");
        frappe.confirm(
            __("Update the Planned Date of {0} row(s) still on {1} to {2}?<br><small>{3}</small><br>Manually overridden rows are left unchanged.",
                [rows.length, old_date, new_date, names]),
            () => {
                rows.forEach((r) => {
                    frappe.model.set_value(r.doctype, r.name, "planned_date", new_date);
                });
                frm.refresh_field("custom_fg_items");
                frm._cr01_prev_posting_date = new_date;
            },
            () => {
                // Declined: keep the new header date, don't re-prompt for it.
                frm._cr01_prev_posting_date = new_date;
            }
        );
    },
});
"""


# CR-01.1 "role-restricted post-submit revision". allow_on_submit lets the
# grid cell be edited after submit; this set is the authoritative gate for
# WHO may actually persist a post-submit date revision. Roles verified to
# exist on the DETOX benches (Production Manager does not exist here). Adjust
# in one place if the client nominates a different owner role.
ALLOWED_DATE_REVISION_ROLES = (
	"System Manager",
	"Manufacturing Manager",
	"Stock Manager",
)


# --------------------------------------------------------------------------
# CZ-27 / CZ-28 — Custom Fields + Property Setter (code-first, idempotent)
# --------------------------------------------------------------------------
def setup_cr01_production_plan_date() -> None:
	"""Create the CR-01 Custom Fields + Property Setter.

	Wire from ``detox_project.setup.after_migrate``. Idempotent: only writes
	when a value actually differs, so re-running on every migrate is cheap.
	"""
	if not frappe.db.exists("DocType", "Production Plan"):
		return

	# CZ-28 — header Custom Fields. Both are allow_on_submit=1 so they can be
	# touched on a submitted plan (the reason is typed by the user; the
	# timestamp is stamped by the server via db_set).
	fields = [
		{
			"fieldname": "custom_date_change_reason",
			"label": "Date Change Reason",
			"fieldtype": "Small Text",
			"insert_after": "posting_date",
			"allow_on_submit": 1,
			# Conditional-mandatory is enforced in code (CVAL-03) only when a
			# submitted plan's date actually changes — a hard reqd=1 would
			# wrongly block ordinary draft saves.
			"description": (
				"Required when the Planned Date of a submitted plan is "
				"revised. Written to the timeline (CL-02)."
			),
			"module": "Detox Project",
		},
		{
			"fieldname": "custom_last_date_revised_on",
			"label": "Last Date Revised On",
			"fieldtype": "Datetime",
			"insert_after": "custom_date_change_reason",
			"read_only": 1,
			"allow_on_submit": 1,
			"description": (
				"Stamped by the server each time a Planned Date is revised "
				"after submit (CL-02)."
			),
			"module": "Detox Project",
		},
	]

	for spec in fields:
		name = f"Production Plan-{spec['fieldname']}"
		if frappe.db.exists("Custom Field", name):
			cf = frappe.get_doc("Custom Field", name)
			dirty = False
			for k, v in spec.items():
				if (cf.get(k) or "") != (v or ""):
					cf.set(k, v)
					dirty = True
			if dirty:
				cf.save(ignore_permissions=True)
			continue
		frappe.get_doc({"doctype": "Custom Field", "dt": "Production Plan", **spec}).insert(
			ignore_permissions=True
		)

	# CZ-27 — Property Setters.
	#   * Detox Production Plan FG.planned_date allow_on_submit=1 lets the
	#     per-item date be corrected on a submitted plan (the child cell is
	#     what update_after_submit validates against).
	#   * The parent Table field custom_fg_items ALSO needs allow_on_submit=1,
	#     otherwise the grid is read-only in the UI: grid.is_editable() returns
	#     display_status == "Write", which for a submitted doc is only "Write"
	#     when the Table field itself is allow_on_submit=1 (frappe grid.js).
	#     Structural row add/remove still fails server-side because the other
	#     child fields (item_code, qty_to_manufacture, ...) are NOT
	#     allow_on_submit, so only the planned_date cell actually persists.
	property_setters = [
		(FG_CHILD_DOCTYPE, "planned_date", "allow_on_submit", "1"),
		("Production Plan", FG_TABLE_FIELD, "allow_on_submit", "1"),
	]
	for doc_type, field_name, prop, value in property_setters:
		_upsert_property_setter(doc_type, field_name, prop, value)

	# CZ-29 — CL-01 header-date cascade Client Script (code-first self-heal).
	_upsert_cl01_client_script()


def _upsert_cl01_client_script() -> None:
	"""Create / heal the CL-01 Client Script document.

	Shipped code-first (not as a client_script.json fixture) because
	client_script.json is a single shared fixture file; a code-first upsert
	is FC-deploy-safe, idempotent and keeps the body versioned in git here.
	"""
	body = CL01_CLIENT_SCRIPT_BODY
	if frappe.db.exists("Client Script", CL01_CLIENT_SCRIPT_NAME):
		cs = frappe.get_doc("Client Script", CL01_CLIENT_SCRIPT_NAME)
		dirty = False
		for k, v in (("dt", "Production Plan"), ("view", "Form"), ("enabled", 1),
					 ("module", "Detox Project"), ("script", body)):
			if cs.get(k) != v:
				cs.set(k, v)
				dirty = True
		if dirty:
			cs.save(ignore_permissions=True)
		return
	frappe.get_doc({
		"doctype": "Client Script",
		"name": CL01_CLIENT_SCRIPT_NAME,
		"dt": "Production Plan",
		"view": "Form",
		"enabled": 1,
		"module": "Detox Project",
		"script": body,
	}).insert(ignore_permissions=True)


def _upsert_property_setter(doc_type: str, field_name: str, prop: str, value: str) -> None:
	name = f"{doc_type}-{field_name}-{prop}"
	if frappe.db.exists("Property Setter", name):
		if frappe.db.get_value("Property Setter", name, "value") != value:
			frappe.db.set_value("Property Setter", name, "value", value)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doc_type,
			"field_name": field_name,
			"property": prop,
			"property_type": "Check",
			"value": value,
			"module": "Detox Project",
		}
	).insert(ignore_permissions=True)


# --------------------------------------------------------------------------
# CVAL-01 / CVAL-02 — date-sequence validation (doc_events: validate)
# --------------------------------------------------------------------------
def validate_production_plan_dates(doc, method=None) -> None:
	"""Every Table 1 planned_date must be on or after the header posting_date.

	CVAL-01 (BLOCK): planned_date earlier than posting_date -> throw.
	CVAL-02 (WARN):  on a new/draft plan, planned_date earlier than today ->
	                 non-blocking warning.
	Only meaningful for No-BOM plans, which are the ones carrying Table 1.
	"""
	rows = doc.get(FG_TABLE_FIELD) or []
	if not rows:
		return

	posting = getdate(doc.get("posting_date")) if doc.get("posting_date") else None
	today_date = getdate(today())

	for row in rows:
		if not row.get("planned_date"):
			continue
		planned = getdate(row.planned_date)

		# CVAL-01 — hard block, always (draft and post-submit).
		if posting and planned < posting:
			frappe.throw(
				_("Row #{0}: Planned Date {1} cannot be earlier than the Plan Posting Date {2}.").format(
					row.idx, formatdate(planned), formatdate(posting),
				)
			)

		# CVAL-02 — warn on a new plan only (past-dated but not out of sequence).
		if doc.docstatus == 0 and planned < today_date:
			frappe.msgprint(
				_("Planned Date for {0} is in the past. Confirm this is intentional before submitting.").format(
					row.get("item_code") or _("row #{0}").format(row.idx)
				),
				title=_("Past Planned Date"),
				indicator="orange",
			)


# --------------------------------------------------------------------------
# CVAL-03 / CL-02 / CL-03 — post-submit revision (doc_events: on_update_after_submit)
# --------------------------------------------------------------------------
def on_update_after_submit_dates(doc, method=None) -> None:
	"""Handle a Planned Date revision on a submitted plan.

	CVAL-03: a reason is mandatory when a submitted plan's date changes.
	CL-02:   stamp custom_last_date_revised_on and write a timeline comment
	         (old -> new, user, reason) for every changed row.
	CL-03:   sync linked DRAFT Work Orders / Stock Entries to the new date;
	         list submitted links in a msgprint — never rewrite them.
	"""
	before = doc.get_doc_before_save()
	if not before:
		return

	old_by_row = {r.name: r.get("planned_date") for r in (before.get(FG_TABLE_FIELD) or [])}

	changes = []  # (idx, item_code, old, new)
	changed_map = {}  # item_code -> new planned_date
	for row in doc.get(FG_TABLE_FIELD) or []:
		old = old_by_row.get(row.name)
		if old is None or not row.get("planned_date"):
			continue
		if getdate(old) != getdate(row.planned_date):
			changes.append((row.idx, row.get("item_code"), getdate(old), getdate(row.planned_date)))
			if row.get("item_code"):
				changed_map[row.item_code] = getdate(row.planned_date)

	if not changes:
		return

	# CR-01.1 — role-restricted post-submit revision.
	if not user_can_revise_planned_date():
		frappe.throw(
			_("You are not permitted to revise Planned Dates on a submitted Production Plan. "
			  "Ask a {0}.").format(" / ".join(ALLOWED_DATE_REVISION_ROLES)),
			frappe.PermissionError,
		)

	# CVAL-03 — reason mandatory.
	reason = (doc.get("custom_date_change_reason") or "").strip()
	if not reason:
		frappe.throw(
			_("Enter a Date Change Reason before revising the Planned Date on a submitted plan.")
		)

	# CL-02 — stamp + timeline comment. db_set because on_update_after_submit
	# does not persist a plain attribute assignment. User-controlled values
	# (item_code, reason) are HTML-escaped — Comment.content renders as HTML in
	# the timeline, so an unescaped reason would be a stored-XSS vector.
	doc.db_set("custom_last_date_revised_on", now_datetime(), update_modified=False)
	safe_reason = frappe.utils.escape_html(reason)
	for idx, item_code, old, new in changes:
		doc.add_comment(
			"Info",
			_("Planned Date for row #{0} ({1}) revised from {2} to {3} by {4}. Reason: {5}").format(
				idx, frappe.utils.escape_html(item_code or "-"), old, new,
				frappe.utils.escape_html(frappe.session.user), safe_reason,
			),
		)

	# CL-03 — downstream draft sync + submitted-link report.
	sync_downstream_dates(doc.name, changed_map)


def sync_downstream_dates(plan_name: str, changed_map: dict) -> None:
	"""CL-03 — push revised dates onto linked DRAFT downstream docs.

	Draft Work Orders get planned_start_date (matched by production_item).
	Draft Stock Entries get posting_date (matched via their Work Order's
	production_item, or the single revised date when unambiguous). Submitted
	documents are never touched — their names are surfaced for manual action.
	"""
	if not changed_map:
		return

	submitted_links = []

	# Work Orders linked to this plan.
	for wo in frappe.get_all(
		"Work Order",
		filters={"production_plan": plan_name},
		fields=["name", "production_item", "docstatus"],
	):
		if wo.docstatus == 1:
			submitted_links.append(("Work Order", wo.name))
			continue
		if wo.docstatus == 0 and wo.production_item in changed_map:
			frappe.db.set_value(
				"Work Order", wo.name, "planned_start_date",
				changed_map[wo.production_item], update_modified=False,
			)

	# Stock Entries linked to this plan.
	single_date = next(iter(changed_map.values())) if len(changed_map) == 1 else None
	for se in frappe.get_all(
		"Stock Entry",
		filters={"production_plan": plan_name},
		fields=["name", "work_order", "docstatus"],
	):
		if se.docstatus == 1:
			submitted_links.append(("Stock Entry", se.name))
			continue
		if se.docstatus != 0:
			continue
		target = None
		if se.work_order:
			pi = frappe.db.get_value("Work Order", se.work_order, "production_item")
			if pi in changed_map:
				target = changed_map[pi]
		if target is None:
			target = single_date
		if target is not None:
			frappe.db.set_value(
				"Stock Entry", se.name, "posting_date", target, update_modified=False
			)

	if submitted_links:
		items = "".join(
			f"<li>{dt}: {frappe.utils.escape_html(nm)}</li>" for dt, nm in submitted_links
		)
		frappe.msgprint(
			_("These submitted downstream documents were NOT changed and may need "
			  "manual date correction:<ul>{0}</ul>").format(items),
			title=_("Submitted downstream documents"),
			indicator="orange",
		)


def user_can_revise_planned_date(user: str | None = None) -> bool:
	"""CR-01.1 role gate. Administrator always allowed."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)).intersection(ALLOWED_DATE_REVISION_ROLES))
