# =====================================================================
# CR-03 — Downtime capture at Stock Entry level.
# DETOX Production Change-Set FRD (Change Set 1). Objects: CZ-33 (SE
# header custom fields), CZ-34 (Production Downtime Detail child),
# CZ-35 (Downtime Reason master), CZ-36 (Downtime Analysis report).
# Process logic CL-07/CL-08/CL-09; Validations CVAL-05/06/07.
#
# CODE-FIRST: the Stock Entry header custom fields are defined and
# upserted here (authoritative). Call install_cr03_downtime() from
# detox_project.setup.after_migrate so the fields survive an FC
# redeploy even after fixture sync (fixture sync runs BEFORE
# after_migrate, so this re-asserts the correct definition last).
#
# The new DocTypes (Downtime Reason, Production Downtime Detail) ship
# as app doctype JSON and install on migrate — they are NOT managed
# here. The Client Script (CL-07/08/09 UI glue) ships via fixtures.
#
# CR-03 introduces NO Property Setters: it changes no standard Stock
# Entry field. The "read-only when rows exist" behaviour of
# custom_downtime lives on the custom field itself
# (read_only_depends_on), not on a standard field.
# =====================================================================

from __future__ import annotations

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt, get_datetime, time_diff_in_seconds

MODULE = "Detox Project"

# The only Stock Entry type that captures downtime (a Manufacture batch).
# Kept independent of the wider MFG_TYPES set used elsewhere — downtime
# is not recorded on Material Transfer for Manufacture or Repack.
DOWNTIME_SE_TYPE = "Manufacture"


# --------------------------------------------------------------------------
# CODE-FIRST custom field install (CZ-33). Idempotent — safe to re-run.
# --------------------------------------------------------------------------
def install_cr03_downtime() -> None:
    """Upsert the Downtime header field group on Stock Entry (CR-03.1/.2).

    Extends the pre-existing `custom_downtime` field (shipped by
    ABP2-I419): it is re-parented from the Manufacturing Process
    section into a dedicated Downtime section and made read-only when
    detail rows drive the value. Nothing is duplicated.
    """
    fields = {
        "Stock Entry": [
            {
                # CR-03.1 — dedicated Downtime section, after the
                # Production Time fields. Gated on Manufacture only; the
                # standard `bom_info_section` that follows closes it, so
                # no fields leak into/out of the gated block.
                "fieldname": "custom_downtime_section",
                "label": "Downtime",
                "fieldtype": "Section Break",
                "insert_after": "custom_end_time",
                "depends_on": 'eval:doc.stock_entry_type=="Manufacture"',
                "module": MODULE,
            },
            {
                # CR-03.2 — re-parented into the Downtime section; sum of
                # detail rows, read-only when the detail table is used
                # (CL-08). Manually editable for a single-figure entry.
                "fieldname": "custom_downtime",
                "label": "Downtime",
                "fieldtype": "Float",
                "insert_after": "custom_downtime_section",
                "read_only_depends_on": "eval:doc.custom_downtime_details && doc.custom_downtime_details.length > 0",
                "non_negative": 1,
                "default": "0",
                "description": (
                    "Total stoppage for this batch. Auto-summed and locked "
                    "when the Downtime Details table is used; manually "
                    "editable otherwise."
                ),
                "module": MODULE,
            },
            {
                # CR-03.1 — unit for custom_downtime; kept independent of
                # custom_time_uom. Mandatory once downtime is recorded.
                "fieldname": "custom_downtime_uom",
                "label": "Downtime UOM",
                "fieldtype": "Select",
                "options": "Hours\nMinutes",
                "default": "Hours",
                "insert_after": "custom_downtime",
                "mandatory_depends_on": "eval:doc.custom_downtime > 0",
                "module": MODULE,
            },
            {
                # CR-03.2 — reason-wise stoppage rows.
                "fieldname": "custom_downtime_details",
                "label": "Downtime Details",
                "fieldtype": "Table",
                "options": "Production Downtime Detail",
                "insert_after": "custom_downtime_uom",
                "module": MODULE,
            },
            {
                "fieldname": "custom_downtime_remarks",
                "label": "Downtime Remarks",
                "fieldtype": "Small Text",
                "insert_after": "custom_downtime_details",
                "module": MODULE,
            },
            {
                # CR-03 — effective running time = production_time − downtime
                # (CL-09). Read-only; feeds the Downtime Analysis report.
                "fieldname": "custom_net_run_time",
                "label": "Net Run Time",
                "fieldtype": "Float",
                "insert_after": "custom_downtime_remarks",
                "read_only": 1,
                "non_negative": 1,
                "description": (
                    "Production Time − Downtime for this shift (never below "
                    "zero). Auto-computed."
                ),
                "module": MODULE,
            },
        ]
    }
    create_custom_fields(fields, update=True)
    frappe.clear_cache(doctype="Stock Entry")


# --------------------------------------------------------------------------
# Server validate (CL-07/08/09 authoritative mirror + CVAL-05/06/07).
# Wire in hooks.py: Stock Entry -> validate.
# --------------------------------------------------------------------------
def validate_downtime(doc, method=None) -> None:
    """Compute + validate the downtime block on a Manufacture entry.

    Mirrors the client scripts server-side so a value produced by the
    API, a bulk upload or a test is treated exactly like one typed into
    the form:
      * CL-07  duration = to_time − from_time in the header Downtime UOM
      * CL-08  custom_downtime = sum of row durations when rows exist
      * CL-09  custom_net_run_time = production_time − downtime (>= 0)
    and enforces CVAL-05 (reason required when downtime > 0), CVAL-06
    (to_time > from_time) and CVAL-07 (production + downtime <= one
    shift day; net not negative).
    """
    if (doc.get("stock_entry_type") or "").strip() != DOWNTIME_SE_TYPE:
        return

    rows = doc.get("custom_downtime_details") or []
    header_cc = _se_header_cost_center(doc)
    dt_uom = (doc.get("custom_downtime_uom") or "Hours").strip()

    row_total = 0.0
    for idx, row in enumerate(rows, start=1):
        # CVAL-05 — a reason is required on every downtime row.
        if not row.get("downtime_reason"):
            frappe.throw(
                _("Select a Downtime Reason for row #{0}. Downtime cannot "
                  "be recorded without a reason.").format(idx),
                title=_("Downtime Reason missing"),
            )

        # Inherit the cost centre so downtime is analysable cost-centre-wise.
        if header_cc and not row.get("cost_center"):
            row.cost_center = header_cc

        # CL-07 / CVAL-06 — times drive the duration.
        ft, tt = row.get("from_time"), row.get("to_time")
        if ft and tt:
            if get_datetime(tt) <= get_datetime(ft):
                frappe.throw(
                    _("Row #{0}: To Time must be later than From Time.").format(idx),
                    title=_("Invalid downtime window"),
                )
            secs = time_diff_in_seconds(tt, ft)
            row.duration = secs / 3600.0 if dt_uom == "Hours" else secs / 60.0

        row_total += flt(row.get("duration"))

    # CL-08 — header downtime is the read-only sum whenever rows exist.
    if rows:
        doc.custom_downtime = row_total

    downtime = flt(doc.get("custom_downtime"))

    # CVAL-05 (header) — a bare downtime figure with no reason row is
    # refused: the reason lives on the detail rows.
    if downtime > 0 and not rows:
        frappe.throw(
            _("Downtime is greater than zero — add at least one Downtime "
              "Details row with a Downtime Reason. Downtime cannot be "
              "recorded without a reason."),
            title=_("Downtime Reason missing"),
        )

    # CVAL-07 + CL-09 — one-shift-day cap and net run time.
    pt = flt(doc.get("custom_production_time"))
    pt_uom = (doc.get("custom_time_uom") or "Hours").strip()
    pt_min = pt * (60.0 if pt_uom == "Hours" else 1.0)
    dt_min = downtime * (60.0 if dt_uom == "Hours" else 1.0)

    if pt_min + dt_min > 1440.0 + 1e-9:
        frappe.throw(
            _("Production Time ({0} {1}) plus Downtime ({2} {3}) exceeds "
              "one shift day (24 hours / 1440 minutes). Split this into "
              "separate Stock Entries.").format(pt, pt_uom, downtime, dt_uom),
            title=_("Shift length exceeded"),
        )

    net_min = pt_min - dt_min
    if net_min < -1e-9:
        frappe.throw(
            _("Net Run Time cannot be negative — Downtime ({0} {1}) exceeds "
              "Production Time ({2} {3}).").format(downtime, dt_uom, pt, pt_uom),
            title=_("Net Run Time negative"),
        )

    # Store net run time in the Production Time UOM. Clamp to zero so
    # float noise from unit conversion never lands a tiny negative on the
    # non_negative field (CL-09 — never below zero).
    doc.custom_net_run_time = max(net_min, 0.0) / (60.0 if pt_uom == "Hours" else 1.0)


def _se_header_cost_center(doc) -> str | None:
    """Header cost centre for downtime rows to inherit.

    Stock Entry has no header `cost_center` in this ERPNext build (that
    is CR-06's rationalisation, out of this scope), so fall back to the
    first item row that carries one. meta.has_field guard keeps this
    version-safe (see the SE cost_center version split).
    """
    if doc.meta.has_field("cost_center") and doc.get("cost_center"):
        return doc.get("cost_center")
    for row in (doc.get("items") or []):
        if row.get("cost_center"):
            return row.get("cost_center")
    return None
