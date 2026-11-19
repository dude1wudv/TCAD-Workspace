"""Offline safety tests for the one-shot campaign runner."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
VALIDATION = ROOT / 'local_runtime/dram-see-v4/interface-completion-r1/validation'
SOURCE = Path(__file__).with_name('campaign_runner.py')
SPEC = importlib.util.spec_from_file_location('_campaign_runner_under_test', SOURCE)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class CampaignRunnerTests(unittest.TestCase):
    def setUp(self):
        VALIDATION.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=VALIDATION)
        self.root = Path(self.temp.name) / 'workspace'
        self.state = self.root / 'local_runtime/dram-see-v4/interface-completion-r1'
        self.r5 = self.root / 'local_runtime/dram-see-v4/source-interface-r5'
        self.rt = self.root / 'local_runtime/dram-see-v4'
        self.here = self.root / 'experiments/dram-see-v4/interface-completion-r1'
        self.v4 = self.root / 'experiments/dram-see-v4'
        for p in (self.state, self.r5 / 'launches', self.here, self.rt, self.v4):
            p.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp.cleanup()

    def patch_run(self, campaign, executions=None, gates=()):
        execution_map = executions or {}
        for role in gates:
            (self.state / 'gates' / (role + '.json')).parent.mkdir(parents=True, exist_ok=True)
            (self.state / 'gates' / (role + '.json')).write_text('{}', encoding='utf-8')

        def fake_read(path):
            path = Path(path)
            if path == self.here / 'campaign.json':
                return campaign
            for label, record in execution_map.items():
                if path == self.r5 / 'launches' / label / 'execution.json':
                    return record
            return json.loads(path.read_text(encoding='utf-8'))

        controller = SimpleController()
        call_patch = patch.object(runner, 'call')
        patches = [
            patch.object(runner, 'ROOT', self.root),
            patch.object(runner, 'STATE', self.state),
            patch.object(runner, 'R5', self.r5),
            patch.object(runner, 'RT', self.rt),
            patch.object(runner, 'HERE', self.here),
            patch.object(runner, 'V4', self.v4),
            patch.object(runner, 'read', side_effect=fake_read),
            patch.object(runner, 'sha', return_value='campaign-sha'),
            patch.object(runner, 'module', return_value=controller),
            patch.object(runner, 'check_release'),
            patch.object(runner, 'update'),
            patch.object(runner, 'budget', return_value={'passed': True}),
            patch.object(runner, 'process_finished', return_value=True),
            call_patch,
            patch.object(runner.msvcrt, 'locking'),
        ]
        call_mock = None
        for p in patches:
            started = p.start()
            if p is call_patch:
                call_mock = started
        return patches, controller, call_mock, fake_read

    @staticmethod
    def stop_patches(patches):
        for p in reversed(patches):
            p.stop()

    def test_failed_runner_invocation_still_counts_toward_attempt_budget(self):
        launches = self.r5 / 'launches'
        for label, code, category in (('good', 0, 'primary'), ('failed', 3, 'reserve')):
            folder = launches / label
            folder.mkdir()
            (folder / 'execution.json').write_text(json.dumps({
                'label': label, 'runner_exit_code': code, 'budget_category': category,
            }), encoding='utf-8')
        campaign = {'roles': [{'role_id': 'a4-b1-main'}]}
        (self.here / 'campaign.json').write_text(json.dumps(campaign), encoding='utf-8')
        patches = [
            patch.object(runner, 'ROOT', self.root),
            patch.object(runner, 'STATE', self.state),
            patch.object(runner, 'R5', self.r5),
            patch.object(runner, 'HERE', self.here),
            patch.object(runner, 'CURRENT', {}),
        ]
        for p in patches:
            p.start()
        try:
            runner.update('TEST')
            state = json.loads((self.state / 'coordination.json').read_text(encoding='utf-8'))
            self.assertEqual(state['new_attempts'], 2)
            self.assertEqual(state['reserve_used'], 1)
        finally:
            self.stop_patches(patches)

    def test_budget_result_flows_to_reporter_and_updates_coordination(self):
        budget_result = {'passed': False, 'output_directory': 'budget/r2'}
        report_result = {'output_directory': 'reports/r2', 'publication_ready': False,
                         'report_errors': ['fixture budget threshold failed']}
        reporter = SimpleNamespace(generate=Mock(return_value=budget_result))
        report_maker = SimpleNamespace(generate=Mock(return_value=report_result))
        def choose_module(path, name):
            return reporter if Path(path).name == 'budget_report.py' else report_maker
        with patch.object(runner, 'HERE', self.here), patch.object(runner, 'module', side_effect=choose_module), \
             patch.object(runner, 'CURRENT', {'state':'TEST_STATE'}), patch.object(runner, 'update') as update:
            result = runner.budget()
        self.assertIs(result, budget_result)
        reporter.generate.assert_called_once_with()
        report_maker.generate.assert_called_once_with(budget_result)
        update.assert_called_once_with('TEST_STATE', latest_budget='budget/r2', latest_report='reports/r2',
            report_publication_ready=False, report_errors=['fixture budget threshold failed'])

    def test_adopted_completed_invocation_is_not_resubmitted(self):
        label = 'r5-a0-b1-main-r1'
        role = {'role_id': 'a0-b1-main', 'case_id': 'A0', 'stored_bit': 1, 'variant': 'main',
                'project': 'projects/a0-b1-main', 'requires': []}
        campaign = {'roles': [role]}
        execution = {'label': label, 'role_id': role['role_id'], 'campaign_sha256': 'campaign-sha',
                     'state': 'RUNNER_EXITED', 'runner_exit_code': 0}
        launch = self.r5 / 'launches' / label
        launch.mkdir(parents=True)
        (launch / 'execution.json').write_text(json.dumps(execution), encoding='utf-8')
        patches, controller, call, _ = self.patch_run(campaign, {label: execution}, gates=[role['role_id']])
        try:
            with patch.object(runner.a, 'validate_invocation') as validate:
                result = runner.run(adopt=label)
            self.assertEqual(result, 0)
            validate.assert_called_once_with(execution, role, label)
            runner.process_finished.assert_called_once_with(role, label)
            controller.check_gate.assert_called_once_with(role['role_id'])
            call.assert_not_called()
        finally:
            self.stop_patches(patches)

    def test_existing_postprocess_is_reused_without_resubmission(self):
        label = 'existing-a4'
        operation = self.rt / 'transport-probe/operations' / (label + '-fields')
        inputs = self.rt / 'transport-probe/inputs' / (label + '-fields')
        audit = self.rt / 'source-field-audit-r2/audit-dev' / label
        for p in (operation / 'collected', inputs, audit):
            p.mkdir(parents=True, exist_ok=True)
        (operation / 'operation.json').write_text(json.dumps({
            'state': 'COLLECTED_PENDING_AUDIT', 'ssh_exit_code': 0,
            'remote_exit_code': 0, 'collection_exit_code': 0,
        }), encoding='utf-8')
        (operation / 'field-extraction-record.json').write_text('{}', encoding='utf-8')
        (audit / 'audit.json').write_text('{}', encoding='utf-8')
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'V4', self.v4), patch.object(runner, 'call') as call:
            result = runner.postprocess(label, self.root / 'unused-run')
        self.assertEqual(result, audit / 'audit.json')
        call.assert_not_called()

    def test_verified_native_postprocess_failure_is_recorded_without_retry(self):
        label = 'known-postprocess-failure'
        operation = self.rt / 'transport-probe/operations' / (label + '-fields')
        operation.mkdir(parents=True)
        self.write_failed_operation(operation)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'a', fake_audit), patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'call') as call:
            result = runner.postprocess(label, self.root / 'unused-run')
        self.assertIsNone(result)
        failure = json.loads((self.state / 'postprocess-failures' / (label + '-fields.json')).read_text(encoding='utf-8'))
        self.assertFalse(failure['passed'])
        self.assertEqual(failure['remote_exit_code'], 42)
        call.assert_not_called()

    def test_verified_native_cleanup_failure_keeps_original_exit_and_does_not_retry(self):
        label = 'known-cleanup-failure'
        operation = self.make_cleanup_inputs(label)
        self.write_failed_operation(operation)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'V4', self.v4), patch.object(runner, 'a', fake_audit), \
             patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'module', return_value=self.cleanup_planner), patch.object(runner, 'call') as call:
            outcome = runner.cleanup_duplicates({'role_id': 'a4-b1-main'}, label)
        self.assertFalse(outcome['passed'])
        self.assertEqual(outcome['native_failure']['remote_exit_code'], 42)
        call.assert_not_called()

    def test_verified_fine_cost_failure_is_recorded_and_not_retried(self):
        label = 'known-fine-cost-failure'
        operation = self.rt / 'transport-probe/operations' / (label + '-cost')
        operation.mkdir(parents=True)
        self.write_failed_operation(operation)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'HERE', self.here), patch.object(runner, 'a', fake_audit), \
             patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'module', return_value=SimpleNamespace()), patch.object(runner, 'call') as call:
            outcome = runner.fine_cost(label, self.root / 'fine-a0-run')
        self.assertFalse(outcome['passed'])
        self.assertEqual(outcome['native_failure']['remote_exit_code'], 42)
        call.assert_not_called()

    def test_missing_fine_cost_gate_blocks_fine_dependents(self):
        role = {'role_id': 'a1-b1-fine', 'case_id': 'A1', 'stored_bit': 1, 'variant': 'fine',
                'project': 'projects/a1-b1-fine', 'requires': []}
        patches, controller, call, _ = self.patch_run({'roles': [role]})
        try:
            result = runner.run()
            self.assertEqual(result, 2)
            self.assertEqual(runner.update.call_args_list[-1].args[0],
                             'PRIMARY_PASS_COMPLETE_WITH_FAILURES_OR_DEPENDENCIES')
            updates = [call.kwargs for call in runner.update.call_args_list]
            self.assertTrue(any(row.get('blocked_dependencies') == ['fine-a0-cost-probe'] for row in updates))
            controller.check_gate.assert_not_called()
            call.assert_not_called()
        finally:
            self.stop_patches(patches)

    def make_cleanup_inputs(self, label, tamper=False, archive_mismatch=False, script_mismatch=False, task_mismatch=False):
        operation = self.rt / 'transport-probe/operations' / (label + '-cleanup')
        inputs = self.rt / 'transport-probe/inputs' / (label + '-cleanup')
        evidence = operation / 'collected/cleanup-evidence'
        evidence.mkdir(parents=True)
        inputs.mkdir(parents=True)
        (operation / 'collected').mkdir(exist_ok=True)
        name = 'gstep_0001_access_des.tdr'
        payload = b'original-mesh-frame'
        digest = hashlib.sha256(payload).hexdigest()
        approved_script = b'#!/bin/sh\n# approved cleanup fixture\nexit 0\n'
        actual_script = b'#!/bin/sh\necho changed\nexit 0\n' if script_mismatch else approved_script
        plan = {'plan_id': 'plan-1', 'remote_target': '/fixture/cleanup',
                'script_sha256': hashlib.sha256(approved_script).hexdigest(),
                'files': [{'name': name, 'sha256': digest, 'bytes': len(payload)}]}
        actual_task = runner.cleanup_task(plan).encode()
        if task_mismatch:
            actual_task += b'# tampered wrapper\n'
        input_members = {
            'plan.json': (json.dumps(plan) + '\n').encode(),
            'remote-cleanup.sh': actual_script,
            'task.sh': actual_task,
        }
        for filename, content in input_members.items():
            (inputs / filename).write_bytes(content)
            (operation / 'collected' / filename).write_bytes(content)
        adapter = self.v4 / 'transport-probe/operation.py'
        adapter.parent.mkdir(parents=True, exist_ok=True)
        adapter.write_bytes(b'# fixture adapter\n')
        wrapper = b'#!/bin/sh\nexec bash task.sh\n'
        (operation / 'run.sh').write_bytes(wrapper)
        (operation / 'collected/run.sh').write_bytes(wrapper)
        (evidence / 'exit-code.txt').write_text('0\n', encoding='utf-8')
        (evidence / 'status.txt').write_text('plan_id=plan-1\nexit_code=0\nautomatic_retry=false\n', encoding='utf-8')
        (evidence / 'disk-before.txt').write_text('Filesystem Used Available\nfixture 10 90\n', encoding='utf-8')
        (evidence / 'disk-after.txt').write_text('Filesystem Used Available\nfixture 9 91\n', encoding='utf-8')
        (evidence / 'allowlist.tsv').write_text('name\tsha256\tbytes\n'+name+'\t'+digest+'\t'+str(len(payload))+'\n', encoding='utf-8')
        action_digest = '0' * 64 if tamper else digest
        with (evidence / 'actions.tsv').open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['name','removed','sha256','source_sha256','bytes'], delimiter='\t')
            writer.writeheader()
            writer.writerow({'name':name,'removed':'0','sha256':action_digest,'source_sha256':digest,'bytes':len(payload)})
            writer.writerow({'name':name,'removed':'1','sha256':digest,'source_sha256':digest,'bytes':len(payload)})
        with (evidence / 'source-after.tsv').open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['name','expected_sha256','actual_sha256','unchanged'], delimiter='\t')
            writer.writeheader()
            writer.writerow({'name':name,'unchanged':'1','actual_sha256':digest,'expected_sha256':digest})
        with (evidence / 'verified-before.tsv').open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['name','duplicate_sha256','source_sha256','bytes'], delimiter='\t')
            writer.writeheader()
            writer.writerow({'name':name,'duplicate_sha256':digest,'source_sha256':digest,'bytes':len(payload)})
        archive = operation / 'results.tar'
        with tarfile.open(archive, 'w') as tar:
            for filename in input_members:
                tar.add(inputs / filename, arcname=filename)
            for filename in ('actions.tsv','source-after.tsv','verified-before.tsv','disk-before.txt','disk-after.txt','exit-code.txt','status.txt','allowlist.tsv'):
                tar.add(evidence / filename, arcname='cleanup-evidence/'+filename)
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if archive_mismatch:
            (evidence / 'actions.tsv').write_text('tampered after archive\n', encoding='utf-8')
        operation_record = {
            'state': 'COLLECTED_PENDING_AUDIT', 'ssh_exit_code': 0, 'remote_exit_code': 0,
            'collection_exit_code': 0, 'archive_sha256': archive_digest,
            'adapter_sha256': hashlib.sha256(adapter.read_bytes()).hexdigest(),
            'wrapper_sha256': hashlib.sha256(wrapper).hexdigest(),
            'input_sha256': {k: hashlib.sha256(v).hexdigest() for k,v in input_members.items()},
        }
        (operation / 'operation.json').write_text(json.dumps(operation_record), encoding='utf-8')
        self.cleanup_planner = FixtureCleanupPlanner(approved_script)
        return operation

    @staticmethod
    def write_failed_operation(operation, remote_exit=42):
        payload = f'{remote_exit}\n'.encode('ascii')
        archive = operation / 'results.tar'
        with tarfile.open(archive, 'w') as tar:
            info = tarfile.TarInfo('exit-code.txt'); info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        (operation / 'operation.json').write_text(json.dumps({
            'state': 'FAILED_COLLECTED', 'ssh_exit_code': remote_exit,
            'remote_exit_code': remote_exit, 'collection_exit_code': 0,
            'archive_sha256': archive_sha,
        }), encoding='utf-8')

    def test_cleanup_validates_each_duplicate_file_and_preserves_source(self):
        label = 'cleanup-one-file'
        self.make_cleanup_inputs(label)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'V4', self.v4), \
             patch.object(runner, 'a', fake_audit), patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'module', return_value=self.cleanup_planner):
            outcome = runner.cleanup_duplicates({'role_id': 'a4-b1-main'}, label)
        self.assertTrue(outcome['passed'])
        self.assertTrue(outcome['original_and_local_tdr_retained'])
        self.assertEqual(outcome['removed_duplicate_files'], 1)

    def test_cleanup_rejects_changed_per_file_action_digest(self):
        label = 'cleanup-tampered-file'
        self.make_cleanup_inputs(label, tamper=True)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'V4', self.v4), \
             patch.object(runner, 'a', fake_audit), patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'module', return_value=self.cleanup_planner):
            with self.assertRaisesRegex(ValueError, 'Cleanup action mismatch'):
                runner.cleanup_duplicates({'role_id': 'a4-b1-main'}, label)
        self.assertFalse((self.state / 'cleanup-outcomes' / (label + '-cleanup.json')).exists())

    def test_cleanup_rejects_unarchived_local_output_mutation(self):
        label = 'cleanup-archive-mismatch'
        self.make_cleanup_inputs(label, archive_mismatch=True)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'V4', self.v4), patch.object(runner, 'a', fake_audit), \
             patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'module', return_value=self.cleanup_planner):
            with self.assertRaisesRegex(ValueError, 'collected output differs from archive'):
                runner.cleanup_duplicates({'role_id': 'a4-b1-main'}, label)
        self.assertFalse((self.state / 'cleanup-outcomes' / (label + '-cleanup.json')).exists())

    def test_cleanup_rejects_script_different_from_approved_plan(self):
        label = 'cleanup-script-mismatch'
        self.make_cleanup_inputs(label, script_mismatch=True)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'V4', self.v4), patch.object(runner, 'a', fake_audit), \
             patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'module', return_value=self.cleanup_planner):
            with self.assertRaisesRegex(ValueError, 'script differs from approved generated plan'):
                runner.cleanup_duplicates({'role_id': 'a4-b1-main'}, label)

    def test_cleanup_rejects_task_wrapper_different_from_plan(self):
        label = 'cleanup-task-mismatch'
        self.make_cleanup_inputs(label, task_mismatch=True)
        fake_audit = SimpleAuditHelpers()
        with patch.object(runner, 'RT', self.rt), patch.object(runner, 'STATE', self.state), \
             patch.object(runner, 'V4', self.v4), patch.object(runner, 'a', fake_audit), \
             patch.object(runner, 'sha', lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch.object(runner, 'module', return_value=self.cleanup_planner):
            with self.assertRaisesRegex(ValueError, 'entry task differs from approved collection wrapper'):
                runner.cleanup_duplicates({'role_id': 'a4-b1-main'}, label)


class FixtureArchive:
    def __init__(self, path):
        self.tar = tarfile.open(path, 'r:*')
        self.members = {m.name: m for m in self.tar.getmembers() if m.isfile()}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.tar.close()

    def digest(self, name):
        member = self.members[name]
        digest = hashlib.sha256()
        with self.tar.extractfile(member) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()


class FixtureCleanupPlanner:
    Archive = FixtureArchive

    def __init__(self, approved_script):
        self.approved_script = approved_script

    def render_script(self, plan):
        return self.approved_script


class SimpleController:
    def __init__(self):
        self.check_gate = Mock()


class SimpleAuditHelpers:
    @staticmethod
    def reference(path, requires_pass=False):
        return {'path': str(path), 'sha256': 'fixture-sha', 'requires_pass': requires_pass}

    @staticmethod
    def save_new(path, data):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
