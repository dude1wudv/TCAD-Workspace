"""Offline evidence and crash-recovery fixtures for the two runner entry points."""
import ast
from contextlib import chdir, contextmanager, redirect_stdout
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import tcad

operation = tcad.load_module(tcad.ROOT/'experiments/dram-see-v4/transport-probe/operation.py', '_seal_operation')


class SealTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.object(tcad, 'STATE_ROOT', self.root/'state'))
        self.enterContext(patch.object(operation, 'RUNTIME', self.root/'state/dram-see-v4/transport-probe'))
        self.cfg = dict(backend='ssh-runtime', ssh_target='offline-fixture', runtime_entry='/fixture/boundary',
                        remote_root='/fixture/control', tool_bin='/fixture/tools/bin')

    def original(self, kind):
        label = 'original'
        is_run = kind == 'run'
        folder = tcad.run_folder(label) if is_run else operation.operation_folder(label)
        remote_folder = self.root/kind
        folder.mkdir(parents=True)
        remote_folder.mkdir()
        directory = self.cfg['remote_root'] + ('/runs/' if is_run else '/dram-see-v4/transport-probe/operations/') + label
        (remote_folder/'run.sh').write_bytes(b'original wrapper')
        (folder/'run.sh').write_bytes(b'original wrapper')
        script_sha = tcad.file_hash(remote_folder/'run.sh')
        identity = dict(schema='tcad-process-identity-r1', run_id=label, cwd=directory, pid=1234, start_ticks=100,
                        boot_id='01234567-0123-0123-0123-0123456789ab', script_sha256=script_sha)
        policy = tcad.parallel_policy(self.cfg, 0, label, directory, kind)
        (remote_folder/'process-identity.json').write_text(json.dumps(identity))
        (remote_folder/'exit-code.txt').write_text('0')
        (remote_folder/'finished-utc.txt').write_text(tcad.utc())
        (remote_folder/'parallel-slot-evidence.json').write_text(json.dumps(dict(
            policy=policy, script_sha256=script_sha, identity=identity, gate_mode='SHARED', slot_mode='EXCLUSIVE',
            gate_fd=9, slot_fd=7)))
        (remote_folder/'parallel-slot-collection-evidence.json').write_text(json.dumps(dict(
            policy=policy, script_sha256=script_sha, identity=identity, gate_mode='SHARED', slot_mode='EXCLUSIVE',
            lease_state='ACTIVE', status='COLLECTION_LOCKS_ACQUIRED')))
        raw_exit = 'metadata-sdevice-version-exit-code.txt' if is_run else 'operation-task-exit-code.txt'
        (remote_folder/raw_exit).write_text('0')
        record = dict(schema='tcad-native-run-r2' if is_run else operation.SCHEMA,
                      state='RUNNING', remote_directory=directory, connection_identity=tcad.connection_identity(self.cfg),
                      input_sha256={}, parallel_policy=policy, script_sha256=script_sha, collection_verified=False,
                      origin='native_pipeline', synthetic=False, runner_sha256='a'*64,
                      ssh_exit_code=255, remote_exit_code=None, collection_exit_code=None, tool_exit_codes={})
        if is_run:
            record.update(run_id=label, steps=[], tool_evidence={})
            tcad.save_manifest(folder, record)
            record_path = folder/'manifest.json'
        else:
            record.update(label=label, capture_svisual_requested=False, submission_phase='LAUNCH')
            operation.save_record(folder, record)
            record_path = folder/'operation.json'
        observation = dict(directory=directory, status='FINISHED', alive=False, remote_exit_code=0, identity=identity)
        return record_path, remote_folder, observation

    def snapshot(self, folder, command, reboot_proof=None):
        code = command.split("<<'TCAD_SNAPSHOT'\n", 1)[1].rsplit('\nTCAD_SNAPSHOT', 1)[0]
        namespace = {}
        if reboot_proof is not None:
            code = code.replace(tcad.INTERRUPTED_CHECK_CODE, '')
            namespace['interrupted_observation'] = reboot_proof
        if sys.platform == 'win32':
            code = code.replace("path.open('rb') as stream:os.fsync", "path.open('r+b') as stream:os.fsync")
            code = code.replace(tcad.REMOTE_DURABILITY_CODE.split('def sync_dir')[1], '(path): pass\n')
        with chdir(folder), redirect_stdout(io.StringIO()) as output:
            exec(code, namespace)
        return SimpleNamespace(stdout=output.getvalue(), returncode=0)

    def test_both_seal_retry_and_collect_without_slot_or_global_owner(self):
        for kind in ('run', 'operation'):
            with self.subTest(kind=kind):
                record_path, remote_folder, observed = self.original(kind)
                seal = (lambda: tcad.seal_run(self.cfg, [], 'original')) if kind == 'run' else (
                    lambda: operation.seal_operation(tcad, self.cfg, [], 'original'))
                release_attempts = []

                def query(ssh, code, args, **kwargs):
                    if code == tcad.STATUS_CODE:
                        return dict(observed)
                    request = json.loads(args[0])
                    self.assertEqual(request['action'], 'release-sealed')
                    record = json.loads(record_path.read_text())
                    self.assertFalse(record['collection_verified'])
                    self.assertEqual(record['sealed_snapshot'], request['sealed_snapshot'])
                    release_attempts.append(request)
                    if len(release_attempts) == 1:
                        raise subprocess.TimeoutExpired('fixture lost release response', 1)
                    snapshot = request['sealed_snapshot']
                    return dict(schema='tcad-sealed-slot-release-r1', state='COLLECTED', policy=request['policy'],
                                script_sha256=request['script_sha256'], identity=request['process_identity'],
                                archive_sha256=snapshot['sha256'], archive_bytes=snapshot['bytes'])

                with patch.object(tcad, 'remote_python', side_effect=query), patch.object(
                    tcad, 'remote', side_effect=lambda ssh, command, **kw: self.snapshot(remote_folder, command)
                ) as snapshot_calls, patch.object(tcad, 'original_ownership', side_effect=AssertionError('global owner')):
                    with self.assertRaises(subprocess.TimeoutExpired):
                        seal()
                    original_stamp = json.loads(record_path.read_text())['sealed_snapshot']['sealed_utc']
                    result = seal()
                    self.assertEqual(result['sealed_snapshot']['sealed_utc'], original_stamp)
                    self.assertEqual(datetime.fromisoformat(original_stamp).utcoffset(), timedelta(0))
                    self.assertTrue(result['parallel_slot_released'])
                    self.assertFalse(result['collection_verified'])
                    self.assertEqual(seal(), result)
                    snapshot_calls.assert_called_once()
                self.assertEqual(len(release_attempts), 2)

                def transfer(ssh, command, stdout, **kwargs):
                    self.assertNotIn('flock', command)
                    self.assertTrue(command.endswith('/.collection/results.tar'))
                    stdout.write((remote_folder/'.collection/results.tar').read_bytes())
                    return SimpleNamespace(returncode=0)

                with patch.object(tcad, 'remote_python', side_effect=AssertionError('slot query')), patch.object(
                    tcad, 'remote', side_effect=transfer
                ), patch.object(tcad, 'original_ownership', side_effect=AssertionError('global owner')), patch.object(
                    tcad, 'connection', return_value=(self.cfg, [], None)
                ), redirect_stdout(io.StringIO()):
                    if kind == 'run':
                        with patch.object(sys, 'argv', ['tcad.py', 'collect', 'original']):
                            tcad.main()
                    else:
                        with patch.object(operation, 'load_tcad', return_value=tcad):
                            self.assertEqual(operation.main(['collect', 'original']), 0)
                collected = json.loads(record_path.read_text())
                self.assertTrue(collected['collection_verified'])
                self.assertEqual(collected['ssh_exit_code'], 255)

    def test_snapshot_publish_recovers_both_sides_of_archive_rename(self):
        path, remote_folder, observed = self.original('run')
        record = json.loads(path.read_text())
        record.update(remote_exit_code=0, process_identity=observed['identity'])
        command = tcad.snapshot_command(self.cfg, record, tcad.run_snapshot_context(record), sealing=True)
        replace = os.replace
        for crash_name in ('results.tar', 'receipt.json'):
            with self.subTest(crash_name=crash_name):
                def interrupted_replace(source, target):
                    if Path(target).name == crash_name:
                        raise RuntimeError('fixture power loss')
                    return replace(source, target)

                with patch.object(os, 'replace', side_effect=interrupted_replace):
                    with self.assertRaisesRegex(RuntimeError, 'fixture power loss'):
                        self.snapshot(remote_folder, command)
        store = remote_folder/'.collection'
        original_hash = tcad.file_hash(store/'results.tar')
        receipt = json.loads(self.snapshot(remote_folder, command).stdout)
        self.assertEqual(receipt['sha256'], original_hash)
        self.assertEqual(tcad.file_hash(store/'results.tar'), original_hash)
        self.assertFalse((store/'receipt.pending.json').exists())

    def test_no_seal_on_missing_exit_or_false_success(self):
        for kind, raw_name in (('run', 'metadata-sdevice-version-exit-code.txt'),
                               ('operation', 'operation-task-exit-code.txt')):
            with self.subTest(kind=kind):
                record_path, remote_folder, observed = self.original(kind)
                seal = (lambda: tcad.seal_run(self.cfg, [], 'original')) if kind == 'run' else (
                    lambda: operation.seal_operation(tcad, self.cfg, [], 'original'))
                (remote_folder/raw_name).write_text('1')
                with patch.object(tcad, 'remote_python', return_value=observed) as query, patch.object(
                    tcad, 'remote', side_effect=lambda ssh, command, **kw: self.snapshot(remote_folder, command)
                ):
                    with self.assertRaisesRegex(ValueError, 'Success marker conflicts'):
                        seal()
                    query.assert_called_once()
                saved = json.loads(record_path.read_text())
                self.assertNotIn('sealed_snapshot', saved)
                self.assertFalse(saved['collection_verified'])
                self.assertFalse((remote_folder/'.collection/receipt.json').exists())
                saved['remote_exit_code'] = None
                record_path.write_text(json.dumps(saved))
                (remote_folder/'exit-code.txt').unlink()
                with patch.object(tcad, 'remote_python', return_value=dict(observed, status='LOST_WITHOUT_EXIT',
                    remote_exit_code=None)), patch.object(tcad, 'remote', side_effect=ValueError('same boot')) as snapshot:
                    with self.assertRaisesRegex(RuntimeError, 'LOST_WITHOUT_EXIT'):
                        seal()
                    snapshot.assert_called_once()
                    self.assertIn('same boot', json.loads(record_path.read_text())['seal_reconciliation_error'])

    def test_both_collect_reboot_proof_as_unknown_exit(self):
        for kind in ('run', 'operation'):
            with self.subTest(kind=kind):
                path, directory, observed = self.original(kind)
                observed.update(status='LOST_WITHOUT_EXIT', remote_exit_code=None)
                (directory/'exit-code.txt').unlink()
                (directory/'finished-utc.txt').unlink()

                def reboot_proof(context):
                    self.assertEqual(context['process_identity'], observed['identity'])
                    return dict(observed_utc=tcad.utc(), current_boot_id='11234567-0123-0123-0123-0123456789ab',
                                original_boot_id=observed['identity']['boot_id'], wrapper_identity=observed['identity'],
                                actual_cwd=context['remote_directory'], active_native_processes=[],
                                active_directory_processes=[], original_wrapper_exit_present=False, native_evidence={},
                                locks=[dict(fd=9, path=context['shared_lock_path'], held=True, device=1, inode=2),
                                       dict(fd=8, path=context['remote_directory']+'/.collection/snapshot.lock',
                                            held=True, device=1, inode=3)])

                def remote(ssh, command, **kwargs):
                    if 'stdout' not in kwargs:
                        self.assertIn('Same-boot missing process', command)
                        return self.snapshot(directory, command, reboot_proof=reboot_proof)
                    self.assertNotIn('flock', command)
                    kwargs['stdout'].write((directory/'.collection/results.tar').read_bytes())
                    return SimpleNamespace(returncode=0)

                def release(cfg, ssh, record, action):
                    self.assertEqual(action, 'release-sealed')
                    self.assertIn('interruption_proof_sha256', record['interrupted_collection_snapshot'])

                with patch.object(tcad, 'remote_python', return_value=observed) as query, patch.object(
                    tcad, 'remote', side_effect=remote
                ), patch.object(tcad, 'parallel_query', side_effect=release) as release_calls:
                    if kind == 'run':
                        tcad.seal_run(self.cfg, [], 'original')
                        tcad.collect_run(self.cfg, [], 'original')
                    else:
                        operation.seal_operation(tcad, self.cfg, [], 'original')
                        operation.collect_operation(tcad, self.cfg, [], 'original')
                    query.assert_called_once()
                    release_calls.assert_called_once()
                collected = json.loads(path.read_text())
                self.assertTrue(collected['collection_verified'])
                self.assertIsNone(collected['remote_exit_code'])
                self.assertEqual(collected['execution_outcome'], 'INTERRUPTED_UNKNOWN_EXIT')
                self.assertEqual(collected['state'], 'INTERRUPTED_COLLECTED' if kind == 'run' else 'FAILED_COLLECTED')

    def test_release_crashes_and_reused_slot_never_locks_or_writes_new_owner(self):
        path, directory, observed = self.original('operation')
        record = json.loads(path.read_text())
        collection = directory/'.collection'
        collection.mkdir()
        store = self.root/'pool'
        store.mkdir()
        lease_path = store/'slot-0.json'
        snapshot = dict(sha256='b'*64, bytes=10240)
        (collection/'results.tar').write_bytes(bytes(snapshot['bytes']))
        (collection/'receipt.json').write_text(json.dumps(dict(snapshot, schema='tcad-original-snapshot-r1')))
        policy = dict(record['parallel_policy'], remote_directory=str(directory))
        identity = observed['identity']
        request = dict(sealed_snapshot=snapshot, process_identity=identity, script_sha256=record['script_sha256'])
        lease = dict(policy=policy, state='ACTIVE', script_sha256=record['script_sha256'], identity=identity)
        lease_path.write_text(json.dumps(lease))
        opened = Mock(return_value=7)
        fail_close = True

        def need(condition, message):
            if not condition:
                raise ValueError(message)

        def save(path, value, durable):
            self.assertTrue(durable)
            if path == lease_path and fail_close:
                raise RuntimeError('fixture failed to close lease')
            path.write_text(json.dumps(value))

        module = ast.parse(tcad.PARALLEL_CODE)
        release = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'release_sealed')
        namespace = dict(Path=Path, stat=stat, policy=policy, request=request, read=lambda path: json.loads(path.read_text()),
                         save=save, need=need, lease_path=lease_path, slot_path=store/'slot-0.lock', store=store,
                         original_identity=lambda lease: identity, identity_alive=lambda identity: False,
                         checked_termination=lambda *_: None, sync_path=Mock(), sync_dir=Mock(), opened=opened,
                         fcntl=SimpleNamespace(flock=Mock(), LOCK_EX=1, LOCK_NB=2))
        exec(compile(ast.Module(body=[release], type_ignores=[]), '<VM release>', 'exec'), namespace)
        release_sealed = namespace['release_sealed']
        newer = dict(lease, policy=dict(policy, kind='run', remote_directory='/replacement'))
        with self.assertRaisesRegex(ValueError, 'without sealed release proof'):
            release_sealed(newer)
        opened.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'fixture failed to close lease'):
            release_sealed(dict(lease))
        self.assertTrue((collection/'slot-release.json').is_file())
        self.assertEqual(json.loads(lease_path.read_text())['state'], 'ACTIVE')
        fail_close = False
        closed = release_sealed(json.loads(lease_path.read_text()))
        self.assertEqual(closed['state'], 'COLLECTED')
        self.assertEqual(release_sealed(json.loads(lease_path.read_text())), closed)
        lease_path.write_text(json.dumps(newer))
        opened.reset_mock()
        self.assertEqual(release_sealed(newer), closed)
        opened.assert_not_called()
        self.assertEqual(json.loads(lease_path.read_text()), newer)

    def test_per_run_writer_allows_peer_and_blocks_same_id(self):
        original = tcad.run_folder('original')
        with tcad.record_writer(original), tcad.record_writer(tcad.run_folder('peer')):
            with self.assertRaisesRegex(RuntimeError, 'writing original work'):
                with tcad.record_writer(original):
                    self.fail('Overlapping writer entered')
        with tcad.record_writer(original):
            self.assertFalse(original.exists())

    def test_staged_cli_reports_contention_and_retries_same_run(self):
        for kind in ('run', 'operation'):
            with self.subTest(kind=kind):
                project = self.root/(kind + '-input')
                project.mkdir()
                (project/'project.json').write_text(json.dumps(dict(name='fixture', steps=[
                    dict(tool='sdevice', args=['fixture.cmd'], outputs=['result.plt'])])))
                (project/'task.sh').write_text('true\n')
                folder = tcad.run_folder('new') if kind == 'run' else operation.operation_folder('new')
                argv = (['run', str(project), '--run-id', 'new'] if kind == 'run' else ['new', str(project)])
                argv += ['--detach', '--parallel-slot', '0', '--staged-launch']
                commands = []
                reservations = []
                holding = False

                @contextmanager
                def owner(**kwargs):
                    nonlocal holding
                    self.assertFalse(holding)
                    holding = True
                    try:
                        yield
                    finally:
                        holding = False

                def query(ssh, code, args, **kwargs):
                    self.assertTrue(holding)
                    self.assertTrue(folder.is_dir())
                    request = json.loads(args[0])
                    self.assertTrue(request['staged_launch'])
                    self.assertEqual(request['action'], 'reserve')
                    reservations.append(request)
                    if len(reservations) == 1:
                        message = 'TCAD_ALLOCATION_LOCK_BUSY: ' + json.dumps(dict(lock='allocator', request=request))
                        raise subprocess.CalledProcessError(74, 'fixture', stderr=message)
                    return dict(policy=request['policy'], script_sha256=request['script_sha256'], state='RESERVED')

                def remote(ssh, command, **kwargs):
                    self.assertFalse(holding)
                    self.assertTrue(folder.is_dir())
                    with self.assertRaisesRegex(RuntimeError, 'writing original work'):
                        with tcad.record_writer(folder):
                            self.fail('Same run writer entered')
                    commands.append(command)

                with patch.object(tcad, 'ROOT', self.root), patch.object(tcad, 'original_ownership', side_effect=owner), \
                        patch.object(tcad, 'connection', return_value=(self.cfg, [], None)), \
                        patch.object(tcad, 'execute', return_value=SimpleNamespace(stdout='fixture')), \
                        patch.object(tcad, 'remote_python', side_effect=query), patch.object(tcad, 'remote', side_effect=remote), \
                        patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}), \
                        patch.object(tcad.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'', stderr=b'')), \
                        patch.object(operation, 'CLOUD_INPUTS_ROOT', self.root), \
                        patch.object(operation, 'load_tcad', return_value=tcad), \
                        patch.object(operation, 'status_operation', return_value={'status': 'RUNNING'}), \
                        patch.object(sys, 'argv', ['tcad.py', *argv]):
                    launch = tcad.main if kind == 'run' else lambda: operation.main(argv)
                    with redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(launch(), 74)
                    refused = json.loads(output.getvalue())
                    self.assertEqual(refused['status'], 'ORIGINAL_ALLOCATOR_BUSY')
                    self.assertEqual(refused['error_code'], 'lock_busy')
                    self.assertFalse(refused['reservation_acquired'])
                    self.assertFalse(refused['solver_launched'])
                    self.assertTrue((Path(refused['diagnostic'])/'allocator-busy.json').is_file())
                    self.assertFalse(folder.exists())
                    self.assertEqual(commands, [])
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(launch(), None if kind == 'run' else 0)
                self.assertEqual(reservations[0], reservations[1])
                self.assertEqual(len(commands), 3)

    def test_remote_allocator_waits_then_times_out_without_reserving(self):
        source = ast.parse(tcad.PARALLEL_CODE)
        acquire = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'acquire')
        flock = Mock(side_effect=[BlockingIOError(), None])
        clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 0.1]), sleep=Mock())
        namespace = dict(fcntl=SimpleNamespace(flock=flock, LOCK_NB=4), request={'staged_launch': True},
                         action='reserve', allocation_wait=8, time=clock, json=json, sys=sys)
        exec(compile(ast.Module(body=[acquire], type_ignores=[]), '<VM allocator>', 'exec'), namespace)
        namespace['acquire'](7, 2, 'allocator')
        self.assertEqual(flock.call_count, 2)
        clock.sleep.assert_called_once_with(0.1)
        flock.side_effect = BlockingIOError
        clock.monotonic.side_effect = [0, 8]
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()) as output, self.assertRaises(SystemExit) as raised:
            namespace['acquire'](7, 2, 'allocator')
        self.assertEqual(raised.exception.code, 74)
        self.assertIn('TCAD_ALLOCATION_LOCK_BUSY: ', output.getvalue())

    def test_staged_lock_only_shares_distinct_projects(self):
        with patch.object(tcad, 'ROOT', self.root), tcad.staged_project_writer(self.root/'first'):
            with tcad.staged_project_writer(self.root/'second'):
                with self.assertRaisesRegex(tcad.ReservationBusy, 'local-project'):
                    with tcad.staged_project_writer(self.root/'second'/'..'/'first'):
                        self.fail('Same project writer entered')


if __name__ == '__main__':
    unittest.main()
