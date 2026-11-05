"""Disable the WBS / Project Budget Client Scripts that are now app code.
The records are kept so they can be re-enabled if needed.

Revenue WBS form scripts                       -> public/js/revenue_wbs_allocation.js
WBS / Sub WBS category filter, dashboard, MR,
Refresh Spent, post-rename redirect            -> doctype/(sub_)wbs_element/*.js
Material Request WBS allocation                -> public/js/material_request_custom.js
Financial Model show / hide                    -> public/js/financial_model.js
WBS Inventory (PR / SE)                        -> detox_waste_management public/js/wbs_inventory_*.js
"""

import frappe

CLIENT_SCRIPTS = (
	"Blanket Order - Revenue WBS Allocation Filters",
	"Delivery Note - Revenue WBS Allocation Filters",
	"Sales Invoice - Revenue WBS Allocation Filters",
	"Sales Order - Revenue WBS Allocation Filters",
	"WBS Element - Category Filter (Expense from FM + Revenue)",
	"Sub WBS Element - Category Filter (Expense from FM + Revenue)",
	"WBS Element - New MR with Project",
	"Sub WBS Element - New MR with Project",
	"Material Request WBS SUB WBS Allocation",
	"hide_show_financial_model",
	"Sub WBS Naming Series",
	"sub wbs naming series v2",
	"Sub WBS Refresh button",
	"Purchase Receipt - WBS Inventory",
	"Stock Entry - WBS Inventory",
)


def execute():
	for name in CLIENT_SCRIPTS:
		if frappe.db.exists("Client Script", name):
			frappe.db.set_value("Client Script", name, "enabled", 0)
	frappe.clear_cache()
