"""Synthetic isolated r4 adapter tests; no runtime mutation or solver calls."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).with_name('continue.py')
spec = importlib.util.spec_from_file_location('r50_restart_r4_test_target', PATH)
M = importlib.util.module_from_spec(spec)
exec(compile(PATH.read_bytes(), str(PATH), 'exec'), M.__dict__)


def fixture():
    cases = M.CORE.original_cases()
    rows = {c['tag']: {'state': 'VERIFIED', 'runner_exit_code': 0, 'parameters': {}} for c in cases[:26]}
    for tag in M.ALIASES:
        rows[tag] = {'state': 'FAILED', 'runner_exit_code': None, 'parameters': {}}
    for original, alias in M.ORIGINAL_ALIASES.items():
        rows[alias] = {'state': 'VERIFIED', 'runner_exit_code': 0, 'parameters': {}, 'retry_of': original}
    return {'schema': 'synthetic-test-only', 'runs': rows, 'stages': {}, 'failures': []}


class Guards(unittest.TestCase):
    def test_three_failures_and_two_existing_retries_are_accepted(self):
        value = fixture()
        M.CORE.validate_ledger(value); M.require_existing_retries(value)
        pending = [M.CORE.actual_case(c)['tag'] for c in M.CORE.original_cases() if M.CORE.actual_case(c)['tag'] not in value['runs']]
        self.assertEqual(len(pending), 39)
        self.assertEqual(pending[0], M.NEW_RETRY)
        self.assertFalse(set(pending) & set(M.ORIGINAL_ALIASES.values()))

    def test_previous_retry_failure_cannot_be_ignored(self):
        value = fixture(); value['runs'][next(iter(M.ORIGINAL_ALIASES.values()))]['state'] = 'FAILED'
        with self.assertRaises(ValueError):
            M.require_existing_retries(value)
        with self.assertRaises(ValueError):
            M.CORE.validate_ledger(value)

    def test_any_original_failed_row_remains_protected(self):
        before = fixture()
        for tag in M.ALIASES:
            value = copy.deepcopy(before); value['runs'][tag]['charged_solver_s'] = 999
            with self.assertRaisesRegex(ValueError, 'row changed'):
                M.CORE.validate_ledger(value, before)

    def test_duplicate_new_retry_rejected(self):
        value = fixture()
        for tag in (M.NEW_RETRY, M.NEW_RETRY + '-again'):
            value['runs'][tag] = {'state': 'VERIFIED', 'runner_exit_code': 0, 'parameters': {}, 'retry_of': M.NEW_FAILED}
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            M.CORE.validate_ledger(value)

    def test_unknown_failure_or_skipping_new_retry_blocks(self):
        value = fixture(); unknown = M.CORE.original_cases()[26]['tag']
        value['runs'][unknown] = {'state': 'FAILED', 'runner_exit_code': None, 'parameters': {}}
        with self.assertRaisesRegex(ValueError, 'Unknown/failed'):
            M.CORE.validate_ledger(value)
        value['runs'][unknown]['state'] = 'VERIFIED'; value['runs'][unknown]['runner_exit_code'] = 0
        with self.assertRaisesRegex(ValueError, 'skipped'):
            M.CORE.validate_ledger(value, fixture())

    def test_three_generation_route_is_exact(self):
        routes = {'old': M.rel(M.CORE.OLD_PLAN), 'r3': M.rel(M.R3_PLAN)}
        self.assertEqual(M.route_plan('old', False, routes), M.CORE.OLD_PLAN)
        self.assertEqual(M.route_plan('r3', False, routes), M.R3_PLAN)
        self.assertEqual(M.route_plan('new', True, routes), M.RUNTIME / 'plan.json')
        with self.assertRaises(ValueError): M.route_plan('r3', True, routes)
        with self.assertRaises(ValueError): M.route_plan('unknown', False, routes)
        with self.assertRaises(ValueError): M.route_plan('bad', False, {'bad': 'unapproved/plan.json'})

    def test_real_case_checker_uses_selected_generation(self):
        case = M.CORE.original_cases()[18]
        routes = {case['tag']: M.rel(M.R3_PLAN)}
        with patch.object(M, 'prior_routes', return_value=routes), patch.object(M.F, 'case_checked', return_value='checked') as check:
            result = M.case_checked(case, {'state': 'VERIFIED'})
        self.assertEqual(result, 'checked')
        check.assert_called_once_with(M.R3_PLAN, case, {'state': 'VERIFIED'})

    def test_route_derivation_uses_frozen_membership(self):
        value = fixture(); cases = M.CORE.original_cases()
        original = {'runs': {c['tag']: {} for c in cases[:17]}}
        upstream = {'ledger_before': 'synthetic-ledger.json', 'dispatch_cases': [M.CORE.actual_case(c) for c in cases]}
        # The third failed original was canonical when r3 froze.
        upstream['dispatch_cases'][25] = cases[25]
        with patch.object(M, 'read', return_value=original):
            routes = M.prior_routes(value, upstream)
        self.assertEqual(routes[cases[0]['tag']], M.rel(M.CORE.OLD_PLAN))
        self.assertEqual(routes[M.NEW_FAILED], M.rel(M.R3_PLAN))
        for alias in M.ORIGINAL_ALIASES.values():
            self.assertEqual(routes[alias], M.rel(M.R3_PLAN))

    def test_existing_r3_aliases_are_never_submitted_again(self):
        ledger = fixture(); metric = {'deltaQ_fC': 1., 'deltaM_V': .001, 'classification': {}, 'sources': {}}
        for case in [c for c in M.CORE.original_cases() if c['tag'] in M.ORIGINAL_ALIASES]:
            with patch.object(M.C, 'load', return_value=ledger), patch.object(M.C, 'resolve', return_value='parent'), \
                    patch.object(M.R, 'matching'), patch.object(M.CORE, 'case_checked'), patch.object(M.F, 'submitted_after_freeze'), \
                    patch.object(M.R, 'bundle', return_value={'parameters': {}}), patch.object(M.R, 'recipe'), \
                    patch.object(M.R.M, 'compute_curves', return_value=metric), patch.object(M.R, 'immutable', return_value={}), \
                    patch.object(M.C, 'record') as record, patch.object(M.CORE, 'prepare_retry') as prepare:
                result = M.CORE.observe(case, {}, ledger)
            record.assert_not_called(); prepare.assert_not_called()
            self.assertEqual(result['actual_ledger_tag'], M.ORIGINAL_ALIASES[case['tag']])

    def test_new_retry_input_parameter_tamper_blocks(self):
        old = {'project.json': 'old', 'parameters.json': 'same', 'device.cmd': 'same', 'cell_msh.tdr': 'same'}
        new = {**old, 'project.json': 'new'}
        p = {'name': M.NEW_FAILED, 'steps': ['unchanged']}; q = {**p, 'name': M.NEW_RETRY}
        M.CORE.same_retry_inputs(old, new, p, q)
        new['parameters.json'] = 'modified'
        with self.assertRaisesRegex(ValueError, 'changes device'):
            M.CORE.same_retry_inputs(old, new, p, q)

    def test_exact64_result_preserves_three_original_failures(self):
        observations = [{'response_id': c['tag'], 'actual_ledger_tag': M.CORE.actual_case(c)['tag']} for c in M.CORE.original_cases()]
        with patch.object(M, 'sha', return_value='synthetic'), patch.object(M.CORE, 'raw_submission_index', return_value=[]):
            result = M.completed_result(observations, {})
            self.assertEqual(result['test_responses'], 64)
            self.assertEqual(result['test_independent_events'], 32)
            self.assertEqual(result['preserved_original_failures'], list(M.ALIASES))
            self.assertEqual(result['schema'], 'dram-see-v3-r50-main-restart-r4-test-result')
            with self.assertRaises(ValueError): M.completed_result(observations[:-1], {})
            wrong = copy.deepcopy(observations); wrong[25]['actual_ledger_tag'] = M.NEW_FAILED
            with self.assertRaises(ValueError): M.completed_result(wrong, {})

    def test_unchanged_scorer_counts64_synthetic_responses(self):
        cases = M.CORE.original_cases()
        predictions = {'predictions': []}; observed = []
        for case in cases:
            row = {'event_label': case['event']['label'], 'stored_bit': case['kwargs']['bit']}
            predictions['predictions'].append({**row, 'predictions': {t: {'training_mean': 0., 'ridge': 0.} for t in M.F.P.TARGETS}})
            observed.append({**row, 'continuous_valid': True, 'targets': {t: 0. for t in M.F.P.TARGETS},
                             'response_id': case['tag'], 'actual_ledger_tag': M.CORE.actual_case(case)['tag']})
        result = M.F.P.score_predictions(predictions, observed, M.R.design())
        self.assertEqual(len(result['scores']), 16)
        self.assertTrue(all(r['valid_n'] == r['planned_n'] == 16 and r['missing_n'] == 0 for r in result['scores']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
