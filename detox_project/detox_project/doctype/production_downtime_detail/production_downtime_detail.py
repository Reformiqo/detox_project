# CR-03.2 / CZ-34 — Production Downtime Detail (child of Stock Entry).
#
# Reason-wise stoppage rows for a Manufacture batch. `duration` is
# computed client-side (CL-07) and re-computed server-side in
# cr03_downtime.validate_downtime (the authoritative pass). `category`
# is fetched from the Downtime Reason master; `cost_center` is inherited
# from the SE header.

from __future__ import annotations

import frappe
from frappe.model.document import Document


class ProductionDowntimeDetail(Document):
    pass
