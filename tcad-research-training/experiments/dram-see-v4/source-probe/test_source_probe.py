"""Focused offline regression checks for the frozen v4 source-probe generator."""
import hashlib
import importlib.util
import io
import json
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION_LOGS = ROOT / 'local_runtime/dram-see-v4/source-probe/validation/logs'
BUILDER_PATH = HERE / 'build_probe.py'
CONTRACT_PATH = HERE / 'source_contract.json'


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class SourceProbeGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load_module(BUILDER_PATH, '_v4_source_probe_test_builder')
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))

    def test_a0_has_event_identity_but_no_source(self):
        spec = self.builder.make_spec('A0')
        result = self.builder.offline_check(spec)
        self.assertEqual(spec['event_id'], 'synthetic-v4-source-probe-a0')
        self.assertTrue(spec['synthetic'])
        self.assertEqual(spec['source_total_fC'], 0)
        self.assertEqual(spec['tracks'], [])
        self.assertEqual(result['analytic_charge_fC'], 0)
        self.assertEqual(result['tracks'], [])
        self.assertNotRegex(self.builder.render_sources(spec), r'\bHeavyIon\s*\(')

    def test_a1_and_a4_preserve_units_geometry_and_analytic_equivalence(self):
        a1 = self.builder.make_spec('A1')
        a4 = self.builder.make_spec('A4')
        self.assertEqual(a1['source_total_fC'], 1)
        self.assertEqual(a4['source_total_fC'], 1)
        self.assertEqual(len(a1['tracks']), 1)
        self.assertEqual(len(a4['tracks']), 2)
        for spec in (a1, a4):
            for track in spec['tracks']:
                self.assertEqual(track['start_um'], [.425, .3])
                self.assertEqual(track['direction'], [0., 1.])
                self.assertEqual(track['length_um'], .6)
                self.assertEqual(track['wt_hi_um'], .03)
                self.assertEqual(track['time_s'], 1e-9)
                self.assertEqual(track['s_hi_s'], 2e-12)
                self.assertAlmostEqual(track['let_pC_per_um'] * track['length_um'] * 1e3,
                                       track['q_fC'], delta=1e-12)
        self.assertEqual([t['q_fC'] for t in a4['tracks']], [.5, .5])
        a1_check = self.builder.offline_check(a1)
        a4_check = self.builder.offline_check(a4)
        self.assertLessEqual(abs(a1_check['analytic_charge_fC'] - 1), .001)
        self.assertLessEqual(abs(a4_check['analytic_charge_fC'] - 1), .001)
        self.assertLessEqual(a4_check['A1_A4_manufactured_field_max_relative_difference'], 1e-12)
        self.assertEqual(set(self.contract['heavyion_parameters']),
                         set(self.builder.load_contract()['heavyion_parameters']))
        parameter_text = self.builder.render_parameters(a4)
        for track in a4['tracks']:
            self.assertRegex(parameter_text, r'HeavyIon\("' + re.escape(track['source_name']) + r'"\)\s*\{')
        for name, value in self.builder.load_contract()['heavyion_parameters'].items():
            self.assertRegex(parameter_text, rf'(?m)^\s*{re.escape(name)}\s*=\s*{re.escape(format(value, ".17g"))}\s*$')

    def test_builds_are_immutable_and_reject_bad_paths_and_changed_inputs(self):
        VALIDATION_LOGS.mkdir(parents=True, exist_ok=True)
        original_root = self.builder.OUTPUT_ROOT
        try:
            with tempfile.TemporaryDirectory(prefix='generator-', dir=VALIDATION_LOGS) as temp:
                test_root = Path(temp)
                self.builder.OUTPUT_ROOT = test_root
                for case in ('A0', 'A1', 'A4'):
                    project = test_root / ('v4-source-probe-' + case.lower() + '-b1')
                    built = self.builder.build(project, case, 1)
                    self.assertEqual(built['status'], 'OFFLINE_INPUT_CHECK_PASSED')
                    self.assertEqual(built['case_id'], case)
                    deck = (project / 'device.cmd').read_text(encoding='utf-8')
                    expected_sources = 0 if case == 'A0' else (1 if case == 'A1' else 2)
                    self.assertEqual(len(re.findall(r'\bHeavyIon\s*\("', deck)), expected_sources)
                target = test_root / 'v4-source-probe-a0-b1'
                with self.assertRaisesRegex(ValueError, 'Immutable output already exists'):
                    self.builder.build(target, 'A0', 1)
                outside = test_root.parent / 'v4-source-probe-a0-b1-outside'
                with self.assertRaisesRegex(ValueError, 'Inputs must stay under'):
                    self.builder.build(outside, 'A0', 1)
                (target / 'device.cmd').write_text('modified\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Input hash mismatch: device.cmd'):
                    self.builder.check_project(target)
        finally:
            self.builder.OUTPUT_ROOT = original_root

    def test_v3_reference_files_are_read_only(self):
        paths = (ROOT / 'experiments/dram-see-v3/r50-main/build_case.py',
                 ROOT / 'experiments/dram-see-v3/r50-main/audit.py')
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        for case in ('A0', 'A1', 'A4'):
            self.builder.offline_check(self.builder.make_spec(case))
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        self.assertEqual(after, before)


class SourceProbeAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_module(HERE / 'audit_probe.py', '_v4_source_probe_test_audit')
        cls.builder = load_module(BUILDER_PATH, '_v4_source_probe_audit_fixture_builder')

    @staticmethod
    def _write_tar(path, members):
        with tarfile.open(path, 'w') as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def _manifest_fixture(self, folder, *, ssh_exit=0, bad_input_hash=False):
        folder.mkdir(parents=True)
        inputs = {name: (name + '\n').encode() for name in (
            'project.json', 'parameters.json', 'geometry.scm', 'device.cmd',
            'source-spec.json', 'source-contract.json')}
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in inputs.items()}
        if bad_input_hash:
            hashes['source-contract.json'] = '0' * 64
        self._write_tar(folder / 'inputs.tar', inputs)
        self._write_tar(folder / 'results.tar', {'placeholder.txt': b'fixture\n'})
        manifest = {
            'run_id': folder.name, 'state': 'COLLECTED', 'ssh_exit_code': ssh_exit,
            'input_sha256': hashes,
            'results_sha256': hashlib.sha256((folder / 'results.tar').read_bytes()).hexdigest(),
        }
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    def test_manifest_rejects_unknown_exit_and_archive_input_hash_mismatch(self):
        VALIDATION_LOGS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='audit-manifest-', dir=VALIDATION_LOGS) as temp:
            root = Path(temp)
            unknown = root / 'unknown-exit'
            self._manifest_fixture(unknown, ssh_exit=None)
            with self.assertRaisesRegex(ValueError, 'actual integer 0'):
                self.audit._manifest(unknown, self.audit._report('test'))
            mismatch = root / 'input-hash-mismatch'
            self._manifest_fixture(mismatch, bad_input_hash=True)
            with self.assertRaisesRegex(ValueError, 'Frozen input hash mismatch: source-contract.json'):
                self.audit._manifest(mismatch, self.audit._report('test'))

    def test_provenance_rejects_unknown_remote_exit_code(self):
        class TinyArchive:
            def read(self, name):
                self.asserted_name = name
                return b'unknown\n'

        with self.assertRaisesRegex(ValueError, 'Unknown/malformed remote exit code'):
            self.audit._provenance(TinyArchive(), {'input_sha256': {}}, Path('.'), None,
                                   {'engineering_evidence': {}})

    def test_curve_audit_rejects_truncation_and_nonfinite_rows(self):
        class TinyArchive:
            def read(self, name):
                return name.encode()

        report = {}
        truncated_rows = [{'time': 0.}, {'time': 4e-9 - 2e-18}]
        with patch.object(self.audit, 'parse_plt', return_value=(['time'], truncated_rows)):
            with self.assertRaisesRegex(ValueError, 'does not reach 4 ns'):
                self.audit._curves(TinyArchive(), report)
        nonfinite_rows = [{'time': 0.}, {'time': float('nan')}]
        with patch.object(self.audit, 'parse_plt', return_value=(['time'], nonfinite_rows)):
            with self.assertRaisesRegex(ValueError, 'Nonfinite raw solver data'):
                self.audit._curves(TinyArchive(), {})

    def test_a0_structural_zero_allows_absent_generation_dataset(self):
        VALIDATION_LOGS.mkdir(parents=True, exist_ok=True)
        original_root = self.builder.OUTPUT_ROOT
        try:
            with tempfile.TemporaryDirectory(prefix='audit-a0-', dir=VALIDATION_LOGS) as temp:
                self.builder.OUTPUT_ROOT = Path(temp)
                project = Path(temp) / 'v4-source-probe-a0-b1'
                self.builder.build(project, 'A0', 1)

                class ProjectArchive:
                    def read(self, name):
                        return (project / name).read_bytes()

                    def digest(self, name):
                        return hashlib.sha256((project / name).read_bytes()).hexdigest()

                parameters = json.loads((project / 'parameters.json').read_text(encoding='utf-8'))
                source = json.loads((project / 'source-spec.json').read_text(encoding='utf-8'))
                curves = {'device': [{'time': 0., 'source TotalCurrent': 0.}]}
                report = {}
                radiation = self.audit._source_audit(ProjectArchive(), parameters, source, curves, report)
                self.assertEqual(radiation['generated_fC'], 0.)
                self.assertIsNone(radiation['generation_dataset'])
                self.assertEqual(radiation['generation_evidence'], 'source_free_deck_without_generation_dataset')
        finally:
            self.builder.OUTPUT_ROOT = original_root

    def test_pair_curve_keeps_frozen_voltage_and_source_tolerances(self):
        self.assertEqual(self.audit.TOLERANCES,
                         self.builder.load_contract()['audit_tolerances'])
        baseline = [{'time': 0., 'v': 1.}, {'time': 1., 'v': 1.}]
        within = [{'time': 0., 'v': 1. + 0.9e-5}, {'time': 1., 'v': 1. + 0.9e-5}]
        beyond = [{'time': 0., 'v': 1. + 1.1e-5}, {'time': 1., 'v': 1. + 1.1e-5}]
        limit = self.audit.TOLERANCES['pair_voltage_abs_V']
        self.assertTrue(self.audit._pair_curve(baseline, within, 'v', absolute=limit)['passed'])
        self.assertFalse(self.audit._pair_curve(baseline, beyond, 'v', absolute=limit)['passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
