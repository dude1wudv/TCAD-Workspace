"""Offline r5 contracts using the same shared runner and /proc fixtures as r4."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import types
import unittest
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    '_quadcore_fixture_module', Path(__file__).with_name('test_runner_multicore.py'))
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


class QuadcoreTests(unittest.TestCase):
    stat = staticmethod(_fixtures.MulticoreTests.stat)
    status = staticmethod(_fixtures.MulticoreTests.status)
    protocol = _fixtures.MulticoreTests.protocol
    process = _fixtures.MulticoreTests.process
    peer = _fixtures.MulticoreTests.peer
    capture_source = _fixtures.MulticoreTests.capture_source
    observed = _fixtures.MulticoreTests.observed

    def setUp(self):
        _fixtures.MulticoreTests.setUp(self)
        self.r4_cfg = copy.deepcopy(self.cfg)
        self.r4_policy = copy.deepcopy(self.policy)
        self.cfg.update(parallel_capacity=2, requested_threads=4,
                        cpu_sets=[[0, 1, 2, 3], [4, 5, 6, 7]])
        self.policy = self.tcad.parallel_policy(self.cfg, 0, 'new', self.directory)

    def snapshot(self, pid=101, ppid=100, name='sdevice', threads=5, cpus='0-3', ticks=20):
        # Reuse real kernel-shaped fixtures, keeping resource metadata consistent.
        if cpus == '0-1':
            cpus = '0-3'
        value = _fixtures.MulticoreTests.snapshot(self, pid, ppid, name, threads, cpus, ticks)
        value['cpu_set'] = [0, 1, 2, 3]
        return value

    def test_r5_exact_layout_and_r4_identity_cannot_be_reinterpreted(self):
        for slot in (0, 1):
            policy = self.tcad.parallel_policy(self.cfg, slot, 'new', self.directory)
            self.assertEqual(policy['schema'], 'tcad-shared-gate-slots-r5')
            self.assertEqual(policy['capacity'], 2)
            self.assertEqual(policy['cpu_set'], list(range(slot * 4, slot * 4 + 4)))
            self.assertEqual(policy['requested_threads'], 4)
            self.assertEqual(policy['pool_root'], self.r4_policy['pool_root'])
            self.helpers['mc_policy'](policy)
        for changes in (
                {'requested_threads': 2}, {'requested_threads': True},
                {'cpu_sets': [[0, 1, 2, 3], [3, 4, 5, 6]]},
                {'cpu_sets': [[False, 1, 2, 3], [4, 5, 6, 7]]},
                {'cpu_sets': [[0, 1, 2, 3], [4, 5, 6, 8]]},
                {'parallel_capacity': 4}, {'parallel_capacity': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.tcad.parallel_capacity(dict(self.cfg, **changes))
        for slot in (2, -1, True, '0'):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                self.tcad.parallel_policy(self.cfg, slot, 'new', self.directory)
        for policy in (self.policy, self.r4_policy):
            for key, value in (
                    ('requested_threads', 2 if policy is self.policy else 4),
                    ('schema', 'tcad-shared-gate-slots-r4' if policy is self.policy
                     else 'tcad-shared-gate-slots-r5'),
                    ('cpu_set', [0, 1, 2, 8]), ('capacity', True)):
                with self.subTest(key=key, policy=policy), self.assertRaises(ValueError):
                    self.helpers['mc_policy'](dict(policy, **{key: value}))
        record = dict(run_id='new', remote_directory=self.directory, parallel_policy=self.r4_policy)
        with self.assertRaisesRegex(ValueError, 'parallel slot'):
            self.tcad.parallel_record_policy(self.cfg, record)
        directory = self.cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/new'
        with self.assertRaisesRegex(ValueError, 'does not admit Geant4'):
            self.tcad.parallel_policy(self.cfg, 0, 'new', directory, 'operation')

    def test_pool_switch_both_directions_requires_idle_all_nine_locks(self):
        ns = self.protocol()
        ns['store'] = self.tmp / 'slots'
        ns['store'].mkdir()
        (ns['store'] / 'capacity.json').write_text('{}')
        ns['admission'] = lambda leases: []
        for requested, previous in ((self.policy, self.r4_policy), (self.r4_policy, self.policy)):
            ns['policy'] = requested
            descriptor = self.helpers['mc_pool_configuration'](previous['schema'])
            ns['read'] = lambda path: descriptor
            for state in ('RESERVED', 'ACTIVE'):
                with self.subTest(direction=requested['schema'], state=state), \
                        self.assertRaisesRegex(ValueError, 'outstanding'):
                    ns['check_pool_capacity']([dict(policy=previous, state=state)])
            opened = []
            ns['opened'] = lambda path: opened.append(path.name) or len(opened)
            ns['action'] = 'reserve'
            with patch.object(ns['os'], 'close'):
                ns['check_pool_capacity']([dict(policy=previous, state='COLLECTED')])
            self.assertEqual(opened, ['slot-%s.lock' % i for i in range(9)])
            opened.clear()
            ns['action'] = 'verify'
            ns['check_pool_capacity']([dict(policy=requested, state='COLLECTED')])
            self.assertEqual(opened, [])
        ns['policy'] = self.policy
        ns['action'] = 'reserve'
        for key, invalid in (('requested_threads', True), ('capacity', True),
                             ('cpu_sets', [[0, 1, 2, 3], [4, 5, 6, True]])):
            descriptor = dict(self.helpers['mc_pool_configuration'](self.policy['schema']),
                              **{key: invalid})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'Malformed pool'):
                ns['check_pool_capacity']([])

    def test_r5_requested_available_cpus_and_all_tid_affinity_are_audited(self):
        ns = self.protocol()
        self.process(ns['proc'], 100, 1, 'bash', 1, '0-3', 10)
        native = self.process(ns['proc'], threads=5, cpus='0-3')
        with patch.object(ns['os'], 'readlink', return_value=self.directory):
            audit = ns['admission']([self.peer()])
            self.assertEqual([item['role'] for item in audit], ['wrapper', 'native'])
            self.assertEqual(audit[-1]['snapshot']['threads'], 5)
            (native / 'task/103/status').write_text(self.status(103, 100, 'sdevice', 5, '8', 101))
            with self.assertRaisesRegex(ValueError, 'Actual task CPU'):
                ns['admission']([self.peer()])
        with patch.object(ns['os'], 'sched_getaffinity', return_value={0, 1, 2}, create=True):
            with self.assertRaisesRegex(ValueError, 'CPU is not available'):
                ns['available_cpu']()

    def test_r5_wrapper_metadata_environment_and_non_sdevice_stay_single_thread(self):
        self.tcad.ROOT = self.tmp
        self.tcad.STATE_ROOT = self.tmp / 'state'
        project = self.tmp / 'input'
        project.mkdir()
        spec = dict(name='quadcore-probe', native_threads=4, native_cores=4, steps=[
            dict(tool='snmesh', args=['mesh'], outputs=['mesh.tdr']),
            dict(tool='sdevice', args=['device.cmd'], outputs=['probe.plt']),
            dict(tool='snmesh', args=['post'], outputs=['post.tdr'])])
        (project / 'project.json').write_text(json.dumps(spec))
        with patch.object(self.tcad, 'parallel_query'), patch.object(self.tcad, 'remote'), \
                patch.object(self.tcad, 'execute', return_value=types.SimpleNamespace(stdout='commit')), \
                patch.object(self.tcad.subprocess, 'run', return_value=types.SimpleNamespace(
                    stdout=b'', stderr=b'', returncode=0)), \
                patch.object(self.tcad, 'status_run', return_value={'status': 'FIXTURE'}):
            self.tcad._run_project(self.cfg, [], project, 'new', True, parallel_slot=1)
        folder = self.tcad.run_folder('new')
        script = (folder / 'run.sh').read_text()
        self.assertIn('cpu=4,5,6,7\ntaskset -pc "$cpu" $$', script)
        self.assertIn('sdevice --threads 4 --exit-on-failure device.cmd', script)
        self.assertIn('flock -s -n 9', script)
        self.assertIn('/.solver-slots/slot-1.lock', script)
        self.assertIn(self.cfg['remote_root'] + '/.solver.lock', script)
        environment_lines = [line for line in script.splitlines()
                             if line.startswith('export OMP_NUM_THREADS=')]
        self.assertEqual(environment_lines, [
            'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1',
            'export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1',
            'export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4',
            'export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1'])
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertEqual(manifest['requested_resources'], dict(
            cpu_set=[4, 5, 6, 7], requested_threads=4,
            sdevice_environment=dict(OMP_NUM_THREADS=4, MKL_NUM_THREADS=4, OPENBLAS_NUM_THREADS=1)))
        self.assertEqual([item['requested_threads'] for item in manifest['tool_evidence'].values()],
                         [1, 4, 1])
        for key in ('native_threads', 'native_cores'):
            wrong = dict(spec, **{key: 2})
            (project / 'project.json').write_text(json.dumps(wrong))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'metadata'):
                self.tcad._run_project(self.cfg, [], project, 'other', True, parallel_slot=0)
        with self.assertRaisesRegex(ValueError, 'explicit parallel slot'):
            self.tcad._run_project(self.cfg, [], project, 'other', True)

    def test_embedded_python36_and_r5_admission_preserve_request_and_reject_escape(self):
        source = self.capture_source('S2_CAPTURE_ADMIT_PY')
        for code in (self.tcad.PARALLEL_CODE, source, self.capture_source('S2_CAPTURE_PROC_PY')):
            ast.parse(code, feature_version=(3, 6))
        for escape in (False, True):
            folder = self.tmp / str(escape)
            folder.mkdir()
            observed = self.observed()
            if escape:
                task = observed['native_resources']['tasks'][-1]
                task['status'] = task['status'].replace('0-3', '8')
            prefix = str(folder / 'step-001-sdevice')
            Path(prefix + '-process-observation.json').write_text(json.dumps(observed))
            Path(prefix + '-process-status.txt').write_bytes(observed['native_resources']['status'].encode())
            with patch.object(sys, 'argv', ['admit', prefix, 'sdevice', '0,1,2,3']), \
                    patch('os.getcwd', return_value=self.directory), patch('sys.stdout', io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    exec(compile(source, '<r5 real native admission>', 'exec'), {})
            report = json.loads(Path(prefix + '-process-admission.json').read_text())
            self.assertEqual(caught.exception.code, 86 if escape else 0, report)
            self.assertEqual(report['requested_threads'], 4)

    def test_r5_non_sdevice_admission_requires_single_thread(self):
        source = self.capture_source('S2_CAPTURE_ADMIT_PY')
        for count in (1, 2):
            folder = self.tmp / str(count)
            folder.mkdir()
            observed = self.observed()
            observed['requested_tool'] = 'snmesh'
            observed['native_resources'] = self.snapshot(name='snmesh', threads=count)
            raw = observed['native_resources']['status'].encode()
            observed['status_sha256'] = hashlib.sha256(raw).hexdigest()
            prefix = str(folder / 'step-001-snmesh')
            Path(prefix + '-process-observation.json').write_text(json.dumps(observed))
            Path(prefix + '-process-status.txt').write_bytes(raw)
            with patch.object(sys, 'argv', ['admit', prefix, 'snmesh', '0,1,2,3']), \
                    patch('os.getcwd', return_value=self.directory), patch('sys.stdout', io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    exec(compile(source, '<r5 real single-thread tool admission>', 'exec'), {})
            report = json.loads(Path(prefix + '-process-admission.json').read_text())
            self.assertEqual(caught.exception.code, 0 if count == 1 else 86, report)
            self.assertEqual(report['requested_threads'], 1)

    def test_r5_archive_request_affinity_and_failed_capture_are_rechecked(self):
        for alteration in (None, 'request', 'escape', 'wrapper'):
            def changed(observed, admitted, activated, collected):
                admitted.update(requested_threads=4, requested_cpu='0,1,2,3')
                if alteration == 'request':
                    admitted['requested_threads'] = 2
                elif alteration == 'escape':
                    observed['native_resources']['tasks'][-1]['status'] = \
                        observed['native_resources']['tasks'][-1]['status'].replace('0-3', '8')
                elif alteration == 'wrapper':
                    observed['wrapper_resources']['start_ticks'] += 1
            data, evidence = _fixtures.MulticoreTests.archive(self, changed)
            with tarfile.open(fileobj=data) as archive:
                members = {member.name: member for member in archive}
                if alteration is None:
                    self.tcad.verify_multicore_archive(archive, members, evidence)
                else:
                    with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                        self.tcad.verify_multicore_archive(archive, members, evidence)
                    if alteration == 'wrapper':
                        with self.assertRaises(ValueError):
                            self.tcad.verify_multicore_archive(
                                archive, members, dict(evidence, remote_exit_code=143))
                    else:
                        self.tcad.verify_multicore_archive(
                            archive, members, dict(evidence, remote_exit_code=143))

    def test_r5_live_audit_missing_or_bad_never_transfers_or_releases(self):
        _fixtures.MulticoreTests.test_status_returns_live_audit_and_missing_audit_cannot_poison_manifest(self)
        _fixtures.MulticoreTests.test_collect_live_audit_failure_never_transfers_or_releases(self)

    def test_r5_real_protocol_activate_verify_collect_release(self):
        # Base test runs actual protocol main; fixtures map its old CPU shorthand
        # to r5 and preserve all wrapper/original identity checks.
        _fixtures.MulticoreTests.test_real_protocol_verify_collect_release_and_activate_keep_resource_gates(self)


if __name__ == '__main__':
    unittest.main()
