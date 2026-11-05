import frappe
from frappe.utils import flt


def execute(filters=None):
	return main(frappe._dict(filters or {}))


def main(filters):
	# Shared engine for "Project Revenue and Expense Hierarchy" and
	# "Project Budget Transactions" (drill-down).
	#
	# run_engine(filters) returns a dict:
	#   wbs     : {wbs_name_id: master row}
	#   subs    : {sub_id: master row}
	#   contribs: list of contribution records, one per (document, WBS line, measure)
	#
	# A contribution record:
	#   section   Expense | Revenue
	#   wbs       WBS Element id, or "" for "Not linked to any WBS"
	#   sub       Sub WBS Element id or ""
	#   measure   actual | commitment | pending
	#   doctype, docname, posting_date, party, doc_status
	#   doc_value       value of the document line(s) for this project (net of tax)
	#   base_amount     allocated amount (linked) or unallocated amount (not linked)
	#   fraction        share of base_amount counted for this measure (0..1)
	#   amount          base_amount * fraction  (this is what the report sums)
	#   basis           short text explaining how the amount was derived


	def run_engine(filters):
		flt = frappe.utils.flt
		project = filters.get("project")
		if not project:
			frappe.throw("Project is mandatory")

		CLOSED_PO = ("Completed", "Closed", "Cancelled", "Delivered")
		CLOSED_SO = ("Completed", "Closed", "Cancelled")
		OPEN_MR = ("Pending", "Partially Ordered")
		TOL = 0.5

		wbs_rows = frappe.db.sql(
			"""
			select name, wbs_name, ifnull(custom_category_type, '') as ctype, status,
				ifnull(category, '') as category, ifnull(budget_amount, 0) as budget_amount,
				ifnull(total_revenue, 0) as total_revenue, creation
			from `tabWBS Element`
			where project = %s
			order by creation, name
			""",
			project,
			as_dict=True,
		)
		sub_rows = frappe.db.sql(
			"""
			select name, sub_wbs_name, main_wbs_element, ifnull(parent_sub_wbs, '') as parent_sub_wbs,
				status, ifnull(budget_amount, 0) as budget_amount,
				ifnull(custom_total_revenue, 0) as total_revenue, creation
			from `tabSub WBS Element`
			where project = %s or main_wbs_element in (select name from `tabWBS Element` where project = %s)
			order by creation, name
			""",
			(project, project),
			as_dict=True,
		)

		wbs = {}
		for w in wbs_rows:
			w["section"] = "Revenue" if w.ctype == "Revenue" else "Expense"
			w["budget"] = flt(w.total_revenue) if w.section == "Revenue" else flt(w.budget_amount)
			wbs[w.name] = w
		subs = {}
		for s in sub_rows:
			parent_wbs = wbs.get(s.main_wbs_element)
			s["section"] = parent_wbs.section if parent_wbs else "Expense"
			s["budget"] = flt(s.total_revenue) if s.section == "Revenue" else flt(s.budget_amount)
			subs[s.name] = s

		wbs_ids = tuple(wbs.keys()) or ("__none__",)
		contribs = []

		def add(section, wbs_id, sub_id, measure, doc, base_amount, fraction, basis):
			amount = flt(base_amount) * flt(fraction)
			if abs(amount) < 0.005:
				return
			contribs.append(
				{
					"section": section,
					"wbs": wbs_id or "",
					"sub": sub_id or "",
					"measure": measure,
					"doctype": doc["doctype"],
					"docname": doc["name"],
					"posting_date": doc.get("dt"),
					"party": doc.get("party") or "",
					"doc_status": doc.get("status") or "",
					"doc_value": flt(doc.get("doc_value")),
					"base_amount": flt(base_amount),
					"fraction": flt(fraction),
					"amount": amount,
					"basis": basis,
				}
			)

		def clamp(x):
			if x < 0:
				return 0.0
			if x > 1:
				return 1.0
			return x

		def pct(x):
			return str(flt(x * 100, 2)) + "%"

		# ------------------------------------------------------------------
		# EXPENSE — linked to WBS (WBS Allocation child table)
		# ------------------------------------------------------------------
		po_lines = frappe.db.sql(
			"""
			select wa.wbs_element, ifnull(wa.sub_wbs_element, '') as sub_wbs_element, wa.allocated_amount,
				po.name, po.transaction_date as dt, po.supplier as party, po.status, po.total as doc_value,
				ifnull((select sum(poi.billed_amt) from `tabPurchase Order Item` poi where poi.parent = po.name), 0) as billed
			from `tabWBS Allocation` wa
			inner join `tabPurchase Order` po on po.name = wa.parent
			where wa.parenttype = 'Purchase Order' and po.docstatus = 1 and wa.wbs_element in %(w)s
			""",
			{"w": wbs_ids},
			as_dict=True,
		)
		for r in po_lines:
			if flt(r.doc_value) <= 0:
				continue
			r["doctype"] = "Purchase Order"
			billed_fraction = clamp(flt(r.billed) / flt(r.doc_value))
			add("Expense", r.wbs_element, r.sub_wbs_element, "actual", r, r.allocated_amount, billed_fraction,
				"Allocated x billed " + pct(billed_fraction))
			if r.status not in CLOSED_PO:
				add("Expense", r.wbs_element, r.sub_wbs_element, "commitment", r, r.allocated_amount,
					1 - billed_fraction, "Allocated x unbilled " + pct(1 - billed_fraction))

		pi_lines = frappe.db.sql(
			"""
			select wa.wbs_element, ifnull(wa.sub_wbs_element, '') as sub_wbs_element, wa.allocated_amount,
				pi.name, pi.posting_date as dt, pi.supplier as party, pi.status, pi.net_total as doc_value
			from `tabWBS Allocation` wa
			inner join `tabPurchase Invoice` pi on pi.name = wa.parent
			where wa.parenttype = 'Purchase Invoice' and pi.docstatus = 1 and wa.wbs_element in %(w)s
				and not exists (
					select 1 from `tabPurchase Invoice Item` pii
					where pii.parent = pi.name and ifnull(pii.purchase_order, '') != ''
				)
			""",
			{"w": wbs_ids},
			as_dict=True,
		)
		for r in pi_lines:
			r["doctype"] = "Purchase Invoice"
			add("Expense", r.wbs_element, r.sub_wbs_element, "actual", r, r.allocated_amount, 1,
				"Direct invoice (no PO), full allocation")

		mr_lines = frappe.db.sql(
			"""
			select wa.wbs_element, ifnull(wa.sub_wbs_element, '') as sub_wbs_element, wa.allocated_amount,
				mr.name, mr.transaction_date as dt, '' as party, mr.status,
				ifnull((select sum(mri.amount) from `tabMaterial Request Item` mri where mri.parent = mr.name), 0) as doc_value,
				ifnull((
					select sum(mri.amount * least(1, ifnull((
						select sum(poi.stock_qty) from `tabPurchase Order Item` poi
						where poi.material_request_item = mri.name and poi.docstatus = 1
					), 0) / mri.stock_qty))
					from `tabMaterial Request Item` mri
					where mri.parent = mr.name and mri.stock_qty > 0
				), 0) as ordered
			from `tabWBS Allocation` wa
			inner join `tabMaterial Request` mr on mr.name = wa.parent
			where wa.parenttype = 'Material Request' and mr.docstatus = 1
				and mr.status in %(st)s and wa.wbs_element in %(w)s
			""",
			{"w": wbs_ids, "st": OPEN_MR},
			as_dict=True,
		)
		for r in mr_lines:
			if flt(r.doc_value) <= 0:
				continue
			r["doctype"] = "Material Request"
			open_fraction = clamp((flt(r.doc_value) - flt(r.ordered)) / flt(r.doc_value))
			add("Expense", r.wbs_element, r.sub_wbs_element, "pending", r, r.allocated_amount, open_fraction,
				"Allocated x not yet ordered " + pct(open_fraction))

		# ------------------------------------------------------------------
		# REVENUE — linked to WBS (Revenue WBS Allocation child table)
		# ------------------------------------------------------------------
		si_lines = frappe.db.sql(
			"""
			select ra.wbs_element, ifnull(ra.sub_wbs_element, '') as sub_wbs_element, ra.allocated_amount,
				si.name, si.posting_date as dt, si.customer as party, si.status, si.net_total as doc_value
			from `tabRevenue WBS Allocation` ra
			inner join `tabSales Invoice` si on si.name = ra.parent
			where ra.parenttype = 'Sales Invoice' and si.docstatus = 1 and ra.wbs_element in %(w)s
			""",
			{"w": wbs_ids},
			as_dict=True,
		)
		for r in si_lines:
			r["doctype"] = "Sales Invoice"
			add("Revenue", r.wbs_element, r.sub_wbs_element, "actual", r, r.allocated_amount, 1,
				"Invoiced, full allocation")

		so_lines = frappe.db.sql(
			"""
			select ra.wbs_element, ifnull(ra.sub_wbs_element, '') as sub_wbs_element, ra.allocated_amount,
				so.name, so.transaction_date as dt, so.customer as party, so.status, so.total as doc_value,
				ifnull((select sum(soi.billed_amt) from `tabSales Order Item` soi where soi.parent = so.name), 0) as billed
			from `tabRevenue WBS Allocation` ra
			inner join `tabSales Order` so on so.name = ra.parent
			where ra.parenttype = 'Sales Order' and so.docstatus = 1
				and so.status not in %(cl)s and ra.wbs_element in %(w)s
			""",
			{"w": wbs_ids, "cl": CLOSED_SO},
			as_dict=True,
		)
		for r in so_lines:
			if flt(r.doc_value) <= 0:
				continue
			r["doctype"] = "Sales Order"
			open_fraction = 1 - clamp(flt(r.billed) / flt(r.doc_value))
			add("Revenue", r.wbs_element, r.sub_wbs_element, "commitment", r, r.allocated_amount, open_fraction,
				"Allocated x not yet invoiced " + pct(open_fraction))

		bo_lines = frappe.db.sql(
			"""
			select ra.wbs_element, ifnull(ra.sub_wbs_element, '') as sub_wbs_element, ra.allocated_amount,
				bo.name, bo.from_date as dt, bo.customer as party, bo.to_date,
				ifnull((select sum(boi.qty * boi.rate) from `tabBlanket Order Item` boi where boi.parent = bo.name), 0) as doc_value,
				ifnull((select sum(least(ifnull(boi.ordered_qty, 0), boi.qty) * boi.rate)
					from `tabBlanket Order Item` boi where boi.parent = bo.name), 0) as ordered
			from `tabRevenue WBS Allocation` ra
			inner join `tabBlanket Order` bo on bo.name = ra.parent
			where ra.parenttype = 'Blanket Order' and bo.docstatus = 1
				and (bo.to_date is null or bo.to_date >= curdate()) and ra.wbs_element in %(w)s
			""",
			{"w": wbs_ids},
			as_dict=True,
		)
		for r in bo_lines:
			if flt(r.doc_value) <= 0:
				continue
			r["doctype"] = "Blanket Order"
			r["status"] = "Valid till " + str(r.to_date or "")
			open_fraction = clamp((flt(r.doc_value) - flt(r.ordered)) / flt(r.doc_value))
			add("Revenue", r.wbs_element, r.sub_wbs_element, "pending", r, r.allocated_amount, open_fraction,
				"Allocated x not yet ordered " + pct(open_fraction))

		# ------------------------------------------------------------------
		# NOT LINKED TO ANY WBS — project transactions (or the part of them)
		# that carry no WBS allocation. Counted on the project's share of the
		# document: item rows with this project, or blank item project on a
		# document whose header project is this project.
		# ------------------------------------------------------------------
		def unlinked(doctype, item_doctype, alloc_table, amount_field, header_has_project, extra_select, where_extra, values):
			# Rows with a blank project count towards this project when the document
			# belongs to it (header project = this project, or no header project at
			# all, e.g. Material Request).
			header_cond = ""
			item_cond = "(i.project = %(p)s or ifnull(i.project, '') = '')"
			if header_has_project:
				header_cond = " or d.project = %(p)s"
				item_cond = "(i.project = %(p)s or (ifnull(i.project, '') = '' and ifnull(d.project, '') in ('', %(p)s)))"
			sql = (
				"select d.name, " + extra_select + ", "
				+ "ifnull((select sum(i." + amount_field + ") from `tab" + item_doctype + "` i where i.parent = d.name and "
				+ item_cond + "), 0) as doc_value, "
				+ "ifnull((select sum(a.allocated_amount) from `tab" + alloc_table + "` a where a.parent = d.name and a.parenttype = '"
				+ doctype + "' and a.wbs_element in %(w)s), 0) as linked "
				+ "from `tab" + doctype + "` d where d.docstatus = 1 " + where_extra
				+ " and (exists (select 1 from `tab" + item_doctype + "` i2 where i2.parent = d.name and i2.project = %(p)s)"
				+ header_cond + ")"
			)
			params = {"p": project, "w": wbs_ids}
			for k in values:
				params[k] = values[k]
			out = []
			for r in frappe.db.sql(sql, params, as_dict=True):
				r["doctype"] = doctype
				r["gap"] = flt(r.doc_value) - flt(r.linked)
				# Only a positive gap is "not linked". A negative gap means the document
				# is allocated for more than its value; that is not unlinked spend.
				if r.gap > TOL:
					out.append(r)
			return out

		for r in unlinked("Purchase Order", "Purchase Order Item", "WBS Allocation", "net_amount", True,
				"d.transaction_date as dt, d.supplier as party, d.status, d.total as po_total, "
				"ifnull((select sum(x.billed_amt) from `tabPurchase Order Item` x where x.parent = d.name), 0) as billed",
				"", {}):
			billed_fraction = clamp(flt(r.billed) / flt(r.po_total)) if flt(r.po_total) > 0 else 0
			add("Expense", "", "", "actual", r, r.gap, billed_fraction, "Not linked x billed " + pct(billed_fraction))
			if r.status not in CLOSED_PO:
				add("Expense", "", "", "commitment", r, r.gap, 1 - billed_fraction,
					"Not linked x unbilled " + pct(1 - billed_fraction))

		for r in unlinked("Purchase Invoice", "Purchase Invoice Item", "WBS Allocation", "net_amount", True,
				"d.posting_date as dt, d.supplier as party, d.status",
				"and not exists (select 1 from `tabPurchase Invoice Item` x where x.parent = d.name and ifnull(x.purchase_order, '') != '')",
				{}):
			add("Expense", "", "", "actual", r, r.gap, 1, "Direct invoice, not linked to WBS")

		for r in unlinked("Material Request", "Material Request Item", "WBS Allocation", "amount", False,
				"d.transaction_date as dt, '' as party, d.status, "
				"ifnull((select sum(x.amount) from `tabMaterial Request Item` x where x.parent = d.name), 0) as mr_total, "
				"ifnull((select sum(x.amount * least(1, ifnull((select sum(poi.stock_qty) from `tabPurchase Order Item` poi "
				"where poi.material_request_item = x.name and poi.docstatus = 1), 0) / x.stock_qty)) "
				"from `tabMaterial Request Item` x where x.parent = d.name and x.stock_qty > 0), 0) as ordered",
				"and d.status in %(st)s", {"st": OPEN_MR}):
			open_fraction = clamp((flt(r.mr_total) - flt(r.ordered)) / flt(r.mr_total)) if flt(r.mr_total) > 0 else 0
			add("Expense", "", "", "pending", r, r.gap, open_fraction, "Not linked x not yet ordered " + pct(open_fraction))

		for r in unlinked("Sales Invoice", "Sales Invoice Item", "Revenue WBS Allocation", "net_amount", True,
				"d.posting_date as dt, d.customer as party, d.status", "", {}):
			add("Revenue", "", "", "actual", r, r.gap, 1, "Invoiced, not linked to WBS")

		for r in unlinked("Sales Order", "Sales Order Item", "Revenue WBS Allocation", "net_amount", True,
				"d.transaction_date as dt, d.customer as party, d.status, d.total as so_total, "
				"ifnull((select sum(x.billed_amt) from `tabSales Order Item` x where x.parent = d.name), 0) as billed",
				"and d.status not in %(cl)s", {"cl": CLOSED_SO}):
			open_fraction = 1 - clamp(flt(r.billed) / flt(r.so_total)) if flt(r.so_total) > 0 else 0
			add("Revenue", "", "", "commitment", r, r.gap, open_fraction, "Not linked x not yet invoiced " + pct(open_fraction))

		return {"wbs": wbs, "subs": subs, "contribs": contribs}



	def build_hierarchy(filters):
		flt = frappe.utils.flt
		view = filters.get("view") or "Both"
		status_filter = filters.get("status") or "Active"
		category_filter = filters.get("category")
		wbs_filter = filters.get("wbs_element")
		narrowed = bool(category_filter or wbs_filter)

		eng = run_engine(filters)
		wbs = eng["wbs"]
		subs = eng["subs"]
		contribs = eng["contribs"]

		# Revenue is shown first, then Expense.
		sections = []
		if view in ("Both", "Revenue"):
			sections.append("Revenue")
		if view in ("Both", "Expense"):
			sections.append("Expense")

		def blank():
			return {"actual": 0.0, "commitment": 0.0, "pending": 0.0, "docs": {}}

		def bump(bucket, c):
			bucket[c["measure"]] = bucket[c["measure"]] + c["amount"]
			bucket["docs"][c["doctype"] + "::" + c["docname"]] = 1

		# ancestors of a Sub WBS (itself first)
		def sub_chain(sub_id):
			chain = []
			seen = {}
			cur = sub_id
			while cur and cur in subs and cur not in seen:
				chain.append(cur)
				seen[cur] = 1
				cur = subs[cur].parent_sub_wbs
			return chain

		wbs_tot = {}
		sub_tot = {}
		direct_tot = {}
		cross_tot = {}
		unlinked_tot = {"Expense": blank(), "Revenue": blank()}
		for c in contribs:
			if not c["wbs"]:
				bump(unlinked_tot[c["section"]], c)
				continue
			key = c["section"] + "::" + c["wbs"]
			if key not in wbs_tot:
				wbs_tot[key] = blank()
			bump(wbs_tot[key], c)
			if c["sub"] and c["sub"] in subs and subs[c["sub"]].main_wbs_element != c["wbs"]:
				# Sub WBS that belongs to another WBS: keep it under the document's WBS.
				if key not in cross_tot:
					cross_tot[key] = blank()
				bump(cross_tot[key], c)
			elif c["sub"]:
				for s in sub_chain(c["sub"]):
					skey = c["section"] + "::" + s
					if skey not in sub_tot:
						sub_tot[skey] = blank()
					bump(sub_tot[skey], c)
			else:
				if key not in direct_tot:
					direct_tot[key] = blank()
				bump(direct_tot[key], c)

		def derive(section, budget, t):
			actual = flt(t["actual"])
			commitment = flt(t["commitment"])
			pending = flt(t["pending"])
			assigned = actual + commitment + pending
			if section == "Revenue":
				available = flt(budget) - actual
				util = (actual / flt(budget) * 100) if flt(budget) else 0
			else:
				available = flt(budget) - assigned
				util = (assigned / flt(budget) * 100) if flt(budget) else 0
			return {
				"budget_amount": flt(budget),
				"actual": actual,
				"commitment": commitment,
				"rem_ord_plan": pending,
				"assigned": assigned,
				"available": available,
				"utilization_pct": util,
				"doc_count": len(t["docs"]),
			}

		def row(entity, entity_type, indent, section, budget, t, wbs_id, sub_id, scope, link_doctype, link_name):
			r = derive(section, budget, t)
			r["entity"] = entity
			r["entity_type"] = entity_type
			r["indent"] = indent
			r["section"] = section
			r["wbs_element"] = wbs_id or ""
			r["sub_wbs_element"] = sub_id or ""
			r["scope"] = scope
			r["link_doctype"] = link_doctype or ""
			r["link_name"] = link_name or ""
			if entity_type in ("Not Linked", "Direct", "Mismatch"):
				r["available"] = None
				r["utilization_pct"] = None
			return r

		def wbs_visible(w):
			if w.status == "Cancelled":
				return False
			if status_filter != "All" and w.status != status_filter:
				return False
			if category_filter and w.category != category_filter:
				return False
			if wbs_filter and w.name != wbs_filter:
				return False
			return True

		def children_of(wbs_id, parent_sub):
			out = []
			for sid in subs:
				s = subs[sid]
				if s.main_wbs_element != wbs_id or s.parent_sub_wbs != (parent_sub or ""):
					continue
				# A cancelled Sub WBS is still shown while documents carry it,
				# otherwise its children would not add up to the WBS.
				if s.status == "Cancelled" and not sub_tot.get(s.section + "::" + s.name):
					continue
				out.append(s)
			return out

		def add_sub_rows(data, section, wbs_id, parent_sub, indent):
			for s in children_of(wbs_id, parent_sub):
				t = sub_tot.get(section + "::" + s.name) or blank()
				data.append(row(s.sub_wbs_name or s.name, "Sub WBS", indent, section, s.budget, t,
					wbs_id, s.name, "Linked to WBS", "Sub WBS Element", s.name))
				add_sub_rows(data, section, wbs_id, s.name, indent + 1)

		data = []
		summary = {}
		for section in sections:
			section_rows = []
			sec_budget = 0.0
			sec_tot = blank()
			for wid in wbs:
				w = wbs[wid]
				if w.section != section or not wbs_visible(w):
					continue
				key = section + "::" + wid
				t = wbs_tot.get(key) or blank()
				section_rows.append(row(w.wbs_name or wid, "WBS", 1, section, w.budget, t,
					wid, "", "Linked to WBS", "WBS Element", wid))
				sec_budget = sec_budget + flt(w.budget)
				for m in ("actual", "commitment", "pending"):
					sec_tot[m] = sec_tot[m] + t[m]
				for d in t["docs"]:
					sec_tot["docs"][d] = 1
				has_children = len(children_of(wid, "")) > 0
				if has_children:
					add_sub_rows(section_rows, section, wid, "", 2)
					dt = direct_tot.get(key)
					if dt and (abs(dt["actual"]) + abs(dt["commitment"]) + abs(dt["pending"])) > 0.005:
						section_rows.append(row("(Booked directly on WBS, no Sub WBS)", "Direct", 2, section, 0, dt,
							wid, "", "Direct to WBS only", "", ""))
				xt = cross_tot.get(key)
				if xt and (abs(xt["actual"]) + abs(xt["commitment"]) + abs(xt["pending"])) > 0.005:
					section_rows.append(row("(Tagged with a Sub WBS of another WBS - check tagging)", "Mismatch", 2, section, 0, xt,
						wid, "", "Sub WBS of another WBS", "", ""))

			if not narrowed:
				ut = unlinked_tot[section]
				if (abs(ut["actual"]) + abs(ut["commitment"]) + abs(ut["pending"])) > 0.005:
					section_rows.append(row("Not linked to any WBS", "Not Linked", 1, section, 0, ut,
						"", "", "Not linked to WBS", "", ""))
					for m in ("actual", "commitment", "pending"):
						sec_tot[m] = sec_tot[m] + ut[m]
					for d in ut["docs"]:
						sec_tot["docs"][d] = 1

			label = "EXPENSE" if section == "Expense" else "REVENUE"
			head = row(label, "Section", 0, section, sec_budget, sec_tot, "", "", "All", "", "")
			data.append(head)
			for r in section_rows:
				data.append(r)
			summary[section] = head

		columns = []
		cards = []
		return columns, data, cards


	def build_summary(filters):
		flt = frappe.utils.flt
		wbs_status = filters.get("status") or "Active"
		project_status = filters.get("project_status") or "All"
		company = filters.get("company")
		only_project = filters.get("project")

		cond = ["exists (select 1 from `tabWBS Element` w where w.project = p.name)"]
		vals = {}
		if company:
			cond.append("p.company = %(company)s")
			vals["company"] = company
		if project_status != "All":
			cond.append("p.status = %(pstatus)s")
			vals["pstatus"] = project_status
		if only_project:
			cond.append("p.name = %(project)s")
			vals["project"] = only_project
		projects = frappe.db.sql(
			"select p.name, p.project_name, p.status from `tabProject` p where " + " and ".join(cond)
			+ " order by p.name",
			vals,
			as_dict=True,
		)

		rows = []
		tot = {}
		keys = ("rev_target", "rev_actual", "rev_open", "rev_pending", "exp_budget", "exp_actual",
			"exp_commit", "exp_pending", "exp_assigned", "net_actual")
		for k in keys:
			tot[k] = 0.0

		for p in projects:
			# Same calculation as the "Project Revenue and Expense Hierarchy" section rows.
			res = build_hierarchy({"project": p.name, "view": "Both", "status": wbs_status})
			heads = {}
			for r in res[1]:
				if r.get("entity_type") == "Section":
					heads[r["section"]] = r
			v = heads.get("Revenue") or {}
			e = heads.get("Expense") or {}
			row = {
				"project": p.name,
				"project_name": p.project_name or p.name,
				"project_status": p.status,
				"rev_target": flt(v.get("budget_amount")),
				"rev_actual": flt(v.get("actual")),
				"rev_open": flt(v.get("commitment")),
				"rev_pending": flt(v.get("rem_ord_plan")),
				"exp_budget": flt(e.get("budget_amount")),
				"exp_actual": flt(e.get("actual")),
				"exp_commit": flt(e.get("commitment")),
				"exp_pending": flt(e.get("rem_ord_plan")),
				"exp_assigned": flt(e.get("assigned")),
			}
			row["net_actual"] = row["rev_actual"] - row["exp_actual"]
			# A target / budget of 1 rupee or less is a placeholder, not a real figure.
			row["rev_achievement"] = (row["rev_actual"] / row["rev_target"] * 100) if row["rev_target"] > 1 else None
			row["exp_utilization"] = (row["exp_assigned"] / row["exp_budget"] * 100) if row["exp_budget"] > 1 else None
			row["net_margin"] = (row["net_actual"] / row["rev_actual"] * 100) if row["rev_actual"] else None
			rows.append(row)
			for k in keys:
				tot[k] = tot[k] + row[k]

		if rows:
			total = {"project": "", "project_name": "TOTAL (" + str(len(rows)) + " projects)", "is_total": 1}
			for k in keys:
				total[k] = tot[k]
			total["rev_achievement"] = (tot["rev_actual"] / tot["rev_target"] * 100) if tot["rev_target"] > 1 else None
			total["exp_utilization"] = (tot["exp_assigned"] / tot["exp_budget"] * 100) if tot["exp_budget"] > 1 else None
			total["net_margin"] = (tot["net_actual"] / tot["rev_actual"] * 100) if tot["rev_actual"] else None
			rows.append(total)

		columns = [
			{"fieldname": "project", "label": "Project", "fieldtype": "Link", "options": "Project", "width": 105},
			{"fieldname": "project_name", "label": "Project Name", "fieldtype": "Data", "width": 260},
			{"fieldname": "project_status", "label": "Status", "fieldtype": "Data", "width": 85},
			{"fieldname": "rev_target", "label": "Revenue Target", "fieldtype": "Currency", "width": 150},
			{"fieldname": "rev_actual", "label": "Revenue Invoiced", "fieldtype": "Currency", "width": 150},
			{"fieldname": "rev_open", "label": "Revenue Open SO", "fieldtype": "Currency", "width": 140},
			{"fieldname": "rev_pending", "label": "Revenue Open BO", "fieldtype": "Currency", "width": 140},
			{"fieldname": "rev_achievement", "label": "Achievement %", "fieldtype": "Percent", "width": 110},
			{"fieldname": "exp_budget", "label": "Expense Budget", "fieldtype": "Currency", "width": 150},
			{"fieldname": "exp_actual", "label": "Expense Actual", "fieldtype": "Currency", "width": 150},
			{"fieldname": "exp_commit", "label": "Expense Open PO", "fieldtype": "Currency", "width": 140},
			{"fieldname": "exp_pending", "label": "Expense Open MR", "fieldtype": "Currency", "width": 140},
			{"fieldname": "exp_utilization", "label": "Utilization %", "fieldtype": "Percent", "width": 110},
			{"fieldname": "net_actual", "label": "Net (Invoiced - Expense Actual)", "fieldtype": "Currency", "width": 190},
			{"fieldname": "net_margin", "label": "Net Margin %", "fieldtype": "Percent", "width": 110},
		]

		cards = [
			{"label": "Revenue Target", "value": tot["rev_target"], "datatype": "Currency", "indicator": "Blue"},
			{"label": "Revenue Invoiced", "value": tot["rev_actual"], "datatype": "Currency", "indicator": "Green"},
			{"label": "Expense Budget", "value": tot["exp_budget"], "datatype": "Currency", "indicator": "Blue"},
			{"label": "Expense Actual", "value": tot["exp_actual"], "datatype": "Currency", "indicator": "Red"},
			{"label": "Net (Invoiced - Expense Actual)", "value": tot["net_actual"], "datatype": "Currency",
				"indicator": "Green" if tot["net_actual"] >= 0 else "Red"},
		]
		return columns, rows, cards

	res = build_summary(filters)
	return [res[0], res[1], None, None, res[2]]
