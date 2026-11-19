"""Focused r5 offline checks and counterexamples; no solver or SVisual calls."""
import ast
import copy
import importlib.util
import math
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
path = HERE / 'build_interface.py'
sp = importlib.util.spec_from_file_location('r5_builder_tests', path)
b = importlib.util.module_from_spec(sp)
exec(compile(path.read_bytes(), str(path), 'exec'), b.__dict__)


class SourceInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = b.OUTPUT_ROOT / 'build-dev'
        work.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='focused-', dir=work)
        cls.projects = {}
        for case, bit, variant in b.PRIMARY_ROLES + b.REUSE_ROLES:
            out = Path(cls.temp.name) / ('v4-source-interface-r5-' + case.lower() + '-b' + str(bit) + '-' + variant)
            result = b.build(out, case, bit, variant)
            if result['status'] != 'OFFLINE_INPUT_CHECK_PASSED':
                raise AssertionError(result)
            cls.projects[(case, bit, variant)] = out

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def proof(self, case):
        return b.offline_proof(b.source_spec(case))

    def test_exact_seventeen_primary_plus_two_reuse_roles(self):
        c = b.contract()
        self.assertEqual(len(c['primary_roles']), 17)
        self.assertEqual(len(c['reuse_roles']), 2)
        self.assertEqual(len({tuple(x) for x in b.PRIMARY_ROLES + b.REUSE_ROLES}), 19)
        for role in [('A0', True, 'main'), ('A1', 1, 'base'), ('A6', 0, 'main'), ('A5', 1, 'time'), ('A4', 1, 'fine')]:
            with self.assertRaises(ValueError):
                b.check_role(*role)

    def test_profile_and_budget_independent(self):
        c = b.contract()
        self.assertEqual(c['variants'], b.PROFILES)
        g = c['global_budget']
        self.assertEqual(g['primary_attempts'] + g['reserve_attempts'], g['this_round_maximum_attempts'])
        self.assertEqual(g['historical_attempts_at_freeze'] + g['this_round_maximum_attempts'], 26)

    def test_offline_references_are_not_primary_candidates(self):
        for role, project in self.projects.items():
            p = b.read_json(project / 'parameters.json')
            reuse = list(role) in b.REUSE_ROLES
            self.assertEqual(p['primary_solver_eligible'], not reuse)
            self.assertEqual(p['recalculation_requires_reserve'], reuse)
            self.assertEqual(p['build_purpose'], 'offline_reuse_reference' if reuse else 'primary_candidate')

    def test_registered_reuse_evidence_exists_and_hashes_match(self):
        for item in b.contract()['reuse_roles']:
            for prefix in ('audit', 'comparison', 'field_audit'):
                if item[prefix + '_path'] is not None:
                    p = b.ROOT / item[prefix + '_path']
                    self.assertEqual(b.sha(p.read_bytes()), item[prefix + '_sha256'])
                    self.assertTrue(b.read_json(p)['passed'])
            project = b.ROOT / item['project_path']
            self.assertEqual(b.sha((project / 'input-manifest.json').read_bytes()), item['manifest_sha256'])
            self.assertEqual(b.sha((b.ROOT / item['run_path'] / 'manifest.json').read_bytes()), item['run_manifest_sha256'])

    def test_main_matches_r4_physics_and_source_bytes(self):
        for case in ('A0', 'A1'):
            project = self.projects[(case, 1, 'main')]
            old = b.ROOT / next(x['project_path'] for x in b.contract()['reuse_roles'] if x['case_id'] == case)
            for name in ('geometry.scm', 'device.cmd', 'heavyion.par', 'source-spec.json'):
                self.assertEqual((project / name).read_bytes(), (old / name).read_bytes(), name)
            p = b.read_json(project / 'parameters.json')['matching_contract']
            q = b.read_json(old / 'parameters.json')['matching_contract']
            self.assertEqual({k for k in p if p[k] != q[k]}, {'variant'})
            self.assertEqual((q['variant'], p['variant']), ('mesh', 'main'))

    def test_main_time_geometry_identical_fine_only_nine_lengths_halved(self):
        main = b.render_geometry('main').decode().splitlines()
        fine = b.render_geometry('fine').decode().splitlines()
        self.assertEqual(b.render_geometry('main'), b.render_geometry('time'))
        differences = [(a, z) for a, z in zip(main, fine) if a != z]
        self.assertEqual(len(main), len(fine))
        self.assertEqual(len(differences), 3)
        counts = []
        for old, new in differences:
            oldparts, newparts = old.split(), new.split()
            self.assertEqual(len(oldparts), len(newparts))
            altered = [(a, z) for a, z in zip(oldparts, newparts) if a != z]
            counts.append(len(altered))
            for a, z in altered:
                self.assertAlmostEqual(float(a.rstrip(')')) / 2, float(z.rstrip(')')), places=16)
            self.assertTrue('define-refinement-size' in old or 'MaxLenInt' in old)
        self.assertEqual(sorted(counts), [1, 4, 4])

    def test_geometry_rejects_unapproved_mesh(self):
        for value in (1., .4, .125, 0., -1., math.nan, True, '.5'):
            with self.assertRaises(ValueError):
                b._geometry_bytes(value)

    def test_geometry_rejects_changed_source(self):
        with mock.patch.object(b.Path, 'read_bytes', return_value=b'altered frozen source'):
            with self.assertRaisesRegex(ValueError, 'source SHA'):
                b._geometry_bytes(.5)

    def test_geometry_rejects_missing_or_ambiguous_assignment(self):
        for text in ('def build():\n pass\n', 'def build():\n geometry=f"{length}"\n geometry=f"{width}"\n'):
            altered = ast.parse(text)
            with mock.patch.object(b.ast, 'parse', return_value=altered):
                with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
                    b._geometry_bytes(.5)

    def test_geometry_rejects_new_ast_function_or_variable(self):
        for expression in ('f"{length}{width}{mesh}{evil()}"', 'f"{length}{width}{mesh}{secret}"'):
            altered = ast.parse('def build():\n geometry=' + expression)
            with mock.patch.object(b.ast, 'parse', return_value=altered):
                with self.assertRaisesRegex(ValueError, 'dependency'):
                    b._geometry_bytes(.5)

    def test_each_role_restores_frozen_physical_deck(self):
        for case, bit, variant in self.projects:
            deck = b.render_deck(case, bit, variant)
            self.assertEqual(b.strip_observers(deck, case, bit, variant), b.physical_deck(case, bit, variant))
            self.assertEqual(deck.count(b.DYNAMIC_PLOT), 1)
            self.assertNotIn('Intervals', deck)
            self.assertNotIn('MinSpacing', deck)
            self.assertEqual(len(re.findall(r'Plot\(FilePrefix="gfield_\d" Time=', deck)), 5)
            injection = deck[deck.index('Transient(InitialTime=0.95e-9'):deck.index('Transient(InitialTime=1.05e-9')]
            self.assertIn(b.DYNAMIC_PLOT, injection)

    def test_time_refinement_changes_only_injection_initial_and_max_step(self):
        for case in ('A0', 'A1', 'A6'):
            main, fine = b.render_deck(case, 1, 'main'), b.render_deck(case, 1, 'time')
            a = b.PROFILES['main']['pulse_max_step_s']
            z = b.PROFILES['time']['pulse_max_step_s']
            before = 'Transient(InitialTime=0.95e-9 FinalTime=1.05e-9 InitialStep=' + b.number(a / 5) + ' MinStep=1e-18 MaxStep=' + b.number(a)
            after = 'Transient(InitialTime=0.95e-9 FinalTime=1.05e-9 InitialStep=' + b.number(z / 5) + ' MinStep=1e-18 MaxStep=' + b.number(z)
            self.assertEqual(main.count(before), 1)
            expected = main.replace(before, after, 1)
            self.assertEqual(fine, expected)

    def test_fine_deck_identical_main_and_only_geometry_changes(self):
        for case in ('A0', 'A1', 'A5'):
            self.assertEqual(b.render_deck(case, 1, 'fine'), b.render_deck(case, 1, 'main'))

    def test_a0_source_free_without_undefined_centroids(self):
        spec, proof = b.source_spec('A0'), self.proof('A0')
        self.assertTrue(spec['event_id'])
        self.assertEqual(spec['tracks'], [])
        self.assertEqual(proof['domain_charge_fC'], 0.)
        self.assertNotIn('HeavyIon("Ion', b.render_deck('A0'))
        self.assertNotIn('Coordinates', b.current_plot('A0'))
        for roi in proof['rois'].values():
            self.assertIsNone(roi['centroid_x_um'])
            self.assertIsNone(roi['time_centroid_s'])

    def test_a3_half_domain_charge_not_renormalized(self):
        proof = self.proof('A3')
        self.assertEqual(proof['source_total_fC'], 1.)
        self.assertAlmostEqual(proof['domain_charge_fC'], .5, places=13)
        self.assertAlmostEqual(proof['outside_domain_fC'], .5, places=13)
        self.assertAlmostEqual(proof['rois']['Total']['centroid_x_um'], .03 / math.sqrt(math.pi), places=12)

    def test_a6_two_distinct_local_time_centers(self):
        proof = self.proof('A6')
        left, right = proof['rois']['SourceLeft'], proof['rois']['SourceRight']
        self.assertAlmostEqual(left['time_centroid_s'], 1e-9, delta=1e-24)
        self.assertAlmostEqual(right['time_centroid_s'], 1.01e-9, delta=1e-24)
        self.assertAlmostEqual(right['time_centroid_s'] - left['time_centroid_s'], 1e-11, delta=1e-24)
        self.assertAlmostEqual(proof['rois']['Total']['time_centroid_s'], 1.005e-9, delta=1e-24)
        self.assertAlmostEqual(left['q_fC'], .5 * math.erf(1), places=12)
        self.assertEqual({p['source_name'] for p in left['tracks']}, {'Ion1', 'Ion2'})

    def test_a4_half_sources_and_a7_order_only_equivalence(self):
        for a, z in (('A1', 'A4'), ('A5', 'A7')):
            pa, pz = self.proof(a), self.proof(z)
            for roi in pa['rois']:
                for k in ('q_fC', 'centroid_x_um', 'centroid_y_um', 'time_centroid_s'):
                    self.assertAlmostEqual(pa['rois'][roi][k], pz['rois'][roi][k], places=12)
        self.assertEqual(list(reversed(b.source_spec('A5')['tracks'])), b.source_spec('A7')['tracks'])
        self.assertEqual([t['q_fC'] for t in b.source_spec('A4')['tracks']], [.5, .5])

    def test_a8_disjoint_segments_conserve_charge_length_and_density(self):
        for case, count in [('A8S2', 2), ('A8S4', 4)]:
            spec = b.source_spec(case)
            self.assertEqual(sum(t['q_fC'] for t in spec['tracks']), 1.)
            self.assertAlmostEqual(sum(t['length_um'] for t in spec['tracks']), .6)
            for i, track in enumerate(spec['tracks']):
                self.assertEqual(track['track_id'], 1)
                self.assertEqual(track['q_fC'], 1 / count)
                self.assertAlmostEqual(track['let_pC_per_um'], .001 / .6)
                self.assertAlmostEqual(track['start_um'][1], .3 + i * .6 / count)
            for y in (.321, .447, .613, .887):
                actual = b.generation(spec, .431, y, 1.001e-9)
                expected = b.generation(b.source_spec('A1'), .431, y, 1.001e-9)
                self.assertAlmostEqual(actual / expected, 1., places=14)
            self.assertAlmostEqual(self.proof(case)['domain_charge_fC'], 1., places=14)

    def test_sigma_is_s_hi_and_corrected_kernel_is_normalized(self):
        track = b.source_spec('A1')['tracks'][0]
        t, s = track['time_s'], track['s_hi_s']
        self.assertAlmostEqual(b.oracle.mass(t-s, t+s, t, s), math.erf(1 / math.sqrt(2)), places=13)
        self.assertAlmostEqual(b.oracle.mass(0., 4e-9, t, s), 1., places=14)
        self.assertAlmostEqual(b.oracle.instantaneous(t+s, t, s) / b.oracle.instantaneous(t, t, s), math.exp(-.5), places=13)
        self.assertNotAlmostEqual(b.oracle.instantaneous(t+s, t, s) / b.oracle.instantaneous(t, t, s), math.exp(-.25), places=3)

    def test_eleven_roi_proof_preserves_old_nine_spatial_quantities(self):
        for case in b.contract()['case_ids']:
            proof = self.proof(case)
            self.assertFalse(proof['is_tcad_result'])
            self.assertEqual(len(proof['rois']), 11)
            old = b.r2.offline_check(b.source_spec(case))
            for roi in b.contract()['legacy_roi_names']:
                for key in ('q_fC', 'centroid_x_um', 'centroid_y_um'):
                    self.assertEqual(proof['rois'][roi][key], old['rois'][roi][key])
            for partition in b.contract()['partitions']:
                self.assertAlmostEqual(sum(proof['rois'][r]['q_fC'] for r in partition), proof['domain_charge_fC'], delta=1e-8)

    def test_missing_conflicting_or_non_2d_source_rejected(self):
        for mutate in (lambda s: s['tracks'][0].pop('q_fC'),
                       lambda s: s['tracks'][0].update(q_fC=2.),
                       lambda s: s['tracks'][0].update(s_hi_s=math.nan),
                       lambda s: s.update(synthetic=False),
                       lambda s: s['tracks'][0].update(start_um=[.425, .3, .1])):
            spec = b.source_spec('A1')
            mutate(spec)
            with self.assertRaises((ValueError, KeyError)):
                b.offline_proof(spec)

    def test_duplicate_segment_ownership_rejected(self):
        spec = b.source_spec('A8S2')
        spec['tracks'][1]['source_step_ids'] = spec['tracks'][0]['source_step_ids']
        with self.assertRaisesRegex(ValueError, 'step ownership'):
            b.offline_proof(spec)

    def test_project_declares_fixed_outputs_without_wildcards(self):
        for project in self.projects.values():
            p = b.read_json(project / 'project.json')
            self.assertEqual([x['tool'] for x in p['steps']], ['sde', 'sdevice'])
            outputs = p['steps'][1]['outputs']
            self.assertEqual(len(outputs), 9)
            self.assertTrue(all('*' not in x and '?' not in x and 'gstep' not in x for x in outputs))
            self.assertIn('transient_des.log', outputs)

    def test_duplicate_and_outside_output_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            b.build(self.projects[('A4', 1, 'main')], 'A4')
        with self.assertRaisesRegex(ValueError, 'new child directory'):
            b.build(b.ROOT / 'v4-source-interface-r5-a4-b1-main', 'A4')

    def test_rehashed_deck_tamper_is_rejected(self):
        project = self.projects[('A2', 1, 'main')]
        path = project / 'device.cmd'
        old, manifest = path.read_bytes(), (project / 'input-manifest.json').read_bytes()
        try:
            path.write_bytes(old.replace(b'NoOverwrite', b'NoOverwrite Intervals=200'))
            m = b.read_json(project / 'input-manifest.json')
            m['files_sha256']['device.cmd'] = b.sha(path.read_bytes())
            (project / 'input-manifest.json').write_bytes(b.encoded(m))
            with self.assertRaisesRegex(ValueError, 'full deck differs'):
                b.check_project(project)
        finally:
            path.write_bytes(old)
            (project / 'input-manifest.json').write_bytes(manifest)

    def test_rehashed_matching_conflict_is_rejected(self):
        project = self.projects[('A5', 1, 'fine')]
        path = project / 'parameters.json'
        old, manifest = path.read_bytes(), (project / 'input-manifest.json').read_bytes()
        try:
            p = b.read_json(path)
            p['matching_contract']['mesh_scale'] = .5
            p['matching_contract_sha256'] = b.sha(b.encoded(p['matching_contract']))
            path.write_bytes(b.encoded(p))
            m = b.read_json(project / 'input-manifest.json')
            m['files_sha256']['parameters.json'] = b.sha(path.read_bytes())
            (project / 'input-manifest.json').write_bytes(b.encoded(m))
            with self.assertRaisesRegex(ValueError, 'Parameters'):
                b.check_project(project)
        finally:
            path.write_bytes(old)
            (project / 'input-manifest.json').write_bytes(manifest)


if __name__ == '__main__':
    unittest.main()
