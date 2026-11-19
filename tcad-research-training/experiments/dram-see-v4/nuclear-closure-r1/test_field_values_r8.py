"""Read-only native field value parser checks for R8; no solver or live writes."""
import ast
import csv
import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / 'experiments/dram-see-v4/nuclear-closure-r1'
VALIDATION = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1/field-values-r8/validation'
VALIDATION.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HERE))

import common as c
field = importlib.import_module('field_audit_values_r8')


class NativeFieldValuesR8Tests(unittest.TestCase):
    def test_integral_and_extrema_values_keep_native_raw_and_coordinates(self):
        scalar = field.native_measurement(' 1.25e2 ', 'integral')
        self.assertEqual(scalar, dict(raw_value=' 1.25e2 ', value=125., location_um=None, native_form='scalar'))
        extreme = field.native_measurement(' -3.5e2 { 0.1 -0.2 0.3 } ', '-max')
        self.assertEqual(extreme['value'], -350.)
        self.assertEqual(extreme['location_um'], [0.1, -0.2, 0.3])
        self.assertEqual(extreme['raw_value'], ' -3.5e2 { 0.1 -0.2 0.3 } ')
        self.assertEqual(extreme['native_form'], 'value {x y z}')

    def test_truncation_nonfinite_and_malformed_extrema_are_rejected(self):
        invalid = [
            ('1.0 2.0', 'integral'),
            ('1.0 {0 0 0} trailing', 'integral'),
            ('1.0 {0 0 0}', 'integral'),
            ('1.0 {0 0}', '-min'),
            ('1.0 {0 0 0 0}', '-max'),
            ('1.0 {0 0 0} extra', '-min'),
            ('nan', 'integral'),
            ('inf', 'integral'),
            ('1.0 {nan 0 0}', '-min'),
            ('1.0 {0 inf 0}', '-max'),
            ('1.0', '-min'),
            ('1.0', 'min'),
        ]
        for raw, operation in invalid:
            with self.subTest(raw=raw, operation=operation):
                with self.assertRaises(ValueError):
                    field.native_measurement(raw, operation)

    def test_extrema_evidence_retains_raw_and_checks_xyz_extent_and_coordinate(self):
        raw_values = [
            dict(source_file='f0.tdr', field='X', native_field='X', scope='SILICON_NO_WINDOW',
                 operation='-min', raw_value='-1 {-1 0 0}', command_status='OK'),
            dict(source_file='f0.tdr', field='G', native_field='NC_G', scope='SILICON_NO_WINDOW',
                 operation='-max', raw_value='5 {0.25 0 0}', command_status='OK'),
        ]
        columns = ['source_file','field','native_field','scope','operation','raw_value','command_status']
        import io
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader(); writer.writerows(raw_values)
        vals = {
            ('X','SILICON_NO_WINDOW','-min'):-1., ('X','SILICON_NO_WINDOW','-max'):1.,
            ('Y','SILICON_NO_WINDOW','-min'):-1., ('Y','SILICON_NO_WINDOW','-max'):1.,
            ('Z','SILICON_NO_WINDOW','-min'):-1., ('Z','SILICON_NO_WINDOW','-max'):1.,
            ('G','SILICON_NO_WINDOW','-min'):0., ('G','SILICON_NO_WINDOW','-max'):5.,
        }
        result = field.extrema_evidence(stream.getvalue(), {'f0.tdr': vals})
        self.assertEqual(result['record_count'], 2)
        self.assertTrue(result['original_raw_values_preserved'])
        self.assertEqual([r['raw_value'] for r in result['rows']], ['-1 {-1 0 0}', '5 {0.25 0 0}'])
        self.assertEqual(result['rows'][0]['location_um'], [-1., 0., 0.])

        bad_coordinate = stream.getvalue().replace('-1 {-1 0 0}', '-0.5 {-1 0 0}')
        with self.assertRaisesRegex(ValueError, 'coordinate extremum disagrees'):
            field.extrema_evidence(bad_coordinate, {'f0.tdr': vals})
        outside = stream.getvalue().replace('5 {0.25 0 0}', '5 {2 0 0}')
        with self.assertRaisesRegex(ValueError, 'outside observed silicon extent'):
            field.extrema_evidence(outside, {'f0.tdr': vals})

    def test_postprocess_identity_requires_exact_attempt_input_and_success_exit(self):
        with tempfile.TemporaryDirectory(prefix='field-r8-identity-', dir=VALIDATION) as temp:
            root = Path(temp) / 'root'
            rt = root / 'local_runtime/dram-see-v4/nuclear-closure-r1'
            old = root / 'local_runtime/dram-see-v4/transport-probe'
            label = 'nc-r1-fields-isolated'
            attempt_path = rt / 'attempts' / (label + '.json')
            attempt_path.parent.mkdir(parents=True)
            inputs = old / 'inputs' / label
            inputs.mkdir(parents=True)
            operation = (old / 'operations' / label).resolve()
            expected = {'task.sh': b'isolated expected task\n'}
            digest = hashlib.sha256(expected['task.sh']).hexdigest()
            attempt = dict(label=label, kind='postprocess', state='EXECUTED', exit_code=0,
                input_directory=inputs.relative_to(root).as_posix(), input_hashes={'task.sh':digest})
            attempt_path.write_text(json.dumps(attempt), encoding='utf-8')
            op = dict(label=label, ssh_exit_code=0, input_sha256={'task.sh':digest})
            with mock.patch.object(c, 'ROOT', root), mock.patch.object(c, 'RT', rt), \
                 mock.patch.object(c, 'OLD_OPS', old), mock.patch.object(field, 'ROOT', root), \
                 mock.patch.object(field, 'RT', rt):
                identity = field.postprocess_identity(operation, op, expected)
                self.assertEqual(identity['local_adapter_exit_code'], 0)
                self.assertEqual(identity['ssh_exit_code'], 0)
                attempt['exit_code'] = 1
                attempt_path.write_text(json.dumps(attempt), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'adapter exit unknown/failed'):
                    field.postprocess_identity(operation, op, expected)
                attempt['exit_code'] = 0
                attempt['input_hashes'] = {'task.sh':'0'*64}
                attempt_path.write_text(json.dumps(attempt), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'input ledgers differ'):
                    field.postprocess_identity(operation, op, expected)

    def test_real_69_frame_operation_parses_measured_zero_and_native_science_rejects(self):
        rt = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1'
        attempt_path = rt / 'attempts/nc-r1-fields-qualification-zero.json'
        attempt = json.loads(attempt_path.read_text(encoding='utf-8'))
        self.assertEqual((attempt['state'], attempt['exit_code']), ('EXECUTED', 0))
        label = attempt['label']
        operation = ROOT / 'local_runtime/dram-see-v4/transport-probe/operations' / label
        run = ROOT / 'local_runtime/runs/20261015T061444Z-v4-nuclear-closure-r1-qualification-zero-fcbd4da7'
        record = operation / 'field-extraction-record.json'
        gate = rt / 'device/gates/qualification-zero.json'
        before = {p: (p.exists(), c.sha(p) if p.is_file() else None) for p in (record, gate)}

        manifest, report = field.source_provenance(run)
        r7_manifest, r7_report = field.preparer().source_provenance(run)
        self.assertEqual((manifest, report), (r7_manifest, r7_report))
        values, receipt = field.operation_evidence(operation, manifest, report)
        self.assertEqual(receipt['runner_exit_code'], 0)
        self.assertEqual(receipt['ssh_exit_code'], 0)
        self.assertEqual(receipt['svisual_exit_code'], 0)
        self.assertEqual(receipt['physical_acceptance'], False)
        self.assertEqual(receipt['extraction_preparer']['path'], 'experiments/dram-see-v4/nuclear-closure-r1/field_audit_index_r7.py')
        self.assertEqual(receipt['audit_code']['path'], 'experiments/dram-see-v4/nuclear-closure-r1/field_audit_values_r8.py')

        raw_path = operation / 'collected/field-measurements.csv'
        with raw_path.open(newline='', encoding='utf-8') as stream:
            raw_rows = list(csv.DictReader(stream))
        self.assertEqual(len(report['accepted_intervals']), 69)
        self.assertEqual(len(raw_rows), 5106)
        frame_names = sorted(report['tdr_sha256'])
        self.assertEqual(len(values), 69)
        for name in frame_names:
            for key in ('T_PMI','DT_PMI','STEP_PMI'):
                self.assertEqual(values[name][key,'SILICON_NO_WINDOW','-min'], 0.)
                self.assertEqual(values[name][key,'SILICON_NO_WINDOW','-max'], 0.)
        with field.libraries().Archive(run / 'results.tar') as archive:
            parsed = field.curves(archive, report['parameters'], {})
        metrics, _ = field.native_metrics(report['accepted_intervals'], values, parsed['device'],
                                           report['source'], report['parameters'])
        self.assertFalse(metrics['passed'])
        self.assertTrue(any('PMI native clock/step identity differs: T_PMI' in e for e in metrics['errors']))
        after = {p: (p.exists(), c.sha(p) if p.is_file() else None) for p in (record, gate)}
        self.assertEqual(after, before)

    def test_native_science_and_r7_preparation_binding_are_unchanged(self):
        r7 = ast.parse((HERE / 'field_audit_index_r7.py').read_text(encoding='utf-8'))
        r8 = ast.parse((HERE / 'field_audit_values_r8.py').read_text(encoding='utf-8'))
        def get_function(tree, name):
            return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        self.assertEqual(ast.dump(get_function(r7, 'native_metrics'), include_attributes=False),
                         ast.dump(get_function(r8, 'native_metrics'), include_attributes=False))
        for name in ('source_provenance','operation_inputs','prepare'):
            source = ast.dump(get_function(r8, name), include_attributes=False)
            self.assertIn('preparer', source)
            self.assertIn(name, source)

        def parse(path):
            return ast.parse(path.read_text(encoding='utf-8'))
        def normalize(tree, constants, modules=None):
            modules = modules or {}
            class Bindings(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if isinstance(node.value, str) and node.value in constants:
                        return ast.copy_location(ast.Constant(constants[node.value]), node)
                    return node
                def visit_Import(self, node):
                    for alias in node.names:
                        if alias.name in modules: alias.name = modules[alias.name]
                    return node
                def visit_ImportFrom(self, node):
                    if node.module in modules: node.module = modules[node.module]
                    return node
            return ast.dump(Bindings().visit(tree), include_attributes=False)
        def adapter(base, revised, constants, modules=None):
            old, new = parse(HERE/base), parse(HERE/revised)
            self.assertEqual(ast.dump(old, include_attributes=False), normalize(new, constants, modules))

        adapter('acceptance_field_r7.py','acceptance_values_r8.py',
                {'field_audit_values_r8.py':'field_audit_index_r7.py'})
        adapter('campaign_field_r7.py','campaign_values_r8.py',
                {'acceptance_values_r8.py':'acceptance_field_r7.py',
                 'field_audit_values_r8.py':'field_audit_index_r7.py'},
                {'acceptance_values_r8':'acceptance_field_r7'})
        adapter('continue_fields_r7.py','continue_values_r8.py',
                {'release-values-r8.json':'release-fields-r7.json',
                 'Field-values r8 not released':'Field-index r7 not released',
                 'campaign_values_r8.py':'campaign_field_r7.py'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
