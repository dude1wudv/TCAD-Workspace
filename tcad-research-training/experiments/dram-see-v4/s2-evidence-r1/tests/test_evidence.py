"""Independent offline boundary tests for the S2 evidence adapters.

All archive payloads originate in tests/fixtures.py and are explicitly synthetic.
No test launches a native tool, SSH, or capture patch.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[3]
MODULE_DIR = HERE.parent
RUNTIME = PROJECT / 'local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/validation'
sys.path.insert(0, str(MODULE_DIR))
import evidence
import audit
import fixtures


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def rewrite_tar(path, replacements=None, removals=()):
    """Rewrite a plain test archive without extracting members to disk."""
    path = Path(path)
    replacements = replacements or {}
    with tarfile.open(path, 'r:') as src:
        entries = [(m, src.extractfile(m).read() if m.isfile() else None)
                   for m in src.getmembers()]
    with tarfile.open(path, 'w:') as dst:
        for info, raw in entries:
            if info.name in removals:
                continue
            if info.name in replacements:
                raw = replacements[info.name]
                info.size = len(raw)
            dst.addfile(info, __import__('io').BytesIO(raw) if raw is not None else None)


def refresh_archive_manifest(folder, solver):
    folder = Path(folder)
    name = 'manifest.json' if solver else 'operation.json'
    key = 'results_sha256' if solver else 'archive_sha256'
    record = load_json(folder / name)
    record[key] = digest((folder / 'results.tar').read_bytes())
    (folder / name).write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def replace_frozen_input(folder, solver, member, raw):
    """Keep inputs.tar, results.tar and manifest inventory internally bound."""
    folder = Path(folder)
    name = 'manifest.json' if solver else 'operation.json'
    archive_key = 'results_sha256' if solver else 'archive_sha256'
    rewrite_tar(folder / 'inputs.tar', {member: raw})
    rewrite_tar(folder / 'results.tar', {member: raw})
    record = load_json(folder / name)
    record['input_sha256'][member] = digest(raw)
    record[archive_key] = digest((folder / 'results.tar').read_bytes())
    (folder / name).write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class EvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='UNIT_FIXTURE_NOT_NATIVE-', dir=RUNTIME)
        self.root = Path(self.tmp.name) / 'family-UNIT_FIXTURE_NOT_NATIVE'
        self.family = fixtures.build_fixture(self.root, bit=0, case='Aalpha')

    def tearDown(self):
        self.tmp.cleanup()

    def inspect_solver(self):
        return evidence.inspect(self.family['solver'], 'solver')

    def inspect_extraction(self):
        return evidence.inspect(self.family['extraction'], 'extraction')

    def audit_fixture(self):
        return audit.audit_fixture(self.family['solver'], self.family['extraction'], self.family['package'])

    def assert_refused(self):
        result = self.audit_fixture()
        self.assertFalse(result['passed'], result)
        self.assertFalse(result['native_qualified'])
        self.assertFalse(result['is_tcad_result'])
        self.assertEqual(result['native_calls'], 0)

    def test_complete_archive_parse_is_synthetic_only(self):
        result = self.audit_fixture()
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['status'], 'SYNTHETIC_ARCHIVE_PARSE_ONLY')
        self.assertFalse(result['native_qualified'])
        self.assertFalse(result['is_tcad_result'])
        self.assertEqual(result['native_calls'], 0)
        self.assertEqual(result['numerical_gates']['schema'], 's2-source-numerical-gates-r1')
        self.assertFalse(result['field_measurements_passed'])

    def test_public_native_entry_rejects_complete_synthetic_archive(self):
        result = audit.audit_native(self.family['solver'], self.family['extraction'], self.family['package'])
        self.assertFalse(result['passed'], result)
        self.assertIn('provenance', ' '.join(result['errors']).lower())
        self.assertFalse(result['native_qualified'])
        self.assertFalse(result['is_tcad_result'])
        self.assertEqual(result['native_calls'], 0)

    def test_observed_zeroes_have_provenance_and_never_qualify_native(self):
        report = self.inspect_solver()
        self.assertTrue(report['all_required_observations_present'])
        for key in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code', 'tool_exit_code'):
            self.assertEqual(report['facts'][key]['value'], 0)
            self.assertEqual(report['facts'][key]['evidence_kind'], 'observed')
            self.assertTrue(report['facts'][key]['source'])
            self.assertRegex(report['facts'][key]['sha256'], r'^[a-f0-9]{64}$')
        self.assertFalse(report['native_qualified'])
        self.assertFalse(report['scientific_acceptance'])
        self.assertFalse(report['receipt_created'])

    def test_missing_remote_exit_remains_unavailable_not_zero(self):
        folder = self.family['solver']
        rewrite_tar(folder / 'results.tar', removals=('exit-code.txt',))
        refresh_archive_manifest(folder, solver=True)
        manifest = load_json(folder / 'manifest.json')
        manifest['remote_exit_code'] = None
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        report = self.inspect_solver()
        fact = report['facts']['remote_exit_code']
        self.assertIsNone(fact['value'])
        self.assertEqual(fact['evidence_kind'], 'unavailable')
        self.assertIn('remote_exit_code', report['observation_gaps'])
        self.assert_refused()

    def test_missing_native_process_observation_cannot_use_wrapper_affinity(self):
        folder = self.family['extraction']
        rewrite_tar(folder / 'results.tar', removals=('svisual-process-status.txt',))
        refresh_archive_manifest(folder, solver=False)
        report = self.inspect_extraction()
        self.assertEqual(report['facts']['tool_affinity']['evidence_kind'], 'unavailable')
        self.assertEqual(report['facts']['tool_affinity']['value'], None)
        self.assertEqual(report['facts']['wrapper_affinity']['evidence_kind'], 'observed')
        self.assertIn('tool_affinity', report['observation_gaps'])
        self.assert_refused()

    def test_missing_step_exit_remains_unavailable(self):
        folder = self.family['solver']
        rewrite_tar(folder / 'results.tar', removals=('step-001-sdevice-exit-code.txt',))
        refresh_archive_manifest(folder, solver=True)
        fact = self.inspect_solver()['facts']['tool_exit_code']
        self.assertIsNone(fact['value'])
        self.assertEqual(fact['evidence_kind'], 'unavailable')
        self.assert_refused()

    def test_nonzero_step_exit_is_observed_and_rejected(self):
        folder = self.family['solver']
        rewrite_tar(folder / 'results.tar', {'step-001-sdevice-exit-code.txt': b'7\n'})
        refresh_archive_manifest(folder, solver=True)
        fact = self.inspect_solver()['facts']['tool_exit_code']
        self.assertEqual((fact['value'], fact['evidence_kind']), (7, 'observed'))
        self.assert_refused()

    def test_multicore_native_affinity_is_rejected(self):
        folder = self.family['solver']
        raw = b'Name:\tsdevice\nThreads:\t1\nCpus_allowed_list:\t0-1\n'
        rewrite_tar(folder / 'results.tar', {'step-001-sdevice-process-status.txt': raw})
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'multicore'):
            self.inspect_solver()

    def test_multithread_native_process_is_rejected(self):
        folder = self.family['solver']
        raw = b'Name:\tsdevice\nThreads:\t2\nCpus_allowed_list:\t0\n'
        rewrite_tar(folder / 'results.tar', {'step-001-sdevice-process-status.txt': raw})
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'thread'):
            self.inspect_solver()

    def test_same_name_prefix_is_not_an_exact_native_identity(self):
        folder = self.family['solver']
        raw = read_tar_member(folder / 'results.tar', 'step-001-sdevice-process-status.txt')
        changed = raw.replace(b'Name:\tsdevice', b'Name:\tsdevice-wrapper')
        observation = load_json_from_tar(folder / 'results.tar', 'step-001-sdevice-process-observation.json')
        observation['status_sha256'] = digest(changed)
        rewrite_tar(folder / 'results.tar', {
            'step-001-sdevice-process-status.txt': changed,
            'step-001-sdevice-process-observation.json': json.dumps(observation).encode(),
        })
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'exact expected native process'):
            self.inspect_solver()

    def test_raw_native_status_hash_mismatch_is_rejected(self):
        folder = self.family['solver']
        raw = read_tar_member(folder / 'results.tar', 'step-001-sdevice-process-status.txt')
        rewrite_tar(folder / 'results.tar', {'step-001-sdevice-process-status.txt': raw + b'Uid:\t1\n'})
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'status identity/hash mismatch'):
            self.inspect_solver()

    def test_native_pid_mismatch_against_parent_chain_is_rejected(self):
        folder = self.family['solver']
        observation = load_json_from_tar(folder / 'results.tar', 'step-001-sdevice-process-observation.json')
        observation['native_pid'] += 5
        rewrite_tar(folder / 'results.tar', {
            'step-001-sdevice-process-observation.json': json.dumps(observation).encode(),
        })
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'leaf identity mismatch'):
            self.inspect_solver()

    def test_native_parent_chain_mismatch_is_rejected(self):
        folder = self.family['solver']
        observation = load_json_from_tar(folder / 'results.tar', 'step-001-sdevice-process-observation.json')
        observation['parent_chain'][0]['ppid'] += 9
        rewrite_tar(folder / 'results.tar', {
            'step-001-sdevice-process-observation.json': json.dumps(observation).encode(),
        })
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'root child'):
            self.inspect_solver()

    def test_missing_independent_process_admission_remains_unavailable(self):
        folder = self.family['solver']
        rewrite_tar(folder / 'results.tar', removals=(
            'step-001-sdevice-process-admission.json',
            'step-001-sdevice-process-admission-exit-code.txt',
        ))
        refresh_archive_manifest(folder, solver=True)
        report = self.inspect_solver()
        self.assertEqual(report['facts']['tool_process_admission']['evidence_kind'], 'unavailable')
        self.assertIn('tool_process_admission', report['observation_gaps'])
        self.assert_refused()

    def test_nonzero_independent_process_admission_is_rejected(self):
        folder = self.family['solver']
        rewrite_tar(folder / 'results.tar', {
            'step-001-sdevice-process-admission-exit-code.txt': b'86\n',
        })
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'admission exit'):
            self.inspect_solver()

    def test_archive_hash_mismatch_is_rejected(self):
        folder = self.family['solver']
        record_path = folder / 'manifest.json'
        record = load_json(record_path)
        record['results_sha256'] = '0' * 64
        record_path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'archive hash mismatch'):
            self.inspect_solver()

    def test_archived_input_sha_mismatch_is_rejected(self):
        folder = self.family['solver']
        rewrite_tar(folder / 'results.tar', {'source-spec.json': b'{"tampered":true}\n'})
        refresh_archive_manifest(folder, solver=True)
        with self.assertRaisesRegex(ValueError, 'Archived input changed'):
            self.inspect_solver()

    def test_wrong_stored_bit_between_solver_and_extractor_is_rejected(self):
        alpha = fixtures._module(fixtures.S2 / 'alpha.py', '_s2_wrong_bit_fixture_alpha')
        wrong = json.dumps(alpha.source_spec('Aalpha', 1, 'main'), separators=(',', ':')).encode() + b'\n'
        replace_frozen_input(self.family['extraction'], False, 'source-spec.json', wrong)
        self.assert_refused()

    def test_execution_without_explicit_authorization_is_rejected(self):
        folder = self.family['solver']
        release = load_json_from_tar(folder / 'results.tar', 'execution-release.json')
        release['explicit_native_authorization'] = False
        raw = json.dumps(release, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
        replace_frozen_input(folder, True, 'execution-release.json', raw)
        self.assert_refused()

    def test_nominal_geometry_cannot_masquerade_as_native_validation(self):
        folder = self.family['solver']
        report = load_json_from_tar(folder / 'results.tar', 'geometry-validation.json')
        report['origin'] = 'nominal_geometry_contract'
        rewrite_tar(folder / 'results.tar', {'geometry-validation.json': json.dumps(report).encode()})
        refresh_archive_manifest(folder, solver=True)
        self.assert_refused()

    def test_geometry_mesh_binding_mismatch_is_rejected(self):
        folder = self.family['solver']
        report = load_json_from_tar(folder / 'results.tar', 'geometry-validation.json')
        report['mesh_sha256'] = '0' * 64
        rewrite_tar(folder / 'results.tar', {'geometry-validation.json': json.dumps(report).encode()})
        refresh_archive_manifest(folder, solver=True)
        self.assert_refused()

    def test_malformed_geometry_structure_returns_refusal_report(self):
        folder = self.family['solver']
        report = load_json_from_tar(folder / 'results.tar', 'geometry-validation.json')
        report['checks'] = None
        rewrite_tar(folder / 'results.tar', {'geometry-validation.json': json.dumps(report).encode()})
        refresh_archive_manifest(folder, solver=True)
        result = self.audit_fixture()
        self.assertFalse(result['passed'], result)
        self.assertEqual(result['status'], 'REFUSED_MISSING_OR_INVALID_EVIDENCE')
        self.assertFalse(result['native_qualified'])

    def test_malformed_manifest_structure_returns_refusal_report(self):
        path = self.family['solver'] / 'manifest.json'
        path.write_text('[]\n', encoding='utf-8')
        result = self.audit_fixture()
        self.assertFalse(result['passed'], result)
        self.assertEqual(result['status'], 'REFUSED_MISSING_OR_INVALID_EVIDENCE')

    def test_malformed_release_structure_returns_refusal_report(self):
        raw = b'[]\n'
        replace_frozen_input(self.family['solver'], True, 'execution-release.json', raw)
        self.assert_refused()

    def test_malformed_authority_structure_returns_refusal_report(self):
        folder = self.family['solver']
        auth_raw = b'[]\n'
        replace_frozen_input(folder, True, 'authorization-evidence.json', auth_raw)
        release = load_json_from_tar(folder / 'results.tar', 'execution-release.json')
        release['authorization_evidence_sha256'] = digest(auth_raw)
        release_raw = json.dumps(release, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
        replace_frozen_input(folder, True, 'execution-release.json', release_raw)
        self.assert_refused()

    def test_malformed_geometry_evidence_inventory_returns_refusal_report(self):
        folder = self.family['solver']
        report = load_json_from_tar(folder / 'results.tar', 'geometry-validation.json')
        report['evidence_sha256'] = None
        rewrite_tar(folder / 'results.tar', {'geometry-validation.json': json.dumps(report).encode()})
        refresh_archive_manifest(folder, solver=True)
        result = self.audit_fixture()
        self.assertFalse(result['passed'], result)
        self.assertEqual(result['status'], 'REFUSED_MISSING_OR_INVALID_EVIDENCE')

    def test_malformed_source_dependency_map_returns_refusal_report(self):
        folder = self.family['solver']
        source = load_json_from_tar(folder / 'results.tar', 'source-contract.json')
        source['dependency_sha256'] = []
        raw = json.dumps(source, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
        replace_frozen_input(folder, True, 'source-contract.json', raw)
        (self.family['package'] / 'source-contract.json').write_bytes(raw)
        self.assert_refused()

    def test_missing_required_geometry_evidence_is_rejected(self):
        folder = self.family['solver']
        rewrite_tar(folder / 'results.tar', removals=('material-measurements.csv',))
        refresh_archive_manifest(folder, solver=True)
        self.assert_refused()


class HandoffBoundaryTests(unittest.TestCase):
    def test_release_candidate_hashes_dependencies_and_has_no_authority(self):
        root = PROJECT / 'local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/release-candidate-r2'
        candidate = load_json(root / 'candidate.json')
        manifest = load_json(root / 'candidate-manifest.json')
        self.assertEqual(candidate['status'], 'OFFLINE_CANDIDATE_NOT_AUTHORIZATION')
        self.assertFalse(candidate['approved'])
        self.assertFalse(candidate['execution_enabled'])
        self.assertFalse(candidate['authorization_received'])
        self.assertFalse(candidate['original_runner_modified'])
        self.assertFalse(candidate['old_budget_modified'])
        self.assertEqual(candidate['native_calls'], 0)
        self.assertEqual(candidate['frozen_package_manifest_sha256'], '165473aacaada00f613885ced15b0d645205740cdf5c0c0fcffb50d82c18a8f3')
        self.assertEqual(candidate['model_sha256'], 'a89d30d0429defaa6dd491869470e168a6574125af1b8f27cb7689e4f8241481')
        for name, expected in candidate['interface_code_sha256'].items():
            self.assertEqual(digest((MODULE_DIR / name).read_bytes()), expected, name)
        for relative, expected in manifest['files_sha256'].items():
            self.assertEqual(digest((root / relative).read_bytes()), expected, relative)
        self.assertEqual(digest((root / 'candidate-manifest.json').read_bytes()), 'c4298135787a0d5908713121ca19423e829f3a3b4cce5e46db14b0c860771539')
        self.assertEqual(candidate['role_order'], ['B1-D2', 'B1-D3', 'B1-A0-main-b0', 'B1-A0-main-b1'])
        budget_path = PROJECT / 'experiments/dram-see-v4/course-plan-r13/budget.proposed.json'
        self.assertEqual(digest(budget_path.read_bytes()), candidate['budget_proposal_sha256'])
        self.assertEqual((root / 'budget.proposed.json').read_bytes(), budget_path.read_bytes())
        budget = json.loads(budget_path.read_text(encoding='utf-8'))
        self.assertEqual(budget['B1_first_slice']['role_ids'], candidate['role_order'])
        self.assertEqual(budget['all_native_and_training_authorized'], 0)
        role_data = {}
        for role in candidate['role_order']:
            record = load_json(root / (role + '.review.json'))
            role_data[role] = record
            self.assertFalse(record['approved'])
            self.assertFalse(record['execution_enabled'])
            self.assertFalse(record['explicit_native_authorization'])
            self.assertEqual(record['native_launch_reservations'], 0)
            self.assertIsNone(record['actual_mesh_sha256'])
            self.assertIsNone(record['actual_run_id'])
            self.assertIsNone(record['actual_resource_observations'])
            self.assertFalse(record['project_json_created'])
            source = Path(record['input_directory'])
            self.assertFalse((source / 'project.json').exists())
            self.assertFalse((root / (role + '.project.json')).exists())
        self.assertEqual(role_data['B1-D2']['dependency_role'], None)
        self.assertEqual(role_data['B1-D3']['dependency_role'], 'B1-D2')
        self.assertEqual(role_data['B1-A0-main-b0']['dependency_role'], 'B1-D3')
        self.assertEqual(role_data['B1-A0-main-b1']['dependency_role'], 'B1-A0-main-b0')
        for role in ('B1-A0-main-b0', 'B1-A0-main-b1'):
            self.assertEqual(role_data[role]['mesh_producer_role'], 'B1-D3')
        self.assertFalse(list(root.rglob('project.json')))
        resources = load_json(root / 'resource-plan.unmeasured.json')
        self.assertFalse(resources['approved'])
        self.assertFalse(resources['forecast_ready'])
        self.assertTrue(all(value is None for value in resources['unknown'].values()))
        self.assertEqual(resources['proposal']['cpu_hours_cap'], 4)
        self.assertEqual(resources['proposal']['new_retained_GiB_cap'], 8)
        self.assertEqual(candidate['capture_patch_sha256']['tcad.review.patch'],
                         digest((PROJECT / 'local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/capture/r3/tcad.review.patch').read_bytes()))

def load_json_from_tar(path, member):
    return json.loads(read_tar_member(path, member))


def read_tar_member(path, member):
    with tarfile.open(path, 'r:') as archive:
        return archive.extractfile(member).read()


if __name__ == '__main__':
    unittest.main()
