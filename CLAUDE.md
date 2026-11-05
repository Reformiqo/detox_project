# CLAUDE.md — detox_project

## Site
- Site: detox.erpera.io
- Bench: /home/frappe/v16

## After making changes

After modifying custom fields, property setters, workflows, notifications, or client scripts, ALWAYS run:

```bash
bench --site detox.erpera.io export-fixtures --app detox_project
```

Then commit the exported fixture JSON files along with your code changes.

## Key doctypes

- **WBS Element** — Budget tracking per project category (budget_amount, budget_spent, budget_utilization_pct)
- **Sub WBS Element** — Sub-level budget under WBS Element
- **WBS Allocation** — Child table on MR/PO/PI/PR for multi-WBS allocation per document

## Custom fields on standard doctypes

Managed via `setup.py` → `create_custom_fields()`:
- Material Request, Purchase Order, Purchase Invoice, Purchase Receipt: `custom_wbs_allocations` (Table → WBS Allocation)
- Old `custom_wbs_element` / `custom_sub_wbs_element` fields are hidden but kept for backward compat
- Project: budget summary, revenue tracking, financial model link, tender details

## WBS on MR / PO / PR / PI (overrides/purchase_wbs.py)

- `custom_wbs_allocations` can be edited by hand and is not copied when a document is mapped (`no_copy`). It must hold one row per WBS + Sub WBS on the items, amount = Σ base_net_amount in company currency (MR: amount). An empty table is filled from the items on save; a filled one is validated, not overwritten. Update Items on a submitted PO rebuilds it.
- Blank item WBS is copied from the source row (MR item → PO item → PR item → PI item); a row whose WBS differs from its source row is blocked.
- Blocked: some rows with a WBS and some without, Sub WBS of another WBS, WBS of another project, ₹0 WBS amount, a header row with no matching item, an item WBS with no header row, a header amount that differs from its items.

## Budget validation flow

- **MR validate**: Hard block per WBS / Sub WBS if Assigned would exceed 100%
- **PO validate**: Hard block per WBS / Sub WBS on items not raised from an MR
- **Spent refresh** (every WBS/Sub WBS on the item rows): PI/PR on submit + cancel; MR/PO on every change of a submitted document (`on_change`), which also covers PO Close / Reopen, MR Stop and Update Items
- **Budget Spent** = Actual (PI items) + Commitment (open PO items × unbilled) + RemOrdPlan (Pending / Partially Ordered MR items × unordered) — all from item rows
- **WBS Element validate**: Category budget checked against Financial Model allocation
- **Sub WBS validate**: Hard block if total exceeds parent WBS budget
