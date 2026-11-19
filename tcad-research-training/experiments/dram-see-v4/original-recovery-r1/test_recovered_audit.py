"""Focused local recovery-adapter tests; no solver, SSH or live state changes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import recovery_proof as proof
import fields_bridge as bridge
import recovered_audit as audit

VALIDATION = proof.ROOT / 'local_runtime/dram-see-v4/interface-completion-r1/recovery-review-20261014'


class Fixture(unittest.TestCase):
    def setUp(self):
        VALIDATION.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=VALIDATION)
        self.root = Path(self.temp.name)
        self.recovered = dict(run_id=proof.RUN_ID, manifest_sha256='manifest', archive_sha256='archive',
                              recovery_reference={'path': 'recovery-contract.json', 'sha256': 'contract'})

    def tearDown(self):
        self.temp.cleanup()

    def record(self):
        return dict(solver_run_id=proof.RUN_ID, **bridge.recovery_metadata(self.recovered))

    def field_report(self, **changes):
        result = dict(schema=audit.FIELD_SCHEMA, passed=True, errors=[], audit_tolerances=audit.T,
                      checks={name: {'passed': True} for name in audit.FIELD_CHECKS},
                      mode='full', field_measurements_passed=True,
                      audit_code_sha256='wrong-adapter', recovery_adapter_sha256='wrong-adapter')
        result.update(changes)
        return result


class BridgeIdentityTests(Fixture):
    def test_prepare_wrong_run_rejected_before_verification(self):
        with patch.object(proof, 'verify') as verify:
            with self.assertRaisesRegex(ValueError, 'Only the original run'):
                bridge.prepare('replacement-run', bridge.FIELD_LABEL)
        verify.assert_not_called()

    def test_other_operation_label_rejected(self):
        with patch.object(proof, 'verify') as verify:
            with self.assertRaisesRegex(ValueError, 'field-operation label'):
                bridge.collect('replacement-fields')
        verify.assert_not_called()

    def test_recovery_metadata_preserves_unknown_original_exits(self):
        record = self.record()
        bridge.validate_recovery_binding(record, self.recovered)
        self.assertIsNone(record['original_runner_exit_code'])
        self.assertIsNone(record['original_ssh_exit_code'])
        self.assertFalse(record['original_engineering_marker_present'])
        self.assertFalse(record['original_execution_contract_passed'])

    def test_original_zero_relabeling_is_rejected(self):
        for key in ('original_runner_exit_code', 'original_ssh_exit_code'):
            with self.subTest(key=key):
                record = self.record(); record[key] = 0
                with self.assertRaisesRegex(ValueError, 'relabeled'):
                    bridge.validate_recovery_binding(record, self.recovered)

    def test_missing_unknown_fact_is_not_equivalent_to_explicit_null(self):
        record = self.record(); del record['original_runner_exit_code']
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            bridge.validate_recovery_binding(record, self.recovered)

    def test_changed_recovery_reference_is_rejected(self):
        record = self.record(); record['recovery_reference'] = {'path': 'foreign', 'sha256': 'other'}
        with self.assertRaisesRegex(ValueError, 'reference differs'):
            bridge.validate_recovery_binding(record, self.recovered)

    def test_other_original_run_is_rejected(self):
        record = self.record(); record['solver_run_id'] = 'other-run'
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            bridge.validate_recovery_binding(record, self.recovered)

    def test_changed_bridge_is_rejected(self):
        record = self.record(); record['bridge_sha256'] = 'foreign-code'
        with self.assertRaisesRegex(ValueError, 'bridge changed'):
            bridge.validate_recovery_binding(record, self.recovered)

    def test_task_keeps_frozen_single_thread_extractor_and_original_directory(self):
        name = 'gstep_0_access_des.tdr'
        remote = '/home/tcad/research-training/runs/' + proof.RUN_ID
        task = bridge.render_task(remote, {name: '0' * 64}).decode()
        self.assertIn(remote + '/' + name, task)
        self.assertIn('svisual --threads 1 --max_threads 1', task)
        self.assertNotIn('sdevice ', task)
        self.assertEqual(task.count('sha256sum -c tdr-sha256.txt'), 2)
        with self.assertRaisesRegex(ValueError, 'remote run binding'):
            bridge.render_task('/runs/other', {name: '0' * 64})

    def test_native_operation_unknown_nonzero_or_boolean_exits_are_rejected(self):
        transport = self.root / 'transport'
        operation = transport / 'operations' / bridge.FIELD_LABEL
        operation.mkdir(parents=True)
        for key in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code'):
            for value in (None, 1, 255, False):
                with self.subTest(key=key, value=value):
                    op = dict(label=bridge.FIELD_LABEL, adapter_sha256=bridge.OPERATION_SHA256,
                              state='COLLECTED_PENDING_AUDIT', ssh_exit_code=0, remote_exit_code=0, collection_exit_code=0)
                    op[key] = value
                    (operation / 'operation.json').write_text(json.dumps(op))
                    with patch.object(bridge, 'TRANSPORT', transport), patch.object(proof, 'verify', return_value=self.recovered):
                        with self.assertRaisesRegex(ValueError, 'outcome unknown or failed'):
                            bridge.collect(bridge.FIELD_LABEL)
        self.assertFalse((operation / 'field-extraction-record.json').exists())


class InventoryTests(Fixture):
    def archive(self, count=405):
        names = [f'gstep_{i}_access_des.tdr' for i in range(count)]
        return SimpleNamespace(members={n: SimpleNamespace(size=1) for n in names}, digest=lambda n: hashlib.sha256(n.encode()).hexdigest())

    def test_complete_original_405_inventory(self):
        self.assertEqual(len(bridge.original_frames(self.archive())), 405)

    def test_missing_empty_and_extra_gstep_are_rejected(self):
        archive = self.archive(404)
        with self.assertRaisesRegex(ValueError, '405-frame'):
            bridge.original_frames(archive)
        archive = self.archive(); archive.members['gstep_unregistered.tdr'] = SimpleNamespace(size=1)
        with self.assertRaisesRegex(ValueError, '405-frame'):
            bridge.original_frames(archive)
        archive = self.archive(); archive.members['gstep_0_access_des.tdr'].size = 0
        with self.assertRaisesRegex(ValueError, 'Empty'):
            bridge.original_frames(archive)

    def test_missing_mapping_frame_never_reaches_numeric_parser(self):
        archive = self.archive()
        with patch.object(audit.field, 'index_frames') as parser:
            with self.assertRaisesRegex(ValueError, '405 gstep'):
                audit._mapping(archive, {'device': []}, list(archive.members)[:-1])
        parser.assert_not_called()


class ScientificRoutingTests(Fixture):
    def test_normal_run_uses_frozen_load_without_recovery(self):
        result = {'summary': {'normal': True}}
        run = self.root / 'normal-run'
        with patch.object(audit.r5, 'load', return_value=result) as load, patch.object(proof, 'verify') as verify:
            self.assertIs(audit.load(run, 'project', 'field'), result)
        load.assert_called_once_with(run.resolve(), 'project', 'field')
        verify.assert_not_called()

    def test_same_run_basename_in_foreign_path_is_not_recoverable(self):
        with patch.object(proof, 'bind_report') as bind:
            bundle = audit.load(self.root / proof.RUN_ID)
        self.assertFalse(bundle['summary']['passed'])
        self.assertIn('exact original run', bundle['summary']['errors'][0]['error'])
        bind.assert_not_called()

    def test_frozen_numerical_functions_are_exported_by_identity(self):
        for name in ('require', 'accepted', 'builder', 'canonical_matching', 'matched_control', 'compare', 'comparison_curves', 'write'):
            self.assertIs(getattr(audit, name), getattr(audit.r5, name))
        self.assertIs(audit.old, audit.r5.old)
        self.assertIs(audit.T, audit.r5.T)

    def test_failed_or_missing_physical_check_cannot_publish_pass(self):
        for mode in ('missing', 'failed', 'error', 'extra'):
            with self.subTest(mode=mode):
                out = dict(errors=[], checks={name: {'passed': True} for name in audit.FIELD_CHECKS})
                if mode == 'missing': del out['checks']['native_full_field_gates']
                if mode == 'failed': out['checks']['native_full_field_gates']['passed'] = False
                if mode == 'error': out['errors'].append({'error': 'physical failure'})
                if mode == 'extra': out['checks']['unregistered'] = {'passed': True}
                audit._finish(out, audit.FIELD_CHECKS, 'success')
                self.assertFalse(out['passed'])

    def test_legacy_field_schema_cannot_be_rebranded(self):
        path = self.root / 'audit.json'
        path.write_text(json.dumps(self.field_report(schema='source-field-audit-r2')))
        with self.assertRaisesRegex(ValueError, 'recovered field audit'):
            audit.bind_recovered_field_rows(path, {}, {}, None)

    def test_changed_adapter_hash_is_rejected_before_data_use(self):
        path = self.root / 'audit.json'
        path.write_text(json.dumps(self.field_report()))
        with self.assertRaisesRegex(ValueError, 'auditor changed'):
            audit.bind_recovered_field_rows(path, {}, {}, None)

    def test_top_level_pass_does_not_hide_failed_field_check(self):
        result = self.field_report(); result['checks']['native_full_field_gates'] = {'passed': False}
        path = self.root / 'audit.json'; path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'missing/failed checks'):
            audit.bind_recovered_field_rows(path, {}, {}, None)

    def test_changed_physical_tolerance_is_rejected(self):
        result = self.field_report(); result['audit_tolerances'] = dict(audit.T, source_relative=1.0)
        path = self.root / 'audit.json'; path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'different thresholds'):
            audit.bind_recovered_field_rows(path, {}, {}, None)

    def test_output_outside_approved_runtime_rejected_before_proof(self):
        with patch.object(proof, 'bind_report') as bind:
            with self.assertRaisesRegex(ValueError, 'allowed v4'):
                audit.field_audit(proof.RUN_FOLDER, 'operation', self.root / 'unapproved')
        bind.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
