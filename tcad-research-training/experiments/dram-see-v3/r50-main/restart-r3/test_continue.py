"""Synthetic isolated guard tests. Never freezes or submits a real TCAD case."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).with_name('continue.py')
spec = importlib.util.spec_from_file_location('r50_restart_r3_test_target', PATH)
M = importlib.util.module_from_spec(spec)
exec(compile(PATH.read_bytes(), str(PATH), 'exec'), M.__dict__)


def fixture():
    cases = M.original_cases()
    rows = {c['tag']: {'state': 'VERIFIED', 'runner_exit_code': 0, 'parameters': {}} for c in cases[:17]}
    for tag in M.ALIASES:
        rows[tag] = {'state': 'FAILED', 'runner_exit_code': None, 'parameters': {}}
    return {'schema': 'synthetic-test-only', 'runs': rows, 'stages': {}, 'failures': []}


class Guards(unittest.TestCase):
    def test_exact_two_failed_originals_accepted(self):
        value = fixture()
        self.assertIs(M.validate_ledger(value), value['runs'])

    def test_unknown_failure_blocks(self):
        value = fixture(); value['runs'][M.original_cases()[0]['tag']]['state'] = 'FAILED'
        with self.assertRaisesRegex(ValueError, 'Unknown/failed'):
            M.validate_ledger(value)

    def test_original_failed_must_not_be_promoted(self):
        value = fixture(); value['runs'][next(iter(M.ALIASES))]['state'] = 'VERIFIED'
        with self.assertRaisesRegex(ValueError, 'remain FAILED'):
            M.validate_ledger(value)

    def test_duplicate_retry_rejected(self):
        value = fixture(); canonical, alias = next(iter(M.ALIASES.items()))
        for tag in (alias, alias + '-again'):
            value['runs'][tag] = {'state': 'VERIFIED', 'runner_exit_code': 0, 'retry_of': canonical, 'parameters': {}}
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            M.validate_ledger(value)

    def test_retry_exact_identity_required(self):
        value = fixture(); alias = next(iter(M.ALIASES.values()))
        value['runs'][alias] = {'state': 'VERIFIED', 'runner_exit_code': 0, 'retry_of': 'wrong', 'parameters': {}}
        with self.assertRaisesRegex(ValueError, 'identity'):
            M.validate_ledger(value)

    def test_unknown_runner_exit_blocks(self):
        value = fixture(); value['runs'][M.original_cases()[0]['tag']]['runner_exit_code'] = None
        with self.assertRaisesRegex(ValueError, 'Unknown/failed'):
            M.validate_ledger(value)

    def test_retry_order_cannot_skip_first_gap(self):
        before = fixture(); value = copy.deepcopy(before)
        canonical, alias = list(M.ALIASES.items())[1]
        value['runs'][alias] = {'state': 'VERIFIED', 'runner_exit_code': 0, 'retry_of': canonical, 'parameters': {}}
        with self.assertRaisesRegex(ValueError, 'skipped'):
            M.validate_ledger(value, before)

    def test_old_failed_evidence_is_protected(self):
        before = fixture(); value = copy.deepcopy(before)
        value['runs'][next(iter(M.ALIASES))]['runner_exit_code'] = 0
        with self.assertRaisesRegex(ValueError, 'row changed'):
            M.validate_ledger(value, before)

    def test_input_equality_all_except_project_name(self):
        canonical, alias = next(iter(M.ALIASES.items()))
        old = {'device.cmd': 'a', 'parameters.json': 'b', 'source-event.json': 'c', 'project.json': 'old'}
        retry = {**old, 'project.json': 'new'}
        left = {'name': canonical, 'steps': [{'tool': 'sdevice'}]}; right = {**left, 'name': alias}
        M.same_retry_inputs(old, retry, left, right)
        for field in ('device.cmd', 'parameters.json', 'source-event.json'):
            changed = {**retry, field: 'tampered'}
            with self.assertRaisesRegex(ValueError, 'changes device'):
                M.same_retry_inputs(old, changed, left, right)
        right['steps'] = [{'tool': 'changed'}]
        with self.assertRaisesRegex(ValueError, 'project name'):
            M.same_retry_inputs(old, retry, left, right)

    def test_frozen_prediction_tamper_blocks(self):
        with patch.object(M, 'sha', return_value='changed'):
            with self.assertRaisesRegex(ValueError, 'prediction freeze bytes'):
                M.prediction()

    def test_unlimited_budget_copy_preserves_scientific_design(self):
        original = M.R.design(); prior = copy.deepcopy(original)
        with patch.object(M, 'authorization'), patch.object(M.R, 'design', return_value=original):
            adapted = M.runner_design()
        self.assertEqual(original, prior)
        self.assertEqual(adapted['gates'], prior['gates'])
        self.assertEqual(adapted['thresholds_mV'], prior['thresholds_mV'])
        self.assertEqual(adapted['execution']['solver_budget_s'], float('inf'))
        self.assertEqual(original['execution']['solver_budget_s'], 86400)

    def test_old_success_does_not_dispatch(self):
        case = M.original_cases()[0]; ledger = fixture()
        metric = {'deltaQ_fC': 1., 'deltaM_V': .001, 'classification': {}, 'sources': {}}
        with patch.object(M.C, 'load', return_value=ledger), patch.object(M.C, 'resolve', return_value='parent'), \
                patch.object(M.R, 'matching'), patch.object(M, 'case_checked'), patch.object(M.F, 'submitted_after_freeze'), \
                patch.object(M.R, 'bundle', return_value={'parameters': {}}), patch.object(M.R, 'recipe'), \
                patch.object(M.R.M, 'compute_curves', return_value=metric), patch.object(M.R, 'immutable', return_value={}), \
                patch.object(M.C, 'record') as record, patch.object(M.C, 'prepare') as prepare:
            result = M.observe(case, {}, ledger)
        record.assert_not_called(); prepare.assert_not_called()
        self.assertEqual(result['response_id'], case['tag'])
        self.assertEqual(result['actual_ledger_tag'], case['tag'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
