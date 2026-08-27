# Copyright (c) 2026, erpera and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Coalesce, IfNull, NullIf, Sum, Trim
from frappe.utils import flt

UNCATEGORISED = "(Uncategorised)"

# label, fieldname, fieldtype, width
COLUMNS = (
	("Cost Category", "cost_category", "Data", 240),
	("Type", "entry_type", "Data", 100),
	("Annual Budget", "annual_budget", "Currency", 150),
	("Actual YTD", "actual_ytd", "Currency", 150),
	("Variance", "variance", "Float", 180),
	("Var %", "variance_pct", "Percent", 120),
	("Balance Budget", "balance_budget", "Float", 180),
	("Consumed %", "consumed_pct", "Percent", 130),
)

# Budget source per block: child table, category field.
BLOCKS = (
	("Revenue", "REVENUE", "FM Revenue Item", "category"),
	("Expense", "EXPENSE", "FM Expense Item", "custom_category"),
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is mandatory"))
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("From Date and To Date are mandatory"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	columns = [
		{"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
		for label, fieldname, fieldtype, width in COLUMNS
	]
	return columns, get_data(filters)


# Annual Budget per category for one block, biggest first.
def get_budget(filters, table, category_field):
	budget_line = frappe.qb.DocType(table)
	financial_model = frappe.qb.DocType("Financial Model")
	category = Coalesce(NullIf(Trim(budget_line[category_field]), ""), UNCATEGORISED)
	annual_budget = Sum(budget_line.annual_base_amount)

	query = (
		frappe.qb.from_(budget_line)
		.inner_join(financial_model)
		.on(financial_model.name == budget_line.parent)
		.select(
			category.as_("cost_category"),
			annual_budget.as_("annual_budget"),
		)
		.where(budget_line.parenttype == "Financial Model")
		.where(financial_model.docstatus < 2)
		.where(financial_model.company == filters.company)
		.groupby(category)
		.orderby(annual_budget, order=Order.desc)
		.orderby(category)
	)
	if filters.get("project"):
		query = query.where(financial_model.project == filters.project)
	return query.run(as_dict=True)


def get_actuals(filters):
	operation = frappe.qb.DocType("Detox Production Plan Operation")
	production_plan = frappe.qb.DocType("Production Plan")
	category = Trim(operation.budget_category)

	query = (
		frappe.qb.from_(operation)
		.inner_join(production_plan)
		.on(production_plan.name == operation.parent)
		.select(
			category.as_("cost_category"),
			Sum(operation.standard_rate * operation.multiply_by).as_("actual_ytd"),
		)
		.where(operation.parenttype == "Production Plan")
		.where(production_plan.docstatus == 1)
		.where(production_plan.company == filters.company)
		.where(production_plan.posting_date.between(filters.from_date, filters.to_date))
		.where(IfNull(operation.budget_category, "") != "")
		.groupby(category)
	)
	if filters.get("project"):
		query = query.where(operation.project == filters.project)
	return {row.cost_category: flt(row.actual_ytd) for row in query.run(as_dict=True)}


def make_row(row_type, entry_type, cost_category, budget, actual):
	budget, actual = flt(budget), flt(actual)
	variance = actual - budget
	return {
		"row_type": row_type,
		"entry_type": entry_type,
		"cost_category": cost_category,
		"annual_budget": budget,
		"actual_ytd": actual,
		"variance": variance,
		# Rounded here: the Percent formatter honours site Float Precision, which is 6 on SEPPL.
		"variance_pct": flt(variance / budget * 100, 2) if budget else 0.0,
		"balance_budget": budget - actual,
		"consumed_pct": flt(actual / budget * 100, 2) if budget else 0.0,
	}


def get_data(filters):
	actuals = get_actuals(filters)
	budgets = {
		entry_type: get_budget(filters, table, category_field)
		for entry_type, _band, table, category_field in BLOCKS
	}
	budgeted = {row.cost_category for rows in budgets.values() for row in rows}

	# Actuals with no budget line still belong here; they sort last on annual_budget = 0.
	budgets["Expense"] += [
		frappe._dict({"cost_category": category, "annual_budget": 0.0})
		for category in sorted(set(actuals) - budgeted)
	]

	wanted = filters.get("cost_category")
	data = []

	for entry_type, band, *_source in BLOCKS:
		rows = [
			make_row(
				"item",
				entry_type,
				budget_row.cost_category,
				budget_row.annual_budget,
				actuals.get(budget_row.cost_category, 0.0),
			)
			for budget_row in budgets[entry_type]
			if not wanted or budget_row.cost_category == wanted
		]
		# A block filtered down to nothing renders as nothing, not an all-zero total.
		if not rows:
			continue

		if data:
			data.append({"row_type": "blank"})
		data.append({"row_type": "section", "cost_category": _(band)})
		data += rows
		data.append(
			make_row(
				"total",
				entry_type,
				_("Total {0}").format(_(entry_type)),
				sum(r["annual_budget"] for r in rows),
				sum(r["actual_ytd"] for r in rows),
			)
		)

	# Netting off is only meaningful with both sides on screen.
	if len({r["entry_type"] for r in data if r["row_type"] == "total"}) == 2:
		totals = {r["entry_type"]: r for r in data if r["row_type"] == "total"}
		net = make_row(
			"net",
			None,
			_("Net Surplus / (Deficit)"),
			totals["Revenue"]["annual_budget"] - totals["Expense"]["annual_budget"],
			totals["Revenue"]["actual_ytd"] - totals["Expense"]["actual_ytd"],
		)
		# Consumed % is meaningless on a net figure.
		net["consumed_pct"] = None
		data += [{"row_type": "blank"}, net]

	return data
