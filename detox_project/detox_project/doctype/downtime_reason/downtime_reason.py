# CR-03.3 / CZ-35 — Downtime Reason master.
#
# Standardises the downtime reasons captured on Stock Entry (Manufacture)
# so stoppages are reportable by category (Downtime Analysis, CZ-36)
# instead of free text. `reason_name` is the naming field (autoname
# field:reason_name) so the master name IS the reason.

from __future__ import annotations

import frappe
from frappe.model.document import Document


class DowntimeReason(Document):
    pass
