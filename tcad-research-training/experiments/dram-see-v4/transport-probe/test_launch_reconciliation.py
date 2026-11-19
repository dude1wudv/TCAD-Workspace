"""Synthetic software-contract checks; no SSH, native solving or science proof."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class LaunchReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.v = load(HERE / 'launch_reconciliation.py', '_receipt_test')
        self.op = load(HERE / 'operation.py', '_receipt_operation_test')
        self.tcad = load(ROOT / 'scripts/tcad.py', '_receipt_runner_test')
        self.cfg = dict(backend='ssh-runtime', ssh_target='tcad-sim-tail',
                        runtime_entry='/existing/entry', remote_root='/existing/pool',
                        parallel_capacity=9, tool_bin='/existing/tools')
        self.profile = self.tmp / 'profile.json'
        self.profile.write_text(json.dumps(self.cfg), encoding='utf-8')
        self.tcad.CONFIG = self.profile
        self.op.RUNTIME = self.tmp / 'runtime'
        self.label = 'original-never-launched'
        self.folder = self.op.operation_folder(self.label)
        self.folder.mkdir(parents=True)
        self.inputs = self.tmp / 'inputs'
        self.inputs.mkdir()
        self.task = b'# SYNTHETIC SOFTWARE FIXTURE; NOT A SOLVER\n'
        (self.inputs / 'task.sh').write_bytes(self.task)
        (self.inputs / 'physics-input.dat').write_bytes(b'frozen fixture input')
        (self.folder / 'run.sh').write_bytes(b'# frozen wrapper fixture\n')
        with tarfile.open(self.folder / 'inputs.tar', 'w:') as archive:
            for path in sorted(self.inputs.iterdir()):
                archive.add(path, arcname=path.name)
        directory = self.cfg['remote_root'] + '/dram-see-v4/transport-probe/operations/' + self.label
        self.record = dict(schema=self.op.SCHEMA, label=self.label,
                           state='FAILED_BEFORE_LAUNCH', submission_phase='REMOTE_STAGING',
                           remote_directory=directory, input_directory=str(self.inputs),
                           input_sha256={p.name: self.op.sha(p) for p in self.inputs.iterdir()},
                           inputs_archive_sha256=self.op.sha(self.folder / 'inputs.tar'),
                           script_sha256=self.op.sha(self.folder / 'run.sh'),
                           wrapper_sha256=self.op.sha(self.folder / 'run.sh'),
                           runner_sha256='a' * 64, adapter_sha256='b' * 64,
                           remote_exit_code=None, collection_exit_code=None,
                           operation_task_exit_code=None, collection_verified=False,
                           ssh_exit_code=1, error='original reserve failed',
                           tool_exit_codes={}, synthetic=False, origin='native_pipeline',
                           connection_identity=self.tcad.connection_identity(self.cfg),
                           parallel_policy=self.tcad.parallel_policy(self.cfg, 0, self.label, directory, 'operation'))
        self.write_record()

    def write_record(self):
        (self.folder / 'operation.json').write_text(json.dumps(self.record, indent=2) + '\n', encoding='utf-8')

    def subject(self):
        return self.v.frozen_subject(self.cfg, self.record, self.folder, self.profile)

    @staticmethod
    def snapshot_file(record):
        raw = json.dumps(record, indent=2).encode()
        return dict(record=record, sha256=hashlib.sha256(raw).hexdigest(), raw_hex=raw.hex())

    def proof(self, subject=None):
        subject = subject or self.subject()
        snapshot = dict(leases={'slot-%s.json' % i: None for i in range(9)},
                        capacity=self.snapshot_file(dict(schema='tcad-slot-pool-r3', capacity=2,
                            requested_threads=4, cpu_sets=[[0, 1, 2, 3], [4, 5, 6, 7]])))
        return dict(schema=self.v.PROOF_SCHEMA, action='prove-unlaunched', status='NOT_LAUNCHED',
                    policy=subject['parallel_policy'], subject_sha256=self.v.canonical_sha256(subject),
                    script_sha256=subject['script_sha256'], boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    observed_utc='2026-11-17T00:00:00+00:00', reservation_acquired=False,
                    solver_launched=False, success=False, directory_exists=False, launch_claim_exists=False,
                    gate_mode='EXCLUSIVE', allocator_mode='EXCLUSIVE', locked_slots=list(range(9)),
                    pool_snapshot=snapshot, pool_snapshot_sha256=self.v.canonical_sha256(snapshot),
                    process_scan=dict(scope='all-uid-native-cmdline-cwd', owner_uid=1000,
                                      checked_processes=2, probe_ancestor_pids=[1, 10]))

    def reconcile(self, proof=None):
        with patch.object(self.tcad, 'parallel_query', return_value=proof or self.proof()) as query:
            result = self.op.reconcile_unlaunched_operation(self.tcad, self.cfg, [], self.label)
        return result, query

    def test_absent_receipt_is_false(self):
        self.assertFalse(self.v.verified_unlaunched_receipt(self.cfg, self.record, self.folder))
        self.assertFalse(self.op.verified_unlaunched_receipt(self.cfg, self.record, self.folder))

    def test_legal_receipt_is_verified_and_manifest_remains_byte_identical(self):
        original = (self.folder / 'operation.json').read_bytes()
        result, query = self.reconcile()
        self.assertEqual(result['status'], 'not_launched')
        for key in ('reservation_acquired', 'solver_launched', 'success'):
            self.assertIs(result[key], False)
        self.assertEqual(query.call_args.args[-1], 'prove-unlaunched')
        self.assertEqual(query.call_args.kwargs['proof_subject_sha256'],
                         self.v.canonical_sha256(self.subject()))
        self.assertTrue(self.op.verified_unlaunched_receipt(self.cfg, self.record, self.folder))
        self.assertEqual((self.folder / 'operation.json').read_bytes(), original)
        self.assertEqual({p.name for p in self.folder.iterdir()},
                         {'operation.json', 'inputs.tar', 'run.sh', self.v.RECEIPT})
        self.assertNotIn('parallel_slot_released', self.record)

    def test_repeat_is_idempotent_without_remote_or_receipt_rewrite(self):
        self.reconcile()
        path = self.folder / self.v.RECEIPT
        original, modified = path.read_bytes(), path.stat().st_mtime_ns
        _, query = self.reconcile()
        query.assert_not_called()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_status_uses_verified_receipt_without_remote_or_manifest_write(self):
        self.reconcile()
        original = (self.folder / 'operation.json').read_bytes()
        with patch.object(self.tcad, 'parallel_query', side_effect=AssertionError('must not query')):
            result = self.op.status_operation(self.tcad, self.cfg, [], self.label)
        self.assertEqual(result['status'], 'NOT_LAUNCHED')
        self.assertIs(result['success'], False)
        self.assertEqual((self.folder / 'operation.json').read_bytes(), original)

    def test_rejects_phase_state_and_launch_or_collection_evidence(self):
        original = copy.deepcopy(self.record)
        for key, value in (
                ('submission_phase', 'LAUNCH'), ('submission_phase', 'INPUT_FREEZE'),
                ('state', 'LAUNCH_REQUESTED'), ('state', 'COLLECTED_PENDING_AUDIT'),
                ('state', 'FAILED_COLLECTED'), ('remote_exit_code', 0),
                ('process_identity', {'pid': 123}), ('last_observation', {'status': 'RUNNING'}),
                ('parallel_slot_released', True), ('collection_verified', True),
                ('collection_attempts', [{'attempt': 1}]), ('tool_exit_codes', {'native': 0})):
            with self.subTest(key=key, value=value):
                self.record = dict(original, **{key: value})
                self.write_record()
                with patch.object(self.tcad, 'parallel_query') as query, self.assertRaises(ValueError):
                    self.op.reconcile_unlaunched_operation(self.tcad, self.cfg, [], self.label)
                query.assert_not_called()
        self.record = original
        self.write_record()

    def test_manifest_whole_bytes_and_supplied_record_are_bound(self):
        self.reconcile()
        path = self.folder / 'operation.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'subject changed'):
            self.v.verified_unlaunched_receipt(self.cfg, self.record, self.folder)
        self.write_record()
        with self.assertRaisesRegex(ValueError, 'supplied record'):
            self.v.verified_unlaunched_receipt(self.cfg, dict(self.record, error='different'), self.folder)

    def test_profile_bytes_connection_policy_and_original_hashes_are_bound(self):
        self.reconcile()
        raw = self.profile.read_bytes()
        self.profile.write_bytes(raw + b'\n')
        with self.assertRaises(ValueError):
            self.v.verified_unlaunched_receipt(self.cfg, self.record, self.folder)
        self.profile.write_bytes(raw)
        for cfg in (dict(self.cfg, ssh_target='other'), dict(self.cfg, parallel_capacity=4),
                    dict(self.cfg, remote_root='/elsewhere')):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                self.v.verified_unlaunched_receipt(cfg, self.record, self.folder)
        for key in ('script_sha256', 'wrapper_sha256', 'inputs_archive_sha256', 'runner_sha256'):
            previous = self.record[key]
            self.record[key] = 'c' * 64
            self.write_record()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.v.verified_unlaunched_receipt(self.cfg, self.record, self.folder)
            self.record[key] = previous
        self.write_record()

    def test_input_archive_wrapper_and_member_drift_rejected(self):
        for path in (self.inputs / 'physics-input.dat', self.folder / 'inputs.tar', self.folder / 'run.sh'):
            original = path.read_bytes()
            path.write_bytes(original + b'drift')
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.subject()
            path.write_bytes(original)
        extra = self.inputs / 'new-input.dat'
        extra.write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.subject()

    def test_self_consistent_archive_with_wrong_members_is_rejected(self):
        with tarfile.open(self.folder / 'inputs.tar', 'w:') as archive:
            for name, raw in (('task.sh', self.task), ('extra.dat', b'unknown')):
                member = tarfile.TarInfo(name)
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        self.record['inputs_archive_sha256'] = self.op.sha(self.folder / 'inputs.tar')
        self.write_record()
        with self.assertRaisesRegex(ValueError, 'member SHA'):
            self.subject()

    def test_local_launch_claim_and_outputs_are_refused(self):
        for name in ('.launch-claim', 'results.tar', 'stdout.txt', 'stderr.txt', 'exit-code.txt'):
            path = self.folder / name
            path.touch()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'artifact exists'):
                self.subject()
            path.unlink()

    def test_remote_uncertainty_and_incomplete_evidence_never_write_receipt(self):
        good = self.proof()
        for key, value in (('directory_exists', True), ('launch_claim_exists', True),
                           ('reservation_acquired', True), ('success', True),
                           ('locked_slots', list(range(8))), ('gate_mode', 'SHARED'),
                           ('boot_id', None), ('pool_snapshot_sha256', '0' * 64),
                           ('subject_sha256', '0' * 64), ('observed_utc', None),
                           ('process_scan', {}), ('status', 'UNKNOWN')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.reconcile(dict(good, **{key: value}))
            self.assertFalse((self.folder / self.v.RECEIPT).exists())
        for error in (PermissionError('proc denied'), TimeoutError('connection uncertain'),
                      BlockingIOError('gate busy')):
            with patch.object(self.tcad, 'parallel_query', side_effect=error), self.assertRaises(type(error)):
                self.op.reconcile_unlaunched_operation(self.tcad, self.cfg, [], self.label)
            self.assertFalse((self.folder / self.v.RECEIPT).exists())

    def test_incomplete_or_modified_existing_receipt_is_not_overwritten(self):
        path = self.folder / self.v.RECEIPT
        for content in (b'{', b'{}', b'null'):
            path.write_bytes(content)
            with patch.object(self.tcad, 'parallel_query') as query, self.assertRaises(ValueError):
                self.op.reconcile_unlaunched_operation(self.tcad, self.cfg, [], self.label)
            query.assert_not_called()
            self.assertEqual(path.read_bytes(), content)
        path.unlink()
        self.reconcile()
        receipt = json.loads(path.read_bytes())
        receipt['proof']['boot_id'] = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        path.write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt SHA'):
            self.v.verified_unlaunched_receipt(self.cfg, self.record, self.folder)

    def test_repeat_with_an_equivalent_but_different_profile_path_is_a_conflict(self):
        self.reconcile()
        duplicate = self.tmp / 'duplicate-profile.json'
        duplicate.write_bytes(self.profile.read_bytes())
        self.tcad.CONFIG = duplicate
        with self.assertRaisesRegex(ValueError, 'frozen subject/profile'):
            self.reconcile()

    def test_validator_accepts_mixed_collected_generations_and_rejects_bad_leases(self):
        subject = self.subject()
        proof = self.proof(subject)
        for index, capacity in enumerate((2, 4, 3, 7, 9)):
            cfg = dict(self.cfg, parallel_capacity=capacity)
            if capacity in (2, 4):
                threads = 4 if capacity == 2 else 2
                cfg.update(requested_threads=threads, cpu_sets=[
                    list(range(i * threads, (i + 1) * threads)) for i in range(capacity)])
            work = 'collected-history-%s' % index
            policy = self.tcad.parallel_policy(cfg, index, work, self.cfg['remote_root'] + '/runs/' + work)
            lease = dict(policy=policy, state='COLLECTED', script_sha256='d' * 64)
            proof['pool_snapshot']['leases']['slot-%s.json' % index] = self.snapshot_file(lease)
        proof['pool_snapshot_sha256'] = self.v.canonical_sha256(proof['pool_snapshot'])
        self.v.validate_proof(proof, subject)
        for state in ('ACTIVE', 'RESERVED', 'unknown'):
            bad = copy.deepcopy(proof)
            lease = bad['pool_snapshot']['leases']['slot-0.json']['record']
            lease['state'] = state
            bad['pool_snapshot']['leases']['slot-0.json'] = self.snapshot_file(lease)
            bad['pool_snapshot_sha256'] = self.v.canonical_sha256(bad['pool_snapshot'])
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'Outstanding'):
                self.v.validate_proof(bad, subject)
        for field, value in (('work_id', self.label), ('schema', 'unknown'),
                             ('cpu_set', [4, 5, 6, 7]), ('requested_threads', True)):
            bad = copy.deepcopy(proof)
            lease = bad['pool_snapshot']['leases']['slot-0.json']['record']
            lease['policy'][field] = value
            bad['pool_snapshot']['leases']['slot-0.json'] = self.snapshot_file(lease)
            bad['pool_snapshot_sha256'] = self.v.canonical_sha256(bad['pool_snapshot'])
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.v.validate_proof(bad, subject)

    def test_valid_outer_checksums_cannot_hide_missing_locks_or_changed_raw_lease(self):
        subject = self.subject()
        proof = self.proof(subject)
        proof['pool_snapshot']['capacity']['record']['capacity'] = 9
        proof['pool_snapshot_sha256'] = self.v.canonical_sha256(proof['pool_snapshot'])
        with self.assertRaisesRegex(ValueError, 'whole-file SHA/content'):
            self.v.validate_proof(proof, subject)
        self.reconcile()
        path = self.folder / self.v.RECEIPT
        receipt = json.loads(path.read_bytes())
        receipt['proof']['locked_slots'] = [0]
        receipt['proof_sha256'] = self.v.canonical_sha256(receipt['proof'])
        receipt.pop('receipt_sha256')
        receipt['receipt_sha256'] = self.v.canonical_sha256(receipt)
        path.write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'lock proof'):
            self.v.verified_unlaunched_receipt(self.cfg, self.record, self.folder)

    def test_cli_acquires_original_owner(self):
        events = []
        class Owner:
            def __enter__(inner):
                events.append('owner')
            def __exit__(inner, *args):
                events.append('release')
        def perform(*args):
            self.assertEqual(events, ['owner'])
            return {'status': 'not_launched'}
        fake = types.SimpleNamespace(original_ownership=Owner,
                                     connection=lambda: (self.cfg, [], None))
        with patch.object(self.op, 'load_tcad', return_value=fake), \
                patch.object(self.op, 'reconcile_unlaunched_operation', side_effect=perform):
            self.op.reconcile_unlaunched(self.label, connection=self.profile)
        self.assertEqual(events, ['owner', 'release'])
        with patch.object(self.op, 'reconcile_unlaunched', return_value={}) as call:
            self.assertEqual(self.op.main(['--connection', str(self.profile), 'reconcile-unlaunched',
                                          self.label, '--json']), 0)
        call.assert_called_once_with(self.label, connection=self.profile)

    def test_privileged_aliases_are_fixed_same_vm_and_root_transport_is_proof_only(self):
        def ssh_g(argv, **kwargs):
            self.assertEqual(argv[:4], ['ssh', '-G', '-F', '/etc/tcad-centos79/ssh_config'])
            alias = argv[-1]
            return types.SimpleNamespace(
                returncode=0,
                stdout='hostname 10.0.0.7\nport 22\nhostkeyalias vm-fixed\n'
                       if alias in ('tcad-guest-sim', 'tcad-guest-root') else '',
                stderr='')
        with patch.object(self.op.os, 'geteuid', create=True, return_value=0), \
                patch.object(self.op.subprocess, 'run', side_effect=ssh_g) as run:
            proof_ssh, sim_ssh, transport = self.op._privileged_proof_ssh()
        self.assertEqual(proof_ssh[-1], 'tcad-guest-root')
        self.assertEqual(sim_ssh[-1], 'tcad-guest-sim')
        self.assertEqual(proof_ssh[1:3], ['-F', '/etc/tcad-centos79/ssh_config'])
        self.assertEqual(transport['sim_alias'], 'tcad-guest-sim')
        self.assertEqual(transport['root_alias'], 'tcad-guest-root')
        self.assertNotIn('identity', transport)
        self.assertEqual(run.call_count, 2)

    def test_privileged_alias_mismatch_and_nonroot_are_refused(self):
        with patch.object(self.op.os, 'geteuid', create=True, return_value=1000), \
                self.assertRaisesRegex(PermissionError, 'euid 0'):
            self.op._privileged_proof_ssh()
        for key, wrong in (('hostname', '10.0.0.8'), ('port', '2222'), ('hostkeyalias', 'other-vm')):
            def mismatch(argv, **kwargs):
                fields = dict(hostname='10.0.0.7', port='22', hostkeyalias='vm-fixed')
                if argv[-1] == 'tcad-guest-root':
                    fields[key] = wrong
                return types.SimpleNamespace(returncode=0,
                    stdout=''.join(k + ' ' + v + '\n' for k, v in fields.items()), stderr='')
            with self.subTest(key=key), patch.object(self.op.os, 'geteuid', create=True, return_value=0), \
                    patch.object(self.op.subprocess, 'run', side_effect=mismatch), \
                    self.assertRaisesRegex(ValueError, 'same VM'):
                self.op._privileged_proof_ssh()

    def test_privileged_config_resolution_failure_unknown_and_ambiguous_identity_refused(self):
        for code, text in ((1, 'identityfile /private/not-to-be-disclosed\n'),
                           (0, 'hostname 10.0.0.7\nport 22\n'),
                           (0, 'hostname none\nport 22\nhostkeyalias vm-fixed\n'),
                           (0, 'hostname 10.0.0.7\nport 22\nhostkeyalias vm\nhostname other\n')):
            result = types.SimpleNamespace(returncode=code, stdout=text, stderr='private key location')
            with self.subTest(code=code, text=text), \
                    patch.object(self.op.subprocess, 'run', return_value=result), \
                    self.assertRaises(ValueError) as error:
                self.op._ssh_config_identity('tcad-guest-root')
            self.assertNotIn('/private/', str(error.exception))
            self.assertNotIn('private key', str(error.exception))

    def test_privileged_reconciliation_binds_sim_boot_and_root_transport(self):
        proof = self.proof()
        proof['process_scan']['owner_uid'] = 0
        transport = dict(schema='tcad-privileged-proof-transport-r1',
                         mode='server-admin-root-ssh',
                         ssh_config='/etc/tcad-centos79/ssh_config',
                         sim_alias='tcad-guest-sim', root_alias='tcad-guest-root',
                         hostname='10.0.0.7', port=22, hostkeyalias='vm-fixed')
        with patch.object(self.op.os, 'geteuid', create=True, return_value=0), \
                patch.object(self.tcad, 'remote_python',
                          return_value={'boot_id': proof['boot_id']}) as sim_boot, \
                patch.object(self.tcad, 'parallel_query', return_value=proof) as query:
            result = self.op.reconcile_unlaunched_operation(
                self.tcad, self.cfg, [], self.label,
                proof_ssh=['ssh', '-F', '/etc/tcad-centos79/ssh_config', 'tcad-guest-root'],
                proof_transport=transport)
        receipt = json.loads((self.folder / self.v.RECEIPT).read_bytes())
        self.assertEqual(result['status'], 'not_launched')
        self.assertEqual(receipt['proof']['proof_transport']['sim_boot_id'], proof['boot_id'])
        self.assertEqual(receipt['proof']['proof_transport']['root_alias'], 'tcad-guest-root')
        sim_boot.assert_called_once()
        self.assertEqual(query.call_args.kwargs['proof_ssh'][0], 'ssh')
        self.assertEqual(query.call_args.args[-1], 'prove-unlaunched')

    def test_privileged_transport_requires_boot_match_and_validator_rejects_bad_source(self):
        proof = self.proof()
        transport = dict(schema='tcad-privileged-proof-transport-r1',
                         mode='server-admin-root-ssh',
                         ssh_config='/etc/tcad-centos79/ssh_config',
                         sim_alias='tcad-guest-sim', root_alias='tcad-guest-root',
                         hostname='10.0.0.7', port=22, hostkeyalias='vm-fixed')
        with patch.object(self.op.os, 'geteuid', create=True, return_value=0), \
                patch.object(self.tcad, 'remote_python',
                          return_value={'boot_id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'}), \
                patch.object(self.tcad, 'parallel_query', return_value=proof), \
                self.assertRaisesRegex(ValueError, 'boot ID'):
            self.op.reconcile_unlaunched_operation(
                self.tcad, self.cfg, [], self.label,
                proof_ssh=['ssh', 'root'], proof_transport=transport)
        proof['proof_transport'] = dict(transport, sim_boot_id=proof['boot_id'])
        proof['proof_transport']['root_alias'] = 'other-root'
        with self.assertRaisesRegex(ValueError, 'transport binding'):
            self.v.validate_proof(proof, self.subject())

    def test_privileged_cli_keeps_original_owner_and_passes_only_fixed_proof(self):
        events = []
        class Owner:
            def __enter__(inner):
                events.append('owner')
            def __exit__(inner, *args):
                events.append('release')
        proof_ssh, sim_ssh, transport = ['ssh', 'fixed-root-fixture'], ['ssh', 'fixed-sim-fixture'], {'fixture': 'transport'}
        def prepare():
            self.assertEqual(events, ['owner'])
            return proof_ssh, sim_ssh, transport
        fake = types.SimpleNamespace(original_ownership=Owner,
                                     connection=lambda: (self.cfg, [], None))
        with patch.object(self.op, 'load_tcad', return_value=fake), \
                patch.object(self.op, '_privileged_proof_ssh', side_effect=prepare), \
                patch.object(self.op, 'reconcile_unlaunched_operation', return_value={}) as perform:
            self.op.reconcile_unlaunched(self.label, connection=self.profile, privileged_proof=True)
        perform.assert_called_once_with(fake, self.cfg, [], self.label,
                                        proof_ssh=proof_ssh, proof_transport=transport,
                                        sim_ssh=sim_ssh)
        self.assertEqual(events, ['owner', 'release'])
        with patch.object(self.op, 'reconcile_unlaunched', return_value={}) as call:
            self.op.main(['reconcile-unlaunched', self.label, '--privileged-proof'])
        call.assert_called_once_with(self.label, connection=None, privileged_proof=True)

    def test_privileged_flag_is_rejected_for_status_and_collect(self):
        for command in ('status', 'collect'):
            with self.subTest(command=command), \
                    self.assertRaises(SystemExit):
                self.op.main([command, self.label, '--privileged-proof'])


if __name__ == '__main__':
    unittest.main()
