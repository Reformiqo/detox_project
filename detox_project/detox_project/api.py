import frappe
from frappe import _


# ---------------------------------------------------------------------------
# Document Event Hooks
# ---------------------------------------------------------------------------

def validate_project(doc, method):
    if doc.custom_total_budget and doc.custom_total_spent:
        doc.custom_budget_utilization_pct = (
            doc.custom_total_spent / doc.custom_total_budget * 100
        )


def on_project_update(doc, method):
    if doc.status == "Cancelled":
        wbs_elements = frappe.get_all(
            "WBS Element",
            filters={"project": doc.name, "status": ["!=", "Cancelled"]},
            pluck="name",
        )
        for wbs_name in wbs_elements:
            frappe.db.set_value("WBS Element", wbs_name, "status", "Cancelled")

    elif doc.status == "Completed":
        wbs_elements = frappe.get_all(
            "WBS Element",
            filters={"project": doc.name, "status": "Active"},
            pluck="name",
        )
        for wbs_name in wbs_elements:
            frappe.db.set_value("WBS Element", wbs_name, "status", "Completed")


def validate_material_request_budget(doc, method):
    """SOFT warning when MR is linked to a WBS that exceeds budget."""
    if not doc.custom_wbs_element:
        return

    wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
    if not wbs.total_budget:
        return

    pct = wbs.overall_utilization_pct or 0
    if pct >= 100:
        frappe.msgprint(
            _("WBS Element {0} has EXCEEDED its budget!").format(wbs.name),
            indicator="red",
            title=_("Budget Exceeded"),
        )
    elif pct >= 80:
        frappe.msgprint(
            _("WBS Element {0} has {1}% budget utilization. Budget: {2}, Spent: {3}").format(
                wbs.name,
                f"{pct:.1f}",
                frappe.format_value(wbs.total_budget, {"fieldtype": "Currency"}),
                frappe.format_value(wbs.total_spent, {"fieldtype": "Currency"}),
            ),
            indicator="orange",
            title=_("Budget Warning"),
        )


def validate_po_budget(doc, method):
    """HARD block when PO linked to WBS exceeds budget."""
    if not doc.custom_wbs_element:
        return

    wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
    if not wbs.total_budget:
        return

    new_total_spent = (wbs.total_spent or 0) + (doc.grand_total or 0)
    new_pct = new_total_spent / wbs.total_budget * 100

    if new_pct > 100:
        frappe.throw(
            _("This Purchase Order ({0}) would cause WBS Element {1} to exceed its budget. "
              "Current spent: {2}, PO amount: {3}, Budget: {4}").format(
                frappe.format_value(doc.grand_total, {"fieldtype": "Currency"}),
                wbs.name,
                frappe.format_value(wbs.total_spent, {"fieldtype": "Currency"}),
                frappe.format_value(doc.grand_total, {"fieldtype": "Currency"}),
                frappe.format_value(wbs.total_budget, {"fieldtype": "Currency"}),
            ),
            title=_("Budget Exceeded"),
        )
    elif new_pct > 80:
        frappe.msgprint(
            _("This PO will bring WBS {0} to {1}% utilization").format(
                wbs.name, f"{new_pct:.1f}"
            ),
            indicator="orange",
            title=_("Budget Warning"),
        )


def on_po_submit(doc, method):
    _update_wbs_spent(doc)


def on_pi_submit(doc, method):
    if not doc.custom_wbs_element:
        return
    try:
        wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
        wbs.refresh_spent_amounts()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WBS PI Submit Update Error")


# ---------------------------------------------------------------------------
# Whitelisted APIs
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_project_from_model(financial_model):
    fm = frappe.get_doc("Financial Model", financial_model)

    if fm.docstatus != 1:
        frappe.throw(_("Financial Model must be submitted first"))

    project = frappe.new_doc("Project")
    project.project_name = fm.model_name
    project.company = fm.company
    project.project_type = fm.project_type
    project.custom_financial_model = fm.name
    project.custom_total_budget = fm.total_project_budget
    project.custom_material_budget = fm.total_material_budget
    project.custom_service_budget = fm.total_service_budget
    project.status = "Open"
    project.insert(ignore_permissions=True)

    wbs_elements = frappe.get_all(
        "WBS Element",
        filters={"financial_model": fm.name},
        pluck="name",
    )
    for wbs_name in wbs_elements:
        frappe.db.set_value("WBS Element", wbs_name, "project", project.name)

    frappe.msgprint(
        _("Project {0} created successfully").format(project.name),
        indicator="green",
        alert=True,
    )
    return project.name


@frappe.whitelist()
def get_project_budget_dashboard(project):
    wbs_elements = frappe.get_all(
        "WBS Element",
        filters={"project": project, "status": ["!=", "Cancelled"]},
        fields=[
            "name", "wbs_name", "wbs_type", "status",
            "material_budget", "service_budget", "total_budget",
            "material_spent", "service_spent", "total_spent",
            "overall_utilization_pct",
        ],
        order_by="creation",
    )

    totals = {
        "total_budget": sum(w.total_budget or 0 for w in wbs_elements),
        "total_spent": sum(w.total_spent or 0 for w in wbs_elements),
        "material_budget": sum(w.material_budget or 0 for w in wbs_elements),
        "service_budget": sum(w.service_budget or 0 for w in wbs_elements),
        "material_spent": sum(w.material_spent or 0 for w in wbs_elements),
        "service_spent": sum(w.service_spent or 0 for w in wbs_elements),
    }

    if totals["total_budget"]:
        totals["utilization_pct"] = totals["total_spent"] / totals["total_budget"] * 100
    else:
        totals["utilization_pct"] = 0

    return {"wbs_elements": wbs_elements, "totals": totals}


@frappe.whitelist()
def recalculate_project_budget(project):
    wbs_elements = frappe.get_all(
        "WBS Element",
        filters={"project": project, "status": ["!=", "Cancelled"]},
        pluck="name",
    )
    for wbs_name in wbs_elements:
        wbs = frappe.get_doc("WBS Element", wbs_name)
        wbs.refresh_spent_amounts()

    frappe.msgprint(
        _("Budget recalculated for {0} WBS elements").format(len(wbs_elements)),
        indicator="green",
        alert=True,
    )


@frappe.whitelist()
def recalculate_all_wbs_budgets(wbs_element=None):
    if wbs_element:
        wbs = frappe.get_doc("WBS Element", wbs_element)
        wbs.refresh_spent_amounts()
    else:
        wbs_elements = frappe.get_all(
            "WBS Element", filters={"status": "Active"}, pluck="name",
        )
        for wbs_name in wbs_elements:
            wbs = frappe.get_doc("WBS Element", wbs_name)
            wbs.refresh_spent_amounts()


@frappe.whitelist()
def get_budget_utilization(project=None, wbs_element=None):
    filters = {"status": ["!=", "Cancelled"]}
    if project:
        filters["project"] = project
    if wbs_element:
        filters["name"] = wbs_element

    return frappe.get_all(
        "WBS Element",
        filters=filters,
        fields=[
            "name", "wbs_name", "wbs_type", "project", "status",
            "material_budget", "service_budget", "total_budget",
            "material_spent", "service_spent", "total_spent",
            "material_utilization_pct", "service_utilization_pct",
            "overall_utilization_pct",
        ],
        order_by="project, creation",
    )


@frappe.whitelist()
def get_project_financial_summary(project):
    wbs_data = frappe.get_all(
        "WBS Element",
        filters={"project": project, "status": ["!=", "Cancelled"]},
        fields=["sum(total_budget) as budget", "sum(total_spent) as spent"],
    )

    wbs_names = frappe.get_all(
        "WBS Element", filters={"project": project}, pluck="name"
    ) or [""]

    mr_count = frappe.db.count("Material Request", {
        "custom_wbs_element": ["in", wbs_names],
        "docstatus": ["<", 2],
    })

    po_data = frappe.db.sql("""
        SELECT COUNT(*) as count, COALESCE(SUM(grand_total), 0) as total
        FROM `tabPurchase Order`
        WHERE custom_wbs_element IN (
            SELECT name FROM `tabWBS Element` WHERE project = %s
        ) AND docstatus = 1
    """, project, as_dict=True)[0]

    return {
        "budget": (wbs_data[0].budget or 0) if wbs_data else 0,
        "spent": (wbs_data[0].spent or 0) if wbs_data else 0,
        "mr_count": mr_count,
        "po_count": po_data.count,
        "po_total": po_data.total,
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def send_budget_alerts():
    """Daily: send alerts for WBS elements above 80% utilization."""
    wbs_elements = frappe.get_all(
        "WBS Element",
        filters={"status": "Active", "overall_utilization_pct": [">=", 80]},
        fields=["name", "wbs_name", "project", "total_budget", "total_spent",
                 "overall_utilization_pct", "person_responsible"],
    )

    if not wbs_elements:
        return

    for wbs in wbs_elements:
        recipients = []
        if wbs.person_responsible:
            email = frappe.db.get_value("Employee", wbs.person_responsible, "user_id")
            if email:
                recipients.append(email)

        if wbs.project:
            pm_email = frappe.db.get_value("Project", wbs.project, "custom_project_approver")
            if pm_email:
                recipients.append(pm_email)

        if not recipients:
            recipients = [frappe.db.get_value("User", "Administrator", "email")]

        pct = wbs.overall_utilization_pct or 0
        subject = _("Budget Alert: {0} at {1}% utilization").format(wbs.wbs_name, f"{pct:.0f}")

        frappe.sendmail(
            recipients=list(set(recipients)),
            subject=subject,
            message=_(
                "WBS Element <b>{0}</b> ({1}) has reached <b>{2}%</b> budget utilization.<br>"
                "Budget: {3}<br>Spent: {4}<br>"
                "Please review and take necessary action."
            ).format(
                wbs.wbs_name, wbs.name, f"{pct:.1f}",
                frappe.format_value(wbs.total_budget, {"fieldtype": "Currency"}),
                frappe.format_value(wbs.total_spent, {"fieldtype": "Currency"}),
            ),
            now=True,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_wbs_spent(doc):
    if doc.custom_wbs_element:
        try:
            wbs = frappe.get_doc("WBS Element", doc.custom_wbs_element)
            wbs.refresh_spent_amounts()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WBS PO Submit Update Error")

    if doc.custom_sub_wbs_element:
        try:
            sub_wbs = frappe.get_doc("Sub WBS Element", doc.custom_sub_wbs_element)
            sub_wbs.refresh_spent_amounts()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Sub WBS PO Submit Update Error")
