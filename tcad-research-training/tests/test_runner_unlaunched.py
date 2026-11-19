"""Linux protocol tests with synthetic /proc; no SSH, solver, or VM mutations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@unittest.skipUnless(sys.platform.startswith('linux'), 'Requires Linux /proc, flock, O_NOFOLLOW')
class UnlaunchedProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.tcad = load(ROOT / 'scripts/tcad.py', '_unlaunched_runner')
        self.root = self.tmp / 'pool'
        self.store = self.root / '.solver-slots'
        self.store.mkdir(parents=True)
        self.lock_paths = [self.root / '.solver.lock', self.store / 'allocation.lock'] + [
            self.store / ('slot-%s.lock' % i) for i in range(9)]
        for path in self.lock_paths:
            path.touch()
        self.cfg = dict(backend='ssh-runtime', ssh_target='tcad-sim-tail',
                        runtime_entry='/existing/entry', remote_root=str(self.root), parallel_capacity=9)
        self.label = 'never-launched'
        self.directory = self.root / 'dram-see-v4/transport-probe/operations' / self.label
        self.directory.parent.mkdir(parents=True)
        self.policy = self.tcad.parallel_policy(self.cfg, 1, self.label, str(self.directory), 'operation')
        self.request = dict(policy=self.policy, action='prove-unlaunched',
                            script_sha256='a' * 64, subject_sha256='b' * 64)
        self.proc = self.tmp / 'proc'
        (self.proc / 'sys/kernel/random').mkdir(parents=True)
        (self.proc / 'sys/kernel/random/boot_id').write_text('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.process(1, 0)
        self.process(100, 1)
        self.write_capacity('tcad-shared-gate-slots-r5')
        # All five generations of COLLECTED history share the same original pool.
        for index, capacity in enumerate((2, 4, 3, 7, 9)):
            cfg = dict(self.cfg, parallel_capacity=capacity)
            slot = index
            if capacity in (2, 4):
                threads = 4 if capacity == 2 else 2
                cfg.update(requested_threads=threads,
                           cpu_sets=[list(range(i * threads, (i + 1) * threads)) for i in range(capacity)])
            work = 'history-%s' % index
            policy = self.tcad.parallel_policy(cfg, slot, work, str(self.root / 'runs' / work))
            self.write_lease(index, dict(policy=policy, state='COLLECTED', script_sha256='c' * 64))
        self.ns = {}
        source = self.tcad.PARALLEL_CODE.split("safe_path(root);need(root.is_dir()")[0]
        with patch.object(sys, 'argv', ['protocol', json.dumps(self.request)]):
            exec(compile(source, '<original protocol definitions>', 'exec'), self.ns)
        self.ns['proc'] = self.proc
        real_os = self.ns['os']
        self.ns['os'] = types.SimpleNamespace(**{name: getattr(real_os, name) for name in dir(real_os)})
        self.ns['os'].getpid = lambda: 100

    def write_capacity(self, schema):
        self.capacity = self.store / 'capacity.json'
        self.capacity.write_text(json.dumps(self.tcad._MULTICORE_HELPERS['mc_pool_configuration'](schema)))

    def write_lease(self, index, value):
        (self.store / ('slot-%s.json' % index)).write_text(json.dumps(value, indent=2))

    def process(self, pid, parent, name='python', cwd=None, cmdline=b'python proof'):
        path = self.proc / str(pid)
        path.mkdir(exist_ok=True)
        fields = ['0'] * 22
        fields[0], fields[1], fields[19] = 'R', str(parent), str(1000 + pid)
        (path / 'stat').write_text('%s (%s) %s' % (pid, name, ' '.join(fields)))
        (path / 'comm').write_text(name)
        (path / 'cmdline').write_bytes(cmdline)
        (path / 'cwd').symlink_to(cwd or self.tmp)
        return path

    def proof(self):
        return self.ns['prove_unlaunched']()

    def files(self):
        return {str(p.relative_to(self.root)): (p.stat().st_ino, p.read_bytes())
                for p in self.root.rglob('*') if p.is_file()}

    def test_mixed_r1_to_r5_history_read_without_any_pool_or_lock_write(self):
        before = self.files()
        proof = self.proof()
        self.assertEqual(proof['locked_slots'], list(range(9)))
        self.assertEqual(proof['gate_mode'], 'EXCLUSIVE')
        self.assertEqual(proof['pool_snapshot']['capacity']['record']['capacity'], 2)
        canonical = json.dumps(proof['pool_snapshot'], sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(proof['pool_snapshot_sha256'], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(proof['subject_sha256'], 'b' * 64)
        for item in proof['pool_snapshot']['leases'].values():
            if item is not None:
                raw = bytes.fromhex(item['raw_hex'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item['sha256'])
                self.assertEqual(json.loads(raw), item['record'])
        self.assertEqual(self.files(), before)

    def test_remote_generated_proof_passes_the_independent_runtime_validator(self):
        validator = load(ROOT / 'experiments/dram-see-v4/transport-probe/launch_reconciliation.py',
                         '_unlaunched_independent_validator')
        subject = dict(label=self.label, remote_directory=str(self.directory),
                       parallel_policy=self.policy, connection_identity=self.tcad.connection_identity(self.cfg),
                       script_sha256='a' * 64)
        self.ns['request']['subject_sha256'] = validator.canonical_sha256(subject)
        self.assertTrue(validator.validate_proof(self.proof(), subject))

    def test_tenth_slot_history_and_lock_are_covered_by_extended_proof(self):
        (self.store / 'slot-9.lock').touch()
        self.write_capacity('tcad-shared-gate-slots-r8')
        cfg = dict(self.cfg, parallel_capacity=10, requested_threads=1,
                   cpu_sets=[[cpu] for cpu in range(10)])
        policy = self.tcad.parallel_policy(cfg, 9, 'history-ten', str(self.root / 'runs/history-ten'))
        self.write_lease(9, dict(policy=policy, state='COLLECTED', script_sha256='c' * 64))
        validator = load(ROOT / 'experiments/dram-see-v4/transport-probe/launch_reconciliation.py',
                         '_extended_unlaunched_validator')
        subject = dict(label=self.label, remote_directory=str(self.directory),
                       parallel_policy=self.policy, connection_identity=self.tcad.connection_identity(self.cfg),
                       script_sha256='a' * 64)
        self.ns['request']['subject_sha256'] = validator.canonical_sha256(subject)
        proof = self.proof()
        self.assertEqual(proof['locked_slots'], list(range(10)))
        self.assertTrue(validator.validate_proof(proof, subject))
        import fcntl
        with (self.store / 'slot-9.lock').open('rb') as busy:
            fcntl.flock(busy, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.proof()

    def use_intent_profile(self):
        cfg = dict(self.cfg, parallel_capacity=4, requested_threads=2,
                   cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]])
        directory = self.root / 'runs' / self.label
        directory.parent.mkdir(exist_ok=True)
        policy = self.tcad.parallel_policy(cfg, 0, self.label, str(directory))
        self.ns['policy'] = policy
        self.ns['action'] = 'prove-unlaunched-intent'
        self.ns['request'].update(policy=policy, action='prove-unlaunched-intent', script_sha256=None)
        return cfg, directory, policy

    def test_r4_intent_proof_is_independent_and_does_not_write_pool(self):
        _, directory, policy = self.use_intent_profile()
        before = self.files()
        validator = load(ROOT / 'automation/server-codex/intent_reconciliation.py', '_intent_validator')
        shared = validator.verifier(ROOT)
        subject = dict(schema='tcad-pre-manifest-intent-subject-r1', label=self.label,
                       remote_directory=str(directory), parallel_policy=policy,
                       connection_identity=policy['connection_identity'], script_sha256=None)
        self.ns['request']['subject_sha256'] = shared.canonical_sha256(subject)
        proof = self.proof()
        self.assertIsNone(proof['script_sha256'])
        self.assertEqual(proof['schema'], validator.PROOF_SCHEMA)
        self.assertTrue(validator.validate_proof(ROOT, proof, subject))
        self.assertEqual(self.files(), before)
        with self.assertRaises(ValueError):
            shared.validate_proof(proof, subject)
        with self.assertRaises(ValueError):
            shared.validate_proof(dict(proof, schema=shared.PROOF_SCHEMA, action='prove-unlaunched'), subject)

    def test_intent_proof_refuses_wrapper_sha_and_old_proof_refuses_null(self):
        self.ns['request']['script_sha256'] = None
        with self.assertRaises(ValueError):
            self.proof()
        self.use_intent_profile()
        self.ns['request']['script_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'wrapper SHA'):
            self.proof()

    def test_intent_directory_lease_and_noncanonical_policy_are_refused(self):
        _, directory, policy = self.use_intent_profile()
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, 'directory/claim'):
            self.proof()
        directory.rmdir()
        self.write_lease(0, dict(policy=policy, state='COLLECTED', script_sha256='a' * 64))
        with self.assertRaisesRegex(ValueError, 'already has a lease'):
            self.proof()

    def test_proof_ssh_is_selected_only_for_prove_unlaunched(self):
        record = dict(label=self.label, remote_directory=str(self.directory),
                      parallel_policy=self.policy, script_sha256='a' * 64)
        calls = []
        self.tcad.remote_python = lambda ssh, code, args: calls.append(ssh) or {
            'policy': self.policy}
        proof_ssh = ['ssh', '-F', '/etc/tcad-centos79/ssh_config', 'tcad-guest-root']
        with patch.object(self.tcad.os, 'geteuid', return_value=0):
            self.tcad.parallel_query(self.cfg, ['sim'], record, 'prove-unlaunched',
                                     proof_subject_sha256='b' * 64, proof_ssh=proof_ssh)
        self.assertEqual(calls, [proof_ssh])
        with self.assertRaisesRegex(ValueError, 'only valid'):
            self.tcad.parallel_query(self.cfg, ['sim'], record, 'verify',
                                     proof_ssh=proof_ssh)
        with patch.object(self.tcad.os, 'geteuid', return_value=1000), \
                self.assertRaisesRegex(PermissionError, 'euid 0'):
            self.tcad.parallel_query(self.cfg, ['sim'], record, 'prove-unlaunched',
                                     proof_subject_sha256='b' * 64, proof_ssh=proof_ssh)

    def test_target_directory_and_claim_are_rejected(self):
        self.directory.mkdir()
        with self.assertRaisesRegex(ValueError, 'directory/claim'):
            self.proof()
        (self.directory / '.launch-claim').mkdir()
        with self.assertRaisesRegex(ValueError, 'directory/claim'):
            self.proof()

    def test_target_collected_lease_is_also_rejected(self):
        self.write_lease(1, dict(policy=self.policy, state='COLLECTED', script_sha256='a' * 64))
        with self.assertRaisesRegex(ValueError, 'already has a lease'):
            self.proof()

    def test_any_noncollected_slot_even_outside_original_active_capacity_rejects(self):
        for state in ('RESERVED', 'ACTIVE', 'UNKNOWN'):
            path = self.store / 'slot-4.json'
            lease = json.loads(path.read_bytes())
            lease['state'] = state
            self.write_lease(4, lease)
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.proof()

    def test_all_eleven_locks_busy_fail_closed_and_remain_intact(self):
        import fcntl
        before = self.files()
        for path in self.lock_paths:
            with path.open('rb') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.subTest(path=path.name), self.assertRaises(BlockingIOError):
                    self.proof()
        self.assertEqual(self.files(), before)
        self.proof()  # All partial acquisitions were closed after failures.

    def test_missing_lock_never_gets_created(self):
        self.lock_paths[-1].unlink()
        with self.assertRaises(FileNotFoundError):
            self.proof()
        self.assertFalse(self.lock_paths[-1].exists())

    def test_dangling_target_lease_capacity_lock_and_parent_links_refused(self):
        for path in (self.directory, self.store / 'slot-8.json', self.capacity,
                     self.lock_paths[-1], self.directory.parent):
            saved = path.read_bytes() if path.is_file() else None
            was_dir = path.is_dir()
            if path.exists():
                path.rmdir() if was_dir else path.unlink()
            path.symlink_to(self.tmp / 'missing', target_is_directory=was_dir)
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.proof()
            path.unlink()
            if saved is not None:
                path.write_bytes(saved)
            elif was_dir:
                path.mkdir()

    def test_native_target_command_and_target_cwd_refused(self):
        for name, command, cwd in (('sdevice', b'native', None),
                                   ('transport_probe', b'native', None),
                                   ('python', self.label.encode(), None),
                                   ('bash', b'bash run.sh', self.directory)):
            process = self.process(200, 1, name, cwd, command)
            with self.subTest(name=name, command=command), self.assertRaises(ValueError):
                self.proof()
            for path in process.iterdir():
                path.unlink()
            process.rmdir()

    def test_permission_partial_unknown_boot_and_unknown_descriptor_refused(self):
        original = self.ns['os'].readlink
        self.ns['os'].readlink = lambda path: (_ for _ in ()).throw(PermissionError('cwd unavailable'))
        with self.assertRaises(PermissionError):
            self.proof()
        self.ns['os'].readlink = original
        (self.proc / '100/comm').unlink()
        with self.assertRaisesRegex(ValueError, 'partial process'):
            self.proof()
        (self.proc / '100/comm').write_text('python')
        (self.proc / 'sys/kernel/random/boot_id').write_text('unknown')
        with self.assertRaisesRegex(ValueError, 'boot'):
            self.proof()
        (self.proc / 'sys/kernel/random/boot_id').write_text('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.capacity.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Unknown pool'):
            self.proof()

    def test_unknown_slot_and_foreign_collected_identity_refused(self):
        unmatched = self.store / 'slot-10.json'
        unmatched.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Extended lease has no original slot lock'):
            self.proof()
        unmatched.unlink()
        extra = self.store / 'slot-99.json'
        extra.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Unknown slot'):
            self.proof()
        extra.unlink()
        path = self.store / 'slot-0.json'
        record = json.loads(path.read_bytes())
        record['policy']['connection_identity']['ssh_target'] = 'foreign'
        self.write_lease(0, record)
        with self.assertRaisesRegex(ValueError, 'Foreign historical'):
            self.proof()

    def test_entire_public_protocol_dispatch_exits_without_creating_or_changing_files(self):
        before = self.files()
        # /proc fixture affects only this offline subprocess. The exact dispatch,
        # lock acquisition and snapshot code are the production PARALLEL_CODE.
        code = self.tcad.PARALLEL_CODE.replace("proc=Path('/proc')", 'proc=Path(%r)' % str(self.proc))
        # The fixture uses 100/1 as the remote proof's ancestry.
        code = code.replace('own=os.geteuid();ancestors=set();pid=os.getpid()',
                            'own=os.geteuid();ancestors=set();pid=100')
        result = subprocess.run([sys.executable, '-B', '-c', code, json.dumps(self.request)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'NOT_LAUNCHED')
        self.assertEqual(before, self.files())

    @unittest.skipUnless(hasattr(os, 'geteuid') and os.geteuid() == 0,
                         'All-UID real /proc evidence requires inspection permission')
    def test_real_linux_proc_and_real_flock_in_isolated_offline_environment(self):
        before = self.files()
        result = subprocess.run([sys.executable, '-B', '-c', self.tcad.PARALLEL_CODE,
                                 json.dumps(self.request)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        proof = json.loads(result.stdout)
        self.assertGreater(proof['process_scan']['checked_processes'], 0)
        self.assertEqual(proof['process_scan']['scope'], 'all-uid-native-cmdline-cwd')
        self.assertEqual(before, self.files())


if __name__ == '__main__':
    unittest.main()
