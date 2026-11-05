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



	def build_detail(filters):
		flt = frappe.utils.flt
		section_filter = filters.get("section") or "All"
		wbs_filter = filters.get("wbs_element")
		sub_filter = filters.get("sub_wbs_element")
		measure_filter = filters.get("measure") or "Assigned (All)"
		scope = filters.get("scope") or "All"
		status_filter = filters.get("status") or "All"
		category_filter = filters.get("category")

		eng = run_engine(filters)
		wbs = eng["wbs"]
		subs = eng["subs"]

		measure_key = {
			"Actual": ("actual",),
			"Commitment": ("commitment",),
			"Pending": ("pending",),
			"Assigned (All)": ("actual", "commitment", "pending"),
		}.get(measure_filter, ("actual", "commitment", "pending"))
		measure_label = {"actual": "Actual", "commitment": "Commitment", "pending": "Pending"}

		# Sub WBS filter covers the Sub WBS and every Sub WBS nested under it.
		def in_sub_tree(sub_id):
			cur = sub_id
			seen = {}
			while cur and cur in subs and cur not in seen:
				if cur == sub_filter:
					return True
				seen[cur] = 1
				cur = subs[cur].parent_sub_wbs
			return False

		rows = []
		total = 0.0
		docs_by_type = {}
		for c in eng["contribs"]:
			if section_filter != "All" and c["section"] != section_filter:
				continue
			if c["measure"] not in measure_key:
				continue
			if scope == "Not linked to WBS" and c["wbs"]:
				continue
			if scope in ("Linked to WBS", "Direct to WBS only") and not c["wbs"]:
				continue
			if scope == "Direct to WBS only" and c["sub"]:
				continue
			cross = bool(c["wbs"] and c["sub"] and c["sub"] in subs and subs[c["sub"]].main_wbs_element != c["wbs"])
			if scope == "Sub WBS of another WBS" and not cross:
				continue
			if wbs_filter and c["wbs"] != wbs_filter:
				continue
			# Same WBS visibility as the hierarchy report (status / category).
			wrow = wbs.get(c["wbs"])
			if wrow and not wbs_filter:
				if wrow.status == "Cancelled":
					continue
				if status_filter != "All" and wrow.status != status_filter:
					continue
			if category_filter and (not wrow or wrow.category != category_filter):
				continue
			if sub_filter and not in_sub_tree(c["sub"]):
				continue
			w = wbs.get(c["wbs"])
			s = subs.get(c["sub"])
			rows.append({
				"section": c["section"],
				"wbs_element": c["wbs"] or "",
				"wbs_name": (w.wbs_name if w else "Not linked to any WBS"),
				"sub_wbs_element": c["sub"] or "",
				"sub_wbs_name": (s.sub_wbs_name if s else ""),
				"measure": measure_label[c["measure"]],
				"ref_doctype": c["doctype"],
				"ref_name": c["docname"],
				"posting_date": c["posting_date"],
				"party": c["party"],
				"doc_status": c["doc_status"],
				"doc_value": c["doc_value"],
				"base_amount": c["base_amount"],
				"fraction_pct": flt(c["fraction"] * 100, 4),
				"amount": c["amount"],
				"basis": c["basis"],
			})
			total = total + c["amount"]
			if c["doctype"] not in docs_by_type:
				docs_by_type[c["doctype"]] = {}
			docs_by_type[c["doctype"]][c["docname"]] = 1

		rows = sorted(rows, key=lambda r: (r["section"], r["wbs_element"] or "zzz", r["sub_wbs_element"],
			r["measure"], r["ref_doctype"], str(r["posting_date"] or ""), r["ref_name"]))

		if rows:
			doc_total = 0
			for k in docs_by_type:
				doc_total = doc_total + len(docs_by_type[k])
			rows.append({
				"section": "",
				"wbs_name": "TOTAL",
				"measure": "",
				"ref_name": str(doc_total) + " documents",
				"amount": total,
				"is_total": 1,
			})

		columns = [
			{"fieldname": "section", "label": "Section", "fieldtype": "Data", "width": 85},
			{"fieldname": "wbs_element", "label": "WBS Element", "fieldtype": "Link", "options": "WBS Element", "width": 110},
			{"fieldname": "wbs_name", "label": "WBS Name", "fieldtype": "Data", "width": 190},
			{"fieldname": "sub_wbs_element", "label": "Sub WBS", "fieldtype": "Link", "options": "Sub WBS Element", "width": 130},
			{"fieldname": "sub_wbs_name", "label": "Sub WBS Name", "fieldtype": "Data", "width": 150},
			{"fieldname": "measure", "label": "Measure", "fieldtype": "Data", "width": 100},
			{"fieldname": "ref_doctype", "label": "Document Type", "fieldtype": "Data", "width": 130},
			{"fieldname": "ref_name", "label": "Document", "fieldtype": "Dynamic Link", "options": "ref_doctype", "width": 170},
			{"fieldname": "posting_date", "label": "Date", "fieldtype": "Date", "width": 95},
			{"fieldname": "party", "label": "Supplier / Customer", "fieldtype": "Data", "width": 200},
			{"fieldname": "doc_status", "label": "Doc Status", "fieldtype": "Data", "width": 120},
			{"fieldname": "doc_value", "label": "Document Value (excl. GST)", "fieldtype": "Currency", "width": 160},
			{"fieldname": "base_amount", "label": "Allocated / Not Linked Amount", "fieldtype": "Currency", "width": 170},
			{"fieldname": "fraction_pct", "label": "Share %", "fieldtype": "Percent", "width": 85},
			{"fieldname": "amount", "label": "Amount Counted", "fieldtype": "Currency", "width": 150},
			{"fieldname": "basis", "label": "Basis", "fieldtype": "Data", "width": 240},
		]

		doc_count = 0
		for k in docs_by_type:
			doc_count = doc_count + len(docs_by_type[k])
		cards = [
			{"label": "Amount Counted", "value": total, "datatype": "Currency", "indicator": "Blue"},
			{"label": "Documents", "value": doc_count, "datatype": "Int", "indicator": "Grey"},
		]
		return columns, rows, cards

	res = build_detail(filters)
	return [res[0], res[1], None, None, res[2]]
