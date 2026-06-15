"""ABP2-I455 — Purchase Order / MR / PI / PR must dedupe duplicate
WBS Allocation rows on validate.

Background (Sahil 2026-06-15):
PO-MAT-2026-00217 was built from 3 source MRs via "Get Items From".
Each MR had 1 WBS Allocation row. Frappe's get_mapped_doc auto-copy
appended every source row → PO ended up with 4 rows where 2 were
expected (WBS-004.1×2 and WBS-004.8×2). The spec: dedupe by
(wbs_element, sub_wbs_element) keeping the first occurrence; same
wbs_element with DIFFERENT sub_wbs_element is a valid multi-row case
and must survive.

These tests exercise the pure dedup function with a duck-typed doc —
no DB writes — so they run fast and don't depend on the bench having
WBS Elements seeded.
"""
import frappe
from frappe.tests import IntegrationTestCase


def _doc(rows):
	"""Build a duck-typed doc with a `custom_wbs_allocations` table."""
	rs = [frappe._dict({"idx": i + 1, **r}) for i, r in enumerate(rows)]
	doc = frappe._dict({"custom_wbs_allocations": rs})

	def _set(field, value):
		doc[field] = value
	doc.set = _set

	def _get(field, default=None):
		return doc.get(field, default)
	doc.get = _get

	return doc


class TestDedupeWBSAllocations(IntegrationTestCase):
	def test_collapses_full_duplicates(self):
		"""Same (wbs, sub_wbs) twice → collapses to one row."""
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.1"},
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.1"},
		])
		dedupe_wbs_allocations(doc)
		self.assertEqual(len(doc.custom_wbs_allocations), 1)
		self.assertEqual(doc.custom_wbs_allocations[0].wbs_element, "WBS-004.1")
		self.assertEqual(doc.custom_wbs_allocations[0].idx, 1)

	def test_preserves_distinct_sub_wbs_on_same_wbs(self):
		"""Same wbs but different sub_wbs → both rows survive (Sahil's
		'unless multiple valid allocations exist' clause)."""
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.1"},
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.2"},
		])
		dedupe_wbs_allocations(doc)
		self.assertEqual(len(doc.custom_wbs_allocations), 2)

	def test_real_world_po_pattern(self):
		"""PO-MAT-2026-00217's actual layout — 4 rows → 2 rows."""
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.1"},
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.1"},
			{"wbs_element": "WBS-004.8", "sub_wbs_element": None},
			{"wbs_element": "WBS-004.8", "sub_wbs_element": None},
		])
		dedupe_wbs_allocations(doc)
		keys = [(r.wbs_element, r.sub_wbs_element)
		        for r in doc.custom_wbs_allocations]
		self.assertEqual(
			keys,
			[("WBS-004.1", "SUB WBS-004.1.1"), ("WBS-004.8", None)],
		)
		# idx must be re-numbered from 1.
		self.assertEqual(
			[r.idx for r in doc.custom_wbs_allocations], [1, 2],
		)

	def test_none_vs_empty_string_treated_same(self):
		"""Null sub_wbs and empty-string sub_wbs are the same row."""
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([
			{"wbs_element": "WBS-004.8", "sub_wbs_element": None},
			{"wbs_element": "WBS-004.8", "sub_wbs_element": ""},
		])
		dedupe_wbs_allocations(doc)
		self.assertEqual(len(doc.custom_wbs_allocations), 1)

	def test_keeps_first_occurrence_of_dup(self):
		"""When deduping, the FIRST row wins — important so PR doesn't
		discard human-edited allocated_amount values that came in first."""
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.1",
			 "allocated_amount": 539520.0},
			{"wbs_element": "WBS-004.1", "sub_wbs_element": "SUB WBS-004.1.1",
			 "allocated_amount": 0.0},   # the auto-copy that overwrites with 0
		])
		dedupe_wbs_allocations(doc)
		self.assertEqual(len(doc.custom_wbs_allocations), 1)
		self.assertEqual(doc.custom_wbs_allocations[0].allocated_amount, 539520.0)

	def test_noop_when_no_rows(self):
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([])
		dedupe_wbs_allocations(doc)
		self.assertEqual(len(doc.custom_wbs_allocations), 0)

	def test_noop_when_already_unique(self):
		"""No duplicates → table reference must NOT be replaced (would
		needlessly mark doc dirty and break subsequent comparisons)."""
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([
			{"wbs_element": "WBS-A", "sub_wbs_element": None},
			{"wbs_element": "WBS-B", "sub_wbs_element": None},
		])
		original_rows = doc.custom_wbs_allocations
		dedupe_wbs_allocations(doc)
		# Same list object — dedupe should early-return on the
		# "len(deduped) == len(rows)" guard.
		self.assertIs(doc.custom_wbs_allocations, original_rows)

	def test_drops_extra_skeleton_empty_rows(self):
		"""Multiple empty (no wbs_element) skeleton rows collapse to one."""
		from detox_project.detox_project.api import dedupe_wbs_allocations

		doc = _doc([
			{"wbs_element": None, "sub_wbs_element": None},
			{"wbs_element": None, "sub_wbs_element": None},
			{"wbs_element": "WBS-A", "sub_wbs_element": None},
		])
		dedupe_wbs_allocations(doc)
		self.assertEqual(len(doc.custom_wbs_allocations), 2)
