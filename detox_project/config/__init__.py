from frappe import _

def get_data():
    return [
        {
            "label": _("Project Management"),
            "icon": "fa fa-project-diagram",
            "items": [
                {"type": "doctype", "name": "WBS Element", "label": _("WBS Element")},
                {"type": "doctype", "name": "Sub WBS Element", "label": _("Sub WBS Element")},
            ],
        },
        {
            "label": _("Reports"),
            "items": [
                {"type": "report", "name": "Budget Utilization", "is_query_report": True, "doctype": "WBS Element"},
                {"type": "report", "name": "Project Summary Report", "is_query_report": True, "doctype": "Project"},
                {"type": "report", "name": "WBS Procurement Summary", "is_query_report": True, "doctype": "WBS Element"},
            ],
        },
    ]
