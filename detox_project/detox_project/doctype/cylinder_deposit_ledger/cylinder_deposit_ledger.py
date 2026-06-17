# ABP2-I419 Phase 6 (Sahil 2026-06-17, Out of BRD) — Cylinder Deposit
# Ledger (FR-33, RPT-09). Lightweight deposit tracking per serial No
# for refundable cylinder deposits.

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class CylinderDepositLedger(Document):

    def validate(self):
        if self.status == "Returned" and not self.return_date:
            self.return_date = frappe.utils.today()
        if self.status == "Outstanding" and self.return_date:
            # Tolerate a flip back to Outstanding by clearing the return date.
            self.return_date = None
        if flt(self.deposit_amount) <= 0:
            frappe.throw(_("Deposit Amount must be greater than zero."))


@frappe.whitelist()
def create_refund_journal_entry(ledger_name: str) -> str:
    """Create a JE crediting the Customer's deposit liability and
    debiting (refund). Returns the JE name."""
    if not frappe.db.exists("Cylinder Deposit Ledger", ledger_name):
        frappe.throw(_("Cylinder Deposit Ledger {0} not found.").format(ledger_name))
    led = frappe.get_doc("Cylinder Deposit Ledger", ledger_name)
    if led.status != "Returned":
        frappe.throw(_("Set status to Returned before raising a refund JE."))
    if led.refund_journal_entry:
        return led.refund_journal_entry

    # Best-effort default accounts. Site can override via the Company's
    # receivable/round-off accounts if a dedicated deposit liability
    # account isn't set up yet.
    company_doc = frappe.get_cached_doc("Company", led.company)
    debtors = company_doc.default_receivable_account
    deposit_account = (
        frappe.db.get_value(
            "Account",
            {"company": led.company, "account_name": ["like", "%Deposit%"]},
            "name",
        )
        or company_doc.default_payable_account
        or debtors
    )

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.posting_date = led.return_date or frappe.utils.today()
    je.company = led.company
    je.user_remark = f"Cylinder deposit refund — {led.name} (Serial {led.serial_no})"
    je.append("accounts", {
        "account": deposit_account,
        "debit_in_account_currency": flt(led.deposit_amount),
        "credit_in_account_currency": 0,
        "party_type": "Customer",
        "party": led.customer,
        "cost_center": led.cost_center,
        "project": led.project,
    })
    je.append("accounts", {
        "account": debtors,
        "debit_in_account_currency": 0,
        "credit_in_account_currency": flt(led.deposit_amount),
        "party_type": "Customer",
        "party": led.customer,
        "cost_center": led.cost_center,
        "project": led.project,
    })
    je.insert(ignore_permissions=True)
    led.db_set("refund_journal_entry", je.name, update_modified=False)
    return je.name


# --------------------------------------------------------------------------
# DN / SI on_submit hook — auto-create ledger entries for cylinder items
# --------------------------------------------------------------------------
def auto_create_deposit_entries(doc, method=None):
    """L21 — on Delivery Note / Sales Invoice submit, create a
    Cylinder Deposit Ledger entry for every serial on a cylinder Item
    that carries `custom_deposit_amount` (or `valuation_rate` as a
    fallback the FRD doesn't specify but is safe).

    Phase 6 keeps this conservative: we only fire when the Item has a
    Custom Field `custom_is_cylinder` = 1 to opt in. Sites without that
    flag get a no-op so the hook is safe to ship globally.
    """
    if doc.doctype not in ("Delivery Note", "Sales Invoice"):
        return
    for row in (doc.get("items") or []):
        if not row.serial_no:
            continue
        item_flags = frappe.db.get_value(
            "Item", row.item_code,
            ["custom_is_cylinder", "custom_deposit_amount"],
            as_dict=True,
        ) or {}
        if not item_flags.get("custom_is_cylinder"):
            continue
        deposit = flt(item_flags.get("custom_deposit_amount"))
        if deposit <= 0:
            continue
        for serial in (row.serial_no or "").splitlines():
            serial = serial.strip()
            if not serial:
                continue
            # One ledger entry per serial — skip if it already exists.
            if frappe.db.exists("Cylinder Deposit Ledger",
                                {"serial_no": serial}):
                continue
            try:
                led = frappe.get_doc({
                    "doctype": "Cylinder Deposit Ledger",
                    "customer": doc.customer,
                    "serial_no": serial,
                    "item_code": row.item_code,
                    "deposit_amount": deposit,
                    "issue_date": doc.posting_date,
                    "status": "Outstanding",
                    "delivery_note": doc.name if doc.doctype == "Delivery Note" else None,
                    "sales_invoice": doc.name if doc.doctype == "Sales Invoice" else None,
                    "company": doc.company,
                    "cost_center": doc.get("cost_center"),
                    "project": doc.project,
                })
                led.insert(ignore_permissions=True)
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Cylinder Deposit auto-create failed for {serial}",
                )
