import frappe
from frappe import _


def after_install():
    create_custom_fields()
    create_project_types()
    setup_workflows()
    setup_notifications()
    frappe.msgprint(_("Detox Project module installed successfully!"))


def after_migrate():
    create_custom_fields()
    create_project_types()


def create_custom_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    custom_fields = {
        # ═══════════════════════════════════════════════════════════════════
        # PROJECT — Classification, Budget, Revenue, Approval, Tender
        # ═══════════════════════════════════════════════════════════════════
        "Project": [
            # --- Classification ---
            dict(fieldname="custom_project_classification_section", fieldtype="Section Break",
                 label="Project Classification", insert_after="project_type",
                 collapsible=1),
            dict(fieldname="custom_project_classification", fieldtype="Select",
                 label="Classification",
                 options="\nInternal\nExternal\nJoint Venture",
                 insert_after="custom_project_classification_section"),
            dict(fieldname="custom_financial_model", fieldtype="Link",
                 label="Financial Model", options="Financial Model",
                 insert_after="custom_project_classification"),
            dict(fieldname="custom_column_break_class", fieldtype="Column Break",
                 insert_after="custom_financial_model"),
            dict(fieldname="custom_project_site", fieldtype="Data",
                 label="Project Site",
                 insert_after="custom_column_break_class"),
            dict(fieldname="custom_project_approver", fieldtype="Link",
                 label="Project Approver", options="User",
                 insert_after="custom_project_site"),

            # --- Budget Summary ---
            dict(fieldname="custom_budget_section", fieldtype="Section Break",
                 label="Budget Summary", insert_after="custom_project_approver"),
            dict(fieldname="custom_material_budget", fieldtype="Currency",
                 label="Material Budget",
                 insert_after="custom_budget_section", read_only=1),
            dict(fieldname="custom_service_budget", fieldtype="Currency",
                 label="Service Budget",
                 insert_after="custom_material_budget", read_only=1),
            dict(fieldname="custom_total_budget", fieldtype="Currency",
                 label="Total Budget",
                 insert_after="custom_service_budget", read_only=1, bold=1),
            dict(fieldname="custom_column_break_budget", fieldtype="Column Break",
                 insert_after="custom_total_budget"),
            dict(fieldname="custom_material_spent", fieldtype="Currency",
                 label="Material Spent",
                 insert_after="custom_column_break_budget", read_only=1),
            dict(fieldname="custom_service_spent", fieldtype="Currency",
                 label="Service Spent",
                 insert_after="custom_material_spent", read_only=1),
            dict(fieldname="custom_total_spent", fieldtype="Currency",
                 label="Total Spent",
                 insert_after="custom_service_spent", read_only=1, bold=1),
            dict(fieldname="custom_column_break_budget2", fieldtype="Column Break",
                 insert_after="custom_total_spent"),
            dict(fieldname="custom_budget_utilization_pct", fieldtype="Percent",
                 label="Budget Utilization %",
                 insert_after="custom_column_break_budget2", read_only=1, bold=1),
            dict(fieldname="custom_budget_remaining", fieldtype="Currency",
                 label="Budget Remaining",
                 insert_after="custom_budget_utilization_pct", read_only=1),

            # --- Revenue Tracking ---
            dict(fieldname="custom_revenue_section", fieldtype="Section Break",
                 label="Revenue Tracking", insert_after="custom_budget_remaining",
                 collapsible=1),
            dict(fieldname="custom_total_revenue", fieldtype="Currency",
                 label="Total Revenue",
                 insert_after="custom_revenue_section"),
            dict(fieldname="custom_total_invoiced", fieldtype="Currency",
                 label="Total Invoiced",
                 insert_after="custom_total_revenue", read_only=1),
            dict(fieldname="custom_column_break_revenue", fieldtype="Column Break",
                 insert_after="custom_total_invoiced"),
            dict(fieldname="custom_total_collected", fieldtype="Currency",
                 label="Total Collected",
                 insert_after="custom_column_break_revenue", read_only=1),
            dict(fieldname="custom_outstanding_amount", fieldtype="Currency",
                 label="Outstanding Amount",
                 insert_after="custom_total_collected", read_only=1),

            # --- Carbon Credits ---
            dict(fieldname="custom_carbon_section", fieldtype="Section Break",
                 label="Carbon Credits", insert_after="custom_outstanding_amount",
                 collapsible=1),
            dict(fieldname="custom_carbon_credits_earned", fieldtype="Float",
                 label="Carbon Credits Earned",
                 insert_after="custom_carbon_section"),
            dict(fieldname="custom_carbon_credits_value", fieldtype="Currency",
                 label="Carbon Credits Value",
                 insert_after="custom_carbon_credits_earned"),

            # --- Tender Details ---
            dict(fieldname="custom_tender_section", fieldtype="Section Break",
                 label="Tender Details", insert_after="custom_carbon_credits_value",
                 collapsible=1),
            dict(fieldname="custom_tender", fieldtype="Data",
                 label="Tender Reference",
                 insert_after="custom_tender_section"),
            dict(fieldname="custom_tender_name", fieldtype="Data",
                 label="Tender Name",
                 insert_after="custom_tender", read_only=1),
            dict(fieldname="custom_column_break_tender", fieldtype="Column Break",
                 insert_after="custom_tender_name"),
            dict(fieldname="custom_client_name", fieldtype="Data",
                 label="Client Name",
                 insert_after="custom_column_break_tender"),
            dict(fieldname="custom_tender_value", fieldtype="Currency",
                 label="Tender Value",
                 insert_after="custom_client_name"),

            # --- Cancellation ---
            dict(fieldname="custom_cancellation_section", fieldtype="Section Break",
                 label="Cancellation Details", insert_after="custom_tender_value",
                 collapsible=1,
                 depends_on="eval:doc.status=='Cancelled'"),
            dict(fieldname="custom_cancellation_reason", fieldtype="Small Text",
                 label="Cancellation Reason",
                 insert_after="custom_cancellation_section"),
            dict(fieldname="custom_cancelled_by", fieldtype="Link",
                 label="Cancelled By", options="User",
                 insert_after="custom_cancellation_reason", read_only=1),
            dict(fieldname="custom_cancellation_date", fieldtype="Date",
                 label="Cancellation Date",
                 insert_after="custom_cancelled_by", read_only=1),
        ],

        # ═══════════════════════════════════════════════════════════════════
        # MATERIAL REQUEST — WBS Element + Project fields
        # ═══════════════════════════════════════════════════════════════════
        "Material Request": [
            dict(fieldname="custom_wbs_section", fieldtype="Section Break",
                 label="WBS / Project", insert_after="schedule_date"),
            dict(fieldname="custom_wbs_element", fieldtype="Link",
                 label="WBS Element", options="WBS Element",
                 insert_after="custom_wbs_section"),
            dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
                 label="Sub WBS Element", options="Sub WBS Element",
                 insert_after="custom_wbs_element"),
            dict(fieldname="custom_request_type", fieldtype="Select",
                 label="Request Type", options="\nMaterial\nService",
                 insert_after="custom_sub_wbs_element"),
            dict(fieldname="custom_column_break_wbs_mr", fieldtype="Column Break",
                 insert_after="custom_request_type"),
            dict(fieldname="custom_project_approver", fieldtype="Link",
                 label="Project Approver", options="User",
                 insert_after="custom_column_break_wbs_mr"),
            dict(fieldname="custom_project_site", fieldtype="Data",
                 label="Project Site",
                 insert_after="custom_project_approver"),
        ],

        # ═══════════════════════════════════════════════════════════════════
        # MATERIAL REQUEST ITEM — WBS at item level
        # ═══════════════════════════════════════════════════════════════════
        "Material Request Item": [
            dict(fieldname="custom_wbs_element", fieldtype="Link",
                 label="WBS Element", options="WBS Element",
                 insert_after="project"),
            dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
                 label="Sub WBS Element", options="Sub WBS Element",
                 insert_after="custom_wbs_element"),
        ],

        # ═══════════════════════════════════════════════════════════════════
        # PURCHASE ORDER — WBS fields
        # ═══════════════════════════════════════════════════════════════════
        "Purchase Order": [
            dict(fieldname="custom_wbs_section", fieldtype="Section Break",
                 label="WBS / Project", insert_after="project"),
            dict(fieldname="custom_wbs_element", fieldtype="Link",
                 label="WBS Element", options="WBS Element",
                 insert_after="custom_wbs_section"),
            dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
                 label="Sub WBS Element", options="Sub WBS Element",
                 insert_after="custom_wbs_element"),
            dict(fieldname="custom_po_type", fieldtype="Select",
                 label="PO Type", options="\nMaterial\nService",
                 insert_after="custom_sub_wbs_element"),
        ],

        # ═══════════════════════════════════════════════════════════════════
        # PURCHASE ORDER ITEM — WBS at item level
        # ═══════════════════════════════════════════════════════════════════
        "Purchase Order Item": [
            dict(fieldname="custom_wbs_element", fieldtype="Link",
                 label="WBS Element", options="WBS Element",
                 insert_after="project"),
            dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
                 label="Sub WBS Element", options="Sub WBS Element",
                 insert_after="custom_wbs_element"),
        ],

        # ═══════════════════════════════════════════════════════════════════
        # PURCHASE INVOICE — WBS fields
        # ═══════════════════════════════════════════════════════════════════
        "Purchase Invoice": [
            dict(fieldname="custom_wbs_section", fieldtype="Section Break",
                 label="WBS / Project", insert_after="project"),
            dict(fieldname="custom_wbs_element", fieldtype="Link",
                 label="WBS Element", options="WBS Element",
                 insert_after="custom_wbs_section"),
            dict(fieldname="custom_sub_wbs_element", fieldtype="Link",
                 label="Sub WBS Element", options="Sub WBS Element",
                 insert_after="custom_wbs_element"),
        ],
    }

    # ═══════════════════════════════════════════════════════════════════
    # TENDER MANAGEMENT — Conditional (only if doctype exists)
    # ═══════════════════════════════════════════════════════════════════
    if frappe.db.exists("DocType", "Tender Management"):
        custom_fields["Tender Management"] = [
            dict(fieldname="custom_linked_project", fieldtype="Link",
                 label="Linked Project", options="Project",
                 insert_after="status", read_only=1),
            dict(fieldname="custom_project_status", fieldtype="Data",
                 label="Project Status",
                 insert_after="custom_linked_project", read_only=1),
        ]

    create_custom_fields(custom_fields, update=True)


def create_project_types():
    """Create standard Project Types for Detox Group."""
    project_types = ["EPC", "O&M", "EPC + O&M", "Internal CAPEX", "Investment"]
    for pt in project_types:
        if not frappe.db.exists("Project Type", pt):
            frappe.get_doc({
                "doctype": "Project Type",
                "project_type": pt,
            }).insert(ignore_permissions=True)
    frappe.db.commit()


def setup_workflows():
    """Create Project Approval Workflow."""
    if frappe.db.exists("Workflow", "Project Approval Workflow"):
        return

    try:
        workflow = frappe.get_doc({
            "doctype": "Workflow",
            "workflow_name": "Project Approval Workflow",
            "document_type": "Project",
            "is_active": 1,
            "send_email_alert": 1,
            "states": [
                {"state": "Draft", "style": "Warning", "doc_status": "0", "allow_edit": "Projects User"},
                {"state": "Pending Approval", "style": "Primary", "doc_status": "0", "allow_edit": "Projects Manager"},
                {"state": "Approved", "style": "Success", "doc_status": "0", "allow_edit": "Projects Manager"},
                {"state": "Rejected", "style": "Danger", "doc_status": "0", "allow_edit": "Projects Manager"},
            ],
            "transitions": [
                {"state": "Draft", "action": "Submit for Approval", "next_state": "Pending Approval", "allowed": "Projects User"},
                {"state": "Pending Approval", "action": "Approve", "next_state": "Approved", "allowed": "Projects Manager"},
                {"state": "Pending Approval", "action": "Reject", "next_state": "Rejected", "allowed": "Projects Manager"},
                {"state": "Rejected", "action": "Resubmit", "next_state": "Pending Approval", "allowed": "Projects User"},
            ],
        })
        workflow.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Workflow Setup Error")


def setup_notifications():
    """Create Budget Threshold Alert notification."""
    if frappe.db.exists("Notification", "Budget Threshold Alert"):
        return

    try:
        notification = frappe.get_doc({
            "doctype": "Notification",
            "name": "Budget Threshold Alert",
            "subject": "Budget Alert: {{ doc.wbs_name }} at {{ doc.overall_utilization_pct }}% utilization",
            "document_type": "WBS Element",
            "event": "Value Change",
            "value_changed": "overall_utilization_pct",
            "condition": "doc.overall_utilization_pct >= 80",
            "channel": "Email",
            "message": """<p>WBS Element <b>{{ doc.wbs_name }}</b> ({{ doc.name }}) has reached
<b>{{ doc.overall_utilization_pct }}%</b> budget utilization.</p>
<p>Budget: {{ frappe.format_value(doc.total_budget, {'fieldtype': 'Currency'}) }}<br>
Spent: {{ frappe.format_value(doc.total_spent, {'fieldtype': 'Currency'}) }}</p>
<p>Please review and take necessary action.</p>""",
            "module": "Detox Project",
            "enabled": 1,
        })
        notification.append("recipients", {"receiver_by_role": "Projects Manager"})
        notification.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Notification Setup Error")
