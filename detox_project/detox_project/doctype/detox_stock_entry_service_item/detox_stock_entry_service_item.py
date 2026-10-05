# ABP2-I782 (2026-10-05) — formalizing a DB-only doctype into git.
#
# This doctype already exists on the live production DB (detox.m.frappe.cloud
# / seppl.erpera.io), created directly via Desk ("custom child doctype"),
# never exported to git, with 32 live rows (oldest 07-Aug-2026) at the time
# of this fix. Eight DB-only Server/Client Scripts ("DETOX Change Set 1")
# read/write it (service-item reroute, PO filter, qty*rate grid calc, FG
# valuation rollup) — see the manager's ABP2-I782 report for the full list.
# None of those scripts are ported here (explicit instruction — they stay
# DB-only on the cloud). This file only adds the doctype's schema to git so
# the new `conversion_factor` field (ABP2-I782 UOM-conversion fix) has
# somewhere to live, matching the pattern already used for
# `Detox Production Plan Operation`.
#
# NOTE for whoever deploys this: migrating this JSON onto the live site will
# ALTER the existing 32-row table (additive — one new nullable column). Test
# on a staging copy first, per the ticket's own instruction.
#
# IMPORTANT (verified against frappe/model/document.py `_validate()` — it
# only calls framework-internal child validators, never a child row's own
# controller `validate()`): this class's methods do NOT fire automatically
# when a parent Stock Entry is saved. The conversion-factor recompute lives
# in detox_project.detox_project.change_set.abp2_i782_fixlist, wired on
# Stock Entry's `validate` doc_event instead.

from frappe.model.document import Document


class DetoxStockEntryServiceItem(Document):
	pass
