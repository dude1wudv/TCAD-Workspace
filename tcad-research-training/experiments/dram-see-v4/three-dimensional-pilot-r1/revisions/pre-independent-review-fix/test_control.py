"""Offline safety properties; fixtures here are never experiment results."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pilot_test_control', HERE / 'control.py')
c = importlib.util.module_from_spec(spec); sys.modules[spec.name] = c; spec.loader.exec_module(c)


class BudgetSafety(unittest.TestCase):
    def test_first_calls_are_permitted(self):
        c.validate_budget([], 'tcad', 'a0-b1-3d')
        c.validate_budget([], 'geant', 'init-h')

    def test_old_budget_cannot_be_used_for_new_roles(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            c.validate_budget([], 'tcad', 'a5-b1-fine')

    def test_unknown_state_blocks_even_an_independent_request(self):
        for state in ['PREPARING', 'RUNNING', 'REQUIRES_ORIGINAL_STATE_RECONCILIATION']:
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'unresolved'):
                c.validate_budget([dict(state=state, kind='tcad')], 'geant', 'init-h')

    def test_known_failed_primary_is_not_silently_retried(self):
        records = [dict(state='KNOWN_FAILURE', kind='tcad', role='a0-b1-3d', category='primary')]
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            c.validate_budget(records, 'tcad', 'a0-b1-3d')

    def test_four_total_calls_include_failures(self):
        records = [dict(state='KNOWN_FAILURE', kind='tcad', role='a0-b1-3d', category='reserve') for _ in range(4)]
        with self.assertRaisesRegex(ValueError, 'cap'):
            c.validate_budget(records, 'tcad', 'a1-b1-3d')

    def test_geant_has_no_repair_allowance(self):
        with self.assertRaisesRegex(ValueError, 'new contract'):
            c.validate_budget([], 'geant', 'normal-h', 'reserve', {})

    def test_geant_zero_event_runs_still_consume_calls(self):
        records = [dict(state='COMPLETED', kind='geant', role='init-h', category='primary', primary_events=0) for _ in range(6)]
        with self.assertRaisesRegex(ValueError, 'cap'):
            c.validate_budget(records, 'geant', 'normal-e')

    def test_geant_event_cap_separate_from_call_cap(self):
        records = [dict(state='COMPLETED', kind='geant', role='normal-h', category='primary', primary_events=8)]
        with self.assertRaisesRegex(ValueError, 'event cap'):
            c.validate_budget(records, 'geant', 'normal-e')

    def test_wrong_category_rejected(self):
        with self.assertRaisesRegex(ValueError, 'category'):
            c.validate_budget([], 'tcad', 'a0-b1-3d', 'free')

    def test_two_same_cause_failures_stop_branch(self):
        repair = dict(role='a0-b1-3d', root_cause='syntax', repair_description='diagnosed',
                      same_root_cause_consecutive_failures=2)
        with self.assertRaisesRegex(ValueError, 'Repeated'):
            c.validate_budget([], 'tcad', 'a0-b1-3d', 'reserve', repair)

    def test_no_launch_before_release(self):
        with patch.object(c, 'module') as imported:
            # Strict release file check occurs before any legacy checker can run.
            with patch.object(c.Path, 'is_file', return_value=False):
                with self.assertRaisesRegex(ValueError, 'verified and frozen'):
                    c.check_release()
            imported.assert_not_called()


if __name__ == '__main__':
    unittest.main()
