"""Regression test for ABP2-I184 layer 5.

Pattern: a Financial Model gets submitted (children docstatus=1), then
cancelled (children → 2), then the parent docstatus is reset to 0 so
the workflow can drive it back into Draft/Approved without amending —
but the children remain at docstatus=2, so the form opens, the workflow
gate says "you can edit", and yet every child-table row is read-only
because Frappe treats cancelled rows as locked.

The `unlock_orphaned_fm_child_rows` after_migrate hook resets those
orphaned children to docstatus=0. This test pins the contract.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestFMOrphanCancelledRows(IntegrationTestCase):

	def test_after_migrate_resets_orphan_cancelled_rows(self):
		# Pick a real FM with revenue_items
		fm_name = frappe.db.get_value(
			"Financial Model",
			{"docstatus": 0},
			"name",
			order_by="modified desc",
		)
		if not fm_name:
			self.skipTest("No draft Financial Model on this site to test against.")

		# Find a child row to mark cancelled
		row_name = frappe.db.get_value(
			"FM Revenue Item",
			{"parent": fm_name, "parenttype": "Financial Model"},
			"name",
		)
		if not row_name:
			self.skipTest("FM has no FM Revenue Item rows — pick another seed.")

		original_ds = frappe.db.get_value("FM Revenue Item", row_name, "docstatus")

		try:
			# Force the row into the broken state.
			frappe.db.sql(
				"UPDATE `tabFM Revenue Item` SET docstatus=2 WHERE name=%s",
				(row_name,),
			)
			frappe.db.commit()

			self.assertEqual(
				frappe.db.get_value("FM Revenue Item", row_name, "docstatus"), 2,
				"setUp seed didn't take",
			)

			# Run the sweep
			from detox_project.setup import unlock_orphaned_fm_child_rows
			unlock_orphaned_fm_child_rows()

			# Row should now be back to draft
			self.assertEqual(
				frappe.db.get_value("FM Revenue Item", row_name, "docstatus"), 0,
				"Sweep did not reset cancelled child to docstatus=0; FM "
				"users will still see a locked form.",
			)
		finally:
			# Restore original state on whatever the previous value was
			# (don't leave the row in a state different from how we found it).
			frappe.db.sql(
				"UPDATE `tabFM Revenue Item` SET docstatus=%s WHERE name=%s",
				(original_ds, row_name),
			)
			frappe.db.commit()

	def test_sweep_skips_when_parent_is_submitted(self):
		"""If the parent is genuinely submitted (docstatus=1), children
		MUST stay cancelled. Don't ever resurrect rows on a real cancelled
		document — that would break the audit trail."""
		fm_name = frappe.db.get_value(
			"Financial Model",
			{"docstatus": 1},
			"name",
		)
		if not fm_name:
			# No submitted FM on this site — nothing to assert. Synthesize.
			from detox_project.setup import unlock_orphaned_fm_child_rows
			# Just ensure it doesn't raise.
			unlock_orphaned_fm_child_rows()
			return

		row_name = frappe.db.get_value(
			"FM Revenue Item",
			{"parent": fm_name},
			"name",
		)
		if not row_name:
			return
		original_ds = frappe.db.get_value("FM Revenue Item", row_name, "docstatus")

		try:
			frappe.db.sql(
				"UPDATE `tabFM Revenue Item` SET docstatus=2 WHERE name=%s",
				(row_name,),
			)
			frappe.db.commit()

			from detox_project.setup import unlock_orphaned_fm_child_rows
			unlock_orphaned_fm_child_rows()

			# Submitted-parent's child must NOT be reset.
			self.assertEqual(
				frappe.db.get_value("FM Revenue Item", row_name, "docstatus"), 2,
				"Sweep wrongly reset a child whose parent is submitted — "
				"this would corrupt audit trail of cancelled FMs.",
			)
		finally:
			frappe.db.sql(
				"UPDATE `tabFM Revenue Item` SET docstatus=%s WHERE name=%s",
				(original_ds, row_name),
			)
			frappe.db.commit()
