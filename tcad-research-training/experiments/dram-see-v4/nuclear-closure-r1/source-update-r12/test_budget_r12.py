"""Isolated accounting regression tests; no production imports or ledger writes."""
import copy
import unittest
from budget_r12 import BudgetError, budget_view, count_tcad, require_capacity

LIMITS = {"tcad_total": 18, "tcad_primary": 14, "tcad_corrective": 4}


def counts(primary, corrective):
    return {"tcad_primary_calls": primary, "tcad_corrective_calls": corrective,
            "tcad_calls": primary + corrective}


class BudgetTests(unittest.TestCase):
    def test_last_primary_survives_prior_correction(self):
        # Old tcad_calls < 14 guard incorrectly rejects this legitimate role.
        result = require_capacity(counts(13, 1), LIMITS, corrective=False)
        self.assertEqual(result, counts(14, 1))

    def test_contract_boundaries_for_every_remaining_combination(self):
        for primary in range(15):
            for corrective in range(5):
                for adding_corrective in (False, True):
                    with self.subTest(primary=primary, corrective=corrective,
                                      adding_corrective=adding_corrective):
                        allowed = (primary + corrective < 18 and
                                   (corrective < 4 if adding_corrective else primary < 14))
                        if allowed:
                            require_capacity(counts(primary, corrective), LIMITS,
                                             corrective=adding_corrective)
                        else:
                            with self.assertRaises(BudgetError):
                                require_capacity(counts(primary, corrective), LIMITS,
                                                 corrective=adding_corrective)

    def test_unknown_failed_reserved_attempts_are_charged(self):
        rows = [{"label": "old-zero", "kind": "tcad", "corrective": False,
                 "state": "FAILED", "exit_code": 1},
                {"label": "repair", "kind": "tcad", "corrective": True,
                 "state": "RESERVED", "exit_code": None},
                {"label": "engineer", "kind": "compile", "state": "EXECUTED"}]
        self.assertEqual(count_tcad(rows), counts(1, 1))

    def test_duplicate_identity_rejected(self):
        row = {"label": "one", "kind": "tcad"}
        with self.assertRaises(BudgetError):
            count_tcad([row, dict(row)])

    def test_inconsistent_or_ambiguous_data_rejected(self):
        for bad in ({**counts(1, 1), "tcad_calls": 1},
                    {**counts(1, 1), "tcad_calls": True},
                    counts(-1, 1)):
            with self.assertRaises(BudgetError):
                require_capacity(bad, LIMITS, corrective=False)
        with self.assertRaises(BudgetError):
            count_tcad([{"label": "x", "kind": "tcad", "corrective": "false"}])

    def test_view_preserves_original_and_limits(self):
        original = {"schema": "original", "limits": dict(LIMITS),
                    "tcad_calls": 2, "tcad_corrective_calls": 1,
                    "old_budget": {"including_history": 21}}
        before = copy.deepcopy(original)
        rows = [{"label": "zero", "kind": "tcad"},
                {"label": "trace", "kind": "tcad", "corrective": True}]
        result = budget_view(original, rows)
        self.assertEqual(original, before)
        self.assertEqual(result["tcad_primary_calls"], 1)
        self.assertEqual(result["limits"], LIMITS)
        self.assertEqual(result["old_budget"], before["old_budget"])
        self.assertTrue(result["derived_only"])
        with self.assertRaises(BudgetError):
            budget_view({**original, "tcad_calls": 1}, rows)


if __name__ == "__main__":
    unittest.main()
