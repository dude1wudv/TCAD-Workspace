"""Focused acceptance/rejection tests; manufactured curves are never TCAD evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
import uuid
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_r5_audit_tests', HERE / 'audit_interface.py')
a = importlib.util.module_from_spec(spec)
exec(compile(spec.loader.get_data(str(HERE / 'audit_interface.py')), str(HERE / 'audit_interface.py'), 'exec'), a.__dict__)


def bundle(case='A1', variant='main', bit=1, offset=0., run=None):
    geometry = 'fine-geometry' if variant == 'fine' else 'main-geometry'
    common = dict(stored_bit=bit, variant=variant, mesh_scale=.25 if variant == 'fine' else .5,
                  pulse_max_step_s=2.5e-13 if variant == 'time' else 5e-13,
                  geometry_sha256=geometry, capacitance_F=1e-14, target_voltage_V=.9 if bit else .1)
    p = dict(common, schema='dram-see-v4-source-interface-r5', case_id=case,
             matching_contract=common, matching_contract_sha256=a.old.sha_bytes(a.old.encoded(common)))
    rows = []
    for time in (0., .95e-9, 1.05e-9, 4e-9):
        value = 0. if case == 'A0' else offset
        row = {'time': time, **{k: value for k in ('v(sn)', 'v(bl)', 'v(ref)', 'v(wl)')}}
        row.update({k: 0. for k in ('i(access,sn)', 'i(access,bl)')})
        rows.append(row)
    device = [{'time': r['time'], **{p + ' TotalCurrent': 0. for p in ('source', 'drain', 'gate', 'body')}} for r in rows]
    native = [{'time': t, **{roi: value for roi in list(a.m.C['rois_um']) + ['SourceLeft', 'SourceRight']}}
              for t, value in ((.95e-9, 0.), (1e-9, 1.), (1.05e-9, 0.))]
    summary = dict(passed=True, errors=[], checks={'individual': {'passed': True}}, audit_tolerances=a.T,
        run_id=run or case + '-' + str(bit) + '-' + variant, mesh_sha256=geometry,
        radiation={'legacy_generated_fC': 1. if case != 'A0' else 0.})
    return dict(summary=summary, parameters=p, source={'physical_source': case},
                curves={'circuit': rows, 'device': device}, native_curves=native)


def manufactured_source(case):
    spec = a.r2.build.make_spec(case)
    proof = a.r2.build.offline_check(spec)  # spatial ledger only; time below uses corrected r3 oracle
    times = [0.] + [.95e-9 + i * .25e-12 for i in range(401)] + [4e-9]
    key = 'IntegrSemiconductor HeavyIonGeneration'
    rows = [{'time': times[0], key: 0.}]
    for start, end in zip(times, times[1:]):
        rows.append({'time': end, key: a.r3.average_profile(spec, proof, 'Total', start, end)[0] / a.CONVERSION})
    return {'device': rows, 'circuit': [{'time': t} for t in times]}, {'case_id': case, 'pulse_max_step_s': .25e-12}, spec, proof


class SourceTests(unittest.TestCase):
    def test_clipped_A3_uses_half_domain_charge(self):
        curves, p, spec, proof = manufactured_source('A3'); out = {}
        self.assertAlmostEqual(proof['domain_charge_fC'], .5, places=6)
        self.assertTrue(a.source_curve(curves, p, spec, proof, out))
        self.assertAlmostEqual(out['radiation']['generated_fC'], .5, places=6)
        key = 'IntegrSemiconductor HeavyIonGeneration'
        for row in curves['device']:
            row[key] *= 2
        with self.assertRaisesRegex(ValueError, 'domain charge'):
            a.source_curve(curves, p, spec, proof, {})

    def test_A6_charge_weighted_time_not_first_track(self):
        curves, p, spec, proof = manufactured_source('A6'); out = {}
        self.assertTrue(a.source_curve(curves, p, spec, proof, out))
        self.assertAlmostEqual(out['radiation']['expected_time_centroid_s'] / 1e-9, 1.005, places=9)
        self.assertGreater(abs(out['radiation']['time_centroid_s'] - spec['tracks'][0]['time_s']), a.T['time_centroid_abs_s'])

    def test_negative_and_missing_total_rejected(self):
        curves, p, spec, proof = manufactured_source('A1')
        curves['device'][1]['IntegrSemiconductor HeavyIonGeneration'] = -1
        with self.assertRaisesRegex(ValueError, 'negative'):
            a.source_curve(curves, p, spec, proof, {})

    def test_A0_missing_total_not_fabricated_numeric_zero(self):
        curves, p, spec, proof = manufactured_source('A0'); out = {}
        for row in curves['device']:
            del row['IntegrSemiconductor HeavyIonGeneration']
        a.source_curve(curves, p, spec, proof, out)
        self.assertIsNone(out['radiation']['generated_fC'])
        self.assertEqual(out['radiation']['evidence'], 'structural_zero_not_measured_zero')


class MatchingTests(unittest.TestCase):
    def test_control_required_and_same_bit_and_mesh(self):
        signal, control = bundle(), bundle('A0')
        self.assertTrue(a.matched_control(signal, control)['passed'])
        for bad in (bundle('A1'), bundle('A0', bit=0), bundle('A0', 'fine')):
            with self.assertRaises(ValueError):
                a.matched_control(signal, bad)
        control['summary']['passed'] = False
        with self.assertRaises(ValueError):
            a.matched_control(signal, control)

    def test_unregistered_r4_alias_rejected(self):
        value = bundle(); value['parameters']['schema'] = 'dram-see-v4-source-interface-r4'
        with self.assertRaisesRegex(ValueError, 'alias'):
            a.canonical_matching(value)

    def test_conflicting_matching_field_rejected(self):
        value = bundle(); value['parameters']['capacitance_F'] = 2e-14
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            a.canonical_matching(value)


class ComparisonTests(unittest.TestCase):
    def test_equivalent_and_order_permutation(self):
        for first, second in [('A1', 'A4'), ('A5', 'A7')]:
            result = a.compare(bundle(first), bundle(second), bundle('A0'), bundle('A0'))
            self.assertTrue(result['passed'], result['errors'])
            self.assertFalse(result['overall_source_interface_passed'])

    def test_native_roi_difference_not_hidden_by_window_currentplot(self):
        left, right = bundle('A1'), bundle('A4')
        right['native_curves'][1]['Center'] *= 1.01
        result = a.compare(left, right, bundle('A0'), bundle('A0'))
        self.assertFalse(result['passed'])
        self.assertEqual(result['errors'][0]['check'], 'generation_comparison')

    def test_unregistered_equivalent_pair_rejected(self):
        result = a.compare(bundle('A1'), bundle('A5'), bundle('A0'), bundle('A0'))
        self.assertFalse(result['passed'])

    def test_segment_needs_main_baseline_and_registered_charge_gate(self):
        self.assertTrue(a.compare(bundle('A1'), bundle('A8S2'), bundle('A0'), bundle('A0'), 'segment')['passed'])
        b = bundle('A8S4'); b['summary']['radiation']['legacy_generated_fC'] = 1.021
        self.assertFalse(a.compare(bundle('A1'), b, bundle('A0'), bundle('A0'), 'segment')['passed'])
        self.assertFalse(a.compare(bundle('A8S2'), bundle('A1'), bundle('A0'), bundle('A0'), 'segment')['passed'])

    def test_refinement_own_control_and_additional_physics_change(self):
        main, time = bundle(offset=.01), bundle(variant='time', offset=.0101)
        self.assertTrue(a.compare(main, time, bundle('A0'), bundle('A0', 'time'), 'refinement')['passed'])
        self.assertFalse(a.compare(main, time, bundle('A0'), bundle('A0'), 'refinement')['passed'])
        time['parameters']['matching_contract']['capacitance_F'] = 2e-14
        time['parameters']['capacitance_F'] = 2e-14
        time['parameters']['matching_contract_sha256'] = a.old.sha_bytes(a.old.encoded(time['parameters']['matching_contract']))
        control = copy.deepcopy(time); control['parameters']['case_id'] = 'A0'
        self.assertFalse(a.compare(main, time, bundle('A0'), control, 'refinement')['passed'])

    def test_refinement_uses_perturbation_and_actual_mesh(self):
        main, fine = bundle(offset=.01), bundle(variant='fine', offset=.012)
        self.assertFalse(a.compare(main, fine, bundle('A0'), bundle('A0', 'fine'), 'refinement')['passed'])
        fine = bundle(variant='fine', offset=.0101)
        self.assertTrue(a.compare(main, fine, bundle('A0'), bundle('A0', 'fine'), 'refinement')['passed'])
        fine['summary']['mesh_sha256'] = main['summary']['mesh_sha256']
        control = bundle('A0', 'fine'); control['summary']['mesh_sha256'] = fine['summary']['mesh_sha256']
        self.assertFalse(a.compare(main, fine, bundle('A0'), control, 'refinement')['passed'])


class EvidenceBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = a.OUTPUT / 'audit-dev' / ('negative-fixtures-' + uuid.uuid4().hex)
        cls.folder.mkdir(parents=True)
        cls.field_path = a.ROOT / 'local_runtime/dram-see-v4/source-field-audit-r1/audit-dev/r4-a1-full-bounded-r1/audit.json'
        cls.field = a.old.json_load(cls.field_path.read_bytes())
        cls.out = {key: cls.field[key] for key in ('run_id', 'archive_sha256', 'manifest_sha256', 'mesh_sha256')}

    def test_field_report_identity_mode_code_and_receipt_tampering_rejected(self):
        changes = [('run_id', 'another-run'), ('mode', 'snapshots'), ('audit_sha256', '0' * 64),
                   ('extraction_record_sha256', '0' * 64), ('errors', [{'check': 'native', 'error': 'failed'}])]
        for key, value in changes:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.field); bad[key] = value
                path = self.folder / (key + '.json'); path.write_text(json.dumps(bad), encoding='utf-8')
                with self.assertRaises(ValueError):
                    a.field_frames(path, dict(self.out), {}, None, revision='r1')

    def test_missing_archive_produces_failed_report(self):
        result = a.load(self.folder / 'no-run')
        self.assertFalse(result['summary']['passed'])
        self.assertEqual(result['summary']['errors'][0]['check'], 'revision_dispatch')

    def test_reuse_registration_does_not_accept_another_run(self):
        bridge = a.module(HERE / 'reuse_bridge.py', '_test_reuse_allowlist')
        with self.assertRaisesRegex(ValueError, 'registered original'):
            bridge.registered(self.folder, a.builder().contract())

    def test_bridge_rejects_even_consistently_rehashed_physical_change(self):
        bridge = a.module(HERE / 'reuse_bridge.py', '_test_reuse_physical')
        b = a.builder(); role = b.contract()['reuse_roles'][0]
        with a.Archive(a.ROOT / role['run_path'] / 'inputs.tar') as archive:
            p = a.old.json_load(archive.read('parameters.json'))
            p['capacitance_F'] = p['matching_contract']['capacitance_F'] = 2e-14
            p['matching_contract_sha256'] = a.old.sha_bytes(a.old.encoded(p['matching_contract']))
            with self.assertRaisesRegex(ValueError, 'additional physical'):
                bridge.physical_equivalence(archive, p, b, 'A0')

    def test_frozen_A4_archive_input_contract_and_tamper(self):
        project = a.OUTPUT / 'inputs/v4-source-interface-r5-a4-b1-main'
        class InputOnlyArchive:
            def __init__(self):
                self.data = {p.name: p.read_bytes() for p in project.iterdir()}
                # Contract-unit fixture only, never a load()/native acceptance result.
                self.members = {'gstep_0000_access_des.tdr': SimpleNamespace(size=1)}
            def read(self, name):
                return self.data[name]
            def digest(self, name):
                return a.old.sha_bytes(self.data[name])
        archive = InputOnlyArchive(); out = {}
        p, source, proof = a.check_contract(archive, project, out)
        self.assertEqual([p['case_id'], p['stored_bit'], p['variant']], ['A4', 1, 'main'])
        self.assertAlmostEqual(proof['domain_charge_fC'], 1., places=6)
        altered = a.old.json_load(archive.data['parameters.json']); altered['source_charge_fC'] = 2.
        archive.data['parameters.json'] = a.old.encoded(altered)
        with self.assertRaises(ValueError):
            a.check_contract(archive, None, {})


if __name__ == '__main__':
    unittest.main()
