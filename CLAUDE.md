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

## Budget validation flow

- **MR validate**: Soft warning per WBS allocation row if budget nearing 80%
- **PO validate**: Hard block per WBS allocation row if any >100%
- **PO/PI/PR submit**: Refresh spent for ALL WBS/Sub WBS in allocation table
- **WBS Element validate**: Category budget checked against Financial Model allocation
- **Sub WBS validate**: Hard block if total exceeds parent WBS budget
