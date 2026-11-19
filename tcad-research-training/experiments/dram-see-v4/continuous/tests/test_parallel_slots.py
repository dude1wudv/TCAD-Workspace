"""Offline slot/identity integration checks; no SSH, native tool or VM launch."""
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import tarfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ParallelSlots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.tcad = module(ROOT / 'scripts/tcad.py', '_parallel_test_tcad')
        self.op = module(ROOT / 'experiments/dram-see-v4/transport-probe/operation.py', '_parallel_test_op')
        self.cfg = dict(backend='ssh-runtime', ssh_target='tcad-tail',
            runtime_entry='/srv/tcad-migration/minimal/scripts/enter-runtime.sh',
            remote_root='/home/tcad/research-training', tool_bin='/usr/synopsys/sentaurus/W-2024.09/bin')
        self.directory = self.cfg['remote_root'] + '/runs/new'
        self.policy = self.tcad.parallel_policy(self.cfg, 1, 'new', self.directory)

    def test_only_three_integer_single_core_slots_and_cloud(self):
        for slot in [0, 1, 2]:
            self.assertEqual(self.tcad.parallel_policy(self.cfg, slot, 'new', self.directory)['cpu'], slot)
        for slot in [3, 4, -1, True, '1', None]:
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                self.tcad.parallel_policy(self.cfg, slot, 'new', self.directory)
        with self.assertRaises(ValueError):
            self.tcad.parallel_policy(dict(self.cfg, backend='vmware'), 0, 'new', self.directory)

    def test_legacy_profiles_keep_exact_policy_keys_after_multicore_extension(self):
        keys = {'schema', 'slot', 'cpu', 'pool_root', 'connection_identity',
                'work_id', 'remote_directory', 'kind'}
        for capacity in (3, 7, 9):
            cfg = dict(self.cfg, parallel_capacity=capacity)
            policy = self.tcad.parallel_policy(cfg, capacity - 1, 'new', self.directory)
            self.assertEqual(set(policy), keys | ({'capacity'} if capacity != 3 else set()))
            self.assertEqual(policy['cpu'], capacity - 1)
            with self.subTest(capacity=capacity), self.assertRaisesRegex(ValueError, 'Legacy single-core'):
                self.tcad.parallel_capacity(dict(cfg, requested_threads=2))

    def test_explicit_seven_slots_freeze_capacity_and_reject_reinterpretation(self):
        cfg = dict(self.cfg, parallel_capacity=7)
        for slot in range(7):
            policy = self.tcad.parallel_policy(cfg, slot, 'new', self.directory)
            self.assertEqual((policy['schema'], policy['capacity'], policy['cpu']),
                             ('tcad-shared-gate-slots-r2', 7, slot))
        for slot in (7, -1, True, False, 1.0, '6', None):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                self.tcad.parallel_policy(cfg, slot, 'new', self.directory)
        for capacity in (0, 4, 8, True, '7', 7.0, None):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=capacity), 0, 'new', self.directory)
        legacy = dict(run_id='new', remote_directory=self.directory, parallel_policy=self.policy)
        self.assertEqual(self.tcad.parallel_record_policy(self.cfg, legacy), self.policy)
        with self.assertRaisesRegex(ValueError, 'parallel slot'):
            self.tcad.parallel_record_policy(cfg, legacy)
        extended = dict(legacy, parallel_policy=self.tcad.parallel_policy(cfg, 1, 'new', self.directory))
        with self.assertRaisesRegex(ValueError, 'parallel slot'):
            self.tcad.parallel_record_policy(self.cfg, extended)
        for field, value in [('capacity', 3), ('capacity', True), ('schema', self.tcad.PARALLEL_SCHEMA)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.tcad.parallel_record_policy(cfg, dict(extended,
                    parallel_policy=dict(extended['parallel_policy'], **{field: value})))

    def test_seven_slot_operation_and_tcad_use_same_gate_pool_and_cpu(self):
        cfg = dict(self.cfg, parallel_capacity=7)
        run = self.tcad.parallel_policy(cfg, 6, 'new', self.directory)
        directory = cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new'
        operation = self.tcad.parallel_policy(cfg, 6, 'new', directory, 'operation')
        for field in ('pool_root', 'slot', 'cpu', 'capacity', 'connection_identity', 'schema'):
            self.assertEqual(run[field], operation[field])
        for policy in (run, operation):
            shell = '\n'.join(self.tcad.parallel_shell_lines(policy, 'activate'))
            self.assertIn(cfg['remote_root'] + '/.solver.lock', shell)
            self.assertIn(cfg['remote_root'] + '/.solver-slots/slot-6.lock', shell)
        wrapper = self.op.render_wrapper(self.tcad, cfg, directory, 'new', False, operation)
        self.assertIn('cpu=6\ntaskset -pc "$cpu" $$', wrapper)

    def test_explicit_nine_slots_preserve_old_schemas_and_bind_original_capacity(self):
        cfg = dict(self.cfg, parallel_capacity=9)
        for slot in range(9):
            policy = self.tcad.parallel_policy(cfg, slot, 'new', self.directory)
            self.assertEqual((policy['schema'], policy['capacity'], policy['cpu']),
                             ('tcad-shared-gate-slots-r3', 9, slot))
        for slot in (9, -1, True, False, 1.0, '8', None):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                self.tcad.parallel_policy(cfg, slot, 'new', self.directory)
        for capacity in (8, 10, 11, 12, True, '9', 9.0, None):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=capacity), 0, 'new', self.directory)
        for capacity, schema in ((3, 'tcad-shared-gate-slots-r1'),
                                 (7, 'tcad-shared-gate-slots-r2'),
                                 (9, 'tcad-shared-gate-slots-r3')):
            old_cfg = dict(self.cfg, parallel_capacity=capacity)
            policy = self.tcad.parallel_policy(old_cfg, 1, 'new', self.directory)
            self.assertEqual(policy['schema'], schema)
            record = dict(run_id='new', remote_directory=self.directory, parallel_policy=policy)
            self.assertEqual(self.tcad.parallel_record_policy(old_cfg, record), policy)
            for other in ({3, 7, 9} - {capacity}):
                with self.subTest(original=capacity, changed=other), self.assertRaisesRegex(ValueError, 'parallel slot'):
                    self.tcad.parallel_record_policy(dict(self.cfg, parallel_capacity=other), record)
        policy = self.tcad.parallel_policy(cfg, 8, 'new', self.directory)
        record = dict(run_id='new', remote_directory=self.directory, parallel_policy=policy)
        for field, value in (('capacity', 7), ('capacity', True), ('schema', self.tcad.PARALLEL_EXTENDED_SCHEMA),
                             ('slot', 7), ('cpu', 7)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.tcad.parallel_record_policy(cfg, dict(record, parallel_policy=dict(policy, **{field: value})))

    def test_nine_slot_operation_and_tcad_share_pool_and_keep_single_cpu(self):
        cfg = dict(self.cfg, parallel_capacity=9)
        run = self.tcad.parallel_policy(cfg, 8, 'new', self.directory)
        directory = cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new'
        operation = self.tcad.parallel_policy(cfg, 8, 'new', directory, 'operation')
        for field in ('pool_root', 'slot', 'cpu', 'capacity', 'connection_identity', 'schema'):
            self.assertEqual(run[field], operation[field])
        for policy in (run, operation):
            shell = '\n'.join(self.tcad.parallel_shell_lines(policy, 'activate'))
            self.assertIn(cfg['remote_root'] + '/.solver.lock', shell)
            self.assertIn(cfg['remote_root'] + '/.solver-slots/slot-8.lock', shell)
        wrapper = self.op.render_wrapper(self.tcad, cfg, directory, 'new', False, operation)
        self.assertIn('cpu=8\ntaskset -pc "$cpu" $$', wrapper)
        self.assertIn('OMP_NUM_THREADS=1', wrapper)
        self.assertIn('flock -s -n 9', wrapper)
        self.assertIn('flock -n 7', wrapper)

    def test_both_clis_accept_slot_eight_without_executing_work(self):
        project = self.tmp / 'fixture'
        project.mkdir()
        (project / 'project.json').write_text('{}')
        with patch.object(self.tcad, 'connection', return_value=(self.cfg, [], None)), \
             patch.object(self.tcad, 'run_project', return_value=dict(status='FIXTURE')) as run, \
             patch.object(sys, 'argv', ['tcad.py', 'run', str(project), '--parallel-slot', '8']):
            self.tcad.main()
        self.assertEqual(run.call_args.kwargs['parallel_slot'], 8)
        with patch.object(self.op, 'run', return_value=0) as operation:
            self.op.main(['fixture', str(self.tmp), '--parallel-slot', '8'])
        self.assertEqual(operation.call_args.kwargs['parallel_slot'], 8)

    def test_slot_cannot_change_host_cpu_root_kind_or_directory(self):
        record = dict(run_id='new', remote_directory=self.directory, parallel_policy=self.policy)
        self.assertEqual(self.tcad.parallel_record_policy(self.cfg, record), self.policy)
        for field, value in [('cpu', 0), ('slot', 2), ('pool_root', '/other'), ('work_id', 'old'),
                             ('kind', 'operation'), ('remote_directory', '/other')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.tcad.parallel_record_policy(self.cfg, dict(record, parallel_policy=dict(self.policy, **{field: value})))
        with self.assertRaises(ValueError):
            self.tcad.parallel_record_policy(dict(self.cfg, ssh_target='tcad-cloud'), record)
        with self.assertRaises(ValueError):
            self.tcad.parallel_policy(self.cfg, 1, 'new', '/srv/other/runs/new')

    def test_operation_default_wrapper_identical_to_frozen_and_parallel_uses_same_pool(self):
        old_path = ROOT / 'local_runtime/cloud-benchmark/runner-pre-parallel/sources/experiments/dram-see-v4/transport-probe/operation.py'
        old = module(old_path, '_parallel_old_op')
        args = (self.tcad, self.cfg, self.directory, 'new', False)
        self.assertEqual(self.op.render_wrapper(*args), old.render_wrapper(*args))
        directory = self.cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new'
        policy = self.tcad.parallel_policy(self.cfg, 2, 'new', directory, 'operation')
        text = self.op.render_wrapper(self.tcad, self.cfg, directory, 'new', False, policy)
        self.assertIn('flock -s -n 9', text)
        self.assertIn('flock -n 7', text)
        self.assertIn('cpu=2\ntaskset -pc "$cpu" $$', text)
        self.assertNotIn('ACTIVE_SOLVER_DETECTED', text)
        self.assertIn('Unregistered active native process', text)  # Formal allowlist, not no scan.

    def test_generic_single_sdevice_new_slot_keeps_threads_managed(self):
        self.tcad.ROOT = self.tmp
        self.tcad.STATE_ROOT = self.tmp / 'local_runtime/cloud-benchmark/state'
        project = self.tmp / 'input'
        project.mkdir()
        (project / 'project.json').write_text(json.dumps(dict(name='performance-probe',
            steps=[dict(tool='sdevice', args=['device.cmd'], outputs=['probe_des.plt'])])))
        (project / 'device.cmd').write_text('frozen synthetic deck bytes; never executed')
        with patch.object(self.tcad, 'parallel_query', return_value={'policy': self.policy}) as query, \
             patch.object(self.tcad, 'assert_no_active_run', side_effect=AssertionError('legacy path')), \
             patch.object(self.tcad, 'execute', return_value=types.SimpleNamespace(stdout='commit')), \
             patch.object(self.tcad, 'remote'), \
             patch.object(self.tcad.subprocess, 'run', return_value=types.SimpleNamespace(stdout=b'', stderr=b'', returncode=0)), \
             patch.object(self.tcad, 'status_run', return_value={'status': 'FIXTURE'}):
            self.tcad._run_project(self.cfg, [], project, 'new', True, parallel_slot=1)
        query.assert_called_once()
        self.assertEqual(query.call_args.args[-1], 'reserve')
        text = (self.tcad.run_folder('new') / 'run.sh').read_text()
        self.assertIn('cpu=1\ntaskset -pc "$cpu" $$', text)
        self.assertIn('sdevice --threads 1 --exit-on-failure device.cmd', text)
        self.assertIn('Actual native process Threads is not 1', text)

    def test_pending_legacy_blocks_new_parallel_but_peer_parallel_is_recognized(self):
        self.tcad.STATE_ROOT = self.tmp
        folder = self.tmp / 'runs/new'
        folder.mkdir(parents=True)
        record = dict(run_id='new', remote_directory=self.directory, state='RUNNING')
        path = folder / 'manifest.json'
        path.write_text(json.dumps(record))
        with self.assertRaises(RuntimeError):
            self.tcad.parallel_assert_local(self.cfg)
        path.write_text(json.dumps(dict(record, parallel_policy=self.policy)))
        self.tcad.parallel_assert_local(self.cfg)

    def test_failed_collection_never_releases_and_success_checks_archive_receipt(self):
        record = dict(run_id='new', remote_directory=self.directory, parallel_policy=self.policy,
                      script_sha256='a' * 64, results_sha256='b' * 64)
        with patch.object(self.tcad, 'parallel_query', side_effect=RuntimeError('receipt mismatch')):
            with self.assertRaises(RuntimeError):
                self.tcad.parallel_release(self.cfg, [], record)
        self.assertNotIn('parallel_slot_released', record)
        with patch.object(self.tcad, 'parallel_query', return_value={}) as query:
            self.tcad.parallel_release(self.cfg, [], record)
            self.tcad.parallel_release(self.cfg, [], record)
        self.assertTrue(record['parallel_slot_released'])
        query.assert_called_once_with(self.cfg, [], record, 'release')

    def test_status_and_collect_reject_tampered_slot_before_remote(self):
        self.tcad.STATE_ROOT = self.tmp
        folder = self.tmp / 'runs/new'
        folder.mkdir(parents=True)
        record = dict(schema='tcad-native-run-r2', run_id='new', remote_directory=self.directory,
            connection_identity=self.tcad.connection_identity(self.cfg), state='RUNNING',
            parallel_policy=dict(self.policy, cpu=0))
        (folder / 'manifest.json').write_text(json.dumps(record))
        with patch.object(self.tcad, 'remote', side_effect=AssertionError('no remote allowed')):
            for call in [self.tcad.status_run, self.tcad.collect_run]:
                with self.assertRaisesRegex(ValueError, 'parallel slot'):
                    call(self.cfg, [], 'new')

    def test_archive_distinguishes_activation_from_failed_before_activation(self):
        script = b'frozen-wrapper-bytes'
        digest = hashlib.sha256(script).hexdigest()
        identity = dict(schema='tcad-process-identity-r1', run_id='new', cwd=self.directory,
                        script_sha256=digest, pid=100, start_ticks=10,
                        boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        collection = dict(policy=self.policy, script_sha256=digest, lease_state='ACTIVE',
                          identity=identity,
                          gate_mode='SHARED', slot_mode='EXCLUSIVE', status='COLLECTION_LOCKS_ACQUIRED')
        execution = dict(policy=self.policy, script_sha256=digest, identity=identity,
                         gate_mode='SHARED', slot_mode='EXCLUSIVE', gate_fd=9, slot_fd=7)
        evidence = dict(input_sha256={}, script_sha256=digest, remote_exit_code=0,
                        steps=[], parallel_policy=self.policy, process_identity=identity,
                        run_id='new', remote_directory=self.directory, last_observation=dict(identity=identity))
        def build(name, collected, executed, actual_identity=None):
            blobs = {'run.sh': script, 'process-identity.json': json.dumps(actual_identity or identity).encode(),
                     'parallel-slot-collection-evidence.json': json.dumps(collected).encode()}
            if executed is not None:
                blobs['parallel-slot-evidence.json'] = json.dumps(executed).encode()
            index = {n: dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()) for n, raw in blobs.items()}
            blobs['_collection-members.json'] = json.dumps(index).encode()
            path = self.tmp / name
            with tarfile.open(path, 'w') as archive:
                for n, raw in blobs.items():
                    member = tarfile.TarInfo(n)
                    member.size = len(raw)
                    archive.addfile(member, io.BytesIO(raw))
            return path
        good = build('good.tar', collection, execution)
        self.tcad.verify_archive(good, evidence)
        mismatch = build('bad.tar', collection, dict(execution, policy=dict(self.policy, cpu=2)))
        with self.assertRaisesRegex(ValueError, 'slot proof'):
            self.tcad.verify_archive(mismatch, evidence)
        early = build('early.tar', dict(collection, lease_state='RESERVED'), None)
        with self.assertRaisesRegex(ValueError, 'slot proof'):
            self.tcad.verify_archive(early, evidence)
        self.tcad.verify_archive(early, dict(evidence, remote_exit_code=75))
        # A self-consistent replacement wrapper is NOT the original producer,
        # even when every archive member and the SHA index agree internally.
        for field, value in [('pid', 200), ('start_ticks', 20),
                             ('boot_id', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')]:
            changed = dict(identity, **{field: value})
            substituted = build(field+'.tar', dict(collection, identity=changed),
                                dict(execution, identity=changed), changed)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'process identity changed'):
                self.tcad.verify_archive(substituted, evidence)
        with self.assertRaisesRegex(ValueError, 'Missing pinned'):
            self.tcad.verify_archive(good, dict(evidence, process_identity=None, last_observation={}))
        wrong_collection = build('wrong-collection.tar', dict(collection, identity=dict(identity, pid=200)), execution)
        with self.assertRaisesRegex(ValueError, 'collection/identity proof'):
            self.tcad.verify_archive(wrong_collection, evidence)

    def original_identity(self):
        return dict(schema='tcad-process-identity-r1', run_id='new', cwd=self.directory,
                    script_sha256='a'*64, pid=100, start_ticks=10,
                    boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')

    def test_status_pins_first_lease_and_rejects_later_wrapper_replacement(self):
        self.tcad.STATE_ROOT = self.tmp
        folder = self.tmp / 'runs/new'
        folder.mkdir(parents=True)
        original = self.original_identity()
        record = dict(schema='tcad-native-run-r2', run_id='new', remote_directory=self.directory,
                      script_sha256='a'*64, connection_identity=self.tcad.connection_identity(self.cfg),
                      parallel_policy=self.policy, state='RUNNING')
        path = folder / 'manifest.json'
        path.write_text(json.dumps(record))
        observation = dict(directory=self.directory, status='RUNNING', alive=True,
                           remote_exit_code=None, identity=original)
        with patch.object(self.tcad, 'parallel_query', return_value=dict(identity=original)), \
             patch.object(self.tcad, 'remote_python', return_value=observation):
            self.tcad.status_run(self.cfg, [], 'new')
        pinned = path.read_bytes()
        self.assertEqual(json.loads(pinned)['process_identity'], original)
        changed = dict(original, pid=200, start_ticks=20, boot_id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')
        with patch.object(self.tcad, 'parallel_query', return_value=dict(identity=original)), \
             patch.object(self.tcad, 'remote_python', return_value=dict(observation, identity=changed)):
            with self.assertRaisesRegex(ValueError, 'process identity changed'):
                self.tcad.status_run(self.cfg, [], 'new')
        self.assertEqual(path.read_bytes(), pinned)  # No poisoned last_observation/exit.
        with patch.object(self.tcad, 'parallel_query', return_value=dict(identity=changed)):
            with self.assertRaisesRegex(ValueError, 'process identity changed'):
                self.tcad.status_run(self.cfg, [], 'new')

    def test_remote_active_lease_and_local_pin_both_bind_current_identity(self):
        ns = self.admission()
        original = self.original_identity()
        lease = dict(state='ACTIVE', identity=original, script_sha256='a'*64)
        ns['read'] = lambda path: original
        self.assertEqual(ns['original_identity'](lease), original)
        changed = dict(original, pid=200, start_ticks=20, boot_id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')
        ns['read'] = lambda path: changed
        with self.assertRaisesRegex(ValueError, 'ACTIVE lease'):
            ns['original_identity'](lease)
        ns['request']['process_identity'] = original
        with self.assertRaisesRegex(ValueError, 'pinned original'):
            ns['original_identity'](dict(lease, identity=changed))
        # RESERVED is legitimate only as an unactivated producer; when status
        # already pinned it, collection must preserve that same failed wrapper.
        reserved = dict(state='RESERVED', script_sha256='a'*64)
        with self.assertRaisesRegex(ValueError, 'pinned original'):
            ns['original_identity'](reserved)
        ns['read'] = lambda path: original
        self.assertEqual(ns['original_identity'](reserved), original)

    def test_remote_verify_result_cannot_replace_pinned_local_identity(self):
        original = self.original_identity()
        record = dict(run_id='new', remote_directory=self.directory, script_sha256='a'*64,
                      parallel_policy=self.policy, process_identity=original)
        changed = dict(original, pid=200)
        with patch.object(self.tcad, 'remote_python', return_value=dict(policy=self.policy, identity=changed)) as remote:
            with self.assertRaisesRegex(ValueError, 'process identity changed'):
                self.tcad.parallel_query(self.cfg, [], record, 'verify')
        request = json.loads(remote.call_args.args[2][0])
        self.assertEqual(request['process_identity'], original)

    def test_parallel_collection_takes_own_slot_and_preserves_peer_progress(self):
        record = dict(schema='tcad-native-run-r2', run_id='new', remote_directory=self.directory,
            state='EXECUTED', script_sha256='a' * 64, parallel_policy=self.policy)
        def locked(ssh, script, **kw):
            self.assertIn('flock -s -n 9', script)
            self.assertIn('slot-1.lock', script)
            self.assertIn('flock -n 7', script)
            self.assertIn('snapshot.lock', script)
            self.assertNotIn('flock -n 9 || exit 75', script)
            raise subprocess.CalledProcessError(75, ['fixture-busy-own-slot'])
        with patch.object(self.tcad, 'read_manifest', return_value=(self.tmp, record)), \
             patch.object(self.tcad, 'status_run', return_value=dict(status='FINISHED', alive=False)), \
             patch.object(self.tcad, 'remote', side_effect=locked), \
             patch.object(self.tcad, 'parallel_release') as release:
            with self.assertRaises(subprocess.CalledProcessError):
                self.tcad.collect_run(self.cfg, [], 'new')
        release.assert_not_called()

    def test_repeated_id_cannot_switch_slot_and_never_submits(self):
        self.tcad.STATE_ROOT = self.tmp
        (self.tmp / 'runs/new').mkdir(parents=True)
        record = dict(parallel_policy=self.policy)
        with patch.object(self.tcad, 'original_ownership'), \
             patch.object(self.tcad, 'read_manifest', return_value=(self.tmp, record)), \
             patch.object(self.tcad, '_run_project', side_effect=AssertionError('no resubmission')):
            with self.assertRaisesRegex(ValueError, 'execution slot'):
                self.tcad.run_project(self.cfg, [], self.tmp, 'new', True, parallel_slot=2)

    def admission(self):
        # Load only actual protocol definitions; no remote main or POSIX opens.
        code = self.tcad.PARALLEL_CODE.split('safe_path(root);need(root.is_dir()')[0]
        fake = types.ModuleType('fcntl')
        namespace = {}
        with patch.dict(sys.modules, {'fcntl': fake}), patch.object(sys, 'argv', ['query', json.dumps(dict(policy=self.policy, action='reserve'))]):
            exec(compile(code, '<actual slot protocol functions>', 'exec'), namespace)
        proc = self.tmp / 'proc'
        (proc / 'sys/kernel/random').mkdir(parents=True)
        (proc / 'sys/kernel/random/boot_id').write_text('boot')
        namespace['proc'] = proc
        namespace['digest'] = lambda path: 'a' * 64
        class RemoteDirectory(PurePosixPath):
            def is_file(self):
                return False
        namespace['Path'] = RemoteDirectory  # Remote Linux path spelling on Windows.
        return namespace

    def test_remote_capacity_scans_all_ten_and_refuses_unknown_slot_file(self):
        ns = self.admission()
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        checked = []
        ns['checked_lease'] = lambda index: checked.append(index)
        self.assertEqual(ns['pool_leases'](), [])
        self.assertEqual(checked, list(range(10)))
        (ns['store'] / 'slot-10.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'outside supported pool'):
            ns['pool_leases']()

    def test_remote_capacity_mismatch_blocks_both_runner_kinds_and_idle_switch_checks_locks(self):
        ns = self.admission()
        extended = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=7), 6, 'new', self.directory)
        ns['policy'] = extended
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        config = ns['store'] / 'capacity.json'
        config.write_text('{}')
        ns['read'] = lambda path: dict(schema='tcad-slot-pool-r1', capacity=3)
        legacy = dict(policy=self.policy, state='RESERVED', script_sha256='a'*64)
        for kind in ('run', 'operation'):
            for state in ('RESERVED', 'ACTIVE'):
                with self.subTest(kind=kind, state=state), self.assertRaisesRegex(ValueError, 'outstanding'):
                    ns['check_pool_capacity']([dict(legacy, state=state,
                        policy=dict(self.policy, kind=kind))])
        # A collected stale record is harmless only after every lock is checked
        # and no unregistered native task remains. The actual Linux exclusion
        # mechanics are exercised by the separate flock integration fixture.
        opened, closed = [], []
        ns['opened'] = lambda path: opened.append(path) or len(opened)
        ns['fcntl'].LOCK_EX, ns['fcntl'].LOCK_NB = 1, 2
        ns['fcntl'].flock = lambda fd, mode: None
        admitted = []
        ns['admission'] = lambda peers: admitted.append(peers)
        with patch.object(ns['os'], 'close', side_effect=closed.append):
            ns['check_pool_capacity']([dict(legacy, state='COLLECTED')])
        self.assertEqual(len(opened), 9)
        self.assertEqual(closed, list(range(1, 10)))
        self.assertEqual(admitted, [[]])
        # The implicit pre-extension capacity is three. Absence of the new
        # manifest must not let a seven-slot profile skip the idle-lock proof.
        config.unlink()
        opened.clear()
        with patch.object(ns['os'], 'close', side_effect=closed.append):
            ns['check_pool_capacity']([])
        self.assertEqual(len(opened), 9)
        with self.assertRaisesRegex(ValueError, 'outstanding'):
            ns['check_pool_capacity']([dict(legacy, policy=extended)])
        ns['fcntl'].flock = lambda fd, mode: (_ for _ in ()).throw(BlockingIOError('busy slot'))
        with patch.object(ns['os'], 'close', side_effect=closed.append), self.assertRaises(BlockingIOError):
            ns['check_pool_capacity']([])
        ns['fcntl'].flock = lambda fd, mode: None
        ns['admission'] = lambda peers: (_ for _ in ()).throw(ValueError('Unregistered active native process'))
        with patch.object(ns['os'], 'close', side_effect=closed.append), \
             self.assertRaisesRegex(ValueError, 'Unregistered'):
            ns['check_pool_capacity']([])

    def test_remote_capacity_switch_locks_extended_slot_for_old_profiles(self):
        ns = self.admission()
        ns['policy'] = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=7), 6, 'new', self.directory)
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'slot-9.lock').touch()
        ns['opened'] = lambda path: int(path.stem.removeprefix('slot-'))
        ns['fcntl'].LOCK_EX, ns['fcntl'].LOCK_NB = 1, 2

        def flock(fd, mode):
            if fd == 9:
                raise BlockingIOError('slot 9 busy')

        ns['fcntl'].flock = flock
        with patch.object(ns['os'], 'close'), self.assertRaisesRegex(BlockingIOError, 'slot 9 busy'):
            ns['check_pool_capacity']([])

    def test_remote_seven_slot_admission_rejects_foreign_capacity_and_unavailable_cpu(self):
        ns = self.admission()
        extended = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=7), 6, 'new', self.directory)
        ns['policy'] = extended
        ns['admission']([dict(policy=extended, state='RESERVED')])
        with self.assertRaisesRegex(ValueError, 'Foreign'):
            ns['admission']([dict(policy=self.policy, state='RESERVED')])
        with patch.object(ns['os'], 'sched_getaffinity', return_value=set(range(6)), create=True):
            with self.assertRaisesRegex(ValueError, 'CPU is not available'):
                ns['available_cpu']()
        with patch.object(ns['os'], 'sched_getaffinity', return_value=set(range(7)), create=True):
            ns['available_cpu']()
        self.fake_process(ns['proc'], 100, 1, 'bash', 10, '6')
        self.fake_process(ns['proc'], 101, 100, 'sdevice', 20, '6')
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            ns['admission']([dict(self.peer(), policy=extended)])
            with self.assertRaisesRegex(ValueError, 'Unregistered'):
                ns['admission']([])
            self.fake_process(ns['proc'], 101, 100, 'sdevice', 20, '0-6')
            with self.assertRaisesRegex(ValueError, 'affinity'):
                ns['admission']([dict(self.peer(), policy=extended)])

    def test_remote_nine_schema_rejects_capacity_or_schema_reinterpretation(self):
        ns = self.admission()
        policies = {n: self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=n), 1,
                    'new', self.directory) for n in (3, 7, 9)}
        for capacity, policy in policies.items():
            self.assertEqual(ns['policy_capacity'](policy), capacity)
            for wrong in (True, float(capacity), str(capacity), 8, 10):
                with self.subTest(capacity=capacity, wrong=wrong), self.assertRaises(ValueError):
                    ns['policy_capacity'](dict(policy, capacity=wrong))
        for schema, capacity in (('tcad-shared-gate-slots-r2', 9),
                                 ('tcad-shared-gate-slots-r3', 7),
                                 ('tcad-shared-gate-slots-r4', 9)):
            with self.subTest(schema=schema, capacity=capacity), self.assertRaises(ValueError):
                ns['policy_capacity'](dict(policies[9], schema=schema, capacity=capacity))
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'capacity.json').write_text('{}')
        ns['policy'] = policies[9]
        for invalid in (True, 8, 10, '9', 9.0, None):
            ns['read'] = lambda path, invalid=invalid: dict(schema='tcad-slot-pool-r1', capacity=invalid)
            with self.subTest(pool_capacity=invalid), self.assertRaisesRegex(ValueError, 'Malformed pool'):
                ns['check_pool_capacity']([])

    def test_all_mixed_three_seven_nine_outstanding_pools_are_rejected(self):
        ns = self.admission()
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'capacity.json').write_text('{}')
        for requested in (3, 7, 9):
            ns['policy'] = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=requested),
                                                    requested-1, 'new', self.directory)
            ns['read'] = lambda path, n=requested: dict(schema='tcad-slot-pool-r1', capacity=n)
            for outstanding in ({3, 7, 9} - {requested}):
                peer = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=outstanding),
                                                 outstanding-1, 'new', self.directory)
                for kind in ('run', 'operation'):
                    for state in ('RESERVED', 'ACTIVE'):
                        with self.subTest(requested=requested, outstanding=outstanding, kind=kind,
                                          state=state), self.assertRaisesRegex(ValueError, 'outstanding'):
                            ns['check_pool_capacity']([dict(policy=dict(peer, kind=kind), state=state)])

    def test_seven_nine_idle_switch_checks_every_slot_even_high_collected_peer(self):
        ns = self.admission()
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'capacity.json').write_text('{}')
        ns['fcntl'].LOCK_EX, ns['fcntl'].LOCK_NB = 1, 2
        for current, requested in ((7, 9), (9, 7), (9, 3), (3, 9)):
            ns['policy'] = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=requested),
                                                    requested-1, 'new', self.directory)
            ns['read'] = lambda path, current=current: dict(schema='tcad-slot-pool-r1', capacity=current)
            peer = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=current),
                                             current-1, 'old', self.cfg['remote_root'] + '/runs/old')
            collected = dict(policy=peer, state='COLLECTED', script_sha256='a'*64)
            opened, closed, admitted = [], [], []
            ns['opened'] = lambda path: opened.append(path.name) or len(opened)
            ns['fcntl'].flock = lambda fd, mode: None
            ns['admission'] = lambda peers: admitted.append(peers)
            with self.subTest(current=current, requested=requested), \
                 patch.object(ns['os'], 'close', side_effect=closed.append):
                ns['check_pool_capacity']([collected])
            self.assertEqual(opened, ['slot-%s.lock' % i for i in range(9)])
            self.assertEqual(closed, list(range(1, 10)))
            self.assertEqual(admitted, [[]])
        # A lock on CPU8 still prevents reducing/replacing the shared pool, even
        # if no stale lease advertises it. Never erase or silently ignore it.
        opened, closed = [], []
        ns['opened'] = lambda path: opened.append(path.name) or len(opened)
        def busy_high_slot(fd, mode):
            if fd == 9:
                raise BlockingIOError('busy slot eight')
        ns['fcntl'].flock = busy_high_slot
        with patch.object(ns['os'], 'close', side_effect=closed.append), \
             self.assertRaisesRegex(BlockingIOError, 'slot eight'):
            ns['check_pool_capacity']([])
        self.assertEqual(opened[-1], 'slot-8.lock')
        self.assertEqual(closed, list(range(1, 10)))

    def test_slot_eight_admission_preserves_parent_affinity_and_original_identity(self):
        ns = self.admission()
        ns['policy'] = self.tcad.parallel_policy(dict(self.cfg, parallel_capacity=9), 8,
                                                'new', self.directory)
        self.fake_process(ns['proc'], 100, 1, 'bash', 10, '8')
        self.fake_process(ns['proc'], 101, 100, 'sdevice', 20, '8')
        peer = dict(self.peer(), policy=ns['policy'])
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            ns['admission']([peer])
            with self.assertRaisesRegex(ValueError, 'Unregistered'):
                ns['admission']([])
            self.fake_process(ns['proc'], 101, 100, 'sdevice', 20, '0-8')
            with self.assertRaisesRegex(ValueError, 'affinity'):
                ns['admission']([peer])
            self.fake_process(ns['proc'], 101, 100, 'sdevice', 20, '8')
            self.fake_process(ns['proc'], 100, 1, 'bash', 11, '8')
            with self.assertRaisesRegex(ValueError, 'outstanding'):
                ns['admission']([peer])
        with patch.object(ns['os'], 'sched_getaffinity', return_value=set(range(8)), create=True):
            with self.assertRaisesRegex(ValueError, 'CPU is not available'):
                ns['available_cpu']()
        original = self.original_identity()
        lease = dict(state='ACTIVE', identity=original, script_sha256='a'*64)
        ns['read'] = lambda path: original
        self.assertEqual(ns['original_identity'](lease), original)
        ns['request']['process_identity'] = original
        for field, value in (('pid', 200), ('start_ticks', 20),
                             ('boot_id', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')):
            ns['read'] = lambda path, field=field, value=value: dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'ACTIVE lease'):
                ns['original_identity'](lease)

    def fake_process(self, proc, pid, ppid, name, ticks, cpu='1'):
        folder = proc / str(pid)
        folder.mkdir(exist_ok=True)
        fields = ['0'] * 22
        fields[0], fields[1], fields[19] = 'R', str(ppid), str(ticks)
        (folder / 'stat').write_text(str(pid) + ' (' + name + ') ' + ' '.join(fields))
        (folder / 'comm').write_text(name)
        (folder / 'status').write_text('Cpus_allowed_list:\t' + cpu + '\n')
        task = folder / 'task' / str(pid)
        task.mkdir(parents=True, exist_ok=True)
        (task / 'status').write_text('Cpus_allowed_list:\t' + cpu + '\n')

    def peer(self):
        return dict(policy=self.policy, state='ACTIVE', script_sha256='a' * 64,
                    identity=dict(pid=100, start_ticks=10, boot_id='boot', cwd=self.directory,
                                  run_id='new', script_sha256='a' * 64))

    def test_registered_native_parent_chain_passes_but_unknown_and_pid_reuse_refuse(self):
        ns = self.admission()
        self.fake_process(ns['proc'], 100, 1, 'bash', 10)
        self.fake_process(ns['proc'], 101, 100, 'sdevice', 20)
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            ns['admission']([self.peer()])
            with self.assertRaisesRegex(ValueError, 'Unregistered'):
                ns['admission']([])
            self.fake_process(ns['proc'], 100, 1, 'bash', 11)
            with self.assertRaisesRegex(ValueError, 'outstanding'):
                ns['admission']([self.peer()])

    def test_registered_native_wrong_cpu_or_cwd_refuse(self):
        ns = self.admission()
        self.fake_process(ns['proc'], 100, 1, 'bash', 10)
        self.fake_process(ns['proc'], 101, 100, 'sdevice', 20, '0')
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            with self.assertRaisesRegex(ValueError, 'affinity'):
                ns['admission']([self.peer()])
        self.fake_process(ns['proc'], 101, 100, 'sdevice', 20)
        def cwd(path):
            return '/unknown' if '/101/' in path.replace('\\', '/') else self.directory
        with patch.object(ns['os'], 'readlink', side_effect=cwd):
            with self.assertRaisesRegex(ValueError, 'cwd'):
                ns['admission']([self.peer()])

    def test_auxiliary_threads_can_exist_but_none_may_escape_cpu(self):
        ns = self.admission()
        self.fake_process(ns['proc'], 100, 1, 'bash', 10)
        self.fake_process(ns['proc'], 101, 100, 'sdevice', 20)
        task = ns['proc'] / '101/task/102'
        task.mkdir()
        (task / 'status').write_text('Cpus_allowed_list:\t1\n')
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            ns['admission']([self.peer()])
            (task / 'status').write_text('Cpus_allowed_list:\t0-3\n')
            with self.assertRaisesRegex(ValueError, 'auxiliary task'):
                ns['admission']([self.peer()])

    def test_protocol_is_python36_syntax_and_release_keeps_lease_until_receipt(self):
        import ast
        ast.parse(self.tcad.PARALLEL_CODE, feature_version=(3, 6))
        self.assertIn("lease['state']='COLLECTED'", self.tcad.PARALLEL_CODE)
        self.assertIn("receipt['sha256']==request['archive_sha256']", self.tcad.PARALLEL_CODE)
        self.assertIn("Slot reserved until verified collection", self.tcad.PARALLEL_CODE)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('wsl.exe'), 'Needs already-running Docker WSL')
    def test_both_real_collect_scripts_keep_only_snapshot_json_on_stdout(self):
        current = subprocess.run(['wsl.exe', '--list', '--running', '--quiet'], capture_output=True, check=True)
        if 'docker-desktop' not in current.stdout.decode('utf-16-le', errors='replace'):
            self.skipTest('Docker WSL is not already running')
        class StopBeforeTransfer(RuntimeError):
            pass
        checked = []
        def execute_real_shell(ssh, script, **kwargs):
            if 'TCAD_SNAPSHOT' not in script:
                raise StopBeforeTransfer('No transfer/native execution in integration fixture')
            # Execute each REAL collector's generated shell with real Linux
            # pipes/redirections/flock. Only Python bodies (remote protocol and
            # archive builder) are stubbed; each deliberately emits one JSON.
            mapped = script.replace('/usr/bin/python3', 'fixture_python').replace(
                self.cfg['remote_root'], '${d}/pool')
            prologue = r'''set -eu
d=$(mktemp -d /tmp/tcad-collect-stdout.XXXXXX)
trap 'rm -rf "$d"' EXIT
mkdir -p "$d/pool/.solver-slots" "$d/pool/runs/new" "$d/pool/dram-see-v4/transport-probe/operations/new"
fixture_python() {
 cat >/dev/null
 case "$*" in
  *'"action": "collect"'*) printf '{"state":"ACTIVE"}\n';;
  *) printf '{"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","bytes":1}\n';;
 esac
}
'''
            response = subprocess.run(['wsl.exe', '-d', 'docker-desktop', '--exec', 'sh', '-s'],
                                      input=(prologue + mapped).encode(), capture_output=True, timeout=30)
            self.assertEqual(response.returncode, 0, response.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(response.stdout), dict(sha256='b'*64, bytes=1))
            # WSL itself may prepend a UTF16 platform warning on stderr; the
            # shell protocol receipt must still be present there, never stdout.
            self.assertTrue(response.stderr.endswith(b'{"state":"ACTIVE"}\n'), repr(response.stderr))
            checked.append(script)
            return types.SimpleNamespace(stdout=response.stdout.decode(), stderr=response.stderr.decode(errors='replace'), returncode=0)
        for kind in ('run', 'operation'):
            with self.subTest(kind=kind):
                folder = self.tmp / kind
                folder.mkdir()
                directory = (self.directory if kind == 'run' else
                             self.cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new')
                record = dict(state='EXECUTED', script_sha256='a'*64, remote_directory=directory,
                              parallel_policy=self.tcad.parallel_policy(self.cfg, 1, 'new', directory, kind))
                record['run_id' if kind == 'run' else 'label'] = 'new'
                record['schema'] = 'tcad-native-run-r2' if kind == 'run' else self.op.SCHEMA
                observed = dict(status='FINISHED', alive=False)
                with patch.object(self.tcad, 'remote', side_effect=execute_real_shell):
                    if kind == 'run':
                        with patch.object(self.tcad, 'read_manifest', return_value=(folder, record)), \
                             patch.object(self.tcad, 'status_run', return_value=observed):
                            with self.assertRaises(StopBeforeTransfer):
                                self.tcad.collect_run(self.cfg, [], 'new')
                    else:
                        with patch.object(self.op, 'read_record', return_value=(folder, record)), \
                             patch.object(self.op, 'status_operation', return_value=observed):
                            with self.assertRaises(StopBeforeTransfer):
                                self.op.collect_operation(self.tcad, self.cfg, [], 'new')
        self.assertEqual(len(checked), 2)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('wsl.exe'), 'Needs already-running Docker WSL for actual Linux flock')
    def test_actual_linux_flock_legacy_slot_exclusion_and_nine_slots(self):
        # No solver/SSH/VM start. Only an already-running local WSL distro.
        current = subprocess.run(['wsl.exe', '--list', '--running', '--quiet'], capture_output=True, check=True)
        if 'docker-desktop' not in current.stdout.decode('utf-16-le', errors='replace'):
            self.skipTest('Docker WSL is not already running')
        script = r'''set -eu
d=$(mktemp -d /tmp/tcad-slot-test.XXXXXX)
pids=''
trap 'touch "$d/release"; for pid in $pids; do wait "$pid" || true; done; rm -f "$d/"*; rmdir "$d"' EXIT
exec 9>"$d/gate"; flock -xn 9
if (exec 8>"$d/gate"; flock -sn 8); then exit 11; fi
flock -u 9
exec 8>"$d/gate"; flock -sn 8
if (exec 4>"$d/gate"; flock -xn 4); then exit 12; fi
for index in 0 1 2 3 4 5 6 7 8; do
 (
  exec 7>"$d/s$index"; flock -xn 7
  touch "$d/ready$index"
  while [ ! -f "$d/release" ]; do sleep .02; done
 ) &
 pids="$pids $!"
done
for index in 0 1 2 3 4 5 6 7 8; do
 count=0
 while [ ! -f "$d/ready$index" ]; do
  count=$((count+1)); [ "$count" -lt 100 ] || exit 13
  sleep .02
 done
 if (exec 4>"$d/s$index"; flock -xn 4); then exit 14; fi
done
echo PASS_ACTUAL_LINUX_FLOCK
'''
        result = subprocess.run(['wsl.exe', '-d', 'docker-desktop', '--exec', 'sh', '-s'],
                                input=script.encode(), capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertIn(b'PASS_ACTUAL_LINUX_FLOCK', result.stdout)
        directory = self.cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new'
        policy = self.tcad.parallel_policy(self.cfg, 2, 'new', directory, 'operation')
        wrapper = self.op.render_wrapper(self.tcad, self.cfg, directory, 'new', False, policy)
        syntax = subprocess.run(['wsl.exe', '-d', 'docker-desktop', '--exec', 'sh', '-n'],
                                input=wrapper.encode(), capture_output=True, timeout=30)
        self.assertEqual(syntax.returncode, 0, syntax.stderr.decode(errors='replace'))


if __name__ == '__main__':
    unittest.main()
