"""Offline r4 resource contracts, actual /proc-shaped fixtures, and collectors.

No SSH, native solver, profile rewrite, or VM launch. All writes are temporary.
"""
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MulticoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.tcad = load(ROOT / 'scripts/tcad.py', '_multicore_tcad')
        self.cfg = dict(backend='ssh-runtime', ssh_target='tcad-sim-tail',
                        runtime_entry='/usr/local/libexec/tcad-centos79-enter',
                        remote_root='/home/tcad/research-training',
                        tool_bin='/usr/synopsys/sentaurus/W-2024.09/bin',
                        parallel_capacity=4, cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]],
                        requested_threads=2)
        self.directory = self.cfg['remote_root'] + '/runs/new'
        self.policy = self.tcad.parallel_policy(self.cfg, 0, 'new', self.directory)
        self.identity = dict(schema='tcad-process-identity-r1', run_id='new',
                             cwd=self.directory, pid=100, start_ticks=10,
                             boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                             script_sha256='a' * 64)
        self.helpers = self.tcad._MULTICORE_HELPERS

    @staticmethod
    def stat(pid, ppid, name, ticks):
        fields = ['0'] * 22
        fields[0], fields[1], fields[19] = 'R', str(ppid), str(ticks)
        return str(pid) + ' (' + name + ') ' + ' '.join(fields)

    @staticmethod
    def status(pid, ppid, name, threads, cpus, tgid=None):
        return ('Name:\t{}\nPid:\t{}\nTgid:\t{}\nPPid:\t{}\nThreads:\t{}\n'
                'Cpus_allowed_list:\t{}\n').format(
                    name, pid, pid if tgid is None else tgid, ppid, threads, cpus)

    def snapshot(self, pid=101, ppid=100, name='sdevice', threads=3, cpus='0-1', ticks=20):
        return dict(schema='tcad-task-resource-snapshot-r1', pid=pid, start_ticks=ticks,
                    cwd=self.directory, cpu_set=[0, 1], threads=threads,
                    status=self.status(pid, ppid, name, threads, cpus),
                    tasks=[dict(tid=pid + i, start_ticks=ticks + i,
                                status=self.status(pid + i, ppid, name, threads, cpus, pid))
                           for i in range(threads)])

    def protocol(self):
        fcntl = types.ModuleType('fcntl')
        fcntl.LOCK_EX, fcntl.LOCK_SH, fcntl.LOCK_NB = 1, 2, 4
        fcntl.flock = lambda fd, mode: None
        namespace = {}
        source = self.tcad.PARALLEL_CODE.split("safe_path(root);need(root.is_dir()")[0]
        with patch.dict(sys.modules, {'fcntl': fcntl}), \
                patch.object(sys, 'argv', ['protocol', json.dumps(dict(policy=self.policy, action='reserve'))]):
            exec(compile(source, '<real shared protocol definitions>', 'exec'), namespace)
        proc = self.tmp / 'proc'
        (proc / 'sys/kernel/random').mkdir(parents=True, exist_ok=True)
        (proc / 'sys/kernel/random/boot_id').write_text(self.identity['boot_id'])
        namespace['proc'] = proc
        namespace['digest'] = lambda path: 'a' * 64
        namespace['Path'] = PurePosixPath
        return namespace

    def process(self, proc, pid=101, ppid=100, name='sdevice', threads=3, cpus='0-1', ticks=20):
        base = proc / str(pid)
        base.mkdir(exist_ok=True)
        snapshot = self.snapshot(pid, ppid, name, threads, cpus, ticks)
        (base / 'stat').write_text(self.stat(pid, ppid, name, ticks))
        (base / 'comm').write_text(name)
        (base / 'status').write_text(snapshot['status'])
        for task in snapshot['tasks']:
            folder = base / 'task' / str(task['tid'])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'stat').write_text(self.stat(task['tid'], ppid, name, task['start_ticks']))
            (folder / 'status').write_text(task['status'])
        return base

    def peer(self):
        return dict(policy=self.policy, state='ACTIVE', identity=self.identity, script_sha256='a' * 64)

    def test_exact_four_slot_profile_and_frozen_resource_identity(self):
        for slot in range(4):
            policy = self.tcad.parallel_policy(self.cfg, slot, 'new', self.directory)
            self.assertEqual(policy['schema'], 'tcad-shared-gate-slots-r4')
            self.assertEqual(policy['cpu_set'], [2 * slot, 2 * slot + 1])
            self.assertEqual(policy['requested_threads'], 2)
            self.assertNotIn('cpu', policy)
        record = dict(run_id='new', remote_directory=self.directory, parallel_policy=self.policy)
        for key, value in [('cpu_set', [1, 2]), ('requested_threads', 1), ('capacity', 9)]:
            changed = dict(record, parallel_policy=dict(self.policy, **{key: value}))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'parallel slot'):
                self.tcad.parallel_record_policy(self.cfg, changed)
        with self.assertRaises(ValueError):
            self.tcad.parallel_policy(self.cfg, 4, 'new', self.directory)

    def test_malformed_overlap_boolean_missing_and_legacy_resource_fields_refused(self):
        for changes in [
            {'cpu_sets': [[0, 1], [1, 2], [4, 5], [6, 7]]},
            {'cpu_sets': [[False, 1], [2, 3], [4, 5], [6, 7]]},
            {'cpu_sets': [[0, 1], [2, 3], [4, 5], [7, 8]]},
            {'cpu_sets': None}, {'requested_threads': True},
            {'requested_threads': 2.0}, {'requested_threads': 1},
            {'parallel_capacity': 9}, {'parallel_capacity': 3},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.tcad.parallel_capacity(dict(self.cfg, **changes))
        for capacity in (3, 7, 9):
            cfg = {k: v for k, v in self.cfg.items() if k not in ('cpu_sets', 'requested_threads')}
            cfg['parallel_capacity'] = capacity
            self.assertEqual(self.tcad.parallel_policy(cfg, 0, 'new', self.directory)['cpu'], 0)

    def test_11_vcpu_layouts_have_stable_schema_and_slot_thread_binding(self):
        layouts = (
            (5, [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]],
             'tcad-shared-gate-slots-r6', 2),
            (8, [[0], [1], [2], [3], [4], [5], [6, 7], [8, 9]],
             'tcad-shared-gate-slots-r7', None),
            (10, [[cpu] for cpu in range(10)], 'tcad-shared-gate-slots-r8', 1),
            (1, [list(range(10))], 'tcad-shared-gate-slots-r9', 10),
        )
        for capacity, cpu_sets, schema, configured_threads in layouts:
            cfg = dict(self.cfg, parallel_capacity=capacity, cpu_sets=cpu_sets)
            if configured_threads is None:
                cfg.pop('requested_threads', None)
            else:
                cfg['requested_threads'] = configured_threads
            self.assertEqual(self.tcad.parallel_capacity(cfg), capacity)
            for slot, cpu_set in enumerate(cpu_sets):
                with self.subTest(schema=schema, slot=slot):
                    policy = self.tcad.parallel_policy(cfg, slot, 'new', self.directory)
                    self.assertEqual(policy['schema'], schema)
                    self.assertEqual(policy['capacity'], capacity)
                    self.assertEqual(policy['cpu_set'], cpu_set)
                    self.assertEqual(policy['requested_threads'], len(cpu_set))
                    self.assertNotIn('cpu', policy)
                    self.helpers['mc_policy'](policy)
                    record = dict(run_id='new', remote_directory=self.directory,
                                  parallel_policy=policy)
                    self.assertEqual(self.tcad.parallel_record_policy(cfg, record), policy)
            with self.assertRaisesRegex(ValueError, 'does not admit Geant4'):
                directory = cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new'
                self.tcad.parallel_policy(cfg, 0, 'new', directory, 'operation')

    def test_11_vcpu_pool_descriptors_and_idle_switch_use_shared_slot_locks(self):
        ns = self.protocol()
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'capacity.json').write_text('{}')
        ns['action'] = 'reserve'
        ns['admission'] = lambda leases: []
        ns['fcntl'].flock = lambda fd, mode: None
        layouts = (
            (5, [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]], 'tcad-shared-gate-slots-r6'),
            (8, [[0], [1], [2], [3], [4], [5], [6, 7], [8, 9]], 'tcad-shared-gate-slots-r7'),
            (10, [[cpu] for cpu in range(10)], 'tcad-shared-gate-slots-r8'),
            (1, [list(range(10))], 'tcad-shared-gate-slots-r9'),
        )
        for capacity, cpu_sets, schema in layouts:
            cfg = dict(self.cfg, parallel_capacity=capacity, cpu_sets=cpu_sets)
            cfg.pop('requested_threads', None)
            policy = self.tcad.parallel_policy(cfg, capacity - 1, 'new', self.directory)
            ns['policy'] = policy
            descriptor = self.helpers['mc_pool_configuration'](schema)
            self.assertEqual(ns['pool_configuration'](), descriptor)
            ns['read'] = lambda path: dict(schema='tcad-slot-pool-r1', capacity=3)
            opened = []
            ns['opened'] = lambda path: opened.append(path.name) or len(opened)
            with self.subTest(schema=schema), patch.object(ns['os'], 'close'):
                ns['check_pool_capacity']([])
            self.assertEqual(opened, ['slot-%s.lock' % i for i in range(max(9, capacity))])

    def test_mixed_layout_rejects_wrong_per_slot_thread_count(self):
        cfg = dict(self.cfg, parallel_capacity=8,
                   cpu_sets=[[0], [1], [2], [3], [4], [5], [6, 7], [8, 9]])
        cfg.pop('requested_threads', None)
        policy = self.tcad.parallel_policy(cfg, 6, 'new', self.directory)
        with self.assertRaisesRegex(ValueError, 'resource policy'):
            self.helpers['mc_policy'](dict(policy, requested_threads=1))
        self.helpers['mc_policy'](policy)

    def test_geant4_shared_interface_refuses_r4_before_any_launch(self):
        operation = load(ROOT / 'experiments/dram-see-v4/transport-probe/operation.py', '_mc_operation')
        directory = self.cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new'
        with self.assertRaisesRegex(ValueError, 'does not admit Geant4'):
            self.tcad.parallel_policy(self.cfg, 0, 'new', directory, 'operation')
        with patch.object(operation, 'operation_folder', return_value=self.tmp / 'operation'), \
                patch.object(self.tcad, 'remote', side_effect=AssertionError('no SSH allowed')):
            with self.assertRaisesRegex(ValueError, 'does not admit Geant4'):
                operation._run_operation(self.tcad, self.cfg, [], 'new', self.tmp, None, True, 0)

    def test_auxiliary_os_threads_and_per_tid_binding_are_separate_from_request(self):
        for count in (1, 2, 3, 5):
            value = self.snapshot(threads=count)
            for index, task in enumerate(value['tasks']):
                task['status'] = task['status'].replace('0-1', str(index % 2))
            self.helpers['mc_validate'](value, [0, 1], None, 101, 20, self.directory)
        for text in ('0-1', '0,1'):
            self.assertEqual(self.helpers['mc_cpus'](text), [0, 1])
        for text in ('0-2', '1,8'):
            value = self.snapshot()
            value['tasks'][-1]['status'] = value['tasks'][-1]['status'].replace('0-1', text)
            with self.assertRaisesRegex(ValueError, 'Actual task CPU'):
                self.helpers['mc_validate'](value, [0, 1], None)
        for text in ('1-0', '0,0', '', '0-999999'):
            with self.assertRaises(ValueError):
                self.helpers['mc_cpus'](text)

    def test_proc_snapshot_refuses_missing_task_wrong_count_wrapper_and_tid_escape(self):
        ns = self.protocol()
        base = self.process(ns['proc'])
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            actual = ns['mc_snapshot'](ns['proc'], 101, [0, 1], None, self.directory, 20)
            self.assertEqual(actual['threads'], 3)
            escaped = base / 'task/103/status'
            escaped.write_text(escaped.read_text().replace('0-1', '0-8'))
            with self.assertRaisesRegex(ValueError, 'Actual task CPU'):
                ns['mc_snapshot'](ns['proc'], 101, [0, 1], None, self.directory)
            escaped.write_text(self.snapshot()['tasks'][-1]['status'])
            (base / 'task/103/stat').unlink()
            with self.assertRaises(FileNotFoundError):
                ns['mc_snapshot'](ns['proc'], 101, [0, 1], None, self.directory)
        wrapper = self.snapshot(100, 1, 'bash', 1, '0', 10)
        with self.assertRaisesRegex(ValueError, 'Actual process CPU'):
            ns['mc_validate'](wrapper, [0, 1], 1, exact=True)
        value = self.snapshot()
        value['tasks'].pop()
        with self.assertRaisesRegex(ValueError, 'Actual task count'):
            ns['mc_validate'](value, [0, 1], None)

    def test_live_admission_audits_wrapper_native_all_tids_and_original_identity(self):
        ns = self.protocol()
        wrapper = self.process(ns['proc'], 100, 1, 'bash', 1, '0-1', 10)
        native = self.process(ns['proc'])
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            report = ns['admission']([self.peer()])
            self.assertEqual([x['role'] for x in report], ['wrapper', 'native'])
            self.assertEqual(report[-1]['snapshot']['threads'], 3)
            with self.assertRaisesRegex(ValueError, 'Unregistered'):
                ns['admission']([])
            (native / 'task/103/status').write_text(self.status(103, 100, 'sdevice', 3, '8', 101))
            with self.assertRaisesRegex(ValueError, 'Actual task CPU'):
                ns['admission']([self.peer()])
            (native / 'task/103/status').write_text(self.snapshot()['tasks'][-1]['status'])
            (wrapper / 'status').write_text(self.status(100, 1, 'bash', 1, '0-8'))
            with self.assertRaisesRegex(ValueError, 'Actual process CPU'):
                ns['admission']([self.peer()])
        with patch.object(ns['os'], 'sched_getaffinity', return_value={0}, create=True):
            with self.assertRaisesRegex(ValueError, 'CPU is not available'):
                ns['available_cpu']()

    def test_pool_switch_is_idle_only_scans_all_nine_and_rejects_old_peers(self):
        ns = self.protocol()
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'capacity.json').write_text('{}')
        ns['read'] = lambda path: dict(schema='tcad-slot-pool-r1', capacity=9)
        old_cfg = {k: v for k, v in self.cfg.items() if k not in ('cpu_sets', 'requested_threads')}
        old_cfg['parallel_capacity'] = 9
        old = self.tcad.parallel_policy(old_cfg, 8, 'old', self.cfg['remote_root'] + '/runs/old')
        for kind in ('run', 'operation'):
            for state in ('RESERVED', 'ACTIVE'):
                with self.subTest(kind=kind, state=state), self.assertRaisesRegex(ValueError, 'outstanding'):
                    ns['check_pool_capacity']([dict(policy=dict(old, kind=kind), state=state)])
        opened = []
        ns['opened'] = lambda path: opened.append(path.name) or len(opened)
        ns['admission'] = lambda peers: []
        with patch.object(ns['os'], 'close'):
            ns['check_pool_capacity']([dict(policy=old, state='COLLECTED')])
        self.assertEqual(opened, ['slot-%s.lock' % i for i in range(9)])
        def flock(fd, mode):
            if fd == 9:
                raise BlockingIOError('busy legacy high slot')
        opened.clear()
        ns['fcntl'].flock = flock
        with patch.object(ns['os'], 'close'), self.assertRaisesRegex(BlockingIOError, 'high slot'):
            ns['check_pool_capacity']([])
        malformed = dict(ns['pool_configuration'](), requested_threads=True)
        ns['read'] = lambda path: malformed
        with self.assertRaisesRegex(ValueError, 'Malformed pool'):
            ns['check_pool_capacity']([])

    def test_r4_pool_cannot_be_reinterpreted_as_idle_legacy_capacity(self):
        ns = self.protocol()
        new = ns['pool_configuration']()
        old_cfg = {k: v for k, v in self.cfg.items() if k not in ('cpu_sets', 'requested_threads')}
        old_cfg['parallel_capacity'] = 9
        ns['policy'] = self.tcad.parallel_policy(old_cfg, 8, 'new', self.directory)
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'capacity.json').write_text('{}')
        ns['read'] = lambda path: new
        with self.assertRaisesRegex(ValueError, 'outstanding'):
            ns['check_pool_capacity']([dict(policy=self.policy, state='RESERVED')])

    def test_generated_wrapper_freezes_cli_cpu_environment_and_original_locks(self):
        self.tcad.ROOT = self.tmp
        self.tcad.STATE_ROOT = self.tmp / 'local_runtime/cloud-benchmark/state'
        project = self.tmp / 'input'
        project.mkdir()
        project_spec = dict(name='multicore-probe', native_threads=2, native_cores=2,
                            steps=[dict(tool='sdevice', args=['device.cmd'], outputs=['probe.plt'])])
        (project / 'project.json').write_text(json.dumps(project_spec))
        (project / 'device.cmd').write_text('frozen fixture, never executed')
        with patch.object(self.tcad, 'parallel_query'), patch.object(self.tcad, 'remote'), \
                patch.object(self.tcad, 'execute', return_value=types.SimpleNamespace(stdout='commit')), \
                patch.object(self.tcad.subprocess, 'run', return_value=types.SimpleNamespace(
                    stdout=b'', stderr=b'', returncode=0)), \
                patch.object(self.tcad, 'status_run', return_value={'status': 'FIXTURE'}):
            self.tcad._run_project(self.cfg, [], project, 'new', True, parallel_slot=0)
        script = (self.tcad.run_folder('new') / 'run.sh').read_text()
        self.assertIn('cpu=0,1\ntaskset -pc "$cpu" $$', script)
        self.assertLess(script.index('cpu=0,1'), script.index('"action": "activate"'))
        self.assertIn('sdevice --threads 2 --exit-on-failure device.cmd', script)
        self.assertIn('export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2', script)
        self.assertIn('/.solver-slots/slot-0.lock', script)
        self.assertIn('/.solver.lock', script)
        self.assertIn('flock -s -n 9', script)
        manifest = json.loads((self.tcad.run_folder('new') / 'manifest.json').read_text())
        self.assertEqual(manifest['requested_resources']['requested_threads'], 2)
        self.assertEqual(manifest['tool_evidence']['step-001-sdevice']['requested_threads'], 2)
        project_spec['native_threads'] = 1
        (project / 'project.json').write_text(json.dumps(project_spec))
        with self.assertRaisesRegex(ValueError, 'metadata'):
            self.tcad._run_project(self.cfg, [], project, 'other', True, parallel_slot=0)
        with self.assertRaisesRegex(ValueError, 'explicit parallel slot'):
            self.tcad._run_project(self.cfg, [], project, 'other', True)

    def capture_source(self, marker):
        lines = self.tcad.native_capture_shell_lines(self.policy)
        start = next(i for i, line in enumerate(lines) if "<<'" + marker + "'" in line) + 1
        end = lines.index(marker, start)
        return '\n'.join(lines[start:end])

    def observed(self):
        native = self.snapshot()
        return dict(schema='native-process-observation-r2', status='OBSERVED',
                    requested_tool='sdevice', resource_policy=self.policy, wrapper_pid=100,
                    native_pid=101, native_start_ticks=20, native_resources=native,
                    wrapper_resources=self.snapshot(100, 1, 'bash', 1, '0-1', 10),
                    family_resources=[], native_process_family=[], selection_method='single_exact_native',
                    status_sha256=hashlib.sha256(native['status'].encode()).hexdigest())

    def test_embedded_python36_and_real_admission_accept_auxiliary_threads_but_not_escape(self):
        for code in (self.tcad.PARALLEL_CODE, self.capture_source('S2_CAPTURE_PROC_PY'),
                     self.capture_source('S2_CAPTURE_ADMIT_PY')):
            ast.parse(code, feature_version=(3, 6))
        source = self.capture_source('S2_CAPTURE_ADMIT_PY')
        for escape in (False, True):
            folder = self.tmp / str(escape)
            folder.mkdir()
            observed = self.observed()
            if escape:
                task = observed['native_resources']['tasks'][-1]
                task['status'] = task['status'].replace('0-1', '8')
            prefix = str(folder / 'step-001-sdevice')
            Path(prefix + '-process-observation.json').write_text(json.dumps(observed))
            Path(prefix + '-process-status.txt').write_bytes(observed['native_resources']['status'].encode())
            with patch.object(sys, 'argv', ['admit', prefix, 'sdevice', '0,1']), \
                    patch('os.getcwd', return_value=self.directory), patch('sys.stdout', io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    exec(compile(source, '<real multicore capture admission>', 'exec'), {})
            report = json.loads(Path(prefix + '-process-admission.json').read_text())
            self.assertEqual(caught.exception.code, 86 if escape else 0, report)
            self.assertEqual(report['requested_threads'], 2)
            self.assertEqual(report['schema'], 'native-process-admission-r2')

    def test_status_returns_live_audit_and_missing_audit_cannot_poison_manifest(self):
        evidence = dict(schema='tcad-native-run-r2', state='RUNNING', run_id='new',
                        parallel_policy=self.policy, process_identity=self.identity,
                        remote_directory=self.directory, script_sha256='a' * 64)
        observation = dict(directory=self.directory, status='RUNNING', alive=True,
                           identity=self.identity, remote_exit_code=None)
        audit = dict(schema='tcad-live-resource-audit-r1', policy=self.policy,
                     snapshots=[dict(role='native', snapshot=self.snapshot())])
        with patch.object(self.tcad, 'read_manifest', return_value=(self.tmp, evidence)), \
                patch.object(self.tcad, 'parallel_query', return_value=dict(identity=self.identity, resource_audit=audit)), \
                patch.object(self.tcad, 'remote_python', return_value=observation), \
                patch.object(self.tcad, 'save_manifest') as save:
            self.assertEqual(self.tcad.status_run(self.cfg, [], 'new')['resource_audit'], audit)
            save.assert_called_once()
        with patch.object(self.tcad, 'read_manifest', return_value=(self.tmp, evidence)), \
                patch.object(self.tcad, 'parallel_query', return_value=dict(identity=self.identity)), \
                patch.object(self.tcad, 'save_manifest') as save:
            with self.assertRaisesRegex(ValueError, 'Missing live'):
                self.tcad.status_run(self.cfg, [], 'new')
            save.assert_not_called()

    def archive(self, changes=None):
        observation = self.observed()
        wrapper = observation['wrapper_resources']
        activated = dict(wrapper_resources=wrapper)
        collected = dict(wrapper_resources=copy.deepcopy(wrapper))
        admission = dict(schema='native-process-admission-r2', resource_policy=self.policy,
                         requested_threads=2, requested_cpu='0,1', requested_tool='sdevice',
                         status='PASSED', errors=[])
        if changes:
            changes(observation, admission, activated, collected)
        blobs = {
            'parallel-slot-evidence.json': json.dumps(activated).encode(),
            'parallel-slot-collection-evidence.json': json.dumps(collected).encode(),
            'step-001-sdevice-process-observation.json': json.dumps(observation).encode(),
            'step-001-sdevice-process-admission.json': json.dumps(admission).encode(),
            'step-001-sdevice-process-status.txt': observation['native_resources']['status'].encode(),
            'step-001-sdevice-process-admission-exit-code.txt': b'0\n',
        }
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            for name, raw in blobs.items():
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
        data.seek(0)
        evidence = dict(parallel_policy=self.policy, process_identity=self.identity, remote_exit_code=0,
                        tool_evidence={'step-001-sdevice': dict(
                            tool='sdevice', process_observation_file='step-001-sdevice-process-observation.json',
                            process_admission_file='step-001-sdevice-process-admission.json',
                            process_status_file='step-001-sdevice-process-status.txt',
                            raw_process_admission_exit_file='step-001-sdevice-process-admission-exit-code.txt')})
        return data, evidence

    def test_archive_rechecks_all_tids_wrapper_request_and_failed_capture_preservation(self):
        def escape(obs, admitted, activated, collected):
            obs['native_resources']['tasks'][-1]['status'] = self.status(103, 100, 'sdevice', 3, '8', 101)
        def wrong_request(obs, admitted, activated, collected):
            admitted['requested_threads'] = 1
        def replaced_wrapper(obs, admitted, activated, collected):
            obs['wrapper_resources']['start_ticks'] += 1
        def missing_tid(obs, admitted, activated, collected):
            obs['native_resources']['tasks'].pop()
        for change in (None, escape, wrong_request, replaced_wrapper, missing_tid):
            data, evidence = self.archive(change)
            with tarfile.open(fileobj=data) as archive:
                members = {m.name: m for m in archive}
                if change is None:
                    self.tcad.verify_multicore_archive(archive, members, evidence)
                else:
                    with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                        self.tcad.verify_multicore_archive(archive, members, evidence)
                    if change is replaced_wrapper:
                        with self.assertRaises(ValueError):
                            self.tcad.verify_multicore_archive(archive, members, dict(evidence, remote_exit_code=143))
                    else:
                        self.tcad.verify_multicore_archive(archive, members, dict(evidence, remote_exit_code=143))

    def test_collect_live_audit_failure_never_transfers_or_releases(self):
        record = dict(schema='tcad-native-run-r2', state='EXECUTED', run_id='new',
                      parallel_policy=self.policy, process_identity=self.identity,
                      script_sha256='a' * 64, remote_directory=self.directory)
        with patch.object(self.tcad, 'read_manifest', return_value=(self.tmp, record)), \
                patch.object(self.tcad, 'parallel_query', side_effect=ValueError('Actual task CPU set differs')), \
                patch.object(self.tcad, 'remote') as remote, \
                patch.object(self.tcad, 'parallel_release') as release:
            with self.assertRaisesRegex(ValueError, 'Actual task CPU'):
                self.tcad.collect_run(self.cfg, [], 'new')
            remote.assert_not_called()
            release.assert_not_called()

    def test_actual_observer_preserves_all_os_threads_and_raw_status(self):
        ns = self.protocol()
        native = self.process(ns['proc'])
        wrapper = self.process(ns['proc'], 100, 1, 'bash', 1, '0-1', 10)
        for base in (native, wrapper):
            (base / 'task' / base.name / 'children').write_text('')
        source = self.capture_source('S2_CAPTURE_PROC_PY')
        # Route only /proc through a real temporary tree. Execute the complete
        # actual observer, including exact installed-ELF and ancestry checks.
        source = source.replace('from pathlib import Path', '')
        def mapped_path(value):
            if str(value) == '/proc':
                return ns['proc']
            return Path(value) if str(value).startswith('/') else self.tmp / value
        def readlink(value):
            return '/installed/W-2024.09/bin/sdevice' if str(value).endswith('/exe') else self.directory
        prefix = 'step-001-sdevice'
        with patch.object(sys, 'argv', ['capture', 'sdevice', '101', '100', prefix, '/installed/W-2024.09']), \
                patch('os.getcwd', return_value=self.directory), patch('os.readlink', side_effect=readlink), \
                patch('os.path.realpath', return_value='/installed/W-2024.09'), \
                patch('os.path.isabs', return_value=True), \
                patch('builtins.open', side_effect=lambda *args, **kwargs: io.BytesIO(b'\x7fELF')), \
                patch('sys.stdout', io.StringIO()):
            exec(compile(source, '<full real multicore observer>', 'exec'), dict(Path=mapped_path))
        observed = json.loads((self.tmp / (prefix + '-process-observation.json')).read_text())
        self.assertEqual(observed['status'], 'OBSERVED', observed)
        self.assertEqual(observed['schema'], 'native-process-observation-r2')
        self.assertEqual(observed['native_resources']['threads'], 3)
        self.assertEqual(len(observed['native_resources']['tasks']), 3)
        self.assertEqual((self.tmp / (prefix + '-process-status.txt')).read_bytes(),
                         observed['native_resources']['status'].encode())

    def test_real_protocol_verify_collect_release_and_activate_keep_resource_gates(self):
        # Execute the real protocol main with file/FD plumbing stubbed, while
        # admission and all /proc resource checks run against actual fixtures.
        ns = self.protocol()
        self.process(ns['proc'], 100, 1, 'bash', 1, '0-1', 10)
        lease = self.peer()
        activated = dict(policy=self.policy, identity=self.identity,
                         wrapper_resources=self.snapshot(100, 1, 'bash', 1, '0-1', 10))
        saved = []
        class RemotePath(PurePosixPath):
            def is_file(self):
                return self.name in ('exit-code.txt', 'finished-utc.txt')
            def exists(self):
                return False
            def write_text(self, text):
                saved.append((self.name, text))
        ns.update(root=self.tmp / 'root', Path=RemotePath, safe_path=lambda path: None,
                  opened=lambda path: 10, checked_lease=lambda slot: lease,
                  pool_leases=lambda: [lease], check_pool_capacity=lambda leases: None,
                  held=lambda *args: None, save=lambda path, value: saved.append((path.name, copy.deepcopy(value))))
        ns['root'].mkdir()
        ns['store'] = ns['root'] / '.solver-slots'
        def read(path):
            if path.name == 'process-identity.json':
                return self.identity
            if path.name == 'parallel-slot-evidence.json':
                return activated
            if path.name == 'receipt.json':
                return dict(sha256='b' * 64)
            raise AssertionError(path)
        ns['read'] = read
        main = "safe_path(root);need(root.is_dir()" + self.tcad.PARALLEL_CODE.split(
            "safe_path(root);need(root.is_dir()", 1)[1]
        def run(action):
            ns['action'] = action
            ns['request'] = dict(action=action, policy=self.policy, process_identity=self.identity,
                                 archive_sha256='b' * 64)
            output = io.StringIO()
            with patch.object(ns['os'], 'readlink', return_value=self.directory), \
                    patch('sys.stdout', output):
                exec(compile(main, '<real r4 protocol main>', 'exec'), ns)
            return json.loads(output.getvalue())
        # A fresh activation audits the wrapper before making its lease ACTIVE.
        lease['state'] = 'RESERVED'
        lease.pop('identity')
        with patch.object(ns['os'], 'getppid', return_value=100):
            run('activate')
        activation = next(value for name, value in saved if name == 'parallel-slot-evidence.json')
        self.assertEqual(activation['wrapper_resources']['threads'], 1)
        self.process(ns['proc'])
        self.assertEqual(len(run('verify')['resource_audit']['snapshots']), 2)
        # Terminal collection uses original wrapper evidence after the kernel
        # process has gone; it cannot synthesize a successful activation.
        ns['identity_alive'] = lambda identity: False
        for path in ns['proc'].glob('[0-9]*'):
            # Hide original processes from admission without deleting fixtures.
            (path / 'comm').write_text('finished')
        run('collect')
        collected = next(value for name, value in saved if name == 'parallel-slot-collection-evidence.json')
        self.assertEqual(collected['wrapper_resources'], activated['wrapper_resources'])
        self.assertEqual(run('release')['state'], 'COLLECTED')
        self.assertEqual(lease['archive_sha256'], 'b' * 64)


if __name__ == '__main__':
    unittest.main()
