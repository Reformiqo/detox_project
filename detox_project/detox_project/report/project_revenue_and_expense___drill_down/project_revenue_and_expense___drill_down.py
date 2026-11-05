import json

import frappe


def execute(filters=None):
	# Project Revenue and Expense - Drill Down
	# Tree: Project > Cost Center > Transaction Type > Account > Voucher.
	# Source: posted GL Entries on Income / Expense accounts (no budget data).

	f = frappe._dict(filters or {})
	company = f.get("company")
	from_date = f.get("from_date")
	to_date = f.get("to_date")
	txn_filter = f.get("transaction_type") or ""
	show_upto = f.get("show_upto") or "Voucher"
	level_names = ["Project", "Cost Center", "Transaction Type", "Account", "Voucher"]
	max_level = level_names.index(show_upto) if show_upto in level_names else 4

	projects = f.get("project") or []
	if isinstance(projects, str):
	    projects = json.loads(projects) if projects.strip().startswith("[") else [projects]
	cost_centers = f.get("cost_center") or []
	if isinstance(cost_centers, str):
	    cost_centers = json.loads(cost_centers) if cost_centers.strip().startswith("[") else [cost_centers]

	vals = {"company": company, "from_date": from_date, "to_date": to_date, "txn": txn_filter}
	conds = [
	    "gle.is_cancelled = 0",
	    "acc.root_type in ('Income', 'Expense')",
	    "gle.company = %(company)s",
	    "gle.posting_date between %(from_date)s and %(to_date)s",
	]
	if projects:
	    conds.append("ifnull(gle.project, '') in %(projects)s")
	    vals["projects"] = tuple(projects)
	if cost_centers:
	    conds.append("ifnull(gle.cost_center, '') in %(cost_centers)s")
	    vals["cost_centers"] = tuple(cost_centers)

	txn_case = """case
    when gle.voucher_type = 'Sales Invoice' then 'Sales Invoice'
    when gle.voucher_type in ('Purchase Invoice', 'Purchase Receipt') then 'Purchase'
    when gle.voucher_type in ('Stock Entry', 'Delivery Note', 'Stock Reconciliation') then 'Stock Consumption'
    when gle.voucher_type = 'Expense Claim' then 'Expense Claim'
    when gle.voucher_type = 'Payment Entry' then 'Payment Entry'
    when gle.voucher_type = 'Journal Entry' and pr.parent is not null then 'Salary'
    when gle.voucher_type = 'Journal Entry' and ea.parent is not null then 'Employee Advance'
    when gle.voucher_type = 'Journal Entry' then 'Journal Entry'
    else 'Other' end"""

	q = """select t.project, t.cost_center, t.txn_type, t.account, t.voucher_type, t.voucher_no,
        min(t.posting_date) as posting_date, max(t.party) as party,
        sum(t.revenue) as revenue, sum(t.expense) as expense, count(*) as line_count
    from (
        select ifnull(gle.project, '') as project, ifnull(gle.cost_center, '') as cost_center,
            gle.account, gle.voucher_type, gle.voucher_no, gle.posting_date, ifnull(vp.party, '') as party,
            (case when acc.root_type = 'Income' then gle.credit - gle.debit else 0 end) as revenue,
            (case when acc.root_type = 'Expense' then gle.debit - gle.credit else 0 end) as expense,
            """ + txn_case + """ as txn_type
        from `tabGL Entry` gle
        join `tabAccount` acc on acc.name = gle.account
        left join (select distinct parent from `tabJournal Entry Account` where reference_type = 'Payroll Entry') pr
            on pr.parent = gle.voucher_no and gle.voucher_type = 'Journal Entry'
        left join (select distinct parent from `tabJournal Entry Account`
            where reference_type = 'Employee Advance'
                or account in (select distinct advance_account from `tabEmployee Advance` where docstatus = 1)) ea
            on ea.parent = gle.voucher_no and gle.voucher_type = 'Journal Entry'
        left join (
            select voucher_type, voucher_no, max(party) as party from `tabGL Entry`
            where is_cancelled = 0 and company = %(company)s and posting_date between %(from_date)s and %(to_date)s
                and ifnull(party, '') <> ''
            group by voucher_type, voucher_no
        ) vp on vp.voucher_type = gle.voucher_type and vp.voucher_no = gle.voucher_no
        where """ + " and ".join(conds) + """
    ) t
    """ + (" where t.txn_type = %(txn)s " if txn_filter else "") + """
    group by t.project, t.cost_center, t.txn_type, t.account, t.voucher_type, t.voucher_no
    order by t.project, t.cost_center, t.txn_type, t.account, posting_date, t.voucher_no"""
	rows = frappe.db.sql(q, vals, as_dict=1)

	project_names = {}
	for p in frappe.get_all("Project", fields=["name", "project_name"]):
	    project_names[p.name] = p.project_name

	txn_order = {"Sales Invoice": "1", "Payment Entry": "2", "Journal Entry": "3", "Purchase": "4", "Stock Consumption": "5",
	    "Salary": "6", "Expense Claim": "7", "Employee Advance": "8", "Other": "9"}

	# Build aggregate nodes keyed by path (no helper functions: the script sandbox does not share outer variables with them)
	nodes = {}
	children = {}
	roots = []
	tot_rev = 0.0
	tot_exp = 0.0
	untagged = 0
	for r in rows:
	    rev = frappe.utils.flt(r.revenue)
	    exp = frappe.utils.flt(r.expense)
	    tot_rev = tot_rev + rev
	    tot_exp = tot_exp + exp
	    if not r.project or not r.cost_center:
	        untagged = untagged + frappe.utils.cint(r.line_count)
	    p_label = (r.project + " - " + (project_names.get(r.project) or "")) if r.project else "(Project not tagged)"
	    k0 = "P|" + r.project
	    k1 = k0 + "|C|" + r.cost_center
	    k2 = k1 + "|T|" + r.txn_type
	    k3 = k2 + "|A|" + r.account
	    k4 = k3 + "|V|" + r.voucher_type + "|" + r.voucher_no
	    chain = [
	        [k0, None, 0, p_label, r.project or "~", {}],
	        [k1, k0, 1, r.cost_center or "(Cost Center not tagged)", r.cost_center or "~", {}],
	        [k2, k1, 2, r.txn_type, txn_order.get(r.txn_type, "9"), {}],
	        [k3, k2, 3, r.account, r.account, {}],
	        [k4, k3, 4, r.voucher_no, frappe.utils.cstr(r.posting_date) + r.voucher_no,
	            {"voucher_type": r.voucher_type, "voucher_no": r.voucher_no, "posting_date": r.posting_date, "party": r.party}],
	    ]
	    lvl = 0
	    while lvl <= max_level:
	        c = chain[lvl]
	        n = nodes.get(c[0])
	        if not n:
	            n = {"row_id": c[0], "parent_row": c[1], "indent": c[2], "label": c[3], "sort": c[4],
	                "revenue": 0.0, "expense": 0.0, "line_count": 0}
	            for ek in c[5]:
	                n[ek] = c[5][ek]
	            nodes[c[0]] = n
	            if c[1]:
	                children.setdefault(c[1], []).append([c[4], c[0]])
	            else:
	                roots.append([c[4], c[0]])
	        n["revenue"] = n["revenue"] + rev
	        n["expense"] = n["expense"] + exp
	        n["line_count"] = n["line_count"] + frappe.utils.cint(r.line_count)
	        lvl = lvl + 1

	# Depth-first output, each level sorted
	result = []
	stack = []
	for pair in sorted(roots, reverse=True):
	    stack.append(pair[1])
	while stack:
	    k = stack.pop()
	    n = nodes[k]
	    n["revenue"] = frappe.utils.flt(n["revenue"], 2)
	    n["expense"] = frappe.utils.flt(n["expense"], 2)
	    n["net"] = frappe.utils.flt(n["revenue"] - n["expense"], 2)
	    n["margin"] = frappe.utils.flt(n["net"] * 100.0 / n["revenue"], 2) if (n["revenue"] > 0 and n["indent"] < 3) else None
	    result.append(n)
	    kids = children.get(k) or []
	    for pair in sorted(kids, reverse=True):
	        stack.append(pair[1])

	if result:
	    result.append({"row_id": "TOTAL", "parent_row": None, "indent": 0, "label": "Grand Total", "is_total": 1,
	        "revenue": frappe.utils.flt(tot_rev, 2), "expense": frappe.utils.flt(tot_exp, 2),
	        "net": frappe.utils.flt(tot_rev - tot_exp, 2),
	        "margin": frappe.utils.flt((tot_rev - tot_exp) * 100.0 / tot_rev, 2) if tot_rev > 0 else None})

	columns = [
	    {"fieldname": "label", "label": "Project / Cost Center / Type / Account / Voucher", "fieldtype": "Data", "width": 420},
	    {"fieldname": "revenue", "label": "Revenue", "fieldtype": "Currency", "width": 150},
	    {"fieldname": "expense", "label": "Expense", "fieldtype": "Currency", "width": 150},
	    {"fieldname": "net", "label": "Net Profit / (Loss)", "fieldtype": "Currency", "width": 150},
	    {"fieldname": "margin", "label": "Margin %", "fieldtype": "Percent", "width": 90},
	    {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "width": 100},
	    {"fieldname": "voucher_type", "label": "Voucher Type", "fieldtype": "Data", "width": 130},
	    {"fieldname": "voucher_no", "label": "Open Voucher", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 170},
	    {"fieldname": "party", "label": "Party", "fieldtype": "Data", "width": 200},
	    {"fieldname": "line_count", "label": "GL Lines", "fieldtype": "Int", "width": 80},
	]

	report_summary = [
	    {"value": tot_rev, "label": "Total Revenue", "datatype": "Currency", "indicator": "Green"},
	    {"value": tot_exp, "label": "Total Expense", "datatype": "Currency", "indicator": "Red"},
	    {"value": tot_rev - tot_exp, "label": "Net Profit / (Loss)", "datatype": "Currency", "indicator": "Blue" if tot_rev >= tot_exp else "Red"},
	    {"value": untagged, "label": "GL Lines without Project / Cost Center", "datatype": "Int", "indicator": "Orange" if untagged else "Green"},
	]

	return [columns, result, None, None, report_summary]
