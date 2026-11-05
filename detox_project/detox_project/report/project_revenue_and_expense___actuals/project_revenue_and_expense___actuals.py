import json

import frappe


def execute(filters=None):
	# Project Revenue and Expense - Actuals
	# Company-level, project / cost center wise P&L from posted GL Entries (no budget data).
	# Views: Summary | Detail | Exceptions (missing / wrong project and cost center tagging).

	f = frappe._dict(filters or {})
	company = f.get("company")
	from_date = f.get("from_date")
	to_date = f.get("to_date")
	view = f.get("view") or "Summary"
	group_by = f.get("group_by") or "Project"
	txn_filter = f.get("transaction_type") or ""
	ho_project = f.get("ho_project") or ""

	projects = f.get("project") or []
	if isinstance(projects, str):
	    projects = json.loads(projects) if projects.strip().startswith("[") else [projects]
	cost_centers = f.get("cost_center") or []
	if isinstance(cost_centers, str):
	    cost_centers = json.loads(cost_centers) if cost_centers.strip().startswith("[") else [cost_centers]

	vals = {"company": company, "from_date": from_date, "to_date": to_date, "txn": txn_filter, "ho_project": ho_project}
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

	need_party = view in ("Detail", "Exceptions")
	party_select = ", ifnull(vp.party, '') as party" if need_party else ", '' as party"
	party_join = ""
	if need_party:
	    party_join = """ left join (
        select voucher_type, voucher_no, max(party) as party from `tabGL Entry`
        where is_cancelled = 0 and company = %(company)s and posting_date between %(from_date)s and %(to_date)s
            and ifnull(party, '') <> ''
        group by voucher_type, voucher_no
    ) vp on vp.voucher_type = gle.voucher_type and vp.voucher_no = gle.voucher_no"""

	base = """select gle.posting_date, gle.voucher_type, gle.voucher_no, gle.account, gle.owner, gle.remarks,
        ifnull(gle.project, '') as project, ifnull(gle.cost_center, '') as cost_center, acc.root_type,
        (case when acc.root_type = 'Income' then gle.credit - gle.debit else 0 end) as revenue,
        (case when acc.root_type = 'Expense' then gle.debit - gle.credit else 0 end) as expense,
        """ + txn_case + """ as txn_type""" + party_select + """
    from `tabGL Entry` gle
    join `tabAccount` acc on acc.name = gle.account
    left join (select distinct parent from `tabJournal Entry Account` where reference_type = 'Payroll Entry') pr
        on pr.parent = gle.voucher_no and gle.voucher_type = 'Journal Entry'
    left join (select distinct parent from `tabJournal Entry Account`
        where reference_type = 'Employee Advance'
            or account in (select distinct advance_account from `tabEmployee Advance` where docstatus = 1)) ea
        on ea.parent = gle.voucher_no and gle.voucher_type = 'Journal Entry'""" + party_join + """
    where """ + " and ".join(conds)

	txn_where = " where t.txn_type = %(txn)s " if txn_filter else " "

	project_names = {}
	project_cc = {}
	cc_owner = {}
	for p in frappe.get_all("Project", fields=["name", "project_name", "cost_center"]):
	    project_names[p.name] = p.project_name
	    project_cc[p.name] = p.cost_center or ""
	    if p.cost_center:
	        cc_owner.setdefault(p.cost_center, []).append(p.name)

	columns = []
	result = []
	chart = None
	report_summary = []

	if view == "Summary":
	    if group_by == "Cost Center":
	        gsel = "t.cost_center as cost_center"
	        ggrp = "t.cost_center"
	    elif group_by == "Project + Cost Center":
	        gsel = "t.project as project, t.cost_center as cost_center"
	        ggrp = "t.project, t.cost_center"
	    else:
	        gsel = "t.project as project"
	        ggrp = "t.project"

	    q = "select " + gsel + """,
        sum(case when t.txn_type = 'Sales Invoice' then t.revenue else 0 end) as rev_si,
        sum(case when t.txn_type = 'Payment Entry' then t.revenue else 0 end) as rev_pe,
        sum(case when t.txn_type in ('Journal Entry', 'Salary', 'Employee Advance') then t.revenue else 0 end) as rev_je,
        sum(case when t.txn_type not in ('Sales Invoice', 'Payment Entry', 'Journal Entry', 'Salary', 'Employee Advance') then t.revenue else 0 end) as rev_other,
        sum(t.revenue) as total_revenue,
        sum(case when t.txn_type = 'Purchase' then t.expense else 0 end) as exp_purchase,
        sum(case when t.txn_type = 'Stock Consumption' then t.expense else 0 end) as exp_stock,
        sum(case when t.txn_type = 'Salary' then t.expense else 0 end) as exp_salary,
        sum(case when t.txn_type = 'Expense Claim' then t.expense else 0 end) as exp_claim,
        sum(case when t.txn_type = 'Employee Advance' then t.expense else 0 end) as exp_advance,
        sum(case when t.txn_type = 'Payment Entry' then t.expense else 0 end) as exp_pe,
        sum(case when t.txn_type = 'Journal Entry' then t.expense else 0 end) as exp_je,
        sum(case when t.txn_type in ('Sales Invoice', 'Other') then t.expense else 0 end) as exp_other,
        sum(t.expense) as total_expense,
        sum(case when t.project = '' or t.cost_center = '' then 1 else 0 end) as untagged_lines
        from (""" + base + ") t" + txn_where + " group by " + ggrp + " order by " + ggrp
	    rows = frappe.db.sql(q, vals, as_dict=1)

	    ea_map = {}
	    if group_by == "Project":
	        ea_rows = frappe.db.sql("""select ifnull(custom_project, '') as project,
                sum(paid_amount - ifnull(claimed_amount, 0) - ifnull(return_amount, 0)) as amt
            from `tabEmployee Advance`
            where docstatus = 1 and company = %(company)s and posting_date between %(from_date)s and %(to_date)s
            group by ifnull(custom_project, '')""", vals, as_dict=1)
	        for e in ea_rows:
	            ea_map[e.project] = frappe.utils.flt(e.amt, 2)

	    num_keys = ["rev_si", "rev_pe", "rev_je", "rev_other", "total_revenue", "exp_purchase", "exp_stock", "exp_salary",
	        "exp_claim", "exp_advance", "exp_pe", "exp_je", "exp_other", "total_expense", "net_profit"]
	    if group_by == "Project":
	        num_keys.append("ea_outstanding")
	    totals = {}
	    for k in num_keys:
	        totals[k] = 0.0
	    untagged = 0

	    for r in rows:
	        for k in num_keys:
	            if k not in ("net_profit", "ea_outstanding"):
	                r[k] = frappe.utils.flt(r.get(k), 2)
	        r["net_profit"] = frappe.utils.flt(r.total_revenue - r.total_expense, 2)
	        r["margin"] = frappe.utils.flt(r.net_profit * 100.0 / r.total_revenue, 2) if r.total_revenue > 0 else None
	        if "project" in r:
	            r["project_name"] = project_names.get(r.project) or ("(Project not tagged)" if not r.project else "")
	        if group_by == "Project":
	            r["ea_outstanding"] = ea_map.get(r.project or "", 0.0)
	        for k in num_keys:
	            totals[k] = totals[k] + frappe.utils.flt(r.get(k))
	        untagged = untagged + frappe.utils.cint(r.untagged_lines)
	        result.append(r)

	    total_row = {"is_total": 1}
	    for k in num_keys:
	        total_row[k] = frappe.utils.flt(totals[k], 2)
	    total_row["margin"] = frappe.utils.flt(totals["net_profit"] * 100.0 / totals["total_revenue"], 2) if totals["total_revenue"] > 0 else None
	    if group_by == "Cost Center":
	        total_row["cost_center"] = "Total"
	    else:
	        total_row["project_name"] = "Total"
	    if result:
	        result.append(total_row)

	    if group_by in ("Project", "Project + Cost Center"):
	        columns.append({"fieldname": "project", "label": "Project", "fieldtype": "Link", "options": "Project", "width": 110})
	        columns.append({"fieldname": "project_name", "label": "Project Name", "fieldtype": "Data", "width": 230})
	    if group_by in ("Cost Center", "Project + Cost Center"):
	        columns.append({"fieldname": "cost_center", "label": "Cost Center", "fieldtype": "Link", "options": "Cost Center", "width": 210})
	    labels = [
	        ["rev_si", "Revenue - Sales Invoice"],
	        ["rev_pe", "Revenue - Payment Entry"],
	        ["rev_je", "Revenue - Journal Entry"],
	        ["rev_other", "Revenue - Other"],
	        ["total_revenue", "Total Revenue"],
	        ["exp_purchase", "Expense - Purchase"],
	        ["exp_stock", "Expense - Stock Consumption"],
	        ["exp_salary", "Expense - Salary"],
	        ["exp_claim", "Expense - Expense Claim"],
	        ["exp_advance", "Expense - Employee Advance (JV)"],
	        ["exp_pe", "Expense - Payment Entry"],
	        ["exp_je", "Expense - Journal Entry"],
	        ["exp_other", "Expense - Other"],
	        ["total_expense", "Total Expense"],
	        ["net_profit", "Net Profit / (Loss)"],
	    ]
	    for l in labels:
	        columns.append({"fieldname": l[0], "label": l[1], "fieldtype": "Currency", "width": 150})
	    columns.append({"fieldname": "margin", "label": "Margin %", "fieldtype": "Percent", "width": 90})
	    if group_by == "Project":
	        columns.append({"fieldname": "ea_outstanding", "label": "Employee Advance Outstanding (Memo)", "fieldtype": "Currency", "width": 170})

	    ranked = []
	    for r in rows:
	        ranked.append([frappe.utils.flt(r.total_revenue) + frappe.utils.flt(r.total_expense), len(ranked), r])
	    ranked = sorted(ranked, reverse=True)[:12]
	    chart_labels = []
	    chart_rev = []
	    chart_exp = []
	    for item in ranked:
	        r = item[2]
	        if group_by == "Cost Center":
	            chart_labels.append(r.cost_center or "(Not tagged)")
	        else:
	            chart_labels.append(r.get("project_name") or r.get("project") or "(Not tagged)")
	        chart_rev.append(r.total_revenue)
	        chart_exp.append(r.total_expense)
	    chart = {
	        "data": {
	            "labels": chart_labels,
	            "datasets": [
	                {"name": "Revenue", "values": chart_rev},
	                {"name": "Expense", "values": chart_exp},
	            ],
	        },
	        "type": "bar",
	        "fieldtype": "Currency",
	    }
	    report_summary = [
	        {"value": totals["total_revenue"], "label": "Total Revenue", "datatype": "Currency", "indicator": "Green"},
	        {"value": totals["total_expense"], "label": "Total Expense", "datatype": "Currency", "indicator": "Red"},
	        {"value": totals["net_profit"], "label": "Net Profit / (Loss)", "datatype": "Currency", "indicator": "Blue" if totals["net_profit"] >= 0 else "Red"},
	        {"value": untagged, "label": "GL Lines without Project / Cost Center", "datatype": "Int", "indicator": "Orange" if untagged else "Green"},
	    ]

	elif view == "Detail":
	    q = """select t.posting_date, t.txn_type, t.voucher_type, t.voucher_no, t.party, t.account, t.project, t.cost_center,
            sum(t.revenue) as revenue, sum(t.expense) as expense, max(t.remarks) as remarks
        from (""" + base + ") t" + txn_where + """
        group by t.posting_date, t.txn_type, t.voucher_type, t.voucher_no, t.party, t.account, t.project, t.cost_center
        order by t.posting_date, t.voucher_type, t.voucher_no"""
	    rows = frappe.db.sql(q, vals, as_dict=1)
	    tot_rev = 0.0
	    tot_exp = 0.0
	    for r in rows:
	        r["revenue"] = frappe.utils.flt(r.revenue, 2)
	        r["expense"] = frappe.utils.flt(r.expense, 2)
	        r["project_name"] = project_names.get(r.project) or ("(Project not tagged)" if not r.project else "")
	        r["remarks"] = frappe.utils.cstr(r.remarks)[:200]
	        tot_rev = tot_rev + r.revenue
	        tot_exp = tot_exp + r.expense
	        result.append(r)
	    if result:
	        result.append({"is_total": 1, "party": "Total", "revenue": frappe.utils.flt(tot_rev, 2), "expense": frappe.utils.flt(tot_exp, 2)})
	    columns = [
	        {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "width": 100},
	        {"fieldname": "txn_type", "label": "Transaction Type", "fieldtype": "Data", "width": 140},
	        {"fieldname": "voucher_type", "label": "Voucher Type", "fieldtype": "Data", "width": 130},
	        {"fieldname": "voucher_no", "label": "Voucher No", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 170},
	        {"fieldname": "party", "label": "Party", "fieldtype": "Data", "width": 180},
	        {"fieldname": "account", "label": "Account", "fieldtype": "Link", "options": "Account", "width": 220},
	        {"fieldname": "project", "label": "Project", "fieldtype": "Link", "options": "Project", "width": 100},
	        {"fieldname": "project_name", "label": "Project Name", "fieldtype": "Data", "width": 200},
	        {"fieldname": "cost_center", "label": "Cost Center", "fieldtype": "Link", "options": "Cost Center", "width": 200},
	        {"fieldname": "revenue", "label": "Revenue", "fieldtype": "Currency", "width": 140},
	        {"fieldname": "expense", "label": "Expense", "fieldtype": "Currency", "width": 140},
	        {"fieldname": "remarks", "label": "Remarks", "fieldtype": "Data", "width": 300},
	    ]
	    report_summary = [
	        {"value": tot_rev, "label": "Total Revenue", "datatype": "Currency", "indicator": "Green"},
	        {"value": tot_exp, "label": "Total Expense", "datatype": "Currency", "indicator": "Red"},
	        {"value": tot_rev - tot_exp, "label": "Net Profit / (Loss)", "datatype": "Currency", "indicator": "Blue"},
	    ]

	else:
	    # Exceptions: one row per voucher + account + project + cost center that needs attention.
	    op_accounts = {}
	    for a in frappe.db.sql("""select a.name from `tabAccount` a
            join `tabAccount` g on a.lft >= g.lft and a.rgt <= g.rgt and g.company = a.company
            where g.company = %(company)s and g.account_name like %(pat)s and a.root_type = 'Income'""",
	            {"company": company, "pat": "Revenue From Operations%"}, as_dict=1):
	        op_accounts[a.name] = 1
	    q = """select t.posting_date, t.txn_type, t.voucher_type, t.voucher_no, t.party, t.account, t.project, t.cost_center,
            max(t.root_type) as root_type, max(t.owner) as created_by, max(t.remarks) as remarks,
            sum(t.revenue + t.expense) as amount
        from (""" + base + ") t" + txn_where + """
        group by t.posting_date, t.txn_type, t.voucher_type, t.voucher_no, t.party, t.account, t.project, t.cost_center
        order by t.posting_date, t.voucher_no"""
	    rows = frappe.db.sql(q, vals, as_dict=1)
	    actions = {
	        "Missing Project": "Select the correct Project on this transaction",
	        "Missing Cost Center": "Select the correct Cost Center on this transaction",
	        "Cost Center belongs to another Project": "Confirm the Project and Cost Center; both should point to the same site",
	        "Operating revenue booked on HO Project": "Confirm the Project; customer revenue should be booked on the site Project, not HO",
	    }
	    counts = {}
	    keyed = []
	    for r in rows:
	        issues = []
	        if not r.project:
	            issues.append("Missing Project")
	        if not r.cost_center:
	            issues.append("Missing Cost Center")
	        owners = cc_owner.get(r.cost_center) or []
	        if r.project and r.cost_center and owners and r.project not in owners and project_cc.get(r.project) != r.cost_center:
	            issues.append("Cost Center belongs to another Project")
	        if ho_project and r.project == ho_project and r.root_type == "Income" and op_accounts.get(r.account):
	            issues.append("Operating revenue booked on HO Project")
	        if not issues:
	            continue
	        r["amount"] = frappe.utils.flt(r.amount, 2)
	        r["issue"] = " + ".join(issues)
	        acts = []
	        for part in issues:
	            acts.append(actions.get(part) or "")
	            counts[part] = counts.get(part, 0) + 1
	        r["action"] = "; ".join(acts)
	        r["project_name"] = project_names.get(r.project) or ""
	        r["cc_owner_project"] = ", ".join(owners)
	        r["remarks"] = frappe.utils.cstr(r.remarks)[:200]
	        keyed.append([r.issue, frappe.utils.cstr(r.posting_date), r.voucher_no, len(keyed), r])
	    for item in sorted(keyed):
	        result.append(item[4])
	    columns = [
	        {"fieldname": "issue", "label": "Issue", "fieldtype": "Data", "width": 240},
	        {"fieldname": "action", "label": "Action Required", "fieldtype": "Data", "width": 320},
	        {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "width": 100},
	        {"fieldname": "txn_type", "label": "Transaction Type", "fieldtype": "Data", "width": 140},
	        {"fieldname": "voucher_type", "label": "Voucher Type", "fieldtype": "Data", "width": 130},
	        {"fieldname": "voucher_no", "label": "Voucher No", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 170},
	        {"fieldname": "party", "label": "Party", "fieldtype": "Data", "width": 180},
	        {"fieldname": "account", "label": "Account", "fieldtype": "Link", "options": "Account", "width": 220},
	        {"fieldname": "project", "label": "Project", "fieldtype": "Link", "options": "Project", "width": 100},
	        {"fieldname": "project_name", "label": "Project Name", "fieldtype": "Data", "width": 200},
	        {"fieldname": "cost_center", "label": "Cost Center (on transaction)", "fieldtype": "Link", "options": "Cost Center", "width": 200},
	        {"fieldname": "cc_owner_project", "label": "Cost Center Belongs To Project", "fieldtype": "Data", "width": 170},
	        {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "width": 140},
	        {"fieldname": "created_by", "label": "Created By", "fieldtype": "Data", "width": 200},
	        {"fieldname": "remarks", "label": "Remarks", "fieldtype": "Data", "width": 300},
	    ]
	    for k in counts:
	        report_summary.append({"value": counts[k], "label": k + " (lines)", "datatype": "Int", "indicator": "Red"})

	return [columns, result, None, chart, report_summary]
