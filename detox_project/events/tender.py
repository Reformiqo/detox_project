import frappe
from frappe import _


def on_update(doc, method):
    if not frappe.db.exists("DocType", "Tender Management"):
        return

    status = doc.get("status") or doc.get("tender_status")
    if not status:
        return

    if status == "Awarded" and not doc.get("custom_linked_project"):
        _create_project_from_tender(doc)
    elif status in ("Lost", "Rejected"):
        _cancel_project_cascade(doc)
    elif status == "Closed":
        _complete_project(doc)


def before_cancel(doc, method):
    if not frappe.db.exists("DocType", "Tender Management"):
        return
    _cancel_project_cascade(doc)


def _create_project_from_tender(doc):
    project = frappe.new_doc("Project")
    project.project_name = doc.get("tender_name") or doc.get("name")
    project.company = doc.get("company")
    project.custom_tender = doc.name
    project.custom_tender_name = doc.get("tender_name") or doc.get("name")
    project.custom_project_classification = "External"
    project.status = "Open"

    if doc.get("expected_start_date"):
        project.expected_start_date = doc.expected_start_date
    if doc.get("expected_end_date"):
        project.expected_end_date = doc.expected_end_date
    if doc.get("project_type"):
        project.project_type = doc.project_type
    if doc.get("estimated_cost") or doc.get("tender_value"):
        project.estimated_costing = doc.get("estimated_cost") or doc.get("tender_value")
    if doc.get("client") or doc.get("customer"):
        project.custom_client_name = doc.get("client") or doc.get("customer")

    project.insert(ignore_permissions=True)

    frappe.db.set_value(doc.doctype, doc.name, {
        "custom_linked_project": project.name,
        "custom_project_status": "Open",
    }, update_modified=False)

    frappe.msgprint(
        _("Project {0} created from Tender {1}").format(project.name, doc.name),
        indicator="green",
        alert=True,
    )


def _cancel_project_cascade(doc):
    project_name = doc.get("custom_linked_project")
    if not project_name or not frappe.db.exists("Project", project_name):
        return

    for wbs_name in frappe.get_all(
        "WBS Element", filters={"project": project_name, "status": ["!=", "Cancelled"]}, pluck="name"
    ):
        frappe.db.set_value("WBS Element", wbs_name, "status", "Cancelled")

    for sub_name in frappe.get_all(
        "Sub WBS Element", filters={"project": project_name, "status": ["!=", "Cancelled"]}, pluck="name"
    ):
        frappe.db.set_value("Sub WBS Element", sub_name, "status", "Cancelled")

    fm_names = frappe.get_all(
        "WBS Element", filters={"project": project_name}, pluck="financial_model"
    )
    for fm_name in set(fm_names):
        if fm_name:
            fm = frappe.get_doc("Financial Model", fm_name)
            if fm.docstatus == 1:
                fm.cancel()

    frappe.db.set_value("Project", project_name, "status", "Cancelled")
    frappe.db.set_value(doc.doctype, doc.name, "custom_project_status", "Cancelled",
                        update_modified=False)

    frappe.msgprint(
        _("Project {0} and linked documents cancelled").format(project_name),
        indicator="red",
        alert=True,
    )


def _complete_project(doc):
    project_name = doc.get("custom_linked_project")
    if not project_name or not frappe.db.exists("Project", project_name):
        return

    frappe.db.set_value("Project", project_name, "status", "Completed")

    for wbs_name in frappe.get_all(
        "WBS Element", filters={"project": project_name, "status": "Active"}, pluck="name"
    ):
        frappe.db.set_value("WBS Element", wbs_name, "status", "Completed")

    frappe.db.set_value(doc.doctype, doc.name, "custom_project_status", "Completed",
                        update_modified=False)


@frappe.whitelist()
def create_project_from_tender(tender):
    if not frappe.db.exists("DocType", "Tender Management"):
        frappe.throw(_("Tender Management doctype not found"))
    doc = frappe.get_doc("Tender Management", tender)
    _create_project_from_tender(doc)
    return doc.get("custom_linked_project")


@frappe.whitelist()
def cascade_cancel_project(tender):
    if not frappe.db.exists("DocType", "Tender Management"):
        frappe.throw(_("Tender Management doctype not found"))
    doc = frappe.get_doc("Tender Management", tender)
    _cancel_project_cascade(doc)
