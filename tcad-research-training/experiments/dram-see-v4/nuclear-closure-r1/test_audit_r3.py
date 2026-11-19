"""Independent counterexample tests for the r3 World-ledger miss audit.

These tests use synthetic dictionaries for isolated failures and read the
already-collected miss-H archive for one complete, read-only audit. They never
invoke transport, SSH, TCAD, or a scheduler.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1'
VALIDATION = RUNTIME / 'audit-r3/validation'
REVIEW = RUNTIME / 'audit-r3/review.json'
R3_PATH = HERE / 'transport_audit_r3.py'
R2_PATH = HERE / 'transport_audit_material_r2.py'
OLD_AUDIT = RUNTIME / 'transport/audits/nc-r1-miss-h/audit.json'
RUN = RUNTIME / 'transport/runs/nc-r1-miss-h'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


AUDIT = module(R3_PATH, '_audit_r3_validation')
sys.path.insert(0, str(HERE))


class FakePaths:
    def __init__(self, **values):
        self.__dict__.update(values)

    @staticmethod
    def read(path):
        return json.loads(Path(path).read_text(encoding='utf-8'))

    @staticmethod
    def sha(path):
        return sha(Path(path))

    @staticmethod
    def require(condition, message):
        if not condition:
            raise AssertionError(message)


class FakeSchedulerPaths:
    def __init__(self, root, contract_value):
        self.RT = root / 'runtime'
        self.OLD_OPS = root / 'old-ops'
        self.HERE = root / 'source'
        self.contract_value = contract_value
        self.reads = []
        self.writes = []

    @staticmethod
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def read(self, path):
        path = Path(path)
        self.reads.append(path)
        return json.loads(path.read_text(encoding='utf-8'))

    def write(self, path, value, **_kwargs):
        self.writes.append((Path(path), value))

    @staticmethod
    def ref(path):
        return {'path': str(path)}

    @staticmethod
    def check_ref(value):
        return Path(value['path'])

    def contract(self):
        return self.contract_value

    @staticmethod
    def utc():
        return 'mock-utc'


def fixture(world_energy=1.3094106576716144e-27):
    events, tracks, steps, ledger = [], [], [], []
    device = ('G4_Si', 'G4_SILICON_DIOXIDE')
    for eid in (0, 1):
        events.append({
            'event_id': eid, 'primary_count': 1, 'track_count': 1,
            'step_count': 1, 'world_step_count': 1, 'si_step_count': 0,
            'hadronic_step_count': 0, 'primary_hadronic_step_count': 0,
            'neutron_tracking_cut_steps': 0, 'neutron_tracking_cut_tracks': 0,
            'edep_all_MeV': world_energy, 'edep_world_MeV': world_energy,
            'niel_all_MeV': 0.0, 'niel_world_MeV': 0.0,
            'ionizing_all_MeV': world_energy, 'ionizing_world_MeV': world_energy,
            'edep_si_MeV': 0.0, 'niel_si_MeV': 0.0, 'ionizing_si_MeV': 0.0,
        })
        tracks.append({
            'event_id': eid, 'track_id': 1, 'parent_id': 0,
            'particle': 'proton', 'pdg': 2212, 'birth_volume': 'World',
            'birth_material': 'G4_Galactic', 'end_volume': 'OUTSIDE',
            'end_material': 'NONE', 'termination_reason': 'escaped_world',
            'edep_all_MeV': world_energy, 'niel_all_MeV': 0.0,
            'ionizing_all_MeV': world_energy,
            'edep_si_MeV': 0.0, 'niel_si_MeV': 0.0, 'ionizing_si_MeV': 0.0,
            **{key: 0 for key in AUDIT.TRACK_BOOL},
        })
        steps.append({
            'event_id': eid, 'track_id': 1, 'parent_id': 0, 'step_id': 0,
            'particle': 'proton', 'pdg': 2212, 'secondary_count': 0,
            'pre_volume': 'World', 'pre_material': 'G4_Galactic',
            'post_volume': 'OUTSIDE', 'post_material': 'NONE',
            'post_process_type': 0, 'edep_MeV': world_energy,
            'niel_MeV': 0.0, 'ionizing_MeV': world_energy,
            **{key: 0 for key in AUDIT.STEP_BOOL},
        })
        ledger.extend([
            {'scope': 'event', 'event_id': eid, 'track_id': 0, 'material': 'G4_Galactic',
             'step_count': 1, 'edep_MeV': world_energy, 'niel_MeV': 0.0, 'ionizing_MeV': world_energy},
            {'scope': 'track', 'event_id': eid, 'track_id': 1, 'material': 'G4_Galactic',
             'step_count': 1, 'edep_MeV': world_energy, 'niel_MeV': 0.0, 'ionizing_MeV': world_energy},
        ])
        for scope, track_id in (('event', 0), ('track', 1)):
            for material in device:
                ledger.append({'scope': scope, 'event_id': eid, 'track_id': track_id,
                               'material': material, 'step_count': 0,
                               'edep_MeV': 0.0, 'niel_MeV': 0.0, 'ionizing_MeV': 0.0})
    return events, tracks, steps, ledger


def invoke(records, links=''):
    events, tracks, steps, ledger = records
    with tempfile.TemporaryDirectory(prefix='audit-r3-counterexample-', dir=VALIDATION) as temp:
        folder = Path(temp)
        (folder / 'birth-links.csv').write_text('event_id,track_id\n' + links, encoding='utf-8')
        report = {}
        AUDIT._miss_device(folder, events, tracks, steps, ledger, report)
        return report


class MissDeviceTests(unittest.TestCase):
    def test_tiny_world_energy_is_retained_and_reported(self):
        records = fixture()
        records[2][0]['post_volume'] = 'World'
        records[2][0]['post_material'] = 'G4_Galactic'
        report = invoke(records)
        expected = 1.3094106576716144e-27
        self.assertEqual(report['miss_device_scope']['world_ionizing_MeV'], [expected, expected])
        self.assertEqual(report['miss_device_scope']['world_ledger'][0]['step_sums_MeV']['ionizing_MeV'], expected)
        self.assertEqual(report['miss_device_scope']['world_closure_absolute_MeV'], 0)
        self.assertEqual(report['miss_device_scope']['world_closure_relative'], 1e-9)

    def test_device_energy_1e_minus_27_is_rejected_even_with_zero_event_total(self):
        records = fixture()
        row = next(r for r in records[3] if r['scope'] == 'event' and r['event_id'] == 0 and r['material'] == 'G4_Si')
        row['edep_MeV'] = row['ionizing_MeV'] = 1e-27
        with self.assertRaises(ValueError):
            invoke(records)

    def test_tiny_oxide_deposit_is_rejected(self):
        records = fixture()
        row = next(r for r in records[3] if r['scope'] == 'track' and r['event_id'] == 1 and r['material'] == 'G4_SILICON_DIOXIDE')
        row['niel_MeV'] = 1e-27
        with self.assertRaises(ValueError):
            invoke(records)

    def test_zero_energy_device_entry_is_rejected_by_endpoint(self):
        records = fixture(world_energy=0.0)
        records[2][0]['post_volume'] = 'R.Si'
        records[2][0]['post_material'] = 'G4_Si'
        with self.assertRaisesRegex(ValueError, 'entered a device'):
            invoke(records)

    def test_world_positive_to_zero_and_double_are_rejected(self):
        for changed in (0.0, 2 * 1.3094106576716144e-27):
            with self.subTest(changed=changed):
                records = fixture()
                records[0][0]['ionizing_world_MeV'] = changed
                with self.assertRaisesRegex(ValueError, 'World energy lost or changed'):
                    invoke(records)

    def test_secondary_or_hadronic_markers_are_rejected(self):
        records = fixture()
        records[2][0]['secondary_count'] = 1
        with self.assertRaisesRegex(ValueError, 'secondary'):
            invoke(records)
        records = fixture()
        records[2][0]['post_process_type'] = 4
        with self.assertRaisesRegex(ValueError, 'hadronic'):
            invoke(records)

    def test_missing_or_duplicate_zero_material_rows_are_rejected(self):
        records = fixture()
        records[3].pop()
        with self.assertRaisesRegex(ValueError, 'Missing/duplicate exact-zero'):
            invoke(records)
        records = fixture()
        records[3].append(copy.deepcopy(records[3][-1]))
        with self.assertRaisesRegex(ValueError, 'Missing/duplicate exact-zero'):
            invoke(records)


class RevisionBindingTests(unittest.TestCase):
    def test_original_failure_hashes_and_raw_archive_identity_remain_bound(self):
        review = json.loads(REVIEW.read_text(encoding='utf-8'))
        old = json.loads(OLD_AUDIT.read_text(encoding='utf-8'))
        self.assertEqual(sha(RUNTIME / 'transport/runs/nc-r1-miss-h/record.json'), review['evidence']['record']['sha256'])
        self.assertEqual(sha(OLD_AUDIT), review['evidence']['old_failed_audit']['sha256'])
        self.assertEqual(sha(ROOT / review['evidence']['raw_archive']['path']), review['evidence']['raw_archive']['sha256'])
        self.assertFalse(old['passed'])
        self.assertEqual(old['audit_revision'], 'r2-strict-run-request-path-identity')
        self.assertFalse(old['checks']['all_material_energy_and_native_particle_coverage']['passed'])
        self.assertTrue(all(v['passed'] for k, v in old['checks'].items() if k != 'all_material_energy_and_native_particle_coverage'))

    def test_non_miss_function_ast_is_unchanged_from_material_r2(self):
        old_tree = ast.parse(R2_PATH.read_text(encoding='utf-8'))
        new_tree = ast.parse(R3_PATH.read_text(encoding='utf-8'))
        excluded = {'_material_ledger', '_miss_device'}
        old_defs = {n.name: ast.dump(n, include_attributes=False) for n in old_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name not in excluded}
        new_defs = {n.name: ast.dump(n, include_attributes=False) for n in new_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name not in excluded}
        self.assertEqual(old_defs.keys(), new_defs.keys())
        self.assertEqual(old_defs, new_defs)

    def test_full_original_archive_r3_audit_passes_without_mutating_original_records(self):
        record_path = RUN / 'record.json'
        old_audit_path = OLD_AUDIT
        before = (sha(record_path), sha(old_audit_path))
        with tempfile.TemporaryDirectory(prefix='complete-audit-r3-', dir=VALIDATION) as temp:
            result = AUDIT.audit_events(RUN, Path(temp))
            saved = json.loads((Path(temp) / 'audit.json').read_text(encoding='utf-8'))
        self.assertTrue(result['passed'], result['errors'])
        self.assertEqual(len(result['checks']), 10)
        self.assertTrue(all(item['passed'] for item in result['checks'].values()))
        self.assertEqual(result['audit_revision'], 'r3-device-miss-with-preserved-world-ledger')
        self.assertEqual(result['record_sha256'], before[0])
        self.assertEqual(result['audit_code_sha256'], sha(R3_PATH))
        self.assertEqual(saved, result)
        self.assertEqual((sha(record_path), sha(old_audit_path)), before)
        miss = result['miss_device_scope']
        self.assertEqual(miss['world_ionizing_MeV'], [1.3094106576716144e-27] * 2)
        self.assertTrue(miss['device_materials_exactly_zero'])

    def test_r3_reaudit_wrapper_reuses_bound_audit_without_running_auditor(self):
        wrapper = module(HERE / 'transport_r3.py', '_transport_r3_validation')
        with tempfile.TemporaryDirectory(prefix='wrapper-reuse-r3-', dir=VALIDATION) as temp:
            root = Path(temp)
            runtime = root / 'runtime'
            source = root / 'source'
            label = 'nc-r1-miss-h'
            record = runtime / 'transport/runs' / label / 'record.json'
            dest = runtime / 'transport/audits-r3' / label
            source.mkdir()
            record.parent.mkdir(parents=True)
            dest.mkdir(parents=True)
            (record.parent / 'record.json').write_text('{}', encoding='utf-8')
            code = source / 'transport_audit_r3.py'
            code.write_text('# bound test source\n', encoding='utf-8')
            expected = {'passed': True, 'record_sha256': sha(record), 'audit_code_sha256': sha(code), 'sentinel': 'reused'}
            (dest / 'audit.json').write_text(json.dumps(expected), encoding='utf-8')
            wrapper.c = FakePaths(RT=runtime, HERE=source)
            result = wrapper.audit(label)
            self.assertEqual(result, expected)

    def test_r3_first_reaudit_keeps_prior_failure_as_reference(self):
        wrapper = module(HERE / 'transport_r3.py', '_transport_r3_first_audit_validation')
        with tempfile.TemporaryDirectory(prefix='prior-failure-r3-', dir=VALIDATION) as temp:
            root = Path(temp)
            runtime, source = root / 'runtime', root / 'source'
            label = 'nc-r1-miss-h'
            record = runtime / 'transport/runs' / label / 'record.json'
            prior = runtime / 'transport/audits' / label / 'audit.json'
            dest = runtime / 'transport/audits-r3' / label
            source.mkdir()
            record.parent.mkdir(parents=True)
            prior.parent.mkdir(parents=True)
            record.write_text('{}', encoding='utf-8')
            prior_bytes = json.dumps({'passed': False, 'error': 'old r2 predicate'}).encode()
            prior.write_bytes(prior_bytes)

            class MockAuditor:
                @staticmethod
                def audit_events(run_dir):
                    return {'passed': True, 'record_sha256': 'new-audit'}

                @staticmethod
                def audit_init(run_dir):
                    raise AssertionError('miss must use audit_events')

                @staticmethod
                def _write(output, result):
                    output.mkdir(parents=True, exist_ok=True)
                    (output / 'audit.json').write_text(json.dumps(result), encoding='utf-8')

            fake = FakePaths(RT=runtime, HERE=source)
            fake.ref = lambda path: {'path': str(Path(path)), 'sha256': sha(Path(path))}
            fake.module = lambda path, name: MockAuditor
            wrapper.c = fake
            wrapper.request = lambda request_label: {'label': request_label, 'mode': 'miss'}
            result = wrapper.audit(label)
            self.assertTrue(result['passed'])
            self.assertEqual(result['prior_material_r2_audit']['passed'], False)
            self.assertEqual(result['prior_material_r2_audit']['reference']['sha256'], sha(prior))
            self.assertIn('no replay or alteration', result['recovery_scope'])
            self.assertEqual(prior.read_bytes(), prior_bytes)
            self.assertTrue((dest / 'audit.json').is_file())

    def test_existing_original_attempt_is_reconciled_without_process_or_budget_calls(self):
        supervisor = module(HERE / 'supervisor_material_r2.py', '_supervisor_material2_validation')
        with tempfile.TemporaryDirectory(prefix='supervisor-reuse-r3-', dir=VALIDATION) as temp:
            root = Path(temp)
            runtime, old_ops = root / 'runtime', root / 'original-ops'
            label = 'nc-r1-miss-h'
            request = {'label': label, 'mode': 'miss', 'arm': 'H', 'event_count': 2}
            attempt = runtime / 'attempts' / (label + '.json')
            operation = old_ops / 'operations' / label / 'operation.json'
            attempt.parent.mkdir(parents=True)
            operation.parent.mkdir(parents=True)
            attempt.write_text(json.dumps({'kind': 'transport', 'request': request}), encoding='utf-8')
            operation.write_text(json.dumps({'state': 'COLLECTED_PENDING_AUDIT', 'ssh_exit_code': 0,
                                             'remote_exit_code': 0, 'collection_exit_code': 0}), encoding='utf-8')
            fake = FakePaths(RT=runtime, OLD_OPS=old_ops)
            supervisor.c = fake
            result = supervisor.operation(label, root / 'unused-inputs', 'transport', request)
            self.assertEqual(result, operation.parent)
            self.assertEqual(sorted(p.name for p in attempt.parent.iterdir()), [label + '.json'])
            self.assertEqual(sorted(p.name for p in operation.parent.iterdir()), ['operation.json'])

    def test_old_stage_pass_cannot_bypass_r3_stage_audit(self):
        scheduler = module(HERE / 'continue_audit_r3.py', '_continue_audit_r3_old_stage_validation')
        with tempfile.TemporaryDirectory(prefix='old-stage-r3-', dir=VALIDATION) as temp:
            root = Path(temp)
            contract = {'transport': {'stage_order': ['P0']}}
            fake_c = FakeSchedulerPaths(root, contract)
            build_label = 'mock-build'
            attempt = fake_c.RT / 'attempts' / (build_label + '.json')
            attempt.parent.mkdir(parents=True)
            attempt.write_text('{}', encoding='utf-8')
            old_stage = fake_c.RT / 'transport/stages/P0.json'
            old_stage.parent.mkdir(parents=True)
            old_stage.write_text(json.dumps({'passed': True, 'qualifying_event_found': True,
                                             'audits': [{'path': 'old-audit'}]}), encoding='utf-8')
            build_operation = fake_c.OLD_OPS / 'operations' / build_label
            class FakeSupervisor:
                calls = []
                @staticmethod
                def operation(*args, **kwargs):
                    FakeSupervisor.calls.append((args, kwargs))
                    return build_operation
                @staticmethod
                def assert_operation_complete(_path):
                    return True
                @staticmethod
                def update_status(**_kwargs):
                    return None
            class FakeTransport:
                BUILD_LABEL = build_label
                @staticmethod
                def check_release():
                    return None
                @staticmethod
                def assert_operation_complete(_path):
                    return True
                @staticmethod
                def contract():
                    return {'requests': []}
                @staticmethod
                def choose(_stage):
                    return None
                @staticmethod
                def compile_inputs():
                    raise AssertionError('Existing build attempt must use its original inputs')
            scheduler.c, scheduler.s, scheduler.t = fake_c, FakeSupervisor, FakeTransport
            result = scheduler.transport_stage()
            self.assertFalse(result)
            self.assertNotIn(old_stage, fake_c.reads)
            r3_stage = fake_c.RT / 'transport/stages-r3/P0.json'
            self.assertTrue(any(path == r3_stage for path, _ in fake_c.writes))
            self.assertEqual(len(FakeSupervisor.calls), 1)
            self.assertEqual(FakeSupervisor.calls[0][0][0], build_label)

    def test_selected_event_from_old_revision_is_rejected_without_reuse(self):
        scheduler = module(HERE / 'continue_audit_r3.py', '_continue_audit_r3_old_selection_validation')
        with tempfile.TemporaryDirectory(prefix='old-selection-r3-', dir=VALIDATION) as temp:
            root = Path(temp)
            fake_c = FakeSchedulerPaths(root, {'transport': {'stage_order': []}})
            build_label = 'mock-build'
            attempt = fake_c.RT / 'attempts' / (build_label + '.json')
            attempt.parent.mkdir(parents=True)
            attempt.write_text('{}', encoding='utf-8')
            selected = fake_c.RT / 'selected-event.json'
            selected.parent.mkdir(parents=True, exist_ok=True)
            selected.write_text(json.dumps({'transport_revision': 'material-r2',
                'record': {'path': 'prior-record'}, 'audit': {'path': 'prior-audit'}}), encoding='utf-8')
            class FakeSupervisor:
                @staticmethod
                def operation(*_args, **_kwargs):
                    return fake_c.OLD_OPS / 'operations' / build_label
                @staticmethod
                def assert_operation_complete(_path):
                    return True
            class FakeTransport:
                BUILD_LABEL = build_label
                @staticmethod
                def check_release():
                    return None
                @staticmethod
                def assert_operation_complete(_path):
                    return True
            scheduler.c, scheduler.s, scheduler.t = fake_c, FakeSupervisor, FakeTransport
            with self.assertRaisesRegex(ValueError, 'another audit revision'):
                scheduler.transport_stage()
            self.assertEqual(fake_c.writes, [])
            self.assertEqual(fake_c.reads, [selected])


if __name__ == '__main__':
    unittest.main(verbosity=2)
