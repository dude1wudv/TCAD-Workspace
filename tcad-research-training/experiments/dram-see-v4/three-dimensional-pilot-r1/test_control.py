"""Offline safety properties; fixtures here are never experiment results."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pilot_test_control', HERE / 'control.py')
c = importlib.util.module_from_spec(spec); sys.modules[spec.name] = c; spec.loader.exec_module(c)


class BudgetSafety(unittest.TestCase):
    def test_empty_gate_evidence_cannot_release_a1(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)
            c.save(state/'gates/a0-b1-3d.json',dict(passed=True,role='a0-b1-3d',evidence=[],
                   campaign_sha256=c.sha(HERE/'campaign.json')),new=True)
            with patch.object(c,'STATE',state),self.assertRaises(ValueError):
                c.pilot_gate('a0-b1-3d')

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


class NativeEvidenceSafety(unittest.TestCase):
    def setUp(self):
        self.a=c.module(HERE/'acceptance.py','pilot_acceptance_test')
        self.keys=['frozen_readonly_dependencies','solver_manifest','original_solver_provenance',
                   'frozen_3d_source_contract','complete_raw_curves','original_extraction_provenance',
                   'native_geometry_doping_probes','accepted_BE_Writing_PLT_bijection',
                   'native_3d_volume_field_gates','safe_original_archive_read']
        self.good=dict(schema='source-field-audit-3d-r1',mode='full',dimension=3,passed=True,
                       errors=[],checks={k:{'passed':True} for k in self.keys},geometry_doping={'passed':True})

    def test_valid_metadata_is_not_rejected_as_boolean_format(self):
        self.a.validate_field_metadata(self.good)

    def test_wrong_schema_despite_top_level_passed(self):
        self.good['schema']='WRONG_SCHEMA'
        with self.assertRaises(ValueError):self.a.validate_field_metadata(self.good)

    def test_internal_failure_despite_top_level_passed(self):
        self.good['checks']['native_3d_volume_field_gates']={'passed':False}
        with self.assertRaises(ValueError):self.a.validate_field_metadata(self.good)

    def test_errors_are_not_hidden_by_all_passed_flags(self):
        self.good['errors']=['missing original frame']
        with self.assertRaises(ValueError):self.a.validate_field_metadata(self.good)

    def test_missing_geometry_observations_are_not_zero(self):
        self.good.pop('geometry_doping')
        with self.assertRaises(ValueError):self.a.validate_field_metadata(self.good)


if __name__ == '__main__':
    unittest.main()
