"""Focused offline tests for the S2 geometry measurement candidate.

All observations created here are explicit UNIT_FIXTURE_NOT_NATIVE data. They
exercise contracts and refusal paths only; they are not native qualification.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[5]
STAGE = ROOT / 'experiments/dram-see-v4/s2-evidence-r1/geometry-producer-r1'
S2 = ROOT / 'experiments/dram-see-v4/s2-evidence-r1'
PACKAGE = ROOT / 'local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/packages-r2'
sys.path.insert(0, str(STAGE))
sys.path.insert(0, str(S2))
import evaluate  # noqa: E402
import producer  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_csv(path, columns, rows):
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def plan_for(dimension):
    name = 'B1-D2' if dimension == 2 else 'B1-D3'
    manifest = json.loads((PACKAGE / 'package-manifest.json').read_text(encoding='utf-8'))['files_sha256']
    rel = f'roles/{name}/geometry-contract.json'
    geometry = json.loads((PACKAGE / rel).read_text(encoding='utf-8'))
    measurements, contact_probes, material_probes = producer.measurement_plan(geometry)
    return dict(schema='s2-geometry-measurement-plan-r1', role_id=name, dimension=dimension,
                geometry_contract_sha256=manifest[rel], execution_enabled=False, policy_approved=False,
                actual_mesh_sha256=None, expected_geometry=geometry, origin='offline_candidate',
                native_qualified=False, comparison_policy=dict(producer.POLICY), measurements=measurements,
                contact_probes=contact_probes, material_probes=material_probes)


def build_fixture(plan, root, *, native=False):
    """Write a complete self-consistent synthetic raw observation directory."""
    raw = Path(root)
    raw.mkdir(parents=True)
    if not native:
        (raw / 'SYNTHETIC_NOT_NATIVE').write_text('UNIT_FIXTURE_NOT_NATIVE\n', encoding='utf-8')
    plan_path = raw.parent / 'plan.json'
    dump(plan_path, plan)
    role_dir = plan_path.parent
    (role_dir / 'geometry-with-measurements.scm').write_text('; fixture producer deck\n', encoding='utf-8')
    (role_dir / 'measure-geometry.tcl').write_text('# fixture observer\n', encoding='utf-8')

    mesh = b'UNIT_FIXTURE_NOT_NATIVE mesh identity\n'
    (raw / 'cell_msh.tdr').write_bytes(mesh)
    mesh_sha = sha(raw / 'cell_msh.tdr')
    run_id = 'fixture-run-' + str(plan['dimension'])
    raw_exit_hashes = {}
    for filename in ('sde-exit-code.txt','mesh-exit-code.txt','svisual-exit-code.txt'):
        (raw / filename).write_text('0\n', encoding='utf-8')
        raw_exit_hashes[filename] = sha(raw / filename)
    context = dict(schema='s2-geometry-observation-context-r1',
                   synthetic=not native,
                   origin='synthetic_fixture' if not native else 'native_pipeline',
                   plan_sha256=sha(plan_path), geometry_contract_sha256=plan['geometry_contract_sha256'],
                   role_id=plan['role_id'], dimension=plan['dimension'], producer_run_id=run_id,
                   sde_deck_sha256=sha(role_dir / 'geometry-with-measurements.scm'),
                   svisual_script_sha256=sha(role_dir / 'measure-geometry.tcl'), mesh_sha256=mesh_sha,
                   sde_exit_code=0, mesh_exit_code=0, svisual_exit_code=0,
                   raw_exit_sha256=raw_exit_hashes)
    dump(raw / 'observation-context.json', context)
    write_csv(raw / 'mesh-identity.csv', ['phase','path','sha256','run_id','command_status'], [
        dict(phase=phase, path='/fixture/original/cell_msh.tdr', sha256=mesh_sha,
             run_id=run_id, command_status='OK') for phase in ('BEFORE','AFTER')])
    (raw / 'sde-geometry-status.txt').write_text('S2_SDE_GEOMETRY_OBSERVATION_COMPLETED\n', encoding='utf-8')
    dump(raw / 'geometry-status.json', dict(schema='s2-geometry-observation-status-r1', completed=True,
         mandatory_errors=0, dimension=plan['dimension'], plan_role=plan['role_id'], reference_mode='original_mesh'))

    g = plan['expected_geometry']
    inventory = ([dict(kind='material', name=name, parent='') for name in ('Silicon','SiO2','Contact')] +
                 [dict(kind='contact', name=c['name'], parent='Contact') for c in g['contacts']] +
                 [dict(kind='region', name=r['name'], parent=r['material']) for r in g['regions']] +
                 [dict(kind='region', name=c['name'], parent='Contact') for c in g['contacts']] +
                 [dict(kind='field', name=axis, parent='') for axis in ('XY' if plan['dimension']==2 else 'XYZ')] +
                 [dict(kind='field', name=g['doping'][key], parent='') for key in ('donor_species','acceptor_species')])
    write_csv(raw / 'geometry-inventory.csv', ['kind','name','parent'], inventory)

    grouped = {'materials': [], 'contacts': [], 'doping': []}
    for item in plan['measurements']:
        grouped['materials' if item['category']=='units' else item['category']].append(
            dict(id=item['id'], raw_value=repr(item['expected']), command_status='OK'))
    for category, rows in grouped.items():
        fname = {'materials':'material-measurements.csv','contacts':'contact-measurements.csv',
                 'doping':'doping-measurements.csv'}[category]
        write_csv(raw / fname, ['id','raw_value','command_status'], rows)

    contact_rows=[]
    for c in g['contacts']:
        boundary = evaluate.bounds(g, c)
        bounds = {key: value for axis, pair in zip('xyz', boundary)
                  for key, value in ((f'min_{axis}',pair[0]),(f'max_{axis}',pair[1]))}
        contact_rows.append(dict(contact=c['name'], entity_count=4 if c['name']=='gate' and plan['dimension']==2 else
                                 6 if c['name']=='gate' else 1, measure=repr(c['measure']), unit=c['measure_unit'],
                                 **{k:repr(v) for k,v in bounds.items()}))
    write_csv(raw / 'sde-contact-measurements.csv',
              ['contact','entity_count','measure','unit','min_x','min_y','min_z','max_x','max_y','max_z'], contact_rows)
    write_csv(raw / 'sde-contact-probes.csv', ['id','contact','matched_count','attached'], [
        dict(id=p['id'], contact=p['contact'], matched_count='1', attached='1') for p in plan['contact_probes']])
    write_csv(raw / 'sde-material-probes.csv', ['id','matched_count','region','material'], [
        dict(id=p['id'], matched_count='1', region=p['expected_region'], material=p['expected_material'])
        for p in plan['material_probes']])
    return plan_path, raw


class MemoryArchive:
    def __init__(self, directory, report):
        self.files = {p.name:p.read_bytes() for p in Path(directory).iterdir() if p.is_file()}
        self.files['geometry-validation.json'] = json.dumps(report).encode('utf-8')
        self.members = {k:type('Member', (), {'size':len(v)})() for k,v in self.files.items()}

    def read(self, name):
        return self.files[name]

    def digest(self, name):
        return hashlib.sha256(self.files[name]).hexdigest()


class GeometryProducerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='geometry-producer-test-')
        self.base = Path(self.tmp.name)
        self.fixture_index = 0

    def tearDown(self):
        self.tmp.cleanup()

    def evaluate_fixture(self, dimension=2, *, mutate=None):
        plan = plan_for(dimension)
        self.fixture_index += 1
        fixture_id = f'{dimension}-{self.fixture_index}'
        plan_path, raw = build_fixture(plan, self.base / 'UNIT_FIXTURE_NOT_NATIVE' / f'raw-{fixture_id}')
        if mutate:
            mutate(plan, plan_path, raw)
        out = self.base / f'out-{fixture_id}'
        report = evaluate.evaluate(plan_path, raw, out, synthetic=True)
        return report, plan_path, raw, out

    def test_prepare_emits_both_dimensions_and_keeps_original_geometry_prefix(self):
        output = self.base / 'prepared'
        result = producer.prepare(PACKAGE, output)
        self.assertEqual(set(result['roles']), {'B1-D2','B1-D3'})
        self.assertFalse(result['execution_enabled'])
        self.assertEqual(result['native_calls'], 0)
        for role in ('B1-D2','B1-D3'):
            source = PACKAGE / 'roles' / role / 'geometry.scm'
            candidate = output / role / 'geometry-with-measurements.scm'
            self.assertTrue(candidate.read_bytes().startswith(source.read_bytes()))
            self.assertFalse((output / role / 'project.json').exists())
            self.assertFalse(any((output / role).glob('*.tdr')))
            self.assertEqual(json.loads((output / role / 'measurement-plan.json').read_text())['dimension'],
                             2 if role.endswith('D2') else 3)

    def test_complete_synthetic_2d_report_is_compatible_with_existing_geometry_audit(self):
        report, _, raw, _ = self.evaluate_fixture(2)
        self.assertTrue(report['passed'], report['errors'])
        self.assertFalse(report['native_qualified'])
        self.assertFalse(report['is_tcad_result'])
        self.assertTrue(report['synthetic'])
        plan = json.loads((raw.parent/'plan.json').read_text(encoding='utf-8'))
        unit_ids = {item['id'] for item in plan['measurements'] if item['category']=='units'}
        self.assertIn('domain.Y.min', unit_ids)
        self.assertNotIn('domain.Z.min', unit_ids)
        self.assertEqual(plan['expected_geometry']['measure_unit'], 'um^2')
        consumed = __import__('audit')._geometry(MemoryArchive(raw, report), {},
                                                 {'case':'D2'}, synthetic=True)
        self.assertEqual(consumed['schema'], 's2-native-geometry-validation-r1')

    def test_complete_synthetic_3d_uses_volume_and_area_units(self):
        report, plan_path, raw, _ = self.evaluate_fixture(3)
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(plan_path.parent.joinpath('geometry-with-measurements.scm').exists(), True)
        plan = json.loads(plan_path.read_text())
        self.assertEqual(plan['expected_geometry']['measure_unit'], 'um^3')
        self.assertTrue(all(c['measure_unit']=='um^2' for c in plan['expected_geometry']['contacts']))
        unit_ids = {item['id'] for item in plan['measurements'] if item['category']=='units'}
        self.assertTrue({'domain.X.min','domain.Y.min','domain.Z.min'} <= unit_ids)
        self.assertEqual(json.loads((raw/'observation-context.json').read_text())['dimension'], 3)

    def test_synthetic_fixture_cannot_use_public_native_path(self):
        plan_path, raw = build_fixture(plan_for(2), self.base / 'raw-native-attempt')
        out = self.base / 'native-attempt-report'
        report = evaluate.evaluate(plan_path, raw, out, synthetic=False)
        self.assertFalse(report['passed'])
        self.assertFalse(report['native_qualified'])
        self.assertTrue(report['errors'])

    def test_native_path_without_release_is_refused_even_after_provenance_relabel(self):
        plan_path, raw = build_fixture(plan_for(2), self.base / 'candidate-observations', native=True)
        report = evaluate.evaluate(plan_path, raw, self.base/'native-no-release', synthetic=False)
        self.assertFalse(report['passed'])
        self.assertIn('No native geometry producer release/authorization', report['errors'])

    def test_wrong_area_or_volume_is_rejected(self):
        def mutate(plan, _, raw):
            rows = read_csv(raw/'material-measurements.csv')
            rows[0]['raw_value'] = str(float(rows[0]['raw_value']) * 1.1)
            write_csv(raw/'material-measurements.csv', ['id','raw_value','command_status'], rows)
        report, *_ = self.evaluate_fixture(3, mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertFalse(report['checks']['materials'])

    def test_contact_length_or_area_measure_is_enforced(self):
        def mutate(_, __, raw):
            rows = read_csv(raw/'sde-contact-measurements.csv')
            rows[0]['measure'] = str(float(rows[0]['measure']) * 2)
            write_csv(raw/'sde-contact-measurements.csv', list(rows[0]), rows)
        report, *_ = self.evaluate_fixture(2, mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertFalse(report['checks']['contacts'])

    def test_detached_contact_probe_is_rejected(self):
        def mutate(_, __, raw):
            rows = read_csv(raw/'sde-contact-probes.csv')
            rows[0]['attached'] = '0'
            write_csv(raw/'sde-contact-probes.csv', list(rows[0]), rows)
        report, *_ = self.evaluate_fixture(2, mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertFalse(report['checks']['contacts'])

    def test_material_region_mapping_must_match(self):
        def mutate(_, __, raw):
            rows = read_csv(raw/'geometry-inventory.csv')
            next(r for r in rows if r['kind']=='region')['parent'] = 'SiO2'
            write_csv(raw/'geometry-inventory.csv', list(rows[0]), rows)
        report, *_ = self.evaluate_fixture(3, mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertTrue(report['errors'])

    def test_negative_or_nonfinite_dopant_value_is_rejected(self):
        for bad in ('-1.0','NaN','Infinity'):
            with self.subTest(value=bad):
                def mutate(_, __, raw):
                    rows = read_csv(raw/'doping-measurements.csv')
                    rows[0]['raw_value'] = bad
                    write_csv(raw/'doping-measurements.csv', ['id','raw_value','command_status'], rows)
                report, *_ = self.evaluate_fixture(2, mutate=mutate)
                self.assertFalse(report['passed'])
                self.assertFalse(report['checks']['doping'])

    def test_missing_and_duplicate_measurement_rows_are_rejected(self):
        for mode in ('missing','duplicate'):
            with self.subTest(mode=mode):
                def mutate(_, __, raw):
                    rows = read_csv(raw/'contact-measurements.csv')
                    if mode=='missing': rows.pop()
                    else: rows.append(dict(rows[0]))
                    write_csv(raw/'contact-measurements.csv', ['id','raw_value','command_status'], rows)
                report, *_ = self.evaluate_fixture(2, mutate=mutate)
                self.assertFalse(report['passed'])
                self.assertTrue(report['errors'])

    def test_raw_command_error_is_rejected(self):
        def mutate(_, __, raw):
            rows = read_csv(raw/'material-measurements.csv')
            rows[0]['command_status'] = 'ERROR'
            write_csv(raw/'material-measurements.csv', ['id','raw_value','command_status'], rows)
        report, *_ = self.evaluate_fixture(2, mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertTrue(report['errors'])

    def test_mesh_before_after_identity_mismatch_is_rejected(self):
        def mutate(_, __, raw):
            rows = read_csv(raw/'mesh-identity.csv')
            rows[1]['sha256'] = '0'*64
            write_csv(raw/'mesh-identity.csv', ['phase','path','sha256','run_id','command_status'], rows)
        report, *_ = self.evaluate_fixture(2, mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertTrue(report['errors'])

    def test_producer_fingerprint_mismatch_is_rejected(self):
        def mutate(_, __, raw):
            context = json.loads((raw/'observation-context.json').read_text())
            context['sde_deck_sha256'] = '0'*64
            dump(raw/'observation-context.json', context)
        report, *_ = self.evaluate_fixture(2, mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertTrue(report['errors'])

    def test_unapproved_native_comparison_policy_is_rejected(self):
        plan_path, raw = build_fixture(plan_for(2), self.base/'native-policy-observations', native=True)
        policy = dict(plan_for(2)['comparison_policy'])
        policy.update(approved=False, status='PROPOSED_NOT_RELEASED')
        dump(raw/'geometry-policy.released.json', policy)
        dump(raw/'geometry-authorization.json', dict(explicit_native_authorization=True, synthetic=False,
             role_ids=[plan_for(2)['role_id']]))
        release_path = raw/'release.json'
        dump(release_path, dict(schema='s2-geometry-producer-release-r1', status='RELEASED',
             execution_enabled=True, explicit_native_authorization=True, synthetic=False,
             plan_sha256=sha(plan_path), evaluator_sha256=sha(STAGE/'evaluate.py'),
             role_id=plan_for(2)['role_id'], producer_run_id='fixture-run-2', budget_id='fixture-budget',
             budget_reservation_id='fixture-reservation', policy_sha256=sha(raw/'geometry-policy.released.json'),
             authorization_sha256=sha(raw/'geometry-authorization.json')))
        report = evaluate.evaluate(plan_path, raw, self.base/'native-unapproved-policy', synthetic=False,
                                   release_path=release_path)
        self.assertFalse(report['passed'])
        self.assertIn('Geometry policy is unapproved', report['errors'])


if __name__ == '__main__':
    unittest.main()
