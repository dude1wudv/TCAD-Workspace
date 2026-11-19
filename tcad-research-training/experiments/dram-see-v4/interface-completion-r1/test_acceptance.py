"""Focused failure-safety tests for acceptance publication ordering."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
VALIDATION = ROOT / 'local_runtime/dram-see-v4/interface-completion-r1/validation'
SOURCE = Path(__file__).with_name('acceptance.py')
SPEC = importlib.util.spec_from_file_location('_acceptance_under_test', SOURCE)
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class FakeAuditAPI:
    def __init__(self):
        self.bundle = {
            'parameters': {'case_id': 'A0', 'stored_bit': 1, 'variant': 'main'},
            'summary': {
                'passed': True,
                'radiation': {'generated_fC': 0, 'source_free': True},
            },
        }

    @staticmethod
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def load(self, run, project, field=None):
        return self.bundle

    @staticmethod
    def accepted(summary):
        if summary.get('passed') is not True:
            raise ValueError('Audit did not pass')

    @staticmethod
    def builder():
        return SimpleNamespace(check_project=lambda project: {'manifest_sha256': 'input-proof'})

    @staticmethod
    def write(output, bundle):
        output.mkdir(parents=True, exist_ok=False)
        (output / 'audit.json').write_text('{}\n', encoding='utf-8')


class AcceptancePublicationTests(unittest.TestCase):
    def setUp(self):
        VALIDATION.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=VALIDATION)
        self.root = Path(self.tmp.name) / 'workspace'
        self.state = self.root / 'local_runtime/dram-see-v4/interface-completion-r1'
        self.r5 = self.root / 'local_runtime/dram-see-v4/source-interface-r5'
        self.here = self.root / 'experiments/dram-see-v4/interface-completion-r1'
        self.state.joinpath('gates').mkdir(parents=True)
        self.r5.joinpath('launches/r5-a0-b1-main-r1').mkdir(parents=True)
        self.api = FakeAuditAPI()
        self.events = []
        self.request = {
            'role_id': 'a0-b1-main', 'case_id': 'A0', 'stored_bit': 1,
            'variant': 'main', 'project': 'projects/a0-b1-main', 'comparison_mode': None,
            'requires': ['reuse-main-b1'],
        }
        self.execution = {
            'label': 'r5-a0-b1-main-r1',
            'role_id': 'a0-b1-main', 'campaign_sha256': 'campaign-sha',
            'identity': ['A0', 1, 'main'],
            'state': 'RUNNER_EXITED', 'runner_exit_code': 0, 'ssh_exit_code': 0,
            'runner_manifest_state': 'COLLECTED', 'manifest_input_matches_project': True,
            'run_id': 'synthetic-run', 'project': 'projects/a0-b1-main',
            'offline_input_check': {'manifest_sha256': 'input-proof'},
            'source_input_sha256': {'source.dat': 'campaign-sha'},
            'dependency_gates': [{'path': 'gate.json', 'sha256': 'old-gate', 'role_id': 'reuse-main-b1'}],
        }
        project = self.root / self.request['project']
        project.mkdir(parents=True)
        (project / 'source.dat').write_text('synthetic source\n', encoding='utf-8')

        def fake_read(path):
            path = Path(path)
            if path == self.here / 'campaign.json':
                return {'roles': [self.request]}
            if path == self.r5 / 'launches/r5-a0-b1-main-r1/execution.json':
                return self.execution
            if path == self.state / 'evidence-registry.json':
                return {'schema': 'test', 'runs': {}}
            return json.loads(path.read_text(encoding='utf-8'))

        self.read_patch = patch.object(acceptance, 'read', side_effect=fake_read)
        self.patches = [
            patch.object(acceptance, 'ROOT', self.root),
            patch.object(acceptance, 'STATE', self.state),
            patch.object(acceptance, 'R5', self.r5),
            patch.object(acceptance, 'HERE', self.here),
            patch.object(acceptance, 'REGISTRY', self.state / 'evidence-registry.json'),
            patch.object(acceptance, 'api', return_value=self.api),
            patch.object(acceptance, 'sha', return_value='campaign-sha'),
            patch.object(acceptance, 'validate_invocation', return_value=[]),
            patch.object(acceptance, 'read', side_effect=fake_read),
            patch.object(acceptance, 'registration', return_value={'role': ['A0', 1, 'main']}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def run_accept(self):
        return acceptance.accept('a0-b1-main', 'r5-a0-b1-main-r1')

    def outcome(self):
        path = self.state / 'outcomes/r5-a0-b1-main-r1.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def test_registry_failure_cannot_publish_gate_or_pass(self):
        def fail_registry(_):
            self.events.append('registry')
            raise OSError('injected registry write failure')

        with patch.object(acceptance, 'update_registry', side_effect=fail_registry) as update, \
             patch.object(acceptance, 'gate') as publish:
            result = self.run_accept()

        self.assertFalse(result['passed'])
        self.assertFalse(self.outcome()['passed'])
        self.assertIn('injected registry write failure', self.outcome()['errors'][0])
        update.assert_called_once()
        publish.assert_not_called()
        self.assertFalse((self.state / 'gates/a0-b1-main.json').exists())

    def test_gate_failure_cannot_return_pass(self):
        def update(_):
            self.events.append('registry')

        def fail_gate(*_args, **_kwargs):
            self.events.append('gate')
            raise OSError('injected gate publication failure')

        with patch.object(acceptance, 'update_registry', side_effect=update), \
             patch.object(acceptance, 'gate', side_effect=fail_gate):
            result = self.run_accept()

        self.assertEqual(self.events, ['registry', 'gate'])
        self.assertFalse(result['passed'])
        self.assertFalse(self.outcome()['passed'])
        self.assertFalse((self.state / 'gates/a0-b1-main.json').exists())

    def test_duplicate_role_is_rejected_without_overwriting_gate(self):
        gate = self.state / 'gates/a0-b1-main.json'
        gate.write_text('preserve-me\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate acceptance refused'):
            self.run_accept()
        self.assertEqual(gate.read_text(encoding='utf-8'), 'preserve-me\n')
        self.assertFalse((self.state / 'outcomes/r5-a0-b1-main-r1.json').exists())
        self.assertFalse((self.r5 / 'audits/r5-a0-b1-main-r1').exists())

    def test_success_publishes_registry_before_gate_and_outcome(self):
        def update(_):
            self.events.append('registry')

        def publish(role, evidence, extra=None):
            self.events.append('gate')
            path = self.state / 'gates' / (role + '.json')
            path.write_text(json.dumps({'passed': True, 'evidence': evidence, 'extra': extra}), encoding='utf-8')

        with patch.object(acceptance, 'update_registry', side_effect=update), \
             patch.object(acceptance, 'gate', side_effect=publish):
            result = self.run_accept()

        self.assertEqual(self.events, ['registry', 'gate'])
        self.assertTrue(result['passed'])
        self.assertTrue(self.outcome()['passed'])
        self.assertTrue((self.state / 'gates/a0-b1-main.json').is_file())


class InvocationBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=VALIDATION)
        self.root = Path(self.tmp.name) / 'workspace'
        self.here = self.root / 'experiments/dram-see-v4/interface-completion-r1'
        self.project = self.root / 'projects/a0-b1-main'
        self.project.mkdir(parents=True)
        (self.project / 'source.dat').write_text('synthetic source\n', encoding='utf-8')
        self.api = FakeAuditAPI()
        self.request = {
            'role_id': 'a0-b1-main', 'case_id': 'A0', 'stored_bit': 1,
            'variant': 'main', 'project': 'projects/a0-b1-main',
            'requires': ['reuse-main-b1'],
        }
        self.execution = {
            'label': 'r5-a0-b1-main-r1', 'role_id': 'a0-b1-main',
            'identity': ['A0', 1, 'main'], 'campaign_sha256': 'campaign-sha',
            'project': 'projects/a0-b1-main',
            'offline_input_check': {'manifest_sha256': 'input-proof'},
            'source_input_sha256': {'source.dat': 'campaign-sha'},
            'dependency_gates': [{'path': 'gate.json', 'sha256': 'old-gate', 'role_id': 'reuse-main-b1'}],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_dependency_gate_change_is_rejected(self):
        changed_gate = {'path': 'gate.json', 'sha256': 'new-gate', 'role_id': 'reuse-main-b1'}
        control = SimpleNamespace(check_gate=lambda role: changed_gate)
        with patch.object(acceptance, 'ROOT', self.root), \
             patch.object(acceptance, 'HERE', self.here), \
             patch.object(acceptance, 'api', return_value=self.api), \
             patch.object(acceptance, 'sha', return_value='campaign-sha'), \
             patch.object(acceptance, 'module', return_value=control):
            with self.assertRaisesRegex(ValueError, 'dependency gate changed or differs'):
                acceptance.validate_invocation(self.execution, self.request, 'r5-a0-b1-main-r1')

    def test_project_deviation_is_rejected_before_input_or_gate_checks(self):
        self.execution['project'] = 'projects/other'
        control = SimpleNamespace(check_gate=Mock())
        with patch.object(acceptance, 'ROOT', self.root), \
             patch.object(acceptance, 'HERE', self.here), \
             patch.object(acceptance, 'api', return_value=self.api), \
             patch.object(acceptance, 'sha', return_value='campaign-sha'), \
             patch.object(acceptance, 'module', return_value=control):
            with self.assertRaisesRegex(ValueError, 'Invocation project differs'):
                acceptance.validate_invocation(self.execution, self.request, 'r5-a0-b1-main-r1')
        control.check_gate.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
