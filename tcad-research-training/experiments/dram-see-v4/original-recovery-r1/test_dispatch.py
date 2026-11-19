"""Offline recovery admission tests. Synthetic fixtures are not experiment results."""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REVIEW = ROOT / 'local_runtime/dram-see-v4/interface-completion-r1/recovery-dispatch-review-20261014'
sys.path.insert(0, str(HERE))
import dispatch as d
import pilot_control as p
import recovery_proof as proof


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
    return path


class DispatchAdmission(unittest.TestCase):
    def setUp(self):
        REVIEW.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='offline-test-', dir=REVIEW)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.campaign = copy.deepcopy(d.read(d.CAMPAIGN))
        self.campaign['historical_records'] = []
        self.previous = []
        for i in range(5):
            path = write(self.folder / f'historical-{i}.json', self.complete())
            self.previous.append(path)
            self.campaign['historical_records'].append(dict(path=d.ref(path), sha256=d.sha(path)))
        roles = [r['role_id'] for r in self.campaign['roles']
                 if r['role_id'] not in ('a1-b1-time', 'a6-b1-time')][:13]
        self.assertEqual(len(roles), 13)
        for i, role in enumerate(roles):
            self.previous.append(write(self.folder / f'new-{i}.json', self.complete(role)))
        self.previous.append(proof.EXECUTION_PATH)
        self.original_before = proof.EXECUTION_PATH.read_bytes()
        self.addCleanup(lambda: self.assertEqual(self.original_before, proof.EXECUTION_PATH.read_bytes()))

    def complete(self, role=None):
        return dict(state='RUNNER_EXITED', runner_exit_code=0, ssh_exit_code=0,
                    runner_manifest_state='COLLECTED', campaign_sha256=d.sha(d.CAMPAIGN),
                    budget_category='primary', role_id=role)

    def test_exact_original_uses_proof_and_remains_one_of_fourteen_attempts(self):
        with patch.object(proof, 'verify_execution', return_value={'recovered_engineering_evidence_passed': True}) as verify:
            new = d.validate_history(self.previous, self.campaign, 'a6-b1-time', 'primary')
        self.assertEqual(len(self.previous), 19)
        self.assertEqual(len(new), 14)
        self.assertEqual(sum(x['budget_category'] == 'reserve' for x in new), 0)
        original = next(x for x in new if x['role_id'] == 'a1-b1-time')
        self.assertEqual(original['state'], 'RUNNING')
        self.assertIsNone(original['runner_exit_code'])
        verify.assert_called_once_with(proof.EXECUTION_PATH, d.read(proof.EXECUTION_PATH))

    def test_original_role_still_cannot_be_repeated(self):
        with patch.object(proof, 'verify_execution'), self.assertRaisesRegex(ValueError, 'already attempted'):
            d.validate_history(self.previous, self.campaign, 'a1-b1-time', 'primary')

    def test_same_record_at_another_path_is_not_allowlisted(self):
        copied = write(self.folder / 'other/execution.json', d.read(proof.EXECUTION_PATH))
        self.assertFalse(proof.is_original_execution(copied))
        with patch.object(proof, 'verify_execution') as verify, self.assertRaisesRegex(ValueError, 'state unknown'):
            d.validate_history(self.previous[:-1] + [copied], self.campaign, 'a6-b1-time', 'primary')
        verify.assert_not_called()

    def test_second_unknown_blocks_even_with_authorized_original(self):
        unknown = self.complete('another-role')
        unknown.update(state='RUNNING', runner_exit_code=None)
        path = write(self.folder / 'unknown.json', unknown)
        with patch.object(proof, 'verify_execution'), self.assertRaisesRegex(ValueError, 'state unknown'):
            d.validate_history(self.previous + [path], self.campaign, 'a6-b1-time', 'primary')

    def test_invalid_original_proof_blocks_dispatch(self):
        with patch.object(proof, 'verify_execution', side_effect=ValueError('proof failed')):
            with self.assertRaisesRegex(ValueError, 'proof failed'):
                d.validate_history(self.previous, self.campaign, 'a6-b1-time', 'primary')

    def test_recovery_does_not_expand_cumulative_cap(self):
        self.campaign['maximum_global_attempts'] = 19
        with patch.object(proof, 'verify_execution') as verify, self.assertRaisesRegex(ValueError, 'Cumulative26'):
            d.validate_history(self.previous, self.campaign, 'a6-b1-time', 'primary')
        verify.assert_not_called()

    def test_recovery_does_not_expand_new_batch_cap(self):
        self.campaign['maximum_new_attempts'] = 14
        with patch.object(proof, 'verify_execution'), self.assertRaisesRegex(ValueError, 'Next-round21'):
            d.validate_history(self.previous, self.campaign, 'a6-b1-time', 'primary')

    def test_wrong_original_record_is_rejected_before_archive_verification(self):
        changed = d.read(proof.EXECUTION_PATH)
        changed['runner_exit_code'] = 0
        with patch.object(proof, 'verify') as verify, self.assertRaisesRegex(ValueError, 'record changed'):
            proof.verify_execution(proof.EXECUTION_PATH, changed)
        verify.assert_not_called()

    def test_wrong_path_is_rejected_before_original_record_verification(self):
        path = write(self.folder / 'forged/execution.json', d.read(proof.EXECUTION_PATH))
        with patch.object(proof, 'verify') as verify, self.assertRaisesRegex(ValueError, 'execution path'):
            proof.verify_execution(path, d.read(path))
        verify.assert_not_called()


class PilotAdmission(unittest.TestCase):
    def setUp(self):
        REVIEW.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='pilot-offline-test-', dir=REVIEW)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.rt = self.folder / 'runtime'
        self.old = self.rt / 'interface-completion-r1'
        self.status = self.old / 'coordination.json'
        write(self.status, dict(state='ALL_PRIMARY_ROLES_PASSED', scheduler_pid=12345))
        self.original = self.rt / 'source-interface-r5/launches' / proof.LABEL / 'execution.json'
        write(self.original, d.read(proof.EXECUTION_PATH))
        self.roles = [r['role_id'] for r in d.read(d.CAMPAIGN)['roles']]
        self.gates = SimpleNamespace(check_gate=Mock(side_effect=lambda role: dict(role_id=role)),
                                     unresolved_postprocessing=Mock(), known_solver_failure=Mock())
        self.old_runner = SimpleNamespace(pid_alive=Mock(return_value=False))
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(p, 'RT', self.rt))
        stack.enter_context(patch.object(p, 'OLD', self.old))
        stack.enter_context(patch.object(proof, 'EXECUTION_PATH', self.original))
        stack.enter_context(patch.object(p, 'module', side_effect=self.module))
        self.verify = stack.enter_context(patch.object(proof, 'verify_execution', return_value={} ))

    def module(self, path, name):
        if path.name == 'campaign_runner.py':
            return self.old_runner
        if path.name == 'control.py':
            return self.gates
        raise AssertionError('Unexpected module: ' + str(path))

    def test_original_exception_still_requires_all_seventeen_role_gates(self):
        result = p.old_queue_gate()
        self.assertEqual([x['role_id'] for x in result['gates']], self.roles)
        self.assertEqual(self.gates.check_gate.call_count, 17)
        self.gates.unresolved_postprocessing.assert_called_once_with()
        self.verify.assert_called_once_with(self.original, d.read(self.original))

    def test_one_missing_gate_blocks_pilot(self):
        def check(role):
            if role == 'a5-b1-fine':
                raise ValueError('Dependency gate missing: ' + role)
            return dict(role_id=role)
        self.gates.check_gate.side_effect = check
        with self.assertRaisesRegex(ValueError, 'Dependency gate missing'):
            p.old_queue_gate()
        self.verify.assert_not_called()

    def test_incomplete_old_queue_state_blocks_pilot(self):
        write(self.status, dict(state='STAGE_RUNNING', scheduler_pid=12345))
        with self.assertRaisesRegex(ValueError, 'not fully passed'):
            p.old_queue_gate()
        self.verify.assert_not_called()

    def test_live_old_scheduler_blocks_pilot(self):
        self.old_runner.pid_alive.return_value = True
        with self.assertRaisesRegex(ValueError, 'still alive'):
            p.old_queue_gate()
        self.verify.assert_not_called()

    def test_another_unknown_old_call_blocks_pilot(self):
        write(self.rt / 'source-interface-r5/launches/another-call/execution.json',
              dict(state='RUNNING', runner_exit_code=None))
        with self.assertRaisesRegex(ValueError, 'invocation unresolved'):
            p.old_queue_gate()

    def test_failed_recovery_proof_blocks_pilot(self):
        self.verify.side_effect = ValueError('recovery archive changed')
        with self.assertRaisesRegex(ValueError, 'recovery archive changed'):
            p.old_queue_gate()

    def test_unresolved_postprocessor_blocks_pilot(self):
        self.gates.unresolved_postprocessing.side_effect = ValueError('postprocessing unresolved')
        with self.assertRaisesRegex(ValueError, 'postprocessing unresolved'):
            p.old_queue_gate()
        self.verify.assert_not_called()


class StaticDerivativeBoundaries(unittest.TestCase):
    def test_frozen_source_versions(self):
        sources = {
            ROOT / 'experiments/dram-see-v4/interface-completion-r1/control.py':
                'ed02cb1b356d11f3bc25de93f3ab30d54ff7ca4b9d07cb271f46785993479baa',
            ROOT / 'experiments/dram-see-v4/three-dimensional-pilot-r1/control.py':
                'c58a893ddfa8fd9a92faa2ada1c1629219a88c1bd8f8a9f576424789b9b5db25',
            ROOT / 'experiments/dram-see-v4/three-dimensional-pilot-r1/campaign_runner.py':
                'e8bc599d54076983b6f9d43eb24ccfcfd1e3f07a324eca689ae151cb2a097366',
        }
        for path, expected in sources.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_pilot_budget_logic_matches_frozen_original_ast(self):
        import ast
        def function(path, name):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), include_attributes=False)
        for name in ('validate_budget', 'verify_history', 'pilot_gate', 'resource_check', 'lock'):
            self.assertEqual(function(HERE / 'pilot_control.py', name), function(p.HERE / 'control.py', name))

    def test_runner_frozen_business_functions_unchanged(self):
        import ast
        def functions(path):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            return {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(functions(HERE / 'pilot_runner.py'), functions(p.HERE / 'campaign_runner.py'))

    def test_release_requires_original_and_recovery_releases(self):
        original = SimpleNamespace(check_release=Mock(return_value=dict(path='frozen-release', sha256='original')))
        with patch.object(p, 'module', return_value=original) as loaded, patch.object(proof, 'check_release') as recovery:
            result = p.check_release()
        loaded.assert_called_once_with(p.HERE / 'control.py', '_recovery_original_pilot_release')
        original.check_release.assert_called_once_with()
        recovery.assert_called_once_with()
        self.assertEqual(result, dict(path='frozen-release', sha256='original'))

    def test_unreleased_recovery_blocks_pilot_release(self):
        original = SimpleNamespace(check_release=Mock(return_value={}))
        with patch.object(p, 'module', return_value=original), patch.object(proof, 'check_release', side_effect=ValueError('not released')):
            with self.assertRaisesRegex(ValueError, 'not released'):
                p.check_release()

    def test_unreleased_recovery_blocks_2d_before_project_or_launch(self):
        with patch.object(proof, 'check_release', side_effect=ValueError('not released')), patch.object(d.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'not released'):
                d.invoke(ROOT / 'unused', 'r5-unused')
        launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
