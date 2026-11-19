"""Focused operation recovery fixtures. No SSH or native tool is executed."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / 'local_runtime/dram-see-v4/continuous/operation-migration'
spec = importlib.util.spec_from_file_location('operation_under_test', ROOT / 'experiments/dram-see-v4/transport-probe/operation.py')
op = importlib.util.module_from_spec(spec)
spec.loader.exec_module(op)
tcad = op.load_tcad()
CFG = {'remote_root': '/fixture/root', 'tool_bin': '/fixture/installation/bin'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class OperationRecoveryTests(unittest.TestCase):
    def setUp(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=OUTPUT, prefix='fixture-')
        self.runtime = Path(self.temp.name)
        self.patch_runtime = patch.object(op, 'RUNTIME', self.runtime)
        self.patch_runtime.start()
        self.label = 'fixture-original'
        self.folder = op.operation_folder(self.label)
        self.folder.mkdir(parents=True)
        script = b'# SOFTWARE_FIXTURE_NOT_NATIVE\n'
        task = b'# SOFTWARE_FIXTURE_NOT_NATIVE task\n'
        self.identity = dict(schema='tcad-process-identity-r1', run_id=self.label,
                             cwd=CFG['remote_root'] + '/dram-see-v4/transport-probe/operations/' + self.label,
                             pid=456, start_ticks=789, boot_id='12345678-1234-1234-1234-123456789abc',
                             script_sha256=digest(script))
        self.record = dict(schema=op.SCHEMA, label=self.label, state='EXECUTED', submission_phase='LAUNCH',
                           remote_directory=self.identity['cwd'], script_sha256=digest(script), wrapper_sha256=digest(script),
                           input_sha256={'task.sh': digest(task)}, process_identity=dict(self.identity),
                           ssh_exit_code=255, remote_exit_code=0, collection_exit_code=None,
                           collection_verified=False, capture_svisual_requested=False, tool_exit_codes={})
        self.files = {'run.sh': script, 'task.sh': task,
                      'process-identity.json': json.dumps(self.identity).encode(),
                      'exit-code.txt': b'0\n', 'operation-task-exit-code.txt': b'0\n',
                      'finished-utc.txt': b'2026-10-17T01:02:03Z\n',
                      'payload.txt': b'SOFTWARE_FIXTURE_NOT_NATIVE\n'}
        op.save_record(self.folder, self.record)
        self.transfer_commands = []

    def tearDown(self):
        self.patch_runtime.stop()
        self.assertTrue(self.runtime.resolve().is_relative_to(OUTPUT.resolve()))
        self.temp.cleanup()

    def observed(self, status='FINISHED'):
        return dict(directory=self.record['remote_directory'], status=status, alive=status == 'RUNNING',
                    remote_exit_code=self.record['remote_exit_code'] if status == 'FINISHED' else None,
                    identity=dict(self.identity))

    def make_archive(self):
        index = {name: dict(size=len(raw), sha256=digest(raw)) for name, raw in self.files.items()}
        contents = dict(self.files, **{'_collection-members.json': json.dumps(index, sort_keys=True).encode()})
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, raw in contents.items():
                member = tarfile.TarInfo(name)
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        self.raw = stream.getvalue()
        self.snapshot = dict(schema='tcad-original-snapshot-r1', sha256=digest(self.raw), bytes=len(self.raw), members=len(index))

    def remote(self, ssh, command, **kwargs):
        if 'TCAD_SNAPSHOT' in command:
            self.assertIn('flock -n 9', command)
            return subprocess.CompletedProcess([], 0, stdout=json.dumps(self.snapshot))
        self.transfer_commands.append(command)
        offset = int(re.search(r'tail -c \+(\d+)', command)[1]) - 1
        kwargs['stdout'].write(self.raw[offset:])
        return subprocess.CompletedProcess([], 0)

    def collect(self):
        with patch.object(tcad, 'remote_python', return_value=self.observed()), patch.object(tcad, 'remote', side_effect=self.remote):
            return op.collect_operation(tcad, CFG, ['NEVER_EXECUTED'], self.label)

    def test_repeated_label_only_locates_original(self):
        with patch.object(op, 'status_operation', return_value={'status': 'RUNNING'}) as status, \
                patch.object(op, 'assert_no_outstanding_operation') as admission, patch.object(op.subprocess, 'run') as launch:
            value = op._run_operation(tcad, CFG, [], self.label, Path('missing-inputs'), None, True)
        self.assertEqual(value['status'], 'RUNNING')
        status.assert_called_once()
        admission.assert_not_called()
        launch.assert_not_called()

    def test_running_job_cannot_be_collected(self):
        with patch.object(tcad, 'remote_python', return_value=self.observed('RUNNING')), patch.object(tcad, 'remote') as remote:
            with self.assertRaisesRegex(RuntimeError, 'completed original'):
                op.collect_operation(tcad, CFG, [], self.label)
        remote.assert_not_called()
        self.assertFalse((self.folder / 'results.tar').exists())

    def test_finished_without_identity_is_not_collectable(self):
        observed = self.observed()
        observed.pop('identity')
        with patch.object(tcad, 'remote_python', return_value=observed), patch.object(tcad, 'remote') as remote:
            with self.assertRaisesRegex(ValueError, 'process identity'):
                op.collect_operation(tcad, CFG, [], self.label)
        remote.assert_not_called()

    def test_boot_pid_start_and_script_cannot_change(self):
        for key, value in [('pid', 999), ('start_ticks', 999),
                           ('boot_id', 'aaaaaaaa-1234-1234-1234-123456789abc'), ('script_sha256', 'a' * 64)]:
            with self.subTest(key=key):
                observed = self.observed()
                observed['identity'][key] = value
                with patch.object(tcad, 'remote_python', return_value=observed):
                    with self.assertRaisesRegex(ValueError, 'identity'):
                        op.status_operation(tcad, CFG, [], self.label)

    def test_interrupted_transfer_resumes_original_bytes_and_preserves_ssh255(self):
        self.make_archive()
        def interrupted(ssh, command, **kwargs):
            if 'TCAD_SNAPSHOT' in command:
                return self.remote(ssh, command, **kwargs)
            kwargs['stdout'].write(self.raw[:1536])
            raise subprocess.CalledProcessError(255, ['MOCK_SSH'])
        with patch.object(tcad, 'remote_python', return_value=self.observed()), patch.object(tcad, 'remote', side_effect=interrupted):
            with self.assertRaises(subprocess.CalledProcessError):
                op.collect_operation(tcad, CFG, [], self.label)
        self.assertEqual((self.folder / 'results.partial.tar').stat().st_size, 1536)
        result = self.collect()
        self.assertEqual(result['state'], 'COLLECTED_PENDING_AUDIT')
        self.assertEqual(result['ssh_exit_code'], 255)
        self.assertEqual(result['collection_exit_code'], 0)
        self.assertTrue(result['collection_verified'])
        self.assertIn('tail -c +1537', self.transfer_commands[-1])
        record = json.loads((self.folder / 'operation.json').read_text())
        self.assertEqual([a['ssh_exit_code'] for a in record['collection_attempts']], [255, 0])
        self.assertEqual(op.sha(self.folder / 'results.tar'), self.snapshot['sha256'])
        self.assertEqual((self.folder / 'collected/payload.txt').read_bytes(), self.files['payload.txt'])

    def test_complete_collection_is_idempotent_and_does_not_overwrite(self):
        self.make_archive()
        self.collect()
        before = (self.folder / 'results.tar').stat().st_mtime_ns
        with patch.object(tcad, 'remote') as remote, patch.object(tcad, 'remote_python') as query:
            result = op.collect_operation(tcad, CFG, [], self.label)
        self.assertTrue(result['collection_verified'])
        self.assertEqual((self.folder / 'results.tar').stat().st_mtime_ns, before)
        remote.assert_not_called()
        query.assert_not_called()
        (self.folder / 'results.tar').write_bytes(b'preserve changed evidence')
        with self.assertRaisesRegex(ValueError, 'immutable archive changed'):
            op.collect_operation(tcad, CFG, [], self.label)
        self.assertEqual((self.folder / 'results.tar').read_bytes(), b'preserve changed evidence')

    def test_existing_different_archive_is_never_overwritten(self):
        self.make_archive()
        (self.folder / 'results.tar').write_bytes(b'older complete archive')
        with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
            self.collect()
        self.assertEqual((self.folder / 'results.tar').read_bytes(), b'older complete archive')
        self.assertEqual(self.transfer_commands, [])

    def test_interrupted_extraction_resumes_without_redownload(self):
        self.make_archive()
        original_replace = op.os.replace
        def interrupt_once(source, destination):
            if Path(source).name.startswith('extraction-fragment-') and Path(destination).name == 'payload.txt':
                raise OSError('MOCK_EXTRACTION_INTERRUPTED')
            return original_replace(source, destination)
        with patch.object(op.os, 'replace', side_effect=interrupt_once):
            with self.assertRaisesRegex(OSError, 'EXTRACTION_INTERRUPTED'):
                self.collect()
        self.assertFalse((self.folder / 'collected').exists())
        self.assertTrue(list(self.folder.glob('extraction-fragment-*.part')))
        previous_transfers = len(self.transfer_commands)
        result = self.collect()
        self.assertEqual(result['state'], 'COLLECTED_PENDING_AUDIT')
        self.assertEqual(len(self.transfer_commands), previous_transfers)
        self.assertTrue(list(self.folder.glob('extraction-fragment-*.part')))

    def test_input_mismatch_remains_rejected(self):
        self.files['task.sh'] = b'CHANGED'
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.collect()
        record = json.loads((self.folder / 'operation.json').read_text())
        self.assertFalse(record['collection_verified'])

    def test_false_success_remains_rejected(self):
        self.files['operation-task-exit-code.txt'] = b'9\n'
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.collect()
        record = json.loads((self.folder / 'operation.json').read_text())
        self.assertFalse(record['collection_verified'])

    def test_failed_native_exit_is_collected_as_failure(self):
        self.record['remote_exit_code'] = 7
        self.files['exit-code.txt'] = self.files['operation-task-exit-code.txt'] = b'7\n'
        op.save_record(self.folder, self.record)
        self.make_archive()
        result = self.collect()
        self.assertEqual(result['state'], 'FAILED_COLLECTED')
        self.assertEqual(result['remote_exit_code'], 7)
        self.assertEqual(result['operation_task_exit_code'], 7)
        self.assertTrue(result['collection_verified'])

    def test_legacy_schema_is_not_reinterpreted(self):
        self.record['schema'] = 'dram-see-v4-transport-operation-v1'
        self.record['state'] = 'REQUIRES_READ_ONLY_RECONCILIATION'
        op.save_record(self.folder, self.record)
        before = (self.folder / 'operation.json').read_bytes()
        with patch.object(tcad, 'remote_python') as query:
            value = op.status_operation(tcad, CFG, [], self.label)
            with self.assertRaisesRegex(ValueError, 'Historical operation'):
                op.collect_operation(tcad, CFG, [], self.label)
        self.assertTrue(value['historical_semantics'])
        self.assertEqual(value['ssh_exit_code'], 255)
        self.assertEqual((self.folder / 'operation.json').read_bytes(), before)
        query.assert_not_called()

    def test_owner_contention_blocks_connection_and_explicit_held_avoids_reentry(self):
        owner = MagicMock()
        owner.__enter__.side_effect = RuntimeError('ORIGINAL_OWNER_BUSY')
        with patch.object(op, 'load_tcad', return_value=tcad), patch.object(tcad, 'original_ownership', return_value=owner) as ownership, \
                patch.object(tcad, 'connection', return_value=(CFG, [], 'fixture')) as connection, \
                patch.object(op, '_run_operation', return_value={'status': 'RUNNING'}) as launch, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_OWNER_BUSY'):
                op.run('new-label', 'unused', detach=True)
            connection.assert_not_called()
            launch.assert_not_called()
            self.assertEqual(op.run('new-label', 'unused', detach=True, owner_held=True), 0)
            self.assertEqual(ownership.call_count, 1)
            launch.assert_called_once()

    def test_launch_once_without_budget_and_before_launch_disconnect(self):
        inputs = self.runtime / 'inputs'
        inputs.mkdir()
        (inputs / 'task.sh').write_bytes(b"# SOFTWARE_FIXTURE_NOT_NATIVE\n'/fixture/installation/bin/svisual' --threads 1\n")
        with patch.object(op, 'assert_no_outstanding_operation'), patch.object(tcad, 'remote') as remote, \
                patch.object(op.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255)) as launch, \
                patch.object(op, 'status_operation', return_value={'status': 'RUNNING'}):
            op._run_operation(tcad, CFG, ['MOCK_SSH'], 'new-launch', inputs, None, True)
            op._run_operation(tcad, CFG, ['MOCK_SSH'], 'new-launch', inputs, None, True)
        launch.assert_called_once()
        self.assertIn('mkdir .launch-claim', launch.call_args.args[0][-1])
        self.assertIn('nohup bash ./run.sh', launch.call_args.args[0][-1])
        record = json.loads((op.operation_folder('new-launch') / 'operation.json').read_text())
        self.assertEqual(record['ssh_exit_code'], 255)
        self.assertTrue(record['capture_svisual_requested'])
        self.assertNotIn('timeout_s', record)
        self.assertNotIn('approved', record)
        self.assertNotIn('budget', record)
        with patch.object(op, 'assert_no_outstanding_operation'), \
                patch.object(tcad, 'remote', side_effect=subprocess.CalledProcessError(255, ['MOCK_STAGE'])), \
                patch.object(op.subprocess, 'run') as no_launch:
            with self.assertRaises(subprocess.CalledProcessError):
                op._run_operation(tcad, CFG, [], 'stage-disconnect', inputs, None, True)
        no_launch.assert_not_called()
        self.assertEqual(op.status_operation(tcad, CFG, [], 'stage-disconnect')['status'], 'NOT_LAUNCHED')

    def test_wrapper_keeps_single_cpu_capture_and_original_raw_exits(self):
        script = op.render_wrapper(tcad, CFG, self.record['remote_directory'], self.label, True)
        self.assertLess(script.index('TCAD_IDENTITY'), script.index('flock -n 9'))
        for text in ('OMP_NUM_THREADS=1', 'taskset -pc "$cpu" $$', 'capture_observe svisual',
                     'capture_admit svisual svisual', 'operation-task-exit-code.txt', 'svisual-process-admission-exit-code.txt'):
            self.assertIn(text, script)
        self.assertNotIn('timeout ', script)
        self.assertNotIn('tee execution.log', script)

    def test_interrupted_staging_is_known_not_launched(self):
        self.record.update(state='PREPARED', submission_phase='REMOTE_STAGING')
        op.save_record(self.folder, self.record)
        with patch.object(tcad, 'remote_python') as query, patch.object(tcad, 'assert_no_active_run') as native_guard:
            value = op.status_operation(tcad, CFG, [], self.label)
            op.assert_no_outstanding_operation(tcad, CFG, [])
        self.assertEqual(value['status'], 'NOT_LAUNCHED')
        query.assert_not_called()
        native_guard.assert_called_once()

    def test_launch_uncertainty_blocks_a_new_label(self):
        self.record.update(state='LAUNCH_UNCERTAIN', submission_phase='LAUNCH')
        op.save_record(self.folder, self.record)
        with patch.object(op, 'status_operation', return_value={'status': 'START_UNCONFIRMED'}), \
                patch.object(tcad, 'assert_no_active_run') as native_guard:
            with self.assertRaisesRegex(RuntimeError, 'original outstanding operation'):
                op.assert_no_outstanding_operation(tcad, CFG, [])
        native_guard.assert_not_called()

    def test_detach_acknowledges_a_fast_success_without_changing_raw_exit(self):
        result = {'status': 'FINISHED', 'local_state': 'EXECUTED', 'remote_exit_code': 0, 'ssh_exit_code': 255}
        with patch.object(op, 'load_tcad', return_value=tcad), patch.object(tcad, 'connection', return_value=(CFG, [], 'fixture')), \
                patch.object(op, '_run_operation', return_value=result), redirect_stdout(io.StringIO()):
            self.assertEqual(op.run('fast-result', 'unused', detach=True, owner_held=True), 0)
        self.assertEqual(result['ssh_exit_code'], 255)

    def test_completed_status_preserves_receipt_hash(self):
        self.make_archive()
        self.collect()
        receipt_hash = op.sha(self.folder / 'operation.json')
        with patch.object(tcad, 'remote_python') as query:
            value = op.status_operation(tcad, CFG, [], self.label)
        self.assertEqual(value['status'], 'FINISHED')
        self.assertEqual(op.sha(self.folder / 'operation.json'), receipt_hash)
        query.assert_not_called()

    def test_missing_final_marker_does_not_write_success(self):
        self.files.pop('finished-utc.txt')
        self.make_archive()
        with self.assertRaises(FileNotFoundError):
            self.collect()
        receipt = json.loads((self.folder / 'operation.json').read_text())
        self.assertNotEqual(receipt['state'], 'COLLECTED_PENDING_AUDIT')
        self.assertFalse(receipt['collection_verified'])

    def test_archive_names_cannot_escape_or_alias(self):
        for name in ('../outside', '/absolute', 'C:drive', 'a\\b', 'a//b', 'a/./b', '.'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                op.safe_member_name(name)


if __name__ == '__main__':
    unittest.main()
