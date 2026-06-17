# ABP2-I419 Phase 1 (Sahil 2026-06-15, Out of BRD) — Production Plan
# Table 2 child row: an operation step with its raw-material / service
# usage on this plan. Flat structure (operation_name is the grouping
# Data field, not a nested DocType) — keeps report SQL + grid UX simple.
# See the FRD's Field Specifications + Process Logic tabs.

from frappe.model.document import Document


class DetoxProductionPlanOperation(Document):
    pass
