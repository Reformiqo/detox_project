"""Disable the WBS / Project Budget Server Scripts that are now app code.
The records are kept so they can be re-enabled if needed.

Revenue WBS allocation, rollup and achievement -> overrides/revenue_wbs.py
refresh_sub_wbs_spent API                      -> api.py
WBS / Sub WBS naming                           -> WBSElement / SubWBSElement controllers
"""

import frappe

SERVER_SCRIPTS = (
	"Blanket Order - Revenue WBS Allocation Validate",
	"Blanket Order - Revenue WBS Allocation Validate (Submit)",
	"Delivery Note - Revenue WBS Allocation Validate",
	"Delivery Note - Revenue WBS Allocation Validate (Submit)",
	"Sales Invoice - Revenue WBS Allocation Validate",
	"Sales Invoice - Revenue WBS Allocation Validate (Submit)",
	"Sales Invoice - Revenue WBS Rollup (Submit)",
	"Sales Invoice - Revenue WBS Rollup (Cancel)",
	"Sales Order - Revenue WBS Allocation Validate",
	"Sales Order - Revenue WBS Allocation Validate (Submit)",
	"Sales Order - Revenue WBS Resync (Update Items)",
	"Sales Order - Revenue WBS Rollup (Submit)",
	"Sales Order - Revenue WBS Rollup (Cancel)",
	"WBS Element - Revenue Achievement",
	"Sub WBS Element - Revenue Achievement",
	"WBS Element naming series - proj",
	"Sub wbs namning v2",
	"Sub WBS Naming Series",
	"refresh_sub_wbs_spent",
	"TEMP - Add Revenue Dashboard Links",
	"TEMP - Revenue Category Type Backfill",
	"TEMP - Revenue Test Docs Cleanup",
)


def execute():
	for name in SERVER_SCRIPTS:
		if frappe.db.exists("Server Script", name):
			frappe.db.set_value("Server Script", name, "disabled", 1)
	frappe.clear_cache()
